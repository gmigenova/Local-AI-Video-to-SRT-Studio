# Development Guide

## Environment

- Python **3.11** venv at `.venv` (created via `uv venv --python 3.11 .venv`)
- Node 22 (Phase 3, frontend)
- FFmpeg/FFprobe on PATH (gyan.dev full build)

Install dependencies:

```powershell
uv pip install --python .venv -r backend/requirements.txt -r backend/requirements-dev.txt
uv pip install --python .venv -r backend/requirements-thai.txt   # optional, Thai word-boundary splitting
```

## Quality gates (run before every phase completion)

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q      # all green
.venv\Scripts\python.exe -m ruff check backend           # no findings
Set-Location backend; ..\.venv\Scripts\python.exe -m mypy app; Set-Location ..   # no issues
```

## Pipeline stages and progress weights

`app.pipeline.TranscriptionPipeline.run` reports progress as:
validate 0-5% → extract 5-10% → transcribe 10-92% → subtitles 92-97% →
export 97-100%. Progress is honest: transcription progress derives from the
last segment end vs. total duration (§11.4) — no fabricated percentages.

## Data flow

```
video --ffprobe--> MediaInfo
     --ffmpeg--> 16 kHz mono WAV        (storage/temp/{id}/extracted.wav)
     --faster-whisper--> TranscriptionResult (raw, persisted: transcript.json)
     --SubtitleProcessor--> Subtitle[]  (rules §6.1, integer ms, wrapped text)
     --exporters--> SRT / VTT / TXT / JSON
```

Raw transcription is never overwritten by subtitle edits; the editor
(Phase 4) mutates only `subtitles`, and `reprocess` (§10.7) regenerates
subtitles from the stored raw transcript without re-running AI.

## Testing conventions

- Unit tests construct `TranscribedSegment`/`WordTiming` directly (no model).
- `FakeEngine` in `backend/tests/test_pipeline.py` is the pattern for
  pipeline-level tests.
- FFmpeg-dependent tests are skipped automatically when FFmpeg is missing
  (`requires_ffmpeg` marker in `backend/tests/conftest.py`).
- Smoke-testing with real speech on Windows: generate TTS via
  `System.Speech` (PowerShell), mux with `ffmpeg`, then run the CLI with
  `--model tiny`.
