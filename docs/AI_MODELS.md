# AI Models

## Primary engine: Faster-Whisper (CTranslate2)

Repo: https://github.com/SYSTRAN/faster-whisper

| Profile   | Model           | Precision (GPU) | Precision (CPU) |
| --------- | --------------- | --------------- | --------------- |
| Quality   | `large-v3`      | float16         | int8            |
| Balanced  | `large-v3-turbo`| float16         | int8            |
| Dev/test  | `tiny`…`medium` | -               | int8            |

Default: `large-v3` (§3.1). Models cache under `models/faster-whisper/`
(configurable via `MODEL_PATH`).

## Device strategy

`resolve_inference_target()` in
`backend/app/services/transcription/faster_whisper_engine.py`:

1. `WHISPER_DEVICE=auto` → CUDA when `ctranslate2.get_cuda_device_count() > 0`,
   else CPU.
2. `WHISPER_DEVICE=cuda` with no CUDA visible → **warning + CPU fallback**
   (never a crash). Native Windows CTranslate2 wheels are CPU-only; CUDA
   requires WSL2/Docker with NVIDIA GPU passthrough (§15).
3. `WHISPER_COMPUTE_TYPE=auto` → `float16` on CUDA, `int8` on CPU.

## Model lifecycle (§3.3)

`ModelManager` keeps **one** loaded engine. Switching model/device/compute
type unloads the previous engine first, protecting the 12 GB VRAM budget on
the target RTX 4070 Super. Models are never reloaded per job.

## Download / offline use

```powershell
.venv\Scripts\python.exe scripts\download_models.py large-v3 large-v3-turbo
```

Afterwards the application runs with no internet connection (§21).

## VAD and word timestamps

- Silero VAD (`vad_filter=True`) removes non-speech; bundled with
  faster-whisper via onnxruntime (CPU) — no extra install.
- `word_timestamps=True` enables word-boundary-aware subtitle splitting.
  Without word timings, long segments are never time-split (no fabricated
  timings, §6.1) — they stay intact and raise a `TOO_LONG_DURATION` warning.

## Parameter compatibility

`TranscriptionOptions` is filtered against the installed
`WhisperModel.transcribe` signature before every call (§3.4), so newer/older
faster-whisper versions do not break jobs.
