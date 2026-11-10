# Local AI Video-to-SRT Studio

Fully local, offline video-to-subtitle (SRT) application. Speech is transcribed
in the **original language** with Faster-Whisper (CTranslate2) — no cloud AI,
no translation, no speaker diarization.

Spec: [writing-block.md](writing-block.md)

## Status — Phase 1 complete (CLI pipeline)

- [x] **Phase 1** — AI engine + CLI: FFprobe validation, FFmpeg audio
      extraction, Faster-Whisper transcription, subtitle processing,
      SRT/VTT/TXT/JSON export, unit/integration tests.
- [ ] **Phase 2** — FastAPI backend, SQLite + SQLAlchemy + Alembic,
      background worker, REST API.
- [ ] **Phase 3** — React + Vite frontend (dashboard, upload, processing).
- [ ] **Phase 4** — Subtitle editor UI.
- [ ] **Phase 5** — Quality, benchmarking, reliability hardening.

## Requirements

- Python 3.11+ (dev venv created via [`uv`](https://docs.astral.sh/uv/))
- FFmpeg + FFprobe on PATH (`scripts/install_ffmpeg.ps1` installs via winget)
- NVIDIA GPU + CUDA **only via WSL2/Docker** — see "GPU / CUDA" below

## Setup

```powershell
# 1. FFmpeg (skip if already installed)
powershell -ExecutionPolicy Bypass -File scripts\install_ffmpeg.ps1

# 2. Python environment
uv venv --python 3.11 .venv
uv pip install --python .venv -r backend/requirements.txt -r backend/requirements-dev.txt

# 3. Optional: better Thai subtitle line-breaking
uv pip install --python .venv -r backend/requirements-thai.txt

# 4. Verify environment
powershell -ExecutionPolicy Bypass -File scripts\check_environment.ps1

# 5. (Optional) pre-download models so the app runs fully offline
.venv\Scripts\python.exe scripts\download_models.py large-v3
```

## Usage (Phase 1 CLI)

Run from the `backend/` directory with the venv active:

```powershell
cd backend

# Inspect a video (streams, duration, codecs)
python -m app.cli probe ..\path\to\video.mp4

# GPU / inference runtime diagnostics
python -m app.cli gpu

# Video -> SRT (auto language detection)
python -m app.cli transcribe ..\path\to\video.mp4 -o ..\output --model large-v3

# Thai audio, all export formats
python -m app.cli transcribe video.mp4 --language th --formats srt,vtt,txt,json
```

CLI options: `--model`, `--language`, `--audio-stream`, `--beam-size`,
`--initial-prompt`, `--no-vad`, `--no-word-timestamps`, `--min-duration`,
`--max-duration`, `--max-chars-per-line`, `--formats`.

## GPU / CUDA — important

CTranslate2 (the runtime behind Faster-Whisper) ships **CPU-only builds for
native Windows**; CUDA builds exist for Linux. The application handles this
automatically:

| Environment                  | Behaviour                                        |
| ---------------------------- | ------------------------------------------------ |
| Native Windows (this repo)   | CPU inference, `int8` compute type               |
| WSL2 / Docker with NVIDIA GPU | CUDA inference, `float16` — set `WHISPER_DEVICE=cuda` |

Device/compute type are resolved in
[backend/app/services/transcription/faster_whisper_engine.py](backend/app/services/transcription/faster_whisper_engine.py):
`auto` → CUDA when available, otherwise CPU with a logged warning. On an
RTX 4070 Super under WSL2, `large-v3` float16 fits comfortably in 12 GB VRAM.

The dev machine used to build Phase 1 has no NVIDIA GPU (Intel iGPU only),
so GPU execution is untested here — the CUDA code path is identical to the
CPU one except for the CTranslate2 device argument.

## Testing

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
.venv\Scripts\python.exe -m ruff check backend
Set-Location backend; ..\.venv\Scripts\python.exe -m mypy app; Set-Location ..
```

## Project layout

```text
backend/app/
  core/            settings, logging, error types
  services/
    media/         FFprobe inspection, FFmpeg 16 kHz mono WAV extraction
    transcription/ engine abstraction, Faster-Whisper impl, ModelManager
    subtitle/      processing rules, Thai-aware line splitting, exporters
  pipeline.py      probe -> extract -> transcribe -> subtitles -> export
  cli.py           Phase 1 command-line interface
backend/tests/     unit + integration tests (67 tests)
scripts/           env checks, model download, PowerShell helpers
storage/ models/ data/ logs/   runtime dirs (gitignored)
```

## Known limitations (tracked for later phases)

- Segments whose text fits the character budget but wraps to 3 lines produce
  a `TOO_MANY_LINES` warning instead of being re-split (Phase 5 refinement).
- Thai line-breaking falls back to character-boundary splits when `pythainlp`
  is not installed (install `requirements-thai.txt` for word boundaries).
- Chunked/resumable uploads, background jobs, and the web UI arrive in
  Phases 2-4.
