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
  subtitle processor, exporters; ruff + mypy clean.
- **Phase 2 DONE** — FastAPI (`app.main:app`, `/api/v1`), SQLAlchemy 2.x +
  Alembic (initial revision `58b722e639c3`), SQLite WAL at
  `data/database/app.db`, repositories incl. atomic job claim
  (`JobsRepository.claim_next`), background worker (`python -m
  app.workers.worker`) with heartbeat/lock/restart-recovery, upload/export
  services, subtitle CRUD + reprocess APIs.
- **Phase 3 DONE** — React+Vite+TS frontend (`frontend/`, strict TS +
  eslint clean, `npm run build` green). Tailwind v4 with CSS-var theming
  (class-based dark mode), TanStack Query polling, Zustand stores
  (`stores/theme.ts`, `stores/settings.ts`), lucide icons. Vite proxies
  `/api` -> `127.0.0.1:8000`. Pages: dashboard, projects, project detail,
  upload (multi-file + audio stream PATCH), processing (poll 1.5s, cancel,
  retry). Start all: `scripts/start_local.ps1`.
- **Phase 4 DONE** — subtitle editor at `/jobs/{id}`:
  `features/subtitle-editor/`. `useSubtitleEditor.ts` holds the working
  copy + undo/redo (typing coalesced) + debounced (1.2s) full-state
  auto-save via `POST /jobs/{id}/subtitles/sync` (atomic replace +
  renumber + SRT regen — the ONLY persistence call the editor needs).
  Split cuts at the playhead (word-boundary for spaced text, character for
  Thai). Quality checks in `quality.ts` mirror §6.1 defaults. Keyboard:
  Space/Ctrl+S/arrows/Delete/Ctrl+Z/Y (guarded while typing). Reprocess
  button regenerates from raw AI transcript (confirm dialog, resets
  editor).
- **Phase 5 DONE — ALL PHASES COMPLETE** — line-aware subtitle packing
  (`_wrapped_lines` in processor; chunks sized by wrapped lines; split
  chunks take timing from their own first word — regression test covers
  the tail-chunk start bug); VAD tuning via
  `TranscriptionOptions.vad_threshold/vad_min_silence_ms`; WER/CER in
  `app/services/transcription/metrics.py`; benchmark runner
  `scripts/benchmark.py`; retention cleanup
  `app/services/maintenance/retention.py` (worker runs it hourly, uploads
  never deleted); Docker files (`docker-compose.yml`, backend/frontend
  Dockerfiles, `requirements-gpu.txt`) — UNTESTED on the build machine.
  Logs/heartbeat paths are configurable via `LOGS_PATH` (container-safe).
- **Post-spec: mobile UI** — app shell is responsive: desktop keeps the
  sidebar, mobile (< md) gets a top bar + native-style bottom tab bar
  (safe-area aware, `Layout.tsx`); modals become bottom sheets; all pages
  are single-column with wrap-friendly headers; editor stacks video over
  the list with stacked start/end timestamps per row. PWA manifest +
  icon (`frontend/public/`) make it installable. Verified at 390px: zero
  horizontal overflow on all pages (CDP-measured).
- **Post-spec: burn-in video export** — hardsub renders via
  `app/services/render/` (`SubtitleBurner` + `RenderManager`), table
  `video_renders` (migrations `a1c4f7e2b9d8`, `b3e6a1f5c2d9`), APIs
  `POST /jobs/{id}/render`, `GET /jobs/{id}/render`, `GET/POST
  /renders/{id}(/cancel|/download)`. The POST accepts multipart form:
  `font_name` + optional `srt_file` — with an external `.srt`
  (validated/normalised by `srt_import.py`, UTF-8 or Thai TIS-874) any job
  status can render; without it the job must be completed with subtitles.
  External files can also be imported as editable editor rows via
  `POST /jobs/{id}/subtitles/import` (same parser; replaces the job's
  subtitle rows + regenerates output.srt — then preview/edit/export/burn
  work exactly like AI-transcribed subtitles).
  Renders are CPU-only FFmpeg work on a background thread inside the API
  process (lifespan starts/stops the manager) — the AI worker is never
  involved. The filter references the SRT by bare name with `cwd` set to
  the render dir (no Windows drive-colon escaping). Renders are NOT
  covered by retention cleanup.
- **Post-spec: subtitle translation** — Google Cloud Translation API (v2,
  API-key auth via `GOOGLE_TRANSLATE_API_KEY` in `.env`; feature disabled
  when empty). `app/services/translation/google_translate.py` is a stdlib
  REST client (no new deps): batches ≤64 texts/4000 chars per request,
  skips empty cues, maps API/network failures to clean messages
  (`TranslationServiceError`, HTTP status preserved). APIs:
  `GET /translation/languages` (live supported list when configured,
  curated `FALLBACK_LANGUAGES` otherwise) and
  `POST /jobs/{id}/subtitles/translate` (target/source/mode) which
  translates the job's *saved* rows and returns raw texts aligned by
  index. The editor's Translate dialog flushes auto-save first, then
  applies results client-side (`applyTranslation` — one undo step;
  `replace` or `dual` bilingual) and lets auto-save persist them; the
  sync endpoint remains the only persistence path.
  **Usage metering**: table `translation_usage` (migration `d7c2f8a4b1e6`)
  accumulates per local month (`YYYY-MM`) the characters sent (Google's
  billing/quota unit), words (display only), texts, HTTP requests and
  operations. `GOOGLE_TRANSLATE_MONTHLY_CHAR_LIMIT` (default 500000, 0 =
  unlimited) is enforced *before* calling Google — a request that would
  exceed the month's budget is rejected with a clean 429 and meters nothing.
  APIs: `GET /translation/usage`; translate responses include the updated
  `usage` block, which the Translate dialog (budget bar + per-request
  estimate) and the editor notice display.

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
