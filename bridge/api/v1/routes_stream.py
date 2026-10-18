import asyncio
import logging
import re
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from telethon import errors as tg_errors
from sqlalchemy.orm import Session
import httpx

from bridge.config import settings
from bridge.source_session import source_headers
from bridge.database import SessionLocal, get_db
from bridge.models import Episode, Series, TelegramChannel
from bridge.uploads import local_video_path
from bridge.streamer import stream_resolver
from bridge.telegram.client import telegram_service
from bridge.urls import public_base_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Stream"])

ALLOWED_PROXY_HOSTS = {
    "dramadunyam.com",
    "dramaflix.net",
    "cdn.dramaflix.net",
    "cdn2.dramaflix.net",
    "v.shortswave.com",
    "hwztvideo.dramaboxdb.com",
}

@router.get("/stream/{series_id_or_source}/{ep}/master.m3u8")
async def get_stream_playlist(
    series_id_or_source: str,
    ep: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Returns the real-time resolved and rewritten HLS master playlist for an episode.
    Rewrites relative URLs to absolute, handles CDN failover, and caches for short TTL.
    """
    # Resolve source_id if a database primary key was provided
    source_id = series_id_or_source
    if series_id_or_source.isdigit():
        series = db.query(Series).filter(
            (Series.id == int(series_id_or_source)) | (Series.source_id == series_id_or_source)
        ).first()
        if series:
            source_id = series.source_id
    else:
        series = db.query(Series).filter(Series.slug == series_id_or_source).first()
        if series:
            source_id = series.source_id

    bridge_base_url = public_base_url(request)

    try:
        content, content_type, ttl = await stream_resolver.get_playlist(
            series_id=source_id,
            ep_num=ep,
            bridge_base_url=bridge_base_url,
        )
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": f"public, max-age={ttl}",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Episode not found on streaming source")
    except Exception as e:
        logger.error(f"Error serving stream for {series_id_or_source}/{ep}: {e}")
        raise HTTPException(status_code=502, detail="Streaming source temporarily unavailable")


@router.get("/subtitles/{series_id_or_source}/{ep}")
async def get_subtitles(
    series_id_or_source: str,
    ep: int,
    lang: str = Query("en"),
    db: Session = Depends(get_db),
):
    """Returns WebVTT subtitles for the episode."""
    source_id = series_id_or_source
    series = None
    if series_id_or_source.isdigit():
        series = db.query(Series).filter(
            (Series.id == int(series_id_or_source)) | (Series.source_id == series_id_or_source)
        ).first()
        if series:
            source_id = series.source_id

    if series_id_or_source.isdigit() and series and series.source_type == "telegram":
        vtt = "WEBVTT\n\n"
    else:
        vtt = await stream_resolver.get_subtitles_vtt(source_id, ep, lang=lang)
    return Response(
        content=vtt,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/stream/seg")
async def proxy_segment(u: str = Query(..., description="Target segment URL")):
    """
    Optional server-side proxy for video segments (.ts / .mp4),
    protecting CDN origins and mitigating client network restrictions.
    Enforces strict SSRF validation.
    """
    if not settings.PROXY_SEGMENTS:
        raise HTTPException(status_code=403, detail="Segment proxying is disabled")

    parsed = urllib.parse.urlparse(u)
    hostname = (parsed.hostname or "").lower()

    # SSRF Protection: verify hostname against whitelist
    is_allowed = any(
        hostname == allowed or hostname.endswith(f".{allowed}")
        for allowed in ALLOWED_PROXY_HOSTS
    )
    if not is_allowed:
        raise HTTPException(status_code=400, detail="Disallowed target host")

    async def stream_generator():
        async with httpx.AsyncClient(headers=source_headers(), **settings.source_client_kwargs()) as client:
            async with client.stream("GET", u) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        stream_generator(),
        media_type="video/MP2T" if ".ts" in u else "video/mp4",
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# Telegram videos (progressive MP4 with HTTP Range support)
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_caching: set = set()


def _cache_path(episode: Episode):
    return settings.MEDIA_DIR / "videos" / f"{abs(episode.tg_peer_id)}_{episode.tg_message_id}.mp4"


async def _cache_video(message, path) -> None:
    """Downloads the whole video once in the background (TG_CACHE_VIDEOS=true)."""
    key = str(path)
    if key in _caching:
        return
    _caching.add(key)
    part = path.with_suffix(".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The message keeps the client of the account that fetched it
        await message.download_media(file=str(part))
        part.replace(path)
    except Exception as e:
        logger.warning(f"Could not cache Telegram video {path.name}: {e}")
        part.unlink(missing_ok=True)
    finally:
        _caching.discard(key)


def _parse_range(header: str, size: int):
    """Returns (start, end) inclusive, or None when the header is absent/invalid."""
    match = _RANGE_RE.fullmatch((header or "").strip())
    if not match or size <= 0:
        return None
    first, last = match.groups()
    if first == "" and last == "":
        return None
    if first == "":  # suffix range: last N bytes
        start, end = max(0, size - int(last)), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start > end or start >= size:
        raise HTTPException(status_code=416, detail="Range not satisfiable", headers={"Content-Range": f"bytes */{size}"})
    return start, end


@router.get("/stream/{series_id_or_slug}/{ep_file}")
async def stream_telegram_episode(
    series_id_or_slug: str,
    ep_file: str,
    request: Request,
):
    """Streams the episode video posted in a Telegram channel, e.g. /stream/12/3.mp4."""
    match = re.fullmatch(r"(\d{1,5})\.mp4", ep_file)
    if not match:
        raise HTTPException(status_code=404, detail="Not found")
    ep_num = int(match.group(1))

    # Short-lived session: a playback lasts minutes and must not hold a pooled
    # DB connection (the pool would run out after ~15 viewers and block the server).
    db = SessionLocal()
    try:
        query = db.query(Series)
        series = (
            query.filter(Series.id == int(series_id_or_slug)).first()
            if series_id_or_slug.isdigit()
            else query.filter(Series.slug == series_id_or_slug).first()
        )
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
        series_id = series.id
        episode = db.query(Episode).filter(Episode.series_id == series.id, Episode.num == ep_num).first()
        if episode:
            db.expunge(episode)
        channel = (
            db.query(TelegramChannel).filter(TelegramChannel.peer_id == episode.tg_peer_id).first()
            if episode and episode.tg_message_id else None
        )
        access_hash = channel.access_hash if channel else None
    finally:
        db.close()

    if not request.headers.get("x-load-test"):  # simulated viewers are not real activity
        from bridge.activity import record_stream
        record_stream(request.client.host if request.client else "?", series_id, ep_num)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not available")

    # Uploaded to the VPS disk
    local = local_video_path(episode)
    if local is not None:
        if not local.is_file():
            raise HTTPException(status_code=404, detail="Video file missing on the server")
        return FileResponse(local, media_type=episode.mime_type or "video/mp4", headers={"Cache-Control": "public, max-age=86400"})

    if not episode.tg_message_id:
        raise HTTPException(status_code=404, detail="Episode not available")

    # Disk cache (compressed copy of the most watched episodes). A playback keeps
    # the same version for all its Range requests: the two files differ in bytes.
    from bridge.optimizer import choose_version, telegram_cache
    range_header = request.headers.get("range", "")
    range_match = _RANGE_RE.fullmatch(range_header.strip())
    range_start = int(range_match.group(1)) if range_match and range_match.group(1) else 0
    optimized = telegram_cache.lookup(episode.tg_peer_id, episode.tg_message_id)
    client_id = request.client.host if request.client else "?"
    if choose_version(client_id, series_id, ep_num, range_start, optimized is not None) == "cache":
        return FileResponse(optimized, media_type="video/mp4", headers={"Cache-Control": "public, max-age=86400"})

    cached = _cache_path(episode)  # legacy TG_CACHE_VIDEOS copy: same bytes as on Telegram
    if cached.is_file():
        return FileResponse(cached, media_type=episode.mime_type or "video/mp4", headers={"Cache-Control": "public, max-age=86400"})

    if not request.headers.get("x-load-test"):
        telegram_cache.note_request(episode.tg_peer_id, access_hash, episode.tg_message_id)

    try:
        message = await telegram_service.get_message(episode.tg_peer_id, access_hash, episode.tg_message_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Video removed from the channel")
    except Exception as e:
        logger.error(f"Telegram stream unavailable for {series_id}/{ep_num}: {e}")
        raise HTTPException(status_code=503, detail="Telegram source unavailable")

    size = message.file.size or episode.file_size or 0
    byte_range = _parse_range(request.headers.get("range", ""), size)
    start, end = byte_range if byte_range else (0, size - 1)

    if settings.TG_CACHE_VIDEOS:
        asyncio.create_task(_cache_video(message, cached))

    async def body():
        nonlocal message
        position = start
        for attempt in range(2):
            try:
                async for chunk in telegram_service.iter_bytes(message, position, end):
                    position += len(chunk)
                    yield chunk
                return
            except tg_errors.FileReferenceExpiredError:
                if attempt:
                    raise
                message = await telegram_service.get_message(
                    episode.tg_peer_id, access_hash, episode.tg_message_id, refresh=True
                )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "public, max-age=3600",
    }
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        body(),
        status_code=206 if byte_range else 200,
        media_type=episode.mime_type or "video/mp4",
        headers=headers,
    )
