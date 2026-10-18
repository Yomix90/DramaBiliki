"""
Load test: how many viewers can the server handle at the same time?

The admin starts a test; a separate process (``python -m bridge.loadtest <config>``)
simulates viewers that behave like the mobile app:
  - open the home feed and a series page (API latency),
  - watch an episode at its real bitrate (a few seconds of buffer first, then paced),
  - swipe to another episode after 15-45 s of playback.
The number of viewers grows step by step (e.g. 5 → 10 → 25 → 50...). For each
step we record the API latency, the video start time, the share of viewers who
watch without buffering, the errors and the server CPU / RAM.
The test stops by itself when the server starts to struggle.

Running in its own process keeps the simulated clients from slowing down the
server's event loop. The traffic stays inside the VPS (loopback or own domain),
so the internet bandwidth of the VPS is estimated separately from its speed.
"""
import asyncio
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from bridge.config import settings

LOADTEST_HEADER = "X-Load-Test"
MAX_USERS = 500
_proc: Optional[subprocess.Popen] = None


def _dir() -> Path:
    path = settings.DATA_DIR / "loadtest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def status_path() -> Path:
    return _dir() / "status.json"


def read_status() -> dict:
    try:
        data = json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "idle", "steps": []}
    if data.get("state") == "running" and not is_running():
        data["state"] = "stopped"
        data["message"] = data.get("message") or "Test interrompu (serveur redémarré ?)"
    return data


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def start(config: dict) -> None:
    global _proc
    if is_running():
        raise RuntimeError("Un test est déjà en cours.")
    cfg_file = _dir() / "config.json"
    cfg_file.write_text(json.dumps(config), encoding="utf-8")
    status_path().write_text(json.dumps({"state": "running", "steps": [], "config": config,
                                         "message": "Démarrage…", "started_at": time.time()}), encoding="utf-8")
    _proc = subprocess.Popen([sys.executable, "-m", "bridge.loadtest", str(cfg_file)],
                             cwd=str(Path(__file__).resolve().parent.parent))


def stop() -> None:
    global _proc
    if is_running():
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None
    data = read_status()
    if data.get("state") == "running" or data.get("state") == "stopped":
        data["state"] = "stopped"
        data["message"] = "Test arrêté."
        finalize(data)
        status_path().write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# System metrics (Linux /proc; empty elsewhere)
# ---------------------------------------------------------------------------

def _cpu_times():
    try:
        with open("/proc/stat") as f:
            parts = [float(x) for x in f.readline().split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        return sum(parts), idle
    except (OSError, ValueError, IndexError):
        return None


def memory_percent() -> Optional[float]:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":", 1)
                info[key] = float(value.split()[0])
        return round(100 * (1 - info["MemAvailable"] / info["MemTotal"]), 1)
    except (OSError, KeyError, ValueError):
        return None


def system_info() -> dict:
    cpus = os.cpu_count() or 1
    mem_total = None
    try:
        with open("/proc/meminfo") as f:
            mem_total = round(float(f.readline().split()[1]) / 1024 ** 2, 1)  # GB
    except (OSError, ValueError, IndexError):
        pass
    return {"cpus": cpus, "ram_gb": mem_total}


class CpuSampler:
    def __init__(self):
        self.last = _cpu_times()
        self.values: List[float] = []

    def sample(self) -> Optional[float]:
        now = _cpu_times()
        if not now or not self.last:
            return None
        total, idle = now[0] - self.last[0], now[1] - self.last[1]
        self.last = now
        if total <= 0:
            return None
        value = round(100 * (1 - idle / total), 1)
        self.values.append(value)
        return value


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def _pct(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 3)


def finalize(data: dict) -> None:
    """Capacity = biggest step where viewers watch smoothly and the API stays fast."""
    ok_steps = [s for s in data.get("steps", []) if s.get("healthy")]
    data["capacity"] = max((s["users"] for s in ok_steps), default=0)
    cfg = data.get("config", {})
    bitrate = cfg.get("bitrate_bps") or 0
    bandwidth = cfg.get("bandwidth_mbps") or 0
    data["network_capacity"] = int(bandwidth * 1e6 * 0.8 / bitrate) if bitrate and bandwidth else None


# ---------------------------------------------------------------------------
# Worker (separate process)
# ---------------------------------------------------------------------------

