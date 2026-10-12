"""
Imports the videos of linked Telegram channels as series and episodes.

Two modes per channel:
- caption: each caption names the series and the episode, e.g.
  "My Drama - Episode 3", "My Drama EP3", "#MyDrama #3", "الحلقة 3".
  Videos without an episode number get the next free number of their series.
- single: the whole channel is one series; videos are episodes in posting order
  (an explicit episode number in the caption still wins).
"""
import asyncio
import datetime
import hashlib
import logging
import os
import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from telethon import errors

from bridge.database import SessionLocal
from bridge.media import save_cover_image
from bridge.models import AppConfig, Episode, Genre, Series, SyncRun, TelegramChannel
from bridge.parsing import VIDEO_EXTENSIONS, parse_video_name, series_title_with_season
from bridge.sync import _sync_lock
from bridge.telegram.client import telegram_service
from bridge.video_check import HEADER_BYTES, check_header

logger = logging.getLogger("bridge.telegram.sync")

# Bump when detection changes so existing channels are rescanned once (imports are idempotent).
SCAN_VERSION = 2

def parse_caption(caption: str) -> Tuple[Optional[str], Optional[int]]:
    """Returns (series title, episode number) found in a caption, each possibly None."""
    parsed = parse_video_name(caption)
    return parsed.title, parsed.episode


