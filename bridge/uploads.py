"""
Batch video uploads from the admin panel.

Browser → bridge: files are sent in chunks (several files in parallel), written
straight to disk. Once complete, each file is queued for processing:
  1. series/episode detection from the file name ("Title - S01E03.ts"),
  2. optional .ts/.mkv → .mp4 remux (fast, no re-encoding), duration, thumbnail,
  3. storage: parallel MTProto upload to a Telegram channel, or the VPS disk,
  4. episode creation (an existing episode number is replaced).
Jobs live in memory; the admin page polls their progress.
"""
import asyncio
import datetime
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from bridge import app_settings
from bridge.config import settings
from bridge.database import SessionLocal
from bridge.media import save_cover_image
from bridge.metadata import apply_metadata
from bridge.models import Episode, Genre, Series, TelegramChannel
from bridge.parsing import VIDEO_EXTENSIONS, parse_video_name, series_title_with_season
from bridge.video_check import HEADER_BYTES, check_header
from bridge.video_tools import probe, remux_to_mp4, thumbnail

logger = logging.getLogger("bridge.uploads")

UPLOAD_TMP_DIR = settings.MEDIA_DIR / "uploads_tmp"
LOCAL_VIDEOS_DIR = settings.MEDIA_DIR / "videos" / "local"
PROCESSING_WORKERS = 3  # analysis / remux run in parallel; Telegram sends are serialized below
JOB_RETENTION_SECONDS = 6 * 3600
UPLOAD_GENRE_SLUG = "uploads"

REMUX_EXTENSIONS = {".ts", ".m2ts", ".mts", ".mkv", ".avi", ".flv", ".mov", ".wmv", ".3gp"}


@dataclass
class UploadJob:
    id: str
    filename: str
    size: int
    received: int = 0
    status: str = "uploading"  # uploading | queued | processing | sending | done | error
    progress: float = 0.0  # 0..1 of the current step
    message: str = ""
    mode: str = "auto"  # auto | series
    series_id: Optional[int] = None
    episode: Optional[int] = None
    detected_title: str = ""
    title_override: str = ""
    meta_id: str = ""
    result_series_id: Optional[int] = None
    result_episode: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    chunks: Dict[int, int] = field(default_factory=dict, repr=False)  # offset -> length

    @property
    def path(self) -> Path:
        return UPLOAD_TMP_DIR / f"{self.id}{Path(self.filename).suffix.lower() or '.mp4'}"

    def touch(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self, key, value)
        self.updated_at = time.time()

    def public(self) -> dict:
        data = asdict(self)
        data.pop("chunks", None)
        data["created_at"] = int(self.created_at)
        return data


_jobs: Dict[str, UploadJob] = {}

# Videos are kept on the VPS disk until their turn: one Telegram upload at a time.
_telegram_lock: Optional[asyncio.Lock] = None
_telegram_waiting = 0

# Information files sent with a batch: id -> {"meta": dict, "cover": bytes | None, "applied": set of series ids}
_metadata: Dict[str, dict] = {}


def register_metadata(meta: dict, cover: Optional[bytes] = None) -> str:
    meta_id = uuid.uuid4().hex
    _metadata[meta_id] = {"meta": meta, "cover": cover, "applied": set(), "created": time.time()}
    for key, value in list(_metadata.items()):
        if time.time() - value["created"] > JOB_RETENTION_SECONDS:
            _metadata.pop(key, None)
    return meta_id
_queue: Optional[asyncio.Queue] = None
_workers: List[asyncio.Task] = []


# ---------------------------------------------------------------------------
# Detection preview
# ---------------------------------------------------------------------------

def detect(filename: str) -> dict:
    """Series title / episode guessed from a file name, plus the matching existing series."""
    parsed = parse_video_name(filename, is_filename=True)
    title = series_title_with_season(parsed.title, parsed.season) if parsed.title else None
    existing = None
    if title:
        db = SessionLocal()
        try:
            series = _find_series_by_title(db, title)
            if series:
                existing = {"id": series.id, "title": series.title}
        finally:
            db.close()
    return {
        "filename": filename,
        "title": title,
        "season": parsed.season,
        "episode": parsed.episode,
        "existing_series": existing,
        "supported": Path(filename).suffix.lower() in VIDEO_EXTENSIONS,
    }


def _find_series_by_title(db, title: str) -> Optional[Series]:
    key = title.casefold().strip()
    for series in db.query(Series).filter(Series.title.ilike(title)).all():
        if series.title.casefold().strip() == key:
            return series
    return None


# ---------------------------------------------------------------------------
# Receiving files
# ---------------------------------------------------------------------------

