"""DFR1154 audio proxy.

* One persistent ffmpeg pulls /audio.wav from the camera. It always runs,
  so audio levels are recorded even if nobody is listening.
* ffmpeg emits two things:
    - AAC ADTS on stdout, broadcast to every /audio.aac subscriber
    - astats metadata on stderr, parsed for RMS_level (5 Hz)
* Levels are kept in a 5-minute ring buffer and served as JSON at
  /levels.json. Client polls every couple of seconds and draws a graph.
"""
import array
import asyncio
import logging
import os
import signal
import time
from collections import deque
from aiohttp import web

UPSTREAM = os.environ.get("UPSTREAM", "http://192.168.2.104:82/audio.wav")
PORT = int(os.environ.get("PORT", "8090"))
AUDIO_GAIN_DB = int(os.environ.get("AUDIO_GAIN_DB", "12"))

# RMS computed in Python over 200 ms windows of raw 16 kHz / mono / s16le PCM.
PCM_RATE = 16000
SAMPLES_PER_WIN = 3200          # 200 ms
BYTES_PER_WIN = SAMPLES_PER_WIN * 2

LEVEL_RATE_HZ = PCM_RATE // SAMPLES_PER_WIN   # = 5
LEVEL_WINDOW_SECONDS = 300                     # 5 min
LEVEL_MAX = LEVEL_RATE_HZ * LEVEL_WINDOW_SECONDS

