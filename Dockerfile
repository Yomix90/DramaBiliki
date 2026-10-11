FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Python requirements (Pillow ships manylinux wheels with WebP support: no compiler needed)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application source
COPY bridge/ bridge/

# Unprivileged user owning the persistent volumes
RUN useradd --create-home --uid 1000 bridge \
    && mkdir -p /app/data /app/media/covers \
    && chown -R bridge:bridge /app
USER bridge

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
