"""Translation endpoints: language catalog, usage metering, translation.

``POST /jobs/{job_id}/subtitles/translate`` translates the job's *saved*
subtitle texts via the Google Cloud Translation API and returns the raw
translations.  Persistence stays with the editor sync endpoint: the client
applies the texts to the working copy (one undo step) and auto-save persists
them - the same flow reprocess/import already use.

Every operation is metered in ``translation_usage`` (characters are Google's
quota unit) and rejected with a clean 429 when it would push the current
month past ``GOOGLE_TRANSLATE_MONTHLY_CHAR_LIMIT``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.base import get_db
from app.models.translation_usage import TranslationUsage
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.repositories.translation_usage import (
    TranslationUsageRepository,
    current_period,
)
from app.schemas.translation import (
    TranslatedTextItem,
    TranslateLanguageOut,
    TranslateSubtitlesRequest,
    TranslateSubtitlesResponse,
    TranslationInfoOut,
    TranslationUsageOut,
)
from app.services.translation import (
    FALLBACK_LANGUAGES,
    TranslationServiceError,
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


@router.get("/translation/languages", response_model=TranslationInfoOut)
def list_translation_languages() -> TranslationInfoOut:
    """Languages the user can pick as translation targets.

    With a configured API key the live supported-language list from Google is
    returned (falling back to the curated catalog on any error); without a
    key only the curated catalog is shown and ``configured`` is false.
    """
    translator = make_translator()
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
    return TranslationInfoOut(configured=configured, languages=languages)


@router.get("/translation/usage", response_model=TranslationUsageOut)
def get_translation_usage(db: Session = Depends(get_db)) -> TranslationUsageOut:
    """Characters translated this month vs. the configured monthly budget."""
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
    """Translate the job's current subtitles into the chosen language."""
    if JobsRepository(db).get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    translator = make_translator(get_settings())
    if translator is None:
        raise HTTPException(status_code=409, detail=_NOT_CONFIGURED_MESSAGE)

    rows = SubtitlesRepository(db).list_for_job(job_id)
    if not rows:
        raise HTTPException(status_code=409, detail="This job has no subtitles to translate.")

    texts = [row.text for row in rows]

    # ---- quota guard: reject before spending any API budget (§16 message) --
    settings = get_settings()
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