WATCHDOG_INTERVAL_S = 5            # check cadence
WATCHDOG_STALL_S = int(os.environ.get("WATCHDOG_STALL_S", "15"))
WATCHDOG_STARTUP_GRACE_S = int(os.environ.get("WATCHDOG_STARTUP_GRACE_S", "30"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("audio-proxy")


class LevelMonitor:
    """Rolling buffers of RMS + peak (both linear 0-1)."""

    def __init__(self, maxlen: int):
        self.rms: deque[float] = deque(maxlen=maxlen)
        self.peak: deque[float] = deque(maxlen=maxlen)
        self.last_ts: float = 0.0

    def push(self, rms: float, peak: float):
        self.rms.append(max(0.0, min(1.0, rms)))
        self.peak.append(max(0.0, min(1.0, peak)))
        self.last_ts = time.time()

    def snapshot(self) -> dict:
        return {
            "rate": LEVEL_RATE_HZ,
            "end_ts": self.last_ts,
            "samples": list(self.peak),    # bars in the graph use peak
            "rms": list(self.rms),         # the text readout uses rms
            "max": LEVEL_MAX,
        }


level_monitor = LevelMonitor(LEVEL_MAX)


# ─────────────────────── broadcaster ───────────────────────
class Broadcaster:
    """Persistent ffmpeg, fan-out to N audio.aac subscribers."""

    def __init__(self, upstream: str):
        self.upstream = upstream
        self.proc: asyncio.subprocess.Process | None = None
        self.decoder: asyncio.subprocess.Process | None = None
        self.subscribers: set[asyncio.Queue[bytes]] = set()
        self.feeder_task: asyncio.Task | None = None
        self.pcm_task: asyncio.Task | None = None
        self.runner_task: asyncio.Task | None = None
        self.watchdog_task: asyncio.Task | None = None
        self.last_spawn_ts: float = 0.0

    async def start(self):
        self.runner_task = asyncio.create_task(self._run_forever())
        self.watchdog_task = asyncio.create_task(self._watchdog())

    async def _run_forever(self):
        # Exponential backoff, capped. Reset to 1 after a run stays healthy long
        # enough so a brief AP blip doesn't permanently slow reconnection.
        backoff = 1
        HEALTHY_RUN_S = 60
        while True:
            run_start = time.time()
            try:
                await self._spawn_ffmpeg()
                await self.proc.wait()
            except Exception as e:
                log.warning("ffmpeg crashed: %s", e)
            finally:
                # Always tear the WHOLE pipeline down before respawning. Without
                # this, every restart (e.g. camera offline) orphaned the decoder
                # ffmpeg and its pcm reader task → unbounded process/memory leak.
                await self._teardown()
            if time.time() - run_start >= HEALTHY_RUN_S:
                backoff = 1
            log.info("ffmpeg exited; restart in %ds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _teardown(self):
        """Cancel feeder/pcm tasks, EOF the decoder, kill + REAP both ffmpegs.
        Idempotent and exception-safe — runs on every restart cycle."""
        for t in (self.feeder_task, self.pcm_task):
            if t is not None and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        self.feeder_task = None
        self.pcm_task = None
        # Kill the decoder first (closing its stdin gives it EOF), then primary.
        for p in (self.decoder, self.proc):
            if p is None:
                continue
            try:
                if p.stdin is not None and not p.stdin.is_closing():
                    p.stdin.close()
            except Exception:
                pass
            if p.returncode is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            try:
                await p.wait()          # reap — no zombies / leaked transports
            except Exception:
                pass
        self.proc = None
        self.decoder = None

    async def _spawn_ffmpeg(self):
        log.info("starting ffmpeg → %s", self.upstream)
        self.last_spawn_ts = time.time()
        # Primary ffmpeg: camera /audio.wav → AAC on stdout (+20 dB).
        self.proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", self.upstream,
            "-af", f"volume={AUDIO_GAIN_DB}dB",
            "-c:a", "aac", "-b:a", "64k",
            "-ar", "16000", "-ac", "1",
            "-f", "adts", "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        log.info("ffmpeg(aac) pid=%s", self.proc.pid)

        # Decoder ffmpeg: AAC stdin → 16 kHz mono PCM stdout (for level analysis).
        # Avoids touching the camera again; we tee the AAC stream we already
        # produce so the camera's single audio.wav slot stays free.
        self.decoder = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-f", "aac", "-i", "-",
            "-ar", "16000", "-ac", "1",
            "-f", "s16le", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        log.info("ffmpeg(decoder) pid=%s", self.decoder.pid)

        self.feeder_task = asyncio.create_task(self._feed_stdout())
        self.pcm_task = asyncio.create_task(self._feed_pcm())

    async def _feed_stdout(self):
        """Read AAC from primary ffmpeg, broadcast AND feed the decoder."""
        assert self.proc is not None and self.proc.stdout is not None
        try:
            while True:
                chunk = await self.proc.stdout.read(4096)
                if not chunk:
                    break
                # Tee into the decoder's stdin
                if self.decoder and self.decoder.stdin and not self.decoder.stdin.is_closing():
                    try:
                        self.decoder.stdin.write(chunk)
                    except (ConnectionResetError, BrokenPipeError):
                        pass
                # Broadcast to all current /audio.aac subscribers
                for q in list(self.subscribers):
                    if q.qsize() > 32:
                        try: q.get_nowait()
                        except asyncio.QueueEmpty: pass
                    q.put_nowait(chunk)
        except Exception as e:
            log.warning("stdout feeder error: %s", e)

    async def _feed_pcm(self):
        """Read PCM, compute RMS + peak amplitude per 200 ms window."""
        assert self.decoder is not None and self.decoder.stdout is not None
        try:
            while True:
                try:
                    chunk = await self.decoder.stdout.readexactly(BYTES_PER_WIN)
                except asyncio.IncompleteReadError:
                    break
                samples = array.array("h")
                samples.frombytes(chunk)
                sq_sum = 0
                pk = 0
                for s in samples:
                    sq_sum += s * s
                    a = -s if s < 0 else s
                    if a > pk:
                        pk = a
                rms = (sq_sum / SAMPLES_PER_WIN) ** 0.5 / 32768.0
                peak = pk / 32768.0
                level_monitor.push(rms, peak)
        except Exception as e:
            log.warning("pcm feeder error: %s", e)

    async def _watchdog(self):
        """Kill ffmpeg if level samples stop arriving — primary may live with
        no output (upstream silently stalled), so proc.wait() never returns."""
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL_S)
            if self.proc is None or self.proc.returncode is not None:
                continue
            now = time.time()
            if now - self.last_spawn_ts < WATCHDOG_STARTUP_GRACE_S:
                continue
            stall = now - level_monitor.last_ts if level_monitor.last_ts else float("inf")
            if stall <= WATCHDOG_STALL_S:
                continue
            log.warning("watchdog: no level samples for %.1fs — killing pipeline "
                        "(primary=%s decoder=%s)",
                        stall, self.proc.pid,
                        self.decoder.pid if self.decoder else None)
            for p in (self.proc, self.decoder):
                if p is None or p.returncode is not None:
                    continue
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    async def subscribe(self) -> asyncio.Queue[bytes]:
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self.subscribers.add(q)
        return q

    async def unsubscribe(self, q):
        self.subscribers.discard(q)


broadcaster = Broadcaster(UPSTREAM)


# ─────────────────────── HTTP handlers ───────────────────────
def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Connection": "close",
    }


async def handle_audio(request):
    if request.method == "HEAD":
        return web.Response(
            headers={**cors_headers(), "Content-Type": "audio/aac"}
        )
    log.info("audio subscribe: %s (%d listeners)",
             request.remote, len(broadcaster.subscribers) + 1)
    q = await broadcaster.subscribe()
    resp = web.StreamResponse(
        headers={**cors_headers(), "Content-Type": "audio/aac"}
    )
    await resp.prepare(request)
    bytes_sent = 0
    try:
        while True:
            chunk = await q.get()
            if not chunk:
                break
            await resp.write(chunk)
            bytes_sent += len(chunk)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        await broadcaster.unsubscribe(q)
        log.info("audio unsubscribe: %s sent=%d (%d left)",
                 request.remote, bytes_sent, len(broadcaster.subscribers))
    return resp


async def handle_levels(request):
    snap = level_monitor.snapshot()
    return web.json_response(snap, headers=cors_headers())


async def on_startup(_app):
    await broadcaster.start()


app = web.Application()
app.on_startup.append(on_startup)
app.router.add_get("/audio.aac", handle_audio)
app.router.add_get("/levels.json", handle_levels)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
