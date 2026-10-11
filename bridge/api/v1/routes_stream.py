import logging
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import httpx

from bridge.config import settings
from bridge.database import get_db
from bridge.models import Series
from bridge.streamer import stream_resolver
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
    if series_id_or_source.isdigit():
        series = db.query(Series).filter(
            (Series.id == int(series_id_or_source)) | (Series.source_id == series_id_or_source)
        ).first()
        if series:
            source_id = series.source_id

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
        async with httpx.AsyncClient(headers={"User-Agent": settings.SOURCE_USER_AGENT}) as client:
            async with client.stream("GET", u) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        stream_generator(),
        media_type="video/MP2T" if ".ts" in u else "video/mp4",
        headers={"Access-Control-Allow-Origin": "*"},
    )
