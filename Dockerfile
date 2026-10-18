FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ffmpeg: video duration, thumbnails, .ts -> .mp4 remux and compression
# nginx: sends videos and the APK itself (X-Accel-Redirect), Python keeps the API
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default

# Python requirements (Pillow ships manylinux wheels with WebP support: no compiler needed)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application source
COPY bridge/ bridge/
COPY docker/ docker/
RUN sed -i 's/\r$//' docker/start.sh

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

# nginx on $PORT in front of Python (internal port 8091); automatic fallback to
# Python alone if nginx fails its self-check. NGINX_ENABLED=false disables nginx.
CMD ["bash", "/app/docker/start.sh"]