def create_job(filename: str, size: int, mode: str = "auto", series_id: Optional[int] = None,
               episode: Optional[int] = None, title: str = "", meta_id: str = "") -> UploadJob:
    _cleanup_old_jobs()
    safe_name = os.path.basename(filename or "video.mp4")[:200]
    if Path(safe_name).suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(f"Format non pris en charge : {safe_name}")
    if size <= 0:
        raise ValueError("Fichier vide")
    free = shutil.disk_usage(settings.MEDIA_DIR).free
    if size * 2.2 > free:  # file + possible remux copy
        raise ValueError(f"Espace disque insuffisant sur le serveur ({free // (1024 ** 2)} Mo libres)")

    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    job = UploadJob(id=uuid.uuid4().hex, filename=safe_name, size=size,
                    mode=mode if mode in ("auto", "series") else "auto",
                    series_id=series_id, episode=episode, title_override=(title or "").strip()[:200],
                    meta_id=meta_id if meta_id in _metadata else "")
    job.path.touch()
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Optional[UploadJob]:
    return _jobs.get(job_id)


def list_jobs() -> List[dict]:
    return [j.public() for j in sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)]


async def write_chunk(job: UploadJob, offset: int, data: bytes) -> None:
    if job.status != "uploading":
        raise ValueError("Téléversement déjà terminé")
    if offset < 0 or offset + len(data) > job.size:
        raise ValueError("Morceau hors limites")

    def _write():
        with open(job.path, "r+b") as fh:
            fh.seek(offset)
            fh.write(data)

    await asyncio.to_thread(_write)
    job.chunks[offset] = len(data)  # a retried chunk simply overwrites itself
    received = sum(job.chunks.values())
    job.touch(received=min(job.size, received), progress=min(1.0, received / job.size))


def complete_job(job: UploadJob) -> None:
    received = sum(job.chunks.values())
    if received < job.size:
        raise ValueError(f"Fichier incomplet ({received}/{job.size} octets reçus)")
    job.touch(status="queued", progress=0.0, message="En attente de traitement")
    _ensure_workers()
    _queue.put_nowait(job.id)


def cancel_job(job: UploadJob) -> None:
    job.path.unlink(missing_ok=True)
    _jobs.pop(job.id, None)


def _cleanup_old_jobs() -> None:
    now = time.time()
    for job_id, job in list(_jobs.items()):
        if job.status in ("done", "error") and now - job.updated_at > JOB_RETENTION_SECONDS:
            _jobs.pop(job_id, None)
        elif job.status == "uploading" and now - job.updated_at > JOB_RETENTION_SECONDS:
            job.path.unlink(missing_ok=True)
            _jobs.pop(job_id, None)


def cleanup_tmp_dir() -> None:
    """Removes leftovers of uploads interrupted by a restart."""
    if UPLOAD_TMP_DIR.exists():
        for f in UPLOAD_TMP_DIR.iterdir():
            try:
                f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def _ensure_workers() -> None:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    alive = [w for w in _workers if not w.done()]
    _workers[:] = alive
    while len(_workers) < PROCESSING_WORKERS:
        _workers.append(asyncio.create_task(_worker()))


async def _worker() -> None:
    while True:
        job_id = await _queue.get()
        job = _jobs.get(job_id)
        if job is None:
            continue
        try:
            await _process(job)
        except Exception as e:
            logger.error(f"Upload {job.filename} failed: {e}", exc_info=True)
            job.touch(status="error", message=str(e)[:300])
        finally:
            job.path.unlink(missing_ok=True)


def _unique_slug(db, base: str) -> str:
    slug = re.sub(r"[^\w]+", "-", base.lower(), flags=re.UNICODE).strip("-")[:80] or "series"
    candidate, n = slug, 2
    while db.query(Series.id).filter(Series.slug == candidate).first():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def create_series(db, title: str, **fields) -> Series:
    """Creates a series managed from the admin (manual or uploaded content)."""
    series = Series(
        source_id=f"up-{uuid.uuid4().hex[:12]}",
        slug=_unique_slug(db, title),
        title=title,
        titles_json={"en": title},
        description=fields.pop("description", ""),
        descriptions_json={},
        platform=fields.pop("platform", "DramaBiliki"),
        source_type="upload",
        status=fields.pop("status", "active"),
        is_new=fields.pop("is_new", True),
        total_episodes=0,
        available_episodes=0,
        **fields,
    )
    db.add(series)
    db.flush()
    return series


