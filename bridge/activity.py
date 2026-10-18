"""
Live activity (in memory): who is watching right now, and disk usage.

- Viewers: the app posts the watch progress every ~10 s; a user seen in the last
  2 minutes counts as an active viewer.
- Streams: each video request is recorded by client address; addresses seen in
  the last minute count as streams in progress.
"""
import datetime
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
        "Cache vidéo Telegram": (sum(_dir_size(f) for f in videos.glob("*.mp4")) if videos.exists() else 0) + _dir_size(videos / "cache"),
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
        for f in list(videos.glob("*.mp4")) + list(videos.glob("*.part")) + list((videos / "cache").glob("*")):
            try:
                freed += f.stat().st_size
                f.unlink()
            except OSError:
                pass
    return freed


# ---------------------------------------------------------------------------
# Outgoing traffic of the month (videos, covers, APK), saved every minute
# ---------------------------------------------------------------------------

_traffic = {"month": "", "bytes": 0, "unsaved": 0, "saved_at": 0.0}


def _month() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m")


def _traffic_key(month: str) -> str:
    return f"traffic_{month}"


def _load_traffic() -> None:
    from bridge.database import SessionLocal
    from bridge.models import AppConfig
    month = _month()
    db = SessionLocal()
    try:
        row = db.get(AppConfig, _traffic_key(month))
        _traffic.update(month=month, bytes=int(row.value) if row and row.value.isdigit() else 0, unsaved=0)
    finally:
        db.close()


def save_traffic() -> None:
    from bridge.database import SessionLocal
    from bridge.models import AppConfig
    if not _traffic["month"]:
        return
    db = SessionLocal()
    try:
        key = _traffic_key(_traffic["month"])
        row = db.get(AppConfig, key)
        if row:
            row.value = str(_traffic["bytes"])
        else:
            db.add(AppConfig(key=key, value=str(_traffic["bytes"]), description="Trafic sortant du mois (octets)"))
        db.commit()
        _traffic["unsaved"] = 0
        _traffic["saved_at"] = time.time()
    finally:
        db.close()


def add_traffic(n: int) -> None:
    if not n:
        return
    if _traffic["month"] != _month():
        if _traffic["month"] and _traffic["unsaved"]:
            save_traffic()
        _load_traffic()
    _traffic["bytes"] += n
    _traffic["unsaved"] += n
    if time.time() - _traffic["saved_at"] > 60:
        try:
            save_traffic()
        except Exception:
            pass  # never break a video because of the counter


def traffic() -> dict:
    """This month's outgoing traffic, the quota and the projection to the end of the month."""
    from bridge import app_settings
    if _traffic["month"] != _month():
        _load_traffic()
    now = datetime.datetime.utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + datetime.timedelta(days=32)).replace(day=1)
    elapsed = max((now - start).total_seconds(), 3600)
    total = (nxt - start).total_seconds()
    try:
        quota = float(app_settings.get("traffic_quota_tb") or 0) * 1e12
    except ValueError:
        quota = 0
    used = _traffic["bytes"]
    projected = used * total / elapsed
    return {
        "used": used,
        "quota": quota,
        "percent": round(100 * used / quota, 1) if quota else 0,
        "projected": projected,
        "projected_percent": round(100 * projected / quota, 1) if quota else 0,
        "avg_mbps": round(used * 8 / elapsed / 1e6, 1),
    }
