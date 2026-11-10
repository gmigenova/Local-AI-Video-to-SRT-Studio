# Local AI Video-to-SRT Studio

Fully local, offline video-to-subtitle (SRT) application. Speech is transcribed
in the **original language** with Faster-Whisper (CTranslate2) — no cloud AI,
no translation, no speaker diarization.

Spec: [writing-block.md](writing-block.md)

## Status — all 5 phases complete

- [x] **Phase 1** — AI engine + CLI: FFprobe validation, FFmpeg audio
      extraction, Faster-Whisper transcription, subtitle processing,
      SRT/VTT/TXT/JSON export, unit/integration tests.
- [x] **Phase 2** — FastAPI backend: SQLite + SQLAlchemy 2.x + Alembic
      (§7 schema), background AI worker with atomic SQLite job queue (§9),
      full REST API (§10) incl. upload, jobs, subtitle editing, reprocess,
      export, health/system info.
- [x] **Phase 3** — React + Vite + TypeScript frontend: dashboard,
      projects, drag-and-drop multi-file upload with audio-stream
      selection, transcription settings (model/language/quality/advanced),
      live processing screen (polling, cancel, retry). Dark/light themes.
- [x] **Phase 4** — Subtitle editor: inline text + timestamp editing,
      add/delete/split-at-playhead/merge, undo/redo with typing
      coalescing, debounced full-state auto-save (atomic `sync` endpoint),
      search & replace, timeline strip with clickable subtitle blocks,
      live quality warnings (§11.6), keyboard shortcuts (Space, Ctrl+S,
      ↑/↓, Delete, Ctrl+Z/Y), real-time preview overlay, exports,
      one-click reprocess from the AI transcript.
- [x] **Phase 5** — Quality & reliability: line-aware subtitle packing
      (chunks sized by wrapped lines, not raw chars — split tails keep
      their own word timing), VAD tuning parameters, WER/CER metrics +
      benchmark runner, retention-based automatic cleanup (never touches
      source videos), Docker/WSL2 GPU deployment files.

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

## Usage

### Full web app (Phase 3)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_local.ps1
```

Starts the AI worker, the API (`http://127.0.0.1:8000`, docs at `/docs`) and
the frontend (`http://localhost:5173`, with `/api` proxied to the backend).
Add `-NoFrontend` for API-only.

### API-only (headless)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_local.ps1 -NoFrontend
```

REST surface (`/api/v1`): `GET /health`, `GET /system/info`, projects CRUD,
`POST /media/upload`, `GET /media/{id}/stream` (Range-supported video
preview), `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`,
`POST /jobs/{id}/retry`, subtitle list/update/bulk-update/reprocess, and
`GET /jobs/{id}/export/{srt|vtt|txt|json}`.

### CLI (Phase 1)

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

## Benchmarks (§18.3)

```powershell
# compare models on your own test videos; reference transcripts optional
.venv\Scripts\python.exe scripts\benchmark.py video1.mp4 video2.mp4 `
    --models large-v3-turbo large-v3 `
    --refs reference1.srt reference2.txt
```

Writes `benchmarks/report.json` + `report.md` with real-time factor,
processing time, detected language, segments, peak RSS and accuracy
(WER for space languages, CER for th/ja/zh). Do not assume a model is
more accurate for Thai simply because it is larger — measure.

## Automatic cleanup (§8)

Retention runs in the worker at startup and hourly. Configure in `.env`:

```env
RETENTION_TEMP_DAYS=7        # storage/temp
RETENTION_AUDIO_DAYS=14      # extracted audio of completed jobs
RETENTION_ARTIFACT_DAYS=0    # transcripts + subtitle exports (0 = keep)
```

Source videos (`storage/uploads`) are **never** deleted automatically —
only an explicit project delete removes them.

## Docker / WSL2 GPU deployment (§15)

```powershell
docker compose up --build
# frontend http://localhost:8080 · API docs http://localhost:8000/docs
```

The worker container runs with `deploy.resources` GPU reservations (CUDA
via pip-provided cuBLAS/cuDNN; requires Docker Desktop + WSL2 GPU
passthrough or nvidia-container-toolkit). Pre-download models into the
mounted volume to run fully offline:

```powershell
docker compose run --rm worker python scripts/download_models.py large-v3
```

> Note: the Docker path is provided per the spec but was **not exercised on
> the build machine** (no Docker / no NVIDIA GPU available there).

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
  database/        engine/session (SQLite WAL), Alembic runner
  models/          SQLAlchemy ORM (§7 schema: projects, media_files,
                   transcription_jobs, transcription_segments, subtitles,
                   transcription_settings)
  repositories/    data access incl. atomic job claim
  schemas/         Pydantic API schemas
  services/
    media/         FFprobe inspection, FFmpeg WAV extraction, uploads
    transcription/ engine abstraction, Faster-Whisper impl, ModelManager
    subtitle/      processing rules, Thai-aware line splitting, exporters
    export/        DB rows -> downloadable files
  workers/         background job worker + heartbeat/lock
  api/v1/          REST routers (§10)
  pipeline.py      probe -> extract -> transcribe -> subtitles -> export
  cli.py           Phase 1 command-line interface
backend/migrations/  Alembic revisions
backend/tests/     85 unit + integration tests
scripts/           env checks, model download, start/stop helpers
storage/ models/ data/ logs/   runtime dirs (gitignored)
```

## Known limitations

- Thai line-breaking falls back to character-boundary splits when `pythainlp`
  is not installed (install `requirements-thai.txt` for word boundaries).
- Chunked/resumable uploads are not implemented yet (single-request upload
  only; fine on localhost for large files).
- The Docker deployment is provided but untested on the build machine.