def _upload_genre(db) -> Genre:
    genre = db.query(Genre).filter_by(slug=UPLOAD_GENRE_SLUG).first()
    if not genre:
        genre = Genre(slug=UPLOAD_GENRE_SLUG, name="Exclusivités", names_json={"en": "Exclusives", "fr": "Exclusivités", "ar": "حصريات"})
        db.add(genre)
        db.flush()
    return genre


async def _process(job: UploadJob) -> None:
    job.touch(status="processing", progress=0.05, message="Analyse")
    src = job.path
    with open(src, "rb") as fh:
        problem = check_header(fh.read(HEADER_BYTES))
    if problem:
        raise RuntimeError(problem)

    # 1. Target series and episode number
    parsed = parse_video_name(job.filename, is_filename=True)
    title = series_title_with_season(parsed.title, parsed.season) if parsed.title else None
    batch_meta = _metadata.get(job.meta_id) if job.meta_id else None
    meta_title = str(batch_meta["meta"].get("title") or "") if batch_meta else ""
    title = job.title_override or meta_title or title
    job.touch(detected_title=title or "")

    db = SessionLocal()
    try:
        if job.mode == "series" and job.series_id:
            series = db.get(Series, job.series_id)
            if series is None:
                raise RuntimeError("Série cible introuvable")
        else:
            if not title:
                raise RuntimeError("Impossible de détecter la série dans le nom du fichier (ex. « Titre - S01E03.mp4 »)")
            series = _find_series_by_title(db, title)
            if series is None:
                series = create_series(db, title)
                db.commit()
        series_id = series.id
        if batch_meta and series_id not in batch_meta["applied"]:
            # Title, synopsis, genres... from the information file sent with the batch
            apply_metadata(db, series, batch_meta["meta"])
            if batch_meta["cover"]:
                name = save_cover_image(series.source_id, batch_meta["cover"])
                if name:
                    series.local_cover = name
            db.commit()
            batch_meta["applied"].add(series_id)
        used = {n for (n,) in db.query(Episode.num).filter(Episode.series_id == series_id)}
        ep_num = job.episode or parsed.episode or ((max(used) + 1) if used else 1)
        needs_cover = not series.local_cover
        cover_source_id = series.source_id
    finally:
        db.close()

    # 2. Remux / probe / thumbnail
    work = src
    if src.suffix.lower() in REMUX_EXTENSIONS and app_settings.get_bool("upload_convert_ts"):
        job.touch(progress=0.15, message="Conversion en MP4")
        mp4 = src.with_name(src.stem + ".remux.mp4")
        if await remux_to_mp4(src, mp4):
            src.unlink(missing_ok=True)
            work = mp4
    info = await probe(work)

    # 3. Compression (heavy videos → ~720p, capped bitrate): less traffic per viewer
    from bridge import optimizer
    if optimizer.needs_compression(work.stat().st_size, info["duration"]):
        if optimizer.encode_lock().locked():
            job.touch(progress=0.25, message="En attente de compression (une à la fois)")
        lighter = work.with_name(work.stem + ".opt.mp4")
        before = work.stat().st_size
        if await _compress_with_progress(job, optimizer, work, lighter):
            work.unlink(missing_ok=True)
            work = lighter
            info = await probe(work)
            job.touch(message=f"Compressée : {before // 1048576} → {work.stat().st_size // 1048576} Mo")
    if needs_cover:
        thumb = work.with_suffix(".jpg")
        if await thumbnail(work, thumb, info["duration"]):
            name = save_cover_image(cover_source_id, thumb.read_bytes())
            thumb.unlink(missing_ok=True)
            if name:
                db = SessionLocal()
                try:
                    s = db.get(Series, series_id)
                    if s and not s.local_cover:
                        s.local_cover = name
                        db.commit()
                finally:
                    db.close()

    ext = work.suffix.lower()
    mime = "video/mp4" if ext in (".mp4", ".m4v") else {".ts": "video/mp2t", ".mkv": "video/x-matroska", ".webm": "video/webm"}.get(ext, "video/mp4")
    episode_fields = {
        "duration": info["duration"] or 120,
        "file_size": work.stat().st_size,
        "mime_type": mime,
    }

    # 3. Storage
    destination = app_settings.get("upload_destination")
    if destination == "telegram":
        global _telegram_lock, _telegram_waiting
        if _telegram_lock is None:
            _telegram_lock = asyncio.Lock()
        _telegram_waiting += 1
        job.touch(status="processing", progress=1.0, message=f"Prêt sur le serveur — en attente d'envoi vers Telegram ({_telegram_waiting} en file)")
        try:
            async with _telegram_lock:
                _telegram_waiting -= 1
                job.touch(status="sending", progress=0.0, message="Envoi vers Telegram")
                peer_id, message_id = await _send_to_telegram(job, work, series_id, ep_num, info)
        finally:
            if job.status != "sending":
                _telegram_waiting = max(0, _telegram_waiting - 1)
        episode_fields.update(tg_peer_id=peer_id, tg_message_id=message_id, local_file="")
    else:
        job.touch(status="sending", progress=0.5, message="Enregistrement sur le serveur")
        LOCAL_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{series_id}_{ep_num}_{uuid.uuid4().hex[:8]}{ext}"
        await asyncio.to_thread(shutil.move, str(work), str(LOCAL_VIDEOS_DIR / name))
        episode_fields.update(local_file=name, tg_peer_id=None, tg_message_id=None)

    # 4. Episode
    db = SessionLocal()
    try:
        episode = db.query(Episode).filter(Episode.series_id == series_id, Episode.num == ep_num).first()
        if episode is None:
            episode = Episode(
                series_id=series_id, num=ep_num, title=f"Episode {ep_num}",
                titles_json={"en": f"Episode {ep_num}", "fr": f"Épisode {ep_num}", "ar": f"الحلقة {ep_num}"},
                is_free=True,
            )
            db.add(episode)
        else:
            remove_local_video(episode)
        for key, value in episode_fields.items():
            setattr(episode, key, value)
        db.flush()
        refresh_series_counts(db, series_id)
        db.commit()
    finally:
        db.close()
    work.unlink(missing_ok=True)
    job.touch(status="done", progress=1.0, message="Terminé", result_series_id=series_id, result_episode=ep_num)


