"""
Runtime settings editable from the admin panel (stored in the app_config table):
mobile app update policy, rewarded ads, Telegram upload destination...
Values are cached for a few seconds to avoid a query per request.
"""
import time
from typing import Dict, Optional, Tuple

from bridge.database import SessionLocal
from bridge.models import AppConfig

DEFAULTS: Dict[str, str] = {
    # Mobile app updates
    "app_latest_version": "1.3.0",
    "app_min_version": "1.0.0",
    "app_update_url": "",
    "app_update_notes": "",
    "app_update_force": "false",
    # Rewarded ads (AdMob)
    "ads_enabled": "false",
    "ads_every_n_episodes": "5",
    "ads_rewarded_unit_id": "",
    # Uploads
    "upload_destination": "telegram",  # telegram | local
    "upload_channel_id": "",
    "upload_convert_ts": "true",
}

_CACHE_SECONDS = 10
_cache: Optional[Tuple[float, Dict[str, str]]] = None


def get_all() -> Dict[str, str]:
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    values = dict(DEFAULTS)
    db = SessionLocal()
    try:
        for row in db.query(AppConfig).filter(AppConfig.key.in_(list(DEFAULTS))):
            values[row.key] = row.value
    finally:
        db.close()
    _cache = (now, values)
    return values


def get(key: str) -> str:
    return get_all().get(key, DEFAULTS.get(key, ""))


def get_bool(key: str) -> bool:
    return get(key).strip().lower() in ("1", "true", "yes", "on")


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get(key))
    except ValueError:
        return default


def set_many(values: Dict[str, str]) -> None:
    global _cache
    db = SessionLocal()
    try:
        for key, value in values.items():
            row = db.get(AppConfig, key)
            if row:
                row.value = value
            else:
                db.add(AppConfig(key=key, value=value, description=""))
        db.commit()
    finally:
        db.close()
    _cache = None


def parse_version(version: Optional[str]) -> Tuple[int, int, int]:
    """'1.2.0', 'v1.3', '1.3.0+5' -> (1, 3, 0); unreadable parts count as 0."""
    text = str(version or "").strip().lstrip("vV").split("+", 1)[0].split("-", 1)[0]
    parts = []
    for piece in text.split(".")[:3]:
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]
