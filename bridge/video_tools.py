"""
ffmpeg helpers: probe duration/size, extract a thumbnail, remux .ts → .mp4.

Remuxing copies the streams (no re-encoding, a few seconds even for large files)
into an MP4 with the index at the start ("faststart"), which phones play and
seek much better than MPEG-TS. Every helper degrades gracefully when ffmpeg is
not installed.
"""
import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bridge.video_tools")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def _run(*args: str, timeout: float = 1800) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        logger.debug(f"{args[0]} failed: {stderr.decode(errors='ignore')[-500:]}")
    return proc.returncode


async def probe(path: Path) -> dict:
    """Returns {'duration': seconds, 'width': px, 'height': px} (zeros when unknown)."""
    info = {"duration": 0, "width": 0, "height": 0}
    if not ffmpeg_available():
        return info
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        data = json.loads(out or b"{}")
        info["duration"] = int(float(data.get("format", {}).get("duration") or 0))
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = int(stream.get("width") or 0)
                info["height"] = int(stream.get("height") or 0)
                break
    except (ValueError, TypeError):
        pass
    return info


async def remux_to_mp4(src: Path, dst: Path) -> bool:
    """Copies the streams into a faststart MP4; re-encodes only the audio if it must."""
    if not ffmpeg_available():
        return False
    base = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0?", "-map", "0:a:0?"]
    tail = ["-movflags", "+faststart", str(dst)]
    if await _run(*base, "-c", "copy", "-bsf:a", "aac_adtstoasc", *tail) == 0 and dst.exists():
        return True
    if await _run(*base, "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", *tail) == 0 and dst.exists():
        return True
    dst.unlink(missing_ok=True)
    return False


async def thumbnail(src: Path, dst: Path, duration: int = 0) -> bool:
    """Grabs a frame at ~10% of the video as a JPEG."""
    if not ffmpeg_available():
        return False
    at = max(1, int(duration * 0.1)) if duration else 3
    ok = await _run("ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(src),
                    "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "3", str(dst), timeout=120) == 0
    if not ok or not dst.exists():
        ok = await _run("ffmpeg", "-y", "-v", "error", "-i", str(src),
                        "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "3", str(dst), timeout=120) == 0
    return ok and dst.exists()
