"""Translation endpoints: engine catalog, Google usage metering, translation.

``POST /jobs/{job_id}/subtitles/translate`` translates the job's *saved*
subtitle texts via the chosen engine (Google Cloud Translation or a local
Ollama TranslateGemma) and returns the raw translations.  Persistence stays
with the editor sync endpoint: the client applies the texts to the working
copy (one undo step) and auto-save persists them - the same flow
reprocess/import already use.

Google operations are metered in ``translation_usage`` (characters are
Google's quota unit) and rejected with a clean 429 when they would push the
current month past ``GOOGLE_TRANSLATE_MONTHLY_CHAR_LIMIT``.  The Ollama
engine is local and free: no quota guard, no metering - but it needs an
explicit source language (the prompt template bakes it in).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.base import get_db
from app.models.subtitle import SubtitleModel
from app.models.translation_usage import TranslationUsage
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.repositories.translation_usage import (
    TranslationUsageRepository,
    current_period,
)
from app.schemas.translation import (
    GoogleEngineOut,
    OllamaEngineOut,
    TranslatedTextItem,
    TranslateLanguageOut,
    TranslateSubtitlesRequest,
    TranslateSubtitlesResponse,
    TranslationEnginesOut,
    TranslationInfoOut,
    TranslationUsageOut,
)
from app.services.translation import (
    FALLBACK_LANGUAGES,
    TranslationServiceError,
    make_ollama_translator,
    make_translator,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_CONFIGURED_MESSAGE = (
    "Google Cloud Translation is not configured. "
    "Set GOOGLE_TRANSLATE_API_KEY in the .env file and restart the backend."
)


def _usage_out(row: TranslationUsage | None, monthly_limit: int) -> TranslationUsageOut:
    return TranslationUsageOut(
        period=row.period if row else current_period(),
        characters_sent=row.characters_sent if row else 0,
        words_sent=row.words_sent if row else 0,
        texts_translated=row.texts_translated if row else 0,
        requests=row.requests if row else 0,
        jobs=row.jobs if row else 0,
        monthly_char_limit=monthly_limit,
        remaining_chars=(
            max(0, monthly_limit - (row.characters_sent if row else 0))
            if monthly_limit > 0
            else None
        ),
    )


def _ollama_engine_out(settings: Settings) -> OllamaEngineOut:
    """Probe the local Ollama server (short timeout; down = unavailable)."""
    client = make_ollama_translator(settings)
    try:
        models = client.list_models()
        return OllamaEngineOut(
            available=True,
            url=settings.ollama_url,
            model=settings.ollama_translate_model,
            models=models,
        )
    except TranslationServiceError as exc:
        logger.debug("Ollama unavailable: %s", exc.message)
        return OllamaEngineOut(
            available=False,
            url=settings.ollama_url,
            model=settings.ollama_translate_model,
            models=[],
        )


@router.get("/translation/languages", response_model=TranslationInfoOut)
def list_translation_languages() -> TranslationInfoOut:
    """Language catalog + per-engine status for the Translate dialog.

    ``languages``/``configured`` mirror the Google engine (legacy fields);
    ``engines`` carries both engines' availability, and for Ollama the
    installed model list (from ``/api/tags``).
    """
    settings = get_settings()
    translator = make_translator(settings)
    configured = translator is not None
    languages: list[TranslateLanguageOut] = []
    if translator is not None:
        try:
            languages = [
                TranslateLanguageOut(code=item["code"], name=item["name"])
                for item in translator.list_supported_languages()
            ]
        except TranslationServiceError as exc:
            logger.warning("Falling back to curated language list: %s", exc.message)
    if not languages:
        languages = [
            TranslateLanguageOut(code=item["code"], name=item["name"])
            for item in FALLBACK_LANGUAGES
        ]
    return TranslationInfoOut(
        configured=configured,
        languages=languages,
        engines=TranslationEnginesOut(
            google=GoogleEngineOut(configured=configured),
            ollama=_ollama_engine_out(settings),
        ),
    )


@router.get("/translation/usage", response_model=TranslationUsageOut)
def get_translation_usage(db: Session = Depends(get_db)) -> TranslationUsageOut:
    """Characters translated this month vs. the configured budget (Google)."""
    settings = get_settings()
    row = TranslationUsageRepository(db).get(current_period())
    return _usage_out(row, settings.google_translate_monthly_char_limit)


@router.post(
    "/jobs/{job_id}/subtitles/translate", response_model=TranslateSubtitlesResponse
)
def translate_job_subtitles(
    job_id: str,
    payload: TranslateSubtitlesRequest,
    db: Session = Depends(get_db),
) -> TranslateSubtitlesResponse:
    """Translate the job's current subtitles with the chosen engine."""
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    rows = SubtitlesRepository(db).list_for_job(job_id)
    if not rows:
        raise HTTPException(status_code=409, detail="This job has no subtitles to translate.")
    texts = [row.text for row in rows]

    if payload.engine == "ollama":
        # the prompt template bakes the source language in - no auto-detect
        effective_source = payload.source_language or job.detected_language
        if effective_source is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Ollama cannot auto-detect the source language. Pick one in "
                    "the dialog, or re-run transcription so the job has a "
                    "detected language."
                ),
            )
        return _translate_with_ollama(job_id, payload, texts, rows, effective_source)

    return _translate_with_google(db, job_id, payload, texts, rows)


