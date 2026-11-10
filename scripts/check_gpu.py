"""Print GPU / inference runtime diagnostics.

Usage: python scripts/check_gpu.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.transcription.model_manager import ModelManager  # noqa: E402


def main() -> int:
    summary = ModelManager.gpu_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not summary["cuda_runtime_available"]:
        print(
            "\nNOTE: CUDA is not visible to CTranslate2. On native Windows, CTranslate2 "
            "builds are CPU-only; run the worker under WSL2 or Docker (with GPU "
            "passthrough) for CUDA inference, or continue on CPU (int8)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
