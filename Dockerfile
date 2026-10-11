FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (curl, libwebp, libmagic)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY bridge/ bridge/
COPY tests/ tests/

# Create data directories
RUN mkdir -p media/covers

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bridge"]
