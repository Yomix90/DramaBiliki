FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ffmpeg: video duration, thumbnails and fast .ts -> .mp4 remux for uploads
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python requirements (Pillow ships manylinux wheels with WebP support: no compiler needed)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application source
COPY bridge/ bridge/

# Runs as root on purpose: volumes created by earlier deployments are root-owned.
RUN mkdir -p /app/data /app/media/covers

# Persistent data: SQLite database + generated secret key, and cached covers.
# Mount both as volumes (Dokploy → Advanced → Volumes) so they survive redeploys.
ENV HOST=0.0.0.0 \
    PORT=8090 \
    APP_ENV=production \
    DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/dramabiliki.db \
    MEDIA_DIR=/app/media \
    COVERS_DIR=/app/media/covers
VOLUME ["/app/data", "/app/media"]

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8090\")}/health', timeout=4)" || exit 1

CMD ["python", "-m", "bridge"]