def detect_series_and_episode(caption: str, file_name: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Combines the caption and the file name: a file name carrying an episode marker
    ("Harem Wars - S01E03.ts") wins, otherwise the caption is used. Season 2+
    becomes its own series ("Title - S2").
    """
    from_file = parse_video_name(file_name, is_filename=True) if file_name else None
    from_caption = parse_video_name(caption)
    if from_file and from_file.episode is not None and from_file.title:
        chosen = from_file
    elif from_caption.title or from_caption.episode is not None:
        chosen = from_caption
        if chosen.title is None and from_file and from_file.title:
            chosen = chosen._replace(title=from_file.title)
    else:
        chosen = from_file or from_caption
    title = series_title_with_season(chosen.title, chosen.season) if chosen.title else None
    return title, chosen.episode


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return slug[:80] or "series"


def _series_source_id(channel: TelegramChannel, key: str) -> str:
    digest = hashlib.sha1(f"{channel.peer_id}:{key}".encode()).hexdigest()[:12]
    return f"tg-{digest}"


def _unique_slug(db: Session, base: str) -> str:
    slug, n = base, 2
    while db.query(Series.id).filter(Series.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _get_or_create_series(db: Session, channel: TelegramChannel, title: str) -> Series:
    key = title.casefold() if channel.mode == "caption" else "__channel__"
    source_id = _series_source_id(channel, key)
    series = db.query(Series).filter(Series.source_id == source_id).first()
    if series:
        return series
    series = Series(
        source_id=source_id,
        slug=_unique_slug(db, _slugify(title)),
        title=title,
        titles_json={"en": title},
        description="",
        descriptions_json={},
        platform=(channel.title or "Telegram")[:64],
        source_type="telegram",
        tg_channel_id=channel.id,
        status="active",
        is_new=True,
        total_episodes=0,
        available_episodes=0,
    )
    db.add(series)
    db.flush()
    return series


async def _save_thumbnail(client, message, series: Series) -> None:
    try:
        data = await client.download_media(message, file=bytes, thumb=-1)
        if data:
            name = save_cover_image(series.source_id, data)
            if name:
                series.local_cover = name
    except Exception as e:
        logger.debug(f"No thumbnail for message {message.id}: {e}")


async def _is_unplayable(client, message) -> bool:
    """Reads the first bytes of the file to reject videos no player can open."""
    try:
        async for chunk in client.iter_download(message.media, offset=0, request_size=HEADER_BYTES, limit=1):
            return check_header(bytes(chunk)) is not None
    except Exception:
        return False  # network hiccup: import it anyway
    return False


def _file_ext(message) -> str:
    f = message.file
    ext = (getattr(f, "ext", None) or os.path.splitext(getattr(f, "name", None) or "")[1] or "").lower()
    return ext


def _is_video(message) -> bool:
    """Videos, including .ts/.mkv files posted as plain documents."""
    f = message.file
    if f is None:
        return False
    if message.video is not None or (f.mime_type or "").lower().startswith("video/"):
        return True
    return _file_ext(message) in VIDEO_EXTENSIONS


def _mime_type(message) -> str:
    mime = (message.file.mime_type or "").lower()
    if mime.startswith("video/"):
        return mime[:64]
    return {".ts": "video/mp2t", ".m2ts": "video/mp2t", ".mts": "video/mp2t", ".mkv": "video/x-matroska",
            ".webm": "video/webm", ".mov": "video/quicktime", ".avi": "video/x-msvideo"}.get(_file_ext(message), "video/mp4")


async def sync_channel(db: Session, channel: TelegramChannel, full: bool = False) -> int:
    """Imports new videos of one channel. Returns the number of episodes added."""
    client = await telegram_service.authorized_client()
    if client is None:
        raise RuntimeError("Compte Telegram non connecté.")

    peer = telegram_service.input_peer(channel.peer_id, channel.access_hash)
    min_id = 0 if full else (channel.last_message_id or 0)
    added = 0
    last_id = channel.last_message_id or 0
    touched = set()
    unplayable = 0

    async for message in client.iter_messages(peer, min_id=min_id, reverse=True):
        last_id = max(last_id, message.id)
        if not _is_video(message):
            continue

        existing = db.query(Episode).filter(
            Episode.tg_peer_id == channel.peer_id, Episode.tg_message_id == message.id
        ).first()
        if existing:
            continue

        if await _is_unplayable(client, message):
            unplayable += 1
            continue

        title, ep_num = detect_series_and_episode(message.message or "", getattr(message.file, "name", None) or "")
        if channel.mode == "single" or not title:
            title = channel.title or "Telegram"
        series = _get_or_create_series(db, channel, title)

        used = {num for (num,) in db.query(Episode.num).filter(Episode.series_id == series.id)}
        if ep_num is None or ep_num in used:
            ep_num = (max(used) + 1) if used else 1

        db.add(Episode(
            series_id=series.id,
            num=ep_num,
            title=f"Episode {ep_num}",
            titles_json={"en": f"Episode {ep_num}", "fr": f"Épisode {ep_num}", "ar": f"الحلقة {ep_num}"},
            duration=int(getattr(message.file, "duration", None) or 0) or 120,
            is_free=True,
            tg_peer_id=channel.peer_id,
            tg_message_id=message.id,
            file_size=message.file.size or 0,
            mime_type=_mime_type(message),
        ))
        if not series.local_cover:
            await _save_thumbnail(client, message, series)
        if not series.description and channel.mode == "caption" and message.message:
            # Use the first caption's extra lines as a synopsis.
            extra = "\n".join(message.message.strip().splitlines()[1:]).strip()
            if extra:
                series.description = extra[:2000]
                series.descriptions_json = {"en": series.description}
        touched.add(series.id)
        added += 1
        db.flush()

        if added % 20 == 0:
            db.commit()

    for series_id in touched:
        series = db.get(Series, series_id)
        count = db.query(Episode).filter(Episode.series_id == series_id).count()
        series.available_episodes = count
        series.total_episodes = max(series.total_episodes or 0, count)
        series.updated_at = datetime.datetime.utcnow()

    channel.last_message_id = last_id
    channel.videos_count = db.query(Episode).filter(Episode.tg_peer_id == channel.peer_id).count()
    channel.last_synced_at = datetime.datetime.utcnow()
    channel.last_error = (
        f"{unplayable} vidéo(s) ignorée(s) : fragments HLS sans segment d'initialisation (illisibles, à retélécharger)."
        if unplayable else ""
    )
    db.commit()
    return added


async def run_telegram_sync(channel_id: Optional[int] = None, full: bool = False) -> Optional[SyncRun]:
    """Syncs one or all enabled channels, recorded as a SyncRun. None if another sync is running."""
    if _sync_lock.locked():
        logger.info("Skipping Telegram sync: another sync is already running.")
        return None

    async with _sync_lock:
        db = SessionLocal()
        # Detection improved (e.g. .ts documents, file names): rescan every channel once.
        scan_row = db.get(AppConfig, "tg_scan_version")
        if scan_row is None or scan_row.value != str(SCAN_VERSION):
            full = True
            channel_id = None
            if scan_row is None:
                db.add(AppConfig(key="tg_scan_version", value=str(SCAN_VERSION), description="Telegram import version"))
            else:
                scan_row.value = str(SCAN_VERSION)
            db.commit()
        run = SyncRun(sync_type="telegram", status="running", started_at=datetime.datetime.utcnow())
        db.add(run)
        db.commit()
        logs = []
        try:
            query = db.query(TelegramChannel)
            query = query.filter(TelegramChannel.id == channel_id) if channel_id else query.filter(TelegramChannel.enabled == True)  # noqa: E712
            channels = query.all()
            if channel_id and channels:
                run.target_slug = channels[0].title[:255]
            for channel in channels:
                try:
                    added = await sync_channel(db, channel, full=full)
                    run.episodes_synced += added
                    run.series_updated += 1
                    logs.append(f"{channel.title}: +{added} vidéo(s)")
                except errors.FloodWaitError as e:
                    db.rollback()
                    channel.last_error = f"Telegram limite les requêtes : réessayez dans {e.seconds} s"
                    run.errors_count += 1
                    logs.append(f"{channel.title}: {channel.last_error}")
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logger.error(f"Telegram sync failed for {channel.title}: {e}", exc_info=True)
                    channel.last_error = str(e)[:500]
                    run.errors_count += 1
                    logs.append(f"{channel.title}: erreur — {e}")
                    db.commit()
                await asyncio.sleep(0)
            run.series_discovered = db.query(Series).filter(Series.source_type == "telegram").count()
            run.status = "completed" if not run.errors_count else ("failed" if run.errors_count == len(channels) else "completed")
        except Exception as e:
            logger.error(f"Telegram sync run failed: {e}", exc_info=True)
            run.status = "failed"
            logs.append(str(e))
        finally:
            run.log_messages = "\n".join(logs)
            run.finished_at = datetime.datetime.utcnow()
            db.commit()
            db.close()
        return run
