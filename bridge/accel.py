"""
Big files (videos, APK) sent by nginx instead of Python ("X-Accel-Redirect").

In the Docker image, nginx listens on the public port and forwards requests to
the Python server. For a video stored on disk, Python only checks the database
and answers with an ``X-Accel-Redirect`` header: nginx then sends the file
itself (sendfile, HTTP Range, thousands of connections) and the Python process
stays free for the API. ``NGINX_ACCEL=1`` is set by docker/start.sh only after
nginx passed its self-check; otherwise files are sent by Python as before.
"""
import os
import re
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse, Response

from bridge.config import settings

ACCEL_PREFIX = "/_protected/"
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def enabled() -> bool:
    return os.getenv("NGINX_ACCEL", "").strip() == "1"


def _sent_bytes(range_header: str, size: int) -> int:
    """Bytes nginx will send for this request (the Python traffic counter cannot see them)."""
    match = _RANGE_RE.fullmatch((range_header or "").strip())
    if not match or size <= 0:
        return size
    first, last = match.groups()
    if first == "" and last:
        return min(size, int(last))
    if first == "":
        return size
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    return max(0, end - start + 1)


def file_response(path: Path, request: Request, media_type: str, headers: Optional[Dict[str, str]] = None,
                  filename: Optional[str] = None) -> Response:
    headers = dict(headers or {})
    media_root = settings.MEDIA_DIR.resolve()
    resolved = path.resolve()
    if enabled() and media_root in resolved.parents:
        rel = resolved.relative_to(media_root).as_posix()
        headers["X-Accel-Redirect"] = ACCEL_PREFIX + quote(rel)
        if filename:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if not request.headers.get("x-load-test"):
            from bridge.activity import add_traffic
            try:
                add_traffic(_sent_bytes(request.headers.get("range", ""), resolved.stat().st_size))
            except OSError:
                pass
        return Response(status_code=200, media_type=media_type, headers=headers)
    return FileResponse(path, media_type=media_type, headers=headers, filename=filename)