def _translate_with_google(
    db: Session,
    job_id: str,
    payload: TranslateSubtitlesRequest,
    texts: list[str],
    rows: list[SubtitleModel],
) -> TranslateSubtitlesResponse:
    settings = get_settings()
    translator = make_translator(settings)
    if translator is None:
        raise HTTPException(status_code=409, detail=_NOT_CONFIGURED_MESSAGE)

    # ---- quota guard: reject before spending any API budget (§16 message) --
    monthly_limit = settings.google_translate_monthly_char_limit
    usage_repo = TranslationUsageRepository(db)
    pending_chars = sum(len(text.strip()) for text in texts if text.strip())
    if monthly_limit > 0:
        used = usage_repo.get(current_period())
        used_chars = used.characters_sent if used else 0
        if used_chars + pending_chars > monthly_limit:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Monthly translation budget would be exceeded: this request needs "
                    f"{pending_chars:,} characters but only "
                    f"{max(0, monthly_limit - used_chars):,} of {monthly_limit:,} remain "
                    f"this month. Raise GOOGLE_TRANSLATE_MONTHLY_CHAR_LIMIT or wait for "
                    f"the next month."
                ),
            )

    try:
        result = translator.translate(
            texts=texts,
            target_language=payload.target_language,
            source_language=payload.source_language,
        )
    except TranslationServiceError as exc:
        logger.warning(
            "Translation failed for job %s -> %s: %s",
            job_id,
            payload.target_language,
            exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # ---- meter the operation (characters are Google's billing unit) --------
    usage_row = usage_repo.add_usage(
        current_period(),
        characters=result.characters_sent,
        words=sum(len(text.split()) for text in texts if text.strip()),
        texts=sum(1 for text in texts if text.strip()),
        requests=result.requests,
    )

    translated = sum(1 for row in rows if row.text.strip())
    return TranslateSubtitlesResponse(
        job_id=job_id,
        engine="google",
        model=None,
        target_language=payload.target_language,
        source_language=payload.source_language,
        detected_source_language=result.detected_source_language,
        mode=payload.mode,
        translated=translated,
        total=len(rows),
        subtitles=[
            TranslatedTextItem(index=i, text=text)
            for i, text in enumerate(result.texts, start=1)
        ],
        usage=_usage_out(usage_row, monthly_limit),
    )


def _translate_with_ollama(
    job_id: str,
    payload: TranslateSubtitlesRequest,
    texts: list[str],
    rows: list[SubtitleModel],
    effective_source: str,
) -> TranslateSubtitlesResponse:
    translator = make_ollama_translator(get_settings(), model=payload.model)
    try:
        result = translator.translate(
            texts=texts,
            target_language=payload.target_language,
            source_language=effective_source,
        )
    except TranslationServiceError as exc:
        logger.warning(
            "Ollama translation failed for job %s -> %s: %s",
            job_id,
            payload.target_language,
            exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    translated = sum(1 for row in rows if row.text.strip())
    return TranslateSubtitlesResponse(
        job_id=job_id,
        engine="ollama",
        model=translator.model_name,
        target_language=payload.target_language,
        source_language=effective_source,
        detected_source_language=None,  # explicit source, nothing detected
        mode=payload.mode,
        translated=translated,
        total=len(rows),
        subtitles=[
            TranslatedTextItem(index=i, text=text)
            for i, text in enumerate(result.texts, start=1)
        ],
        usage=None,  # local + free: not metered
    )
