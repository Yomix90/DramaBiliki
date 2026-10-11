import datetime
import hmac
import time
import urllib.parse
from typing import Dict, Optional, Tuple

import jwt
from fastapi import HTTPException, Request, Response, status

from bridge.config import settings

SESSION_COOKIE = "dramabiliki_admin"
SESSION_SCOPE = "admin"

# Brute-force protection: per client IP, at most MAX_FAILURES failed logins per window.
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
_failures: Dict[str, Tuple[int, float]] = {}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_locked_out(ip: str) -> bool:
    count, first = _failures.get(ip, (0, 0.0))
    if count and time.time() - first > FAILURE_WINDOW_SECONDS:
        _failures.pop(ip, None)
        return False
    return count >= MAX_FAILURES


def register_failure(ip: str) -> None:
    count, first = _failures.get(ip, (0, time.time()))
    if time.time() - first > FAILURE_WINDOW_SECONDS:
        count, first = 0, time.time()
    _failures[ip] = (count + 1, first)


def clear_failures(ip: str) -> None:
    _failures.pop(ip, None)


def check_credentials(username: str, password: str) -> bool:
    if not settings.admin_login_allowed:
        return False
    user_ok = hmac.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode())
    pass_ok = hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())
    return user_ok and pass_ok


def set_session_cookie(response: Response, request: Request, username: str) -> None:
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=settings.ADMIN_SESSION_HOURS)
    token = jwt.encode(
        {"sub": username, "scope": SESSION_SCOPE, "exp": expires},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.ADMIN_SESSION_HOURS * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/admin",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/admin")


def current_admin(request: Request) -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("scope") != SESSION_SCOPE or payload.get("sub") != settings.ADMIN_USERNAME:
        return None
    return payload["sub"]


def _same_origin(request: Request) -> bool:
    """Rejects cross-site form posts (defense in depth on top of SameSite=strict)."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True
    return urllib.parse.urlparse(origin).netloc == request.url.netloc


def require_admin(request: Request) -> str:
    """FastAPI dependency: redirects to the login page when no valid session is present."""
    admin = current_admin(request)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    if request.method not in ("GET", "HEAD") and not _same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request refused")
    return admin