class Viewer:
    def __init__(self, cfg: dict, stats: dict, stop_at: float):
        self.cfg, self.stats, self.stop_at = cfg, stats, stop_at
        self.stalled = False
        self.watched = False  # at least one video started

    async def run(self, client) -> None:
        import httpx
        headers = {LOADTEST_HEADER: "1"}
        episodes = self.cfg["episodes"]
        while time.time() < self.stop_at:
            ep = random.choice(episodes)
            try:
                t0 = time.time()
                r = await client.get("/api/v1/home", headers=headers)
                r.raise_for_status()
                r = await client.get(f"/api/v1/series/{ep['series_id']}", headers=headers)
                r.raise_for_status()
                self.stats["api"].append(time.time() - t0)
                await self.watch(client, ep, headers)
            except (httpx.HTTPError, OSError) as e:
                self.stalled = True  # the viewer could not watch
                self.stats["errors"] += 1
                self.stats["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
                await asyncio.sleep(1)

    async def watch(self, client, ep: dict, headers: dict) -> None:
        bitrate = max(ep.get("bitrate_bps") or self.cfg["bitrate_bps"], 200_000)
        byte_rate = bitrate / 8
        watch_seconds = random.uniform(15, 45)
        buffer_seconds = 5  # the player buffers ~5 s before starting
        url = f"/stream/{ep['series_id']}/{ep['num']}.mp4"
        t0 = time.time()
        first_byte = None
        received = 0
        complete = False  # whole file downloaded (short episode)
        try:
            async with client.stream("GET", url, headers={**headers, "Range": "bytes=0-"}) as resp:
                if resp.status_code >= 400:
                    raise OSError(f"HTTP {resp.status_code} sur {url}")
                complete = True
                async for chunk in resp.aiter_bytes(64 * 1024):
                    now = time.time()
                    if first_byte is None:
                        first_byte = now - t0
                        self.stats["ttfb"].append(first_byte)
                    received += len(chunk)
                    self.stats["bytes"] += len(chunk)
                    played = max(0.0, now - t0 - first_byte - 1.0)  # playback starts ~1 s after the first byte
                    if played > 2 and received < played * byte_rate:
                        self.stalled = True  # the player would be waiting for data
                    ahead = received / byte_rate - played - buffer_seconds
                    if ahead > 0:
                        await asyncio.sleep(min(ahead, 2))  # pace like a real player
                    if now - t0 > watch_seconds or now > self.stop_at:
                        complete = False
                        break
        except BaseException:
            complete = False
            raise
        finally:
            # Data that never arrived (server blocked, timeout) is a stall too
            elapsed = time.time() - t0
            if first_byte is None:
                if elapsed > 4:
                    self.stalled = True
            else:
                self.watched = True
                played = max(0.0, elapsed - first_byte - 1.0)
                if not complete and played > 2 and received < played * byte_rate * 0.95:
                    self.stalled = True


async def run_worker(cfg_file: str) -> None:
    import httpx
    cfg = json.loads(Path(cfg_file).read_text(encoding="utf-8"))
    data = {"state": "running", "config": cfg, "steps": [], "message": "", "started_at": time.time(),
            "system": system_info()}
    out = status_path()

    def save():
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(out)

    stopping = False

    def on_term(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, on_term)
    limits = httpx.Limits(max_connections=MAX_USERS * 2 + 10, max_keepalive_connections=MAX_USERS * 2)
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(base_url=cfg["base_url"], limits=limits, timeout=timeout, verify=False) as client:
        for users in cfg["steps"]:
            if stopping:
                break
            stats: Dict = {"api": [], "ttfb": [], "bytes": 0, "errors": 0, "last_error": ""}
            stop_at = time.time() + cfg["step_seconds"]
            viewers = [Viewer(cfg, stats, stop_at) for _ in range(users)]
            cpu = CpuSampler()
            mem: List[float] = []
            t_start = time.time()
            data["message"] = f"Palier en cours : {users} spectateurs simultanés"
            data["current"] = {"users": users, "ends_at": stop_at}
            save()

            async def stagger(i, v):
                await asyncio.sleep(i * min(0.05, 3 / max(users, 1)))  # people do not all arrive in the same ms
                await v.run(client)

            tasks = [asyncio.create_task(stagger(i, v)) for i, v in enumerate(viewers)]
            while time.time() < stop_at and not stopping:
                await asyncio.sleep(1)
                cpu.sample()
                m = memory_percent()
                if m is not None:
                    mem.append(m)
                elapsed = time.time() - t_start
                data["current"].update(mbps=round(stats["bytes"] * 8 / elapsed / 1e6, 1), errors=stats["errors"])
                save()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            elapsed = max(time.time() - t_start, 1)
            smooth = sum(1 for v in viewers if not v.stalled)
            requests = len(stats["api"]) + stats["errors"]
            step = {
                "users": users,
                "smooth_pct": round(100 * smooth / users, 1),
                "api_p50": _pct(stats["api"], 0.5),
                "api_p95": _pct(stats["api"], 0.95),
                "ttfb_p50": _pct(stats["ttfb"], 0.5),
                "ttfb_p95": _pct(stats["ttfb"], 0.95),
                "mbps": round(stats["bytes"] * 8 / elapsed / 1e6, 1),
                "errors": stats["errors"],
                "error_pct": round(100 * stats["errors"] / requests, 1) if requests else 0,
                "last_error": stats["last_error"],
                "cpu": round(sum(cpu.values) / len(cpu.values), 1) if cpu.values else None,
                "cpu_max": max(cpu.values) if cpu.values else None,
                "ram": max(mem) if mem else None,
            }
            step["healthy"] = (
                step["smooth_pct"] >= 95
                and step["error_pct"] <= 2
                and (step["api_p95"] or 0) < 2.0
                and (step["ttfb_p95"] or 0) < 4.0
            )
            data["steps"].append(step)
            finalize(data)
            save()
            if not step["healthy"] and cfg.get("stop_on_failure", True):
                data["message"] = f"Arrêt : le serveur sature à {users} spectateurs."
                break
    data.pop("current", None)
    data["state"] = "done" if not stopping else "stopped"
    if not data["message"] or data["message"].startswith("Palier"):
        data["message"] = "Test terminé." if not stopping else "Test arrêté."
    data["finished_at"] = time.time()
    finalize(data)
    save()


if __name__ == "__main__":
    asyncio.run(run_worker(sys.argv[1]))
