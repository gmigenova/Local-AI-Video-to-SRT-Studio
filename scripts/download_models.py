"""Download Faster-Whisper models into ./models/faster-whisper (section 8).

Usage (from repository root):
    python scripts/download_models.py large-v3
    python scripts/download_models.py large-v3 large-v3-turbo
    python scripts/download_models.py --list

Downloads run through huggingface_hub; after this the application works
fully offline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import MODEL_CATALOG, get_settings  # noqa: E402

REPOS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "Systran/faster-whisper-large-v3-turbo",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="*", help="Model names to download")
    parser.add_argument("--list", action="store_true", help="List known models")
    args = parser.parse_args()

    if args.list or not args.models:
        for name, repo in REPOS.items():
            marker = " (in catalog)" if name in MODEL_CATALOG else ""
            print(f"{name:<16} {repo}{marker}")
        return 0

    settings = get_settings()
    root = settings.whisper_download_root
    root.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: huggingface_hub is not installed. "
              "Run: pip install -r backend/requirements.txt", file=sys.stderr)
        return 1

    failures: list[str] = []
    for name in args.models:
        repo = REPOS.get(name, f"Systran/faster-whisper-{name}")
        dest = root / name
        print(f"Downloading {repo} -> {dest} ...")
        try:
            snapshot_download(repo_id=repo, local_dir=str(dest))
            print(f"OK: {name}")
        except Exception as exc:  # noqa: BLE001 - report and continue with others
            print(f"FAILED: {name}: {exc}", file=sys.stderr)
            failures.append(name)

    if failures:
        print(f"\n{len(failures)} download(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nAll models downloaded. The app can now run offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
