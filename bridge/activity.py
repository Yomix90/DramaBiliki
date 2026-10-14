"""
Live activity (in memory): who is watching right now, and disk usage.

- Viewers: the app posts the watch progress every ~10 s; a user seen in the last
  2 minutes counts as an active viewer.
- Streams: each video request is recorded by client address; addresses seen in
  the last minute count as streams in progress.
"""
import shutil
import time
from pathlib import Path
from typing import Dict, Tuple

from bridge.config import settings

VIEWER_WINDOW = 120
STREAM_WINDOW = 60

_viewers: Dict[int, Tuple[float, int, int]] = {}  # user id -> (time, series id, episode)
_streams: Dict[str, Tuple[float, int, int]] = {}  # client address -> (time, series id, episode)


def record_progress(user_id: int, series_id: int, episode: int) -> None:
    _viewers[user_id] = (time.time(), series_id, episode)


def record_stream(client: str, series_id: int, episode: int) -> None:
    _streams[client] = (time.time(), series_id, episode)


def _prune(store: dict, window: int) -> dict:
    now = time.time()
    for key in [k for k, v in store.items() if now - v[0] > window]:
        store.pop(key, None)
    return store


def snapshot() -> dict:
    viewers = _prune(_viewers, VIEWER_WINDOW)
    streams = _prune(_streams, STREAM_WINDOW)
    watching: Dict[int, int] = {}
    for _, series_id, _ in list(viewers.values()) + list(streams.values()):
        watching[series_id] = watching.get(series_id, 0) + 1
    return {
        "viewers": len(viewers),
        "streams": len(streams),
        "watching": sorted(watching.items(), key=lambda kv: kv[1], reverse=True)[:5],  # (series id, count)
    }


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def disk_usage() -> dict:
    usage = shutil.disk_usage(settings.MEDIA_DIR)
    db_url = settings.DATABASE_URL
    db_file = Path(db_url[len("sqlite:///"):]) if db_url.startswith("sqlite:///") else None
    videos = settings.MEDIA_DIR / "videos"
    parts = {
        "Base de données": _dir_size(db_file) if db_file else 0,
        "Affiches": _dir_size(settings.COVERS_DIR),
        "Vidéos sur le serveur": _dir_size(videos / "local"),
        "Cache vidéo Telegram": sum(_dir_size(f) for f in videos.glob("*.mp4")) if videos.exists() else 0,
        "Téléversements en cours": _dir_size(settings.MEDIA_DIR / "uploads_tmp"),
        "APK": _dir_size(settings.MEDIA_DIR / "apk"),
        "Sauvegardes automatiques": _dir_size(settings.DATA_DIR / "backups"),
    }
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(100 * usage.used / usage.total, 1) if usage.total else 0,
        "parts": parts,
    }


def clear_telegram_cache() -> int:
    """Deletes the disk copies of Telegram videos (they are re-downloaded on demand)."""
    videos = settings.MEDIA_DIR / "videos"
    freed = 0
    if videos.exists():
        for f in list(videos.glob("*.mp4")) + list(videos.glob("*.part")):
            try:
                freed += f.stat().st_size
                f.unlink()
            except OSError:
                pass
    return freed
