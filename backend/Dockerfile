# Backend image (API + worker share it; section 15).
# Build:  docker build -t video-to-srt-backend ./backend
# Run API:    docker run ... video-to-srt-backend uvicorn app.main:app --host 0.0.0.0 --port 8000
# Run worker: docker run --gpus all ... video-to-srt-backend python -m app.workers.worker
#
# CUDA note: this image uses the standard (CUDA-linked) ctranslate2 wheel +
# pip-provided CUDA 12 libraries; requires NVIDIA Container Toolkit on the
# host (Docker Desktop with WSL2 GPU passthrough on Windows).

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-gpu.txt ./
RUN grep -v -e '^ctranslate2' requirements.txt > requirements.base.txt \
    && pip install -r requirements.base.txt -r requirements-gpu.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# container paths (override with env; mounted volumes in docker-compose)
ENV STORAGE_PATH=/data/storage \
    MODEL_PATH=/data/models \
    DATABASE_URL=sqlite:////data/database/app.db \
    WHISPER_DEVICE=cuda \
    WHISPER_COMPUTE_TYPE=float16

# unprivileged user
RUN useradd -m appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]
