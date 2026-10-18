"""
Performance: lighter videos and a disk cache for Telegram episodes.

1. Compression — videos are re-encoded to ~720p H.264 with a capped bitrate
   (≈1.2 Mbit/s) when the source is heavier. A typical 1080p short-drama
   episode shrinks by 50-70 %: each viewer costs half the outgoing traffic.
   Uploads are compressed before being stored; Telegram episodes are
   compressed when they enter the cache (the original stays on Telegram).

2. Disk cache — the most watched Telegram episodes are kept on the VPS disk
   (size-limited, least recently watched removed first). Served from disk they
   no longer go through Telegram: no incoming download, no MTProto decryption.
   The episodes with the most requests are processed first.

Encoding runs one at a time with a low CPU priority (nice), so viewers are
always served first on a small VPS.
"""
import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from bridge import app_settings
from bridge.config import settings
from bridge.video_tools import _run, ffmpeg_available, probe

logger = logging.getLogger("bridge.optimizer")

CACHE_DIR = settings.MEDIA_DIR / "videos" / "cache"
MAX_PENDING = 500
TOUCH_EVERY = 600  # refresh a cached file's mtime (LRU) at most every 10 min

_encode_lock: Optional[asyncio.Lock] = None


def encode_lock() -> asyncio.Lock:
    """One encoding at a time on the whole server (uploads + cache)."""
    global _encode_lock
    if _encode_lock is None:
        _encode_lock = asyncio.Lock()
    return _encode_lock


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def target_bitrate() -> int:
    return max(300, app_settings.get_int("perf_maxrate_kbps", 1200)) * 1000


def needs_compression(size: int, duration: int) -> bool:
    """True when the video is clearly heavier than the target bitrate."""
    if not app_settings.get_bool("perf_optimize") or not size or not duration or duration < 5:
        return False
    return size * 8 / duration > target_bitrate() * 1.3


async def compress(src: Path, dst: Path) -> bool:
    """Re-encodes to H.264 (max 720p on the short side), AAC audio, faststart MP4.
    Returns True only when the result exists and is at least 15 % smaller."""
    if not ffmpeg_available():
        return False
    side = app_settings.get_int("perf_max_height", 720)
    crf = app_settings.get_int("perf_crf", 27)
    maxrate = target_bitrate() // 1000
    # Limit the short side (portrait 1080x1920 -> 720x1280), never upscale
    info = await probe(src)
    w, h = info["width"], info["height"]
    if w and h and min(w, h) > side:
        ratio = side / min(w, h)
        w, h = int(w * ratio) // 2 * 2, int(h * ratio) // 2 * 2
    scale = f"scale={w}:{h}" if w and h else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    nice = ["nice", "-n", "15"] if os.name != "nt" and shutil.which("nice") else []
    args = [
        *nice, "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", scale,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-profile:v", "high",
        "-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2",
        "-movflags", "+faststart", "-threads", "2", str(dst),
    ]
    async with encode_lock():
        try:
            code = await _run(*args, timeout=3600)
        except asyncio.TimeoutError:
            code = -1
    if code != 0 or not dst.exists():
        dst.unlink(missing_ok=True)
        return False
    if dst.stat().st_size > src.stat().st_size * 0.85:
        dst.unlink(missing_ok=True)  # not worth it: keep the original
        return False
    return True


# ---------------------------------------------------------------------------
# Disk cache of Telegram episodes
# ---------------------------------------------------------------------------

def cache_key(peer_id: int, message_id: int) -> str:
    return f"{abs(peer_id)}_{message_id}"


def cache_path(peer_id: int, message_id: int) -> Path:
    return CACHE_DIR / f"{cache_key(peer_id, message_id)}.mp4"


