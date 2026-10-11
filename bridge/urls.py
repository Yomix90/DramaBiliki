from fastapi import Request

from bridge.config import settings


def public_base_url(request: Request) -> str:
    """
    Base URL the mobile app must use to reach this bridge.

    PUBLIC_BASE_URL wins when set; otherwise the request URL is used, which is
    correct behind a reverse proxy (Traefik/Dokploy) because uvicorn runs with
    proxy headers enabled (X-Forwarded-Proto / X-Forwarded-Host).
    """
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def series_cover_url(series, base_url: str) -> str:
    """Locally cached WebP cover when available, upstream URL otherwise."""
    if series.local_cover:
        return f"{base_url}/media/covers/{series.local_cover}"
    return series.cover_url or ""
