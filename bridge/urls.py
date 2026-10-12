import re
from urllib.parse import urlparse

from fastapi import Request

from bridge.config import settings

_INTERNAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "bridge", "testserver"}
_VALID_HOST = re.compile(r"^[A-Za-z0-9.-]+$")


def _valid_public_url(value: str) -> bool:
    """PUBLIC_BASE_URL must be a plain http(s)://host[:port] URL."""
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and bool(_VALID_HOST.match(parsed.hostname))
            and parsed.path in ("", "/")
            and parsed.port is not False
        )
    except ValueError:
        return False


def public_base_url(request: Request) -> str:
    """
    Base URL the mobile app must use to reach this bridge.

    The address the app actually called is used (correct behind Traefik/Dokploy
    thanks to the proxy headers), so links keep working whatever the domain or IP.
    PUBLIC_BASE_URL only serves as a fallback when the request comes from an
    internal host name, and is ignored when it is not a valid URL.
    """
    request_url = str(request.base_url).rstrip("/")
    host = (request.url.hostname or "").lower()
    if host in _INTERNAL_HOSTS and settings.PUBLIC_BASE_URL and _valid_public_url(settings.PUBLIC_BASE_URL):
        return settings.PUBLIC_BASE_URL.rstrip("/")
    return request_url


def public_base_url_problem() -> str:
    """Explains why PUBLIC_BASE_URL is ignored (shown in the admin), or ''."""
    if settings.PUBLIC_BASE_URL and not _valid_public_url(settings.PUBLIC_BASE_URL):
        return (
            f"La variable PUBLIC_BASE_URL est invalide ({settings.PUBLIC_BASE_URL!r}) et est ignorée : "
            "supprimez-la dans Dokploy → Environment (elle n'est pas nécessaire)."
        )
    return ""


def series_cover_url(series, base_url: str) -> str:
    """Locally cached WebP cover when available, upstream URL otherwise."""
    if series.local_cover:
        return f"{base_url}/media/covers/{series.local_cover}"
    return series.cover_url or ""
