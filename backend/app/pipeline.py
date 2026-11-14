"""End-to-end transcription pipeline.

Orchestrates: FFprobe validation -> FFmpeg audio extraction -> transcription
-> (optional speaker diarization) -> subtitle processing -> export.  Used
today by the CLI and later by the background worker, so all progress
reporting is callback-based.

Progress weights: validate 0-5%, extract 5-10%, transcribe 10-92%
(or 10-75% + diarization 75-88% when enabled), subtitles 92-97%,
export 97-100%.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from app.core.config import Settings, get_settings
from app.core.errors import DiarizationUnavailable
from app.services.diarization import (
    DiarizationService,
    DiarizationTurn,
    assign_speakers_to_subtitles,
    write_diarization_payload,
)
from app.services.media import AudioExtractor, MediaInfo, probe_video
from app.services.subtitle import (
    Subtitle,
    SubtitleProcessor,
    SubtitleRules,
    SubtitleWarning,
    export_subtitles,
    supported_formats,
)
from app.services.transcription import (
    ModelManager,
    TranscriptionOptions,
    TranscriptionResult,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


@dataclass
class PipelineResult:
    """Everything produced by one pipeline run."""

    media_info: MediaInfo
    language: str | None
    language_probability: float | None
    subtitles: list[Subtitle]
    warnings: list[SubtitleWarning]
    audio_path: Path
    work_dir: Path
    transcript_path: Path | None = None
    export_paths: dict[str, Path] = field(default_factory=dict)
    transcription: TranscriptionResult | None = None
    #: persisted speaker turns (diarization), when it ran
    diarization_path: Path | None = None
    #: how many subtitle rows received a speaker label
    labelled_subtitles: int = 0


def _noop_progress(fraction: float, stage: str) -> None:  # pragma: no cover
    return None


class TranscriptionPipeline:
    """Runs the full video-to-subtitles pipeline for one media file."""

    def __init__(
        self,
        settings: Settings | None = None,
        model_manager: ModelManager | None = None,
        extractor: AudioExtractor | None = None,
        diarizer: DiarizationService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_manager = model_manager or ModelManager(self.settings)
        self.extractor = extractor or AudioExtractor(
            ffmpeg_path=self.settings.ffmpeg_path,
            timeout_seconds=self.settings.ffmpeg_timeout_seconds,
        )
        self.diarizer = diarizer

    # ------------------------------------------------------------------
    def probe(self, video_path: Path | str) -> MediaInfo:
        """Validate and inspect a media file (FFprobe)."""
        return probe_video(Path(video_path), ffprobe_path=self.settings.ffprobe_path)

    # ------------------------------------------------------------------
    def run(
        self,
        video_path: Path | str,
        options: TranscriptionOptions | None = None,
        rules: SubtitleRules | None = None,
        audio_stream_index: int = 0,
        work_dir: Path | str | None = None,
        output_dir: Path | str | None = None,
        export_formats: Sequence[str] | None = None,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline. Raises application errors on failure."""
        report = progress or _noop_progress
        options = options or TranscriptionOptions(model=self.settings.whisper_model)
        formats = list(export_formats) if export_formats is not None else ["srt"]
        for fmt in formats:
            if fmt not in supported_formats():
                from app.core.errors import ExportError

                raise ExportError(f"Unknown export format '{fmt}'.")

        # 1. Validate media -------------------------------------------------
        report(0.02, "Validating media")
        media_info = self.probe(video_path)
        stream = media_info.audio_stream_by_index(
            _absolute_audio_index(media_info, audio_stream_index)
        )
        if stream is None:
            from app.core.errors import NoAudioStreamError

            raise NoAudioStreamError(
                f"Audio stream #{audio_stream_index} not found in this file."
            )

        # 2. Extract audio --------------------------------------------------
        if work_dir is None:
            self.settings.ensure_directories()
            work_dir = self.settings.storage_subdir("temp") / f"cli-{uuid.uuid4().hex[:12]}"
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        audio_path = work_dir / "extracted.wav"

        report(0.05, f"Extracting audio (stream #{stream.stream_index})")
        extraction = self.extractor.extract(
            video_path=media_info.file_path,
            output_path=audio_path,
            audio_stream_index=audio_stream_index,
            cancel_event=cancel_event,
        )

        # 3. Transcribe -----------------------------------------------------
        report(0.10, f"Loading model '{options.model}'")
        engine = self.model_manager.get_engine(
            model_name=options.model,
            device=self.settings.whisper_device,
            compute_type=self.settings.whisper_compute_type,
        )

        def _transcribe_progress(fraction: float, stage: str) -> None:
            report(0.10 + fraction * transcribe_span, stage)

        # when diarization runs, transcription yields part of its progress
        # span to it so the reported fraction stays monotonic
        transcribe_span = 0.65 if options.diarize else 0.82

        transcription: TranscriptionResult = engine.transcribe(
            audio_path=extraction.audio_path,
            options=options,
            progress_callback=_transcribe_progress,
            cancel_event=cancel_event,
        )

        # 3b. Optional speaker diarization (post-spec feature) ---------------
        # Runs after transcription on the same extracted WAV. Unavailability
        # (no token / no pyannote) is a warning, never a failed job; the
        # turns are persisted next to the transcript so reprocess can
        # re-apply speakers without re-running the model.
        turns: list[DiarizationTurn] = []
        diarization_path: Path | None = None
        if options.diarize:
            if self.diarizer is None:
                logger.warning(
                    "Diarization requested but no diarizer is configured; skipping."
                )
                report(0.80, "Skipped speaker diarization: not configured")
            else:
                try:

                    def _diarize_progress(fraction: float, stage: str) -> None:
                        report(0.75 + fraction * 0.13, stage)

                    turns = self.diarizer.diarize(
                        extraction.audio_path,
                        progress_callback=_diarize_progress,
                        cancel_event=cancel_event,
                    )
                except DiarizationUnavailable as exc:
                    logger.warning("Diarization skipped for this job: %s", exc)
                    report(0.80, "Skipped speaker diarization: not configured")
                else:
                    diarization_path = work_dir / "diarization.json"
                    try:
                        write_diarization_payload(turns, diarization_path)
                    except OSError as exc:
                        logger.warning("Could not write diarization.json: %s", exc)
                        diarization_path = None

        # 4. Persist the raw transcript -------------------------------------
        report(0.92, "Processing subtitles")
        transcript_path: Path | None = None
        transcript_target = work_dir / "transcript.json"
        try:
            transcript_target.write_text(
                json.dumps(transcription.to_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            transcript_path = transcript_target
        except OSError as exc:
            logger.warning("Could not write transcript.json: %s", exc)

        result = SubtitleProcessor(rules).process(transcription.segments)
        labelled = 0
        if turns:
            labelled = assign_speakers_to_subtitles(result.subtitles, turns).apply_to(
                result.subtitles
            )

        # 5. Export -----------------------------------------------------------
        report(0.97, "Exporting subtitles")
        out_dir = Path(output_dir) if output_dir else work_dir
        export_paths: dict[str, Path] = {}
        for fmt in formats:
            export_paths[fmt] = export_subtitles(
                result.subtitles, out_dir / f"output.{fmt}", fmt
            )

        report(1.0, "Completed")
        return PipelineResult(
            media_info=media_info,
            language=transcription.language,
            language_probability=transcription.language_probability,
            subtitles=result.subtitles,
            warnings=result.warnings,
            audio_path=extraction.audio_path,
            work_dir=work_dir,
            transcript_path=transcript_path,
            export_paths=export_paths,
            transcription=transcription,
            diarization_path=diarization_path,
            labelled_subtitles=labelled,
        )


def _absolute_audio_index(media_info: MediaInfo, nth_audio: int) -> int:
    """Map the Nth audio stream (0-based) to its absolute stream index."""
    streams = sorted(media_info.audio_streams, key=lambda s: s.stream_index)
    if 0 <= nth_audio < len(streams):
        return streams[nth_audio].stream_index
    return -1


__all__ = ["PipelineResult", "TranscriptionPipeline", "ProgressCallback"]