async def _compress_with_progress(job: UploadJob, optimizer, src: Path, dst: Path) -> bool:
    async def wait_for_lock():
        while optimizer.encode_lock().locked():
            await asyncio.sleep(1)
    await wait_for_lock()
    job.touch(progress=0.3, message="Compression de la vidéo")
    return await optimizer.compress(src, dst)


async def _send_to_telegram(job: UploadJob, path: Path, series_id: int, ep_num: int, info: dict):
    from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo
    from bridge.telegram.client import telegram_service
    from bridge.telegram.fast_upload import fast_upload_file

    channel_id = app_settings.get("upload_channel_id")
    db = SessionLocal()
    try:
        channel = db.get(TelegramChannel, int(channel_id)) if channel_id.isdigit() else None
        series = db.get(Series, series_id)
        caption = f"{series.title} - Episode {ep_num}" if series else job.filename
    finally:
        db.close()
    if channel is None:
        raise RuntimeError("Aucune chaîne Telegram de destination choisie (Admin → Téléverser)")
    client = await telegram_service.client_for_channel(channel)
    if client is None:
        raise RuntimeError("Compte Telegram de la chaîne non connecté (ou choisissez le stockage « Serveur »)")

    def on_progress(sent: int, total: int) -> None:
        job.touch(progress=sent / total)

    uploaded = await fast_upload_file(client, path, file_name=f"{Path(job.filename).stem}{path.suffix}", progress=on_progress)
    thumb = path.with_suffix(".thumb.jpg")
    has_thumb = await thumbnail(path, thumb, info["duration"])
    try:
        message = await client.send_file(
            telegram_service.input_peer(channel.peer_id, channel.access_hash),
            file=uploaded,
            caption=caption,
            thumb=str(thumb) if has_thumb else None,
            supports_streaming=True,
            attributes=[
                DocumentAttributeFilename(file_name=f"{Path(job.filename).stem}{path.suffix}"),
                DocumentAttributeVideo(
                    duration=info["duration"] or 0,
                    w=info["width"] or 720,
                    h=info["height"] or 1280,
                    supports_streaming=True,
                ),
            ],
        )
    finally:
        thumb.unlink(missing_ok=True)
    return channel.peer_id, message.id


# ---------------------------------------------------------------------------
# Helpers shared with the admin
# ---------------------------------------------------------------------------

def local_video_path(episode: Episode) -> Optional[Path]:
    if not episode.local_file:
        return None
    path = (LOCAL_VIDEOS_DIR / episode.local_file).resolve()
    if LOCAL_VIDEOS_DIR.resolve() not in path.parents:
        return None
    return path


def remove_local_video(episode: Episode) -> None:
    path = local_video_path(episode)
    if path and path.exists():
        path.unlink()


def refresh_series_counts(db, series_id: int) -> None:
    series = db.get(Series, series_id)
    if series is None:
        return
    count = db.query(Episode).filter(Episode.series_id == series_id).count()
    series.available_episodes = count
    series.total_episodes = max(series.total_episodes or 0, count)
    series.updated_at = datetime.datetime.utcnow()
