# CLAUDE.md — development guide

Spec source of truth: `writing-block.md` (sections referenced below as §N).
Build incrementally; never mark a phase complete with failing tests (§20).

## Commands

```powershell
# tests / lint / types (from repo root)
.venv\Scripts\python.exe -m pytest backend/tests -q
.venv\Scripts\python.exe -m ruff check backend
Set-Location backend; ..\.venv\Scripts\python.exe -m mypy app; Set-Location ..

# CLI (must run from backend/)
Set-Location backend; ..\.venv\Scripts\python.exe -m app.cli transcribe <video> -o <dir>
```

Python 3.11 venv at `.venv` (created with `uv`). Config comes from `.env`
(see `.env.example`); all paths resolve relative to the repo root — never
hardcode absolute user paths (§20.11).

## Phase tracker

- **Phase 1 DONE** — CLI pipeline: media services, transcription engine,
  subtitle processor, exporters, 67 passing tests, ruff + mypy clean.
- **Phase 2 NEXT** — FastAPI + SQLAlchemy 2.x + Alembic, SQLite WAL at
  `data/database/app.db`, tables per §7 (projects, media_files,
  transcription_jobs, transcription_segments, subtitles,
  transcription_settings), SQLite-backed job queue + worker process per §9,
  REST API per §10 (`/api/v1`), background worker reuses
  `app.pipeline.TranscriptionPipeline`.
- Phase 3 — React+Vite+TS frontend (§11). Phase 4 — subtitle editor (§11.5).
- Phase 5 — quality/reliability (§19).

## Architecture invariants (do not break)

- Transcription and subtitle formatting stay separate (§6): raw Whisper
  segments persist to `transcript.json`; `SubtitleProcessor` turns them into
  editable subtitles; exporters never see raw segments.
- Timestamps are **integer milliseconds** everywhere; string formatting only
  in `exporters.py`.
- One loaded model at a time via `ModelManager` (§3.3); GPU concurrency = 1.
- Task is always `transcribe`, never `translate` (§3.2).
- FFmpeg/FFprobe always invoked with argument arrays, `-nostdin`, timeouts,
  cancellation support (§17).
- Engine kwargs are filtered against the installed faster-whisper signature
  (`FasterWhisperEngine._supported_transcribe_kwargs`).
- Device resolution (`resolve_inference_target`) auto-falls-back CUDA→CPU
  (native Windows CTranslate2 is CPU-only; GPU needs WSL2/Docker).

## Error handling

All app errors derive from `app.core.errors.VideoToSrtError`; never leak
paths/stack traces to users (§16) — log details, show clean messages.
