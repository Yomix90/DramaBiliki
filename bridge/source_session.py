"""
Browser session reused for requests to the source.

The admin can paste the Cookie header and User-Agent of a browser that can open
the source (e.g. after passing Cloudflare). They are stored in the app_config
table and applied to every outbound client (scanner, stream resolver, covers).
The SOURCE_COOKIES / SOURCE_USER_AGENT environment variables act as defaults.
"""
import os
import time
import urllib.parse
from typing import Dict, Optional, Tuple

import httpx

from bridge.config import settings
from bridge.database import SessionLocal
from bridge.models import AppConfig

KEY_COOKIES = "source_cookies"
KEY_USER_AGENT = "source_user_agent"

_cache: Optional[Tuple[float, str, str]] = None
_CACHE_SECONDS = 30


def parse_cookie_header(raw: str) -> Dict[str, str]:
    """Parses 'a=1; b=2' (also accepts a leading 'Cookie:' and one cookie per line)."""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):]
    cookies: Dict[str, str] = {}
    for part in raw.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if name:
            cookies[name] = value
    return cookies


def get_session_values() -> Tuple[str, str]:
    """Returns (cookie_header, user_agent), cached for a few seconds."""
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1], _cache[2]

    cookies = os.getenv("SOURCE_COOKIES", "")
    user_agent = settings.SOURCE_USER_AGENT
    db = SessionLocal()
    try:
        rows = {r.key: r.value for r in db.query(AppConfig).filter(AppConfig.key.in_([KEY_COOKIES, KEY_USER_AGENT]))}
        cookies = rows.get(KEY_COOKIES) or cookies
        user_agent = rows.get(KEY_USER_AGENT) or user_agent
    except Exception:
        pass
    finally:
        db.close()

    _cache = (now, cookies, user_agent)
    return cookies, user_agent


def save_session_values(cookies: str, user_agent: str) -> None:
    global _cache
    db = SessionLocal()
    try:
        for key, value, desc in (
            (KEY_COOKIES, cookies.strip(), "Browser Cookie header used for source requests"),
            (KEY_USER_AGENT, user_agent.strip(), "Browser User-Agent used for source requests"),
        ):
            row = db.query(AppConfig).filter(AppConfig.key == key).first()
            if not value:
                if row:
                    db.delete(row)
                continue
            if row:
                row.value = value
            else:
                db.add(AppConfig(key=key, value=value, description=desc))
        db.commit()
    finally:
        db.close()
    _cache = None


def source_headers() -> Dict[str, str]:
    """User-Agent to send to the source (browser one when configured)."""
    return {"User-Agent": get_session_values()[1]}


def apply_session(client: httpx.AsyncClient) -> None:
    """Injects the browser cookies and User-Agent into an outbound client."""
    cookie_header, user_agent = get_session_values()
    client.headers["User-Agent"] = user_agent
    host = urllib.parse.urlparse(settings.SOURCE_BASE_URL).hostname or ""
    for name, value in parse_cookie_header(cookie_header).items():
        client.cookies.set(name, value, domain=host)


async def test_source() -> Tuple[int, str]:
    """Hits the source catalog with the current session. Returns (status_code, summary)."""
    async with httpx.AsyncClient(
        headers={"Accept": "application/json, text/plain, */*", "Referer": f"{settings.SOURCE_BASE_URL}/"},
        timeout=15.0,
        follow_redirects=True,
        **settings.source_client_kwargs(),
    ) as client:
        apply_session(client)
        try:
            await client.get(f"{settings.SOURCE_BASE_URL}/api/config")
            resp = await client.get(
                f"{settings.SOURCE_BASE_URL}/api/series",
                params={"type": "tumu", "page": 1, "limit": 2, "lang": "en"},
            )
        except httpx.HTTPError as e:
            return 0, f"Connexion impossible : {e}"
    if resp.status_code == 200:
        try:
            count = len(resp.json().get("data", []))
        except Exception:
            count = 0
        return 200, f"OK — la source répond ({count} série(s) reçue(s) en test)."
    if resp.status_code == 403:
        return 403, ("403 Forbidden — Cloudflare bloque toujours le VPS. Les cookies cf_clearance sont "
                     "souvent liés à l'IP du navigateur : utilisez plutôt SOURCE_PROXY.")
    return resp.status_code, f"La source a répondu HTTP {resp.status_code}."
