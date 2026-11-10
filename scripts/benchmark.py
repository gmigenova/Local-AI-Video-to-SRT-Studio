"""Model benchmark runner (section 18.3).

Runs one or more models against one or more media files, measures
processing time / real-time factor / accuracy, and writes a JSON +
Markdown report.

Usage (repo root):
    python scripts/benchmark.py video1.mp4 video2.mp4
        --models large-v3 large-v3-turbo
        --refs reference1.srt reference2.txt      # optional accuracy refs
        --out benchmarks

Reference files may be plain text (.txt) or SRT (.srt). Accuracy uses CER
for unspaced languages (th/ja/zh) and WER otherwise. Peak memory is the
process RSS (best effort on Windows/Linux).

NOTE: models are compared on the same audio extraction; extraction happens
once per file, transcription once per (model, file).
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.media import AudioExtractor  # noqa: E402
from app.services.media.ffprobe import probe_video  # noqa: E402
from app.services.subtitle import SubtitleProcessor  # noqa: E402
from app.services.transcription import (  # noqa: E402
    ModelManager,
    TranscriptionOptions,
)
from app.services.transcription.metrics import (  # noqa: E402
    character_error_rate,
    real_time_factor,
    word_error_rate,
)

CER_LANGUAGES = {"th", "ja", "zh"}


def parse_srt(path: Path) -> str:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").strip())
    lines: list[str] = []
    for block in blocks:
        rows = [r.strip() for r in block.splitlines() if r.strip()]
        if len(rows) >= 3:  # index, timestamps, text...
            lines.append(" ".join(rows[2:]))
    return " ".join(lines)


def load_reference(path: Path) -> str:
    if path.suffix.lower() == ".srt":
        return parse_srt(path)
    return path.read_text(encoding="utf-8-sig")


def peak_rss_mb() -> float | None:
    try:
        import ctypes
        import ctypes.wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            ctypes.windll.kernel32.GetCurrentProcess(),  # type: ignore[attr-defined]
            ctypes.byref(counters),
            counters.cb,
        )
        return round(counters.PeakWorkingSetSize / 1024**2, 1)
    except Exception:
        return None


def run_benchmark(models: list[str], files: list[Path], refs: dict[str, str],
                  out_dir: Path, language: str | None) -> dict:
    settings = get_settings()
    settings.ensure_directories()
    extractor = AudioExtractor()
    manager = ModelManager(settings)
    report: dict = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "results": [],
    }

    for media_path in files:
        info = probe_video(media_path)
        audio_path = out_dir / f"audio-{media_path.stem}.wav"
        extractor.extract(media_path, audio_path)
        media_seconds = (info.duration_ms or 0) / 1000
        reference = refs.get(media_path.name)

        for model in models:
            print(f"\n=== {media_path.name} | model={model} ===", flush=True)
            engine = manager.get_engine(model_name=model)
            options = TranscriptionOptions(model=model, language=language)
            started = time.perf_counter()
            result = engine.transcribe(audio_path, options)
            elapsed = time.perf_counter() - started

            text = " ".join(seg.text for seg in result.segments)
            entry: dict = {
                "file": media_path.name,
                "model": model,
                "media_seconds": round(media_seconds, 2),
                "processing_seconds": round(elapsed, 2),
                "real_time_factor": round(real_time_factor(elapsed, media_seconds), 3),
                "detected_language": result.language,
                "language_probability": result.language_probability,
                "segments": len(result.segments),
                "peak_rss_mb": peak_rss_mb(),
            }
            if reference:
                detected = result.language or language or "en"
                use_cer = detected in CER_LANGUAGES
                error = (
                    character_error_rate(reference, text)
                    if use_cer
                    else word_error_rate(reference, text)
                )
                entry["metric"] = "CER" if use_cer else "WER"
                entry["error_rate"] = round(error, 4)
                entry["accuracy"] = round(max(0.0, 1 - error), 4)
            report["results"].append(entry)
            print(json.dumps(entry, indent=2), flush=True)

        audio_path.unlink(missing_ok=True)
        manager.unload()  # free VRAM between models

    return report


def write_report(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# Benchmark report", "", f"Generated: {report['created_at']}", ""]
    md.append("| File | Model | RTF | Time (s) | Segments | Language | Accuracy |")
    md.append("|---|---|---|---|---|---|---|")
    for r in report["results"]:
        accuracy = (
            f"{r['accuracy']:.1%} ({r['metric']})" if "accuracy" in r else "-"
        )
        md.append(
            f"| {r['file']} | {r['model']} | {r['real_time_factor']} | "
            f"{r['processing_seconds']} | {r['segments']} | "
            f"{r['detected_language']} | {accuracy} |"
        )
    (out_dir / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nReport written to {json_path} and {out_dir / 'report.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="Media files to test")
    parser.add_argument("--models", nargs="+", default=["large-v3-turbo", "large-v3"])
    parser.add_argument("--refs", nargs="*", default=[], type=Path,
                        help="Reference transcript per input file, in the same order "
                             "(.txt or .srt); omit to skip accuracy")
    parser.add_argument("--language", default=None,
                        help="Force language code (default: auto-detect)")
    parser.add_argument("--out", default=str(REPO_ROOT / "benchmarks"), type=Path)
    args = parser.parse_args()

    refs: dict[str, str] = {}
    if args.refs:
        if len(args.refs) != len(args.files):
            parser.error("--refs must match the number of input files (use '' to skip one)")
        for media, ref in zip(args.files, args.refs):
            if str(ref):
                refs[media.name] = load_reference(ref)

    report = run_benchmark(args.models, args.files, refs, args.out, args.language)
    write_report(report, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