class TelegramCache:
    def __init__(self):
        self._requests: Dict[str, int] = {}
        self._pending: Dict[str, Tuple[int, Optional[int], int]] = {}  # key -> (peer, access hash, message)
        self._touched: Dict[str, float] = {}
        self._worker: Optional[asyncio.Task] = None
        self._wake: Optional[asyncio.Event] = None
        self.current = ""
        self.saved_bytes = 0
        self.processed = 0
        self.failures = 0

    @staticmethod
    def enabled() -> bool:
        return app_settings.get_bool("perf_cache_enabled")

    def lookup(self, peer_id: int, message_id: int) -> Optional[Path]:
        """Cached file for this episode, refreshing its LRU date."""
        path = cache_path(peer_id, message_id)
        if not path.is_file():
            return None
        key = path.stem
        now = time.time()
        if now - self._touched.get(key, 0) > TOUCH_EVERY:
            self._touched[key] = now
            try:
                os.utime(path, None)
            except OSError:
                pass
        return path

    def note_request(self, peer_id: int, access_hash: Optional[int], message_id: int) -> None:
        """Counts a viewer of a Telegram episode not yet cached and queues it."""
        if not self.enabled():
            return
        key = cache_key(peer_id, message_id)
        self._requests[key] = self._requests.get(key, 0) + 1
        if key in self._pending or len(self._pending) >= MAX_PENDING:
            return
        self._pending[key] = (peer_id, access_hash, message_id)
        if self._worker is None or self._worker.done():
            self._wake = asyncio.Event()
            self._worker = asyncio.create_task(self._run())
        self._wake.set()

    async def _run(self) -> None:
        while True:
            if not self._pending:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=600)
                except asyncio.TimeoutError:
                    return  # idle: the worker restarts with the next request
                continue
            if not self.enabled():
                self._pending.clear()
                continue
            # Most requested episode first
            key = max(self._pending, key=lambda k: self._requests.get(k, 0))
            peer_id, access_hash, message_id = self._pending.pop(key)
            self.current = key
            try:
                await self._cache_one(peer_id, access_hash, message_id)
                self.processed += 1
            except Exception as e:
                self.failures += 1
                logger.warning(f"Cache of Telegram video {key} failed: {e}")
            finally:
                self.current = ""
            self._requests.pop(key, None)
            await asyncio.sleep(1)

    async def _cache_one(self, peer_id: int, access_hash: Optional[int], message_id: int) -> None:
        from bridge.telegram.client import telegram_service
        final = cache_path(peer_id, message_id)
        if final.is_file():
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        raw = final.with_suffix(".download")
        opt = final.with_suffix(".opt.mp4")
        try:
            message = await telegram_service.get_message(peer_id, access_hash, message_id)
            size = message.file.size or 0
            self.evict(extra=size)
            async with telegram_service.downloading(message):
                await message.download_media(file=str(raw))
            duration = int(getattr(message.file, "duration", None) or 0)
            if needs_compression(raw.stat().st_size, duration) and await compress(raw, opt):
                self.saved_bytes += raw.stat().st_size - opt.stat().st_size
                opt.replace(final)
            else:
                raw.replace(final)
        finally:
            raw.unlink(missing_ok=True)
            opt.unlink(missing_ok=True)
        self.evict()

    def evict(self, extra: int = 0) -> int:
        """Deletes the least recently watched files above the size limit. Returns bytes freed."""
        limit = max(1.0, float(app_settings.get("perf_cache_max_gb") or 15)) * 1024 ** 3
        files = [f for f in CACHE_DIR.glob("*.mp4") if not f.name.endswith(".opt.mp4")] if CACHE_DIR.exists() else []
        entries = []
        for f in files:
            try:
                st = f.stat()
                entries.append((st.st_mtime, st.st_size, f))
            except OSError:
                pass
        total = sum(e[1] for e in entries) + extra
        freed = 0
        for _, size, f in sorted(entries):
            if total <= limit:
                break
            try:
                f.unlink()
                total -= size
                freed += size
            except OSError:
                pass
        return freed

    def clear(self) -> int:
        freed = 0
        if CACHE_DIR.exists():
            for f in CACHE_DIR.iterdir():
                try:
                    freed += f.stat().st_size
                    f.unlink()
                except OSError:
                    pass
        return freed

    def stats(self) -> dict:
        files = list(CACHE_DIR.glob("*.mp4")) if CACHE_DIR.exists() else []
        size = 0
        for f in files:
            try:
                size += f.stat().st_size
            except OSError:
                pass
        return {
            "enabled": self.enabled(),
            "files": len(files),
            "size": size,
            "limit": max(1.0, float(app_settings.get("perf_cache_max_gb") or 15)) * 1024 ** 3,
            "pending": len(self._pending),
            "current": self.current,
            "processed": self.processed,
            "failures": self.failures,
            "saved_bytes": self.saved_bytes,
        }


telegram_cache = TelegramCache()


# ---------------------------------------------------------------------------
# Version pinning: a playback keeps the same file for all its Range requests
# ---------------------------------------------------------------------------

_pins: Dict[Tuple[str, int, int], Tuple[float, str]] = {}
PIN_SECONDS = 3 * 3600


def choose_version(client: str, series_id: int, ep: int, range_start: int, cache_available: bool) -> str:
    """'cache' or 'origin'. A new playback (range from 0) takes the best version;
    following requests keep it, so the bytes never change in the middle of a video."""
    key = (client, series_id, ep)
    now = time.time()
    if len(_pins) > 20000:
        for k in [k for k, v in _pins.items() if now - v[0] > PIN_SECONDS]:
            _pins.pop(k, None)
    pinned = _pins.get(key)
    if range_start == 0 or pinned is None or now - pinned[0] > PIN_SECONDS:
        version = "cache" if cache_available else "origin"
    else:
        version = pinned[1]
        if version == "cache" and not cache_available:
            version = "origin"
    _pins[key] = (now, version)
    return version
