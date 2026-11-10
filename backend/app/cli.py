"""Phase 1 command-line interface.

Usage (from ``backend/`` with the venv active):
    python -m app.cli probe VIDEO
    python -m app.cli gpu
    python -m app.cli models
    python -m app.cli transcribe VIDEO [-o OUTPUT_DIR] [--model MODEL] ...

The CLI is a thin wrapper around :class:`app.pipeline.TranscriptionPipeline`;
the FastAPI backend (Phase 2) reuses the same services.
"""

from __future__ import annotations

import argparse
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from app.core.config import MODEL_CATALOG, Settings, get_settings
from app.core.errors import OperationCancelled, VideoToSrtError
from app.core.logging_setup import configure_logging
from app.pipeline import TranscriptionPipeline
from app.services.subtitle import SubtitleRules, supported_formats
from app.services.transcription import TranscriptionOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-to-srt",
        description="Local AI Video-to-SRT Studio - transcription pipeline CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe_parser = sub.add_parser("probe", help="Inspect a video file with FFprobe")
    probe_parser.add_argument("video", type=Path)

    sub.add_parser("gpu", help="Show GPU / inference runtime status")
    sub.add_parser("models", help="List known model profiles")

    transcribe_parser = sub.add_parser("transcribe", help="Run the full pipeline")
    transcribe_parser.add_argument("video", type=Path)
    transcribe_parser.add_argument("-o", "--output", type=Path, default=None,
                                   help="Directory for exported subtitle files")
    transcribe_parser.add_argument("--model", default=None, help="Model name (default from settings)")
    transcribe_parser.add_argument("--language", default=None,
                                   help="ISO language code, e.g. th / en / ja (default: auto-detect)")
    transcribe_parser.add_argument("--audio-stream", type=int, default=0,
                                   help="Nth audio stream to use (0-based, default 0)")
    transcribe_parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default=None)
    transcribe_parser.add_argument("--compute-type", default=None,
                                   help="e.g. float16, int8 (default: auto)")
    transcribe_parser.add_argument("--beam-size", type=int, default=None)
    transcribe_parser.add_argument("--initial-prompt", default=None)
    transcribe_parser.add_argument("--no-vad", action="store_true", help="Disable VAD filter")
    transcribe_parser.add_argument("--no-word-timestamps", action="store_true")
    transcribe_parser.add_argument("--formats", default="srt",
                                   help=f"Comma-separated export formats: {','.join(supported_formats())}")
    transcribe_parser.add_argument("--min-duration", type=float, default=None,
                                   help="Minimum subtitle duration in seconds")
    transcribe_parser.add_argument("--max-duration", type=float, default=None,
                                   help="Maximum subtitle duration in seconds")
    transcribe_parser.add_argument("--max-chars-per-line", type=int, default=None)
    return parser


def _print_media(info) -> None:
    print(f"File:        {info.file_path.name}")
    print(f"Container:   {info.container or 'unknown'}")
    print(f"Duration:    {info.duration_ms} ms" if info.duration_ms else "Duration:    unknown")
    print(f"Video:       {info.video_codec or 'none'} "
          f"({info.width or '?'}x{info.height or '?'})")
    print(f"Audio streams ({len(info.audio_streams)}):")
    for stream in info.audio_streams:
        print(f"  - {stream.label}")


def cmd_probe(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = TranscriptionPipeline(settings=settings)
    _print_media(pipeline.probe(args.video))
    return 0


def cmd_gpu(_args: argparse.Namespace, _settings: Settings) -> int:
    from app.services.transcription.model_manager import ModelManager

    summary = ModelManager.gpu_summary()
    print(f"CTranslate2 CUDA devices : {summary['ctranslate2_cuda_devices']}")
    print(f"GPU name                 : {summary['gpu_name'] or 'not detected'}")
    print(f"GPU VRAM                 : "
          f"{summary['gpu_vram_total_mb'] or 'n/a'}"
          f"{' MB' if summary['gpu_vram_total_mb'] else ''}")
    print(f"NVIDIA driver            : {summary['nvidia_driver'] or 'not detected'}")
    print(f"CUDA runtime available   : {summary['cuda_runtime_available']}")
    if summary["note"]:
        print(f"Note: {summary['note']}")
    return 0


def cmd_models(_args: argparse.Namespace, _settings: Settings) -> int:
    for name, meta in MODEL_CATALOG.items():
        print(f"{name:<16} [{meta['profile']:<8}] {meta['note']}")
    return 0


def cmd_transcribe(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_directories()
    options = TranscriptionOptions(
        model=args.model or settings.whisper_model,
        language=args.language,
        beam_size=args.beam_size if args.beam_size is not None else 5,
        vad_filter=not args.no_vad,
        word_timestamps=not args.no_word_timestamps,
        initial_prompt=args.initial_prompt,
    )
    if args.device or args.compute_type:
        settings.whisper_device = args.device or settings.whisper_device
        settings.whisper_compute_type = args.compute_type or settings.whisper_compute_type

    rules_kwargs = {
        key: value
        for key, value in {
            "min_duration": args.min_duration,
            "max_duration": args.max_duration,
            "max_chars_per_line": args.max_chars_per_line,
        }.items()
        if value is not None
    }
    rules = SubtitleRules(**rules_kwargs)  # type: ignore[arg-type]

    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    pipeline = TranscriptionPipeline(settings=settings)
    cancel_event = threading.Event()

    last_stage: dict[str, str | None] = {"text": None}

    def progress(fraction: float, stage: str) -> None:
        if stage != last_stage["text"]:
            print(f"==> {stage}")
            last_stage["text"] = stage
        print(f"\r    {fraction * 100:5.1f}%", end="", flush=True)
        if fraction >= 1.0:
            print()

    result = pipeline.run(
        video_path=args.video,
        options=options,
        rules=rules,
        audio_stream_index=args.audio_stream,
        output_dir=args.output,
        export_formats=formats,
        cancel_event=cancel_event,
        progress=progress,
    )

    print()
    if result.language:
        probability = result.language_probability or 0.0
        print(f"Detected language : {result.language} (p={probability:.2f})")
    else:
        print("Detected language : n/a")
    print(f"Subtitles         : {len(result.subtitles)}")
    print(f"Warnings          : {len(result.warnings)}")
    for warning in result.warnings[:10]:
        print(f"  ! {warning}")
    if len(result.warnings) > 10:
        print(f"  ... and {len(result.warnings) - 10} more")
    print(f"Work directory    : {result.work_dir}")
    for fmt, path in result.export_paths.items():
        print(f"Export ({fmt:<4})     : {path}")
    return 0


_HANDLERS = {
    "probe": cmd_probe,
    "gpu": cmd_gpu,
    "models": cmd_models,
    "transcribe": cmd_transcribe,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        return _HANDLERS[args.command](args, settings)
    except VideoToSrtError as exc:
        if isinstance(exc, OperationCancelled):
            print("\nCancelled.")
            return 130
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
