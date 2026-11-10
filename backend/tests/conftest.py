"""Shared pytest fixtures and path setup.

IMPORTANT: the environment override block below runs before any ``app``
import (pytest imports conftest first), so every test - including the API
and worker tests - runs against a throwaway database and storage tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---- test environment isolation (must precede app imports) -----------
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="v2srt-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'test.db').as_posix()}"
os.environ["STORAGE_PATH"] = str(_TEST_ROOT / "storage")
os.environ["MODEL_PATH"] = str(_TEST_ROOT / "models")

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG and FFPROBE), reason="FFmpeg/FFprobe not installed"
)


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: Path) -> Path:
    """A tiny MP4 (2s test pattern + 440 Hz tone) generated with FFmpeg."""
    if not FFMPEG:
        pytest.skip("ffmpeg not available")
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    cmd = [
        FFMPEG,  # type: ignore[list-item]
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=15",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    return out
