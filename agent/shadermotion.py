"""ShaderMotion preview (prototype): the ShaderMotion strip in an actor's VRChat window, decoded live
on the actor's PC (Windows) while their own UI has the preview open or a director watches.

ffmpeg's gfxcapture (Windows.Graphics.Capture) scales the window on the GPU to ShaderMotion's 80×45
grid with point sampling, which picks each square's centre pixel, so only 80×45 pixels leave the GPU.
Layer 0 is the 12 left columns: 270 slots (humanoid, then the face block), sent to the UI as
"shadermotion" events (peerId "self"), every frame (about 30 a second), or with the reason there are none.

Over a v2 relay a director with the preview open sends shadermotion.watch to actors with the
`shadermotion` capability every WATCH_EVERY_S; each sends its frames (int16, base64) to the directors
it heard from within WATCH_TTL_S, and the director's agent turns them into the same UI events.

VRCAS_SHADERMOTION_SOURCE (testing): a video file to play instead of VRChat (looped, at its own
speed), or a gfxcapture window selector such as "window_title=SMTEST".
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import statistics
import struct
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from . import vrchat_window

if TYPE_CHECKING:
    from .core import Agent

log = logging.getLogger("vrcas")

SQUARES = 12  # layer 0: 6 slot columns of 2 squares
ROWS = 45
FRAME_BYTES = SQUARES * ROWS * 4  # BGRA
NO_FRAMES_S = 1.0
RETRY_S = 2.0
STATS_S = 10.0
WATCH_EVERY_S = 5.0
WATCH_TTL_S = 15.0
PACK = struct.Struct("<270h")  # a frame on the relay: 270 slot values × 32767
FFMPEG_DIRS = (Path(r"C:\ffmpeg\bin"),)

# Tile decoder, from ShaderMotion/tools/decode_frame_lib.py (a port of Shader/Codec.hlsl DecodeVideoSnorm):
# each square's RGB holds three base-3 Gray-code digits in GRB order; a slot is two squares side by side.
RADIX, LEN = 3, 2
POW = RADIX ** (LEN * 3)


def _enc_add(state, x):
    sx, sy, sz = state
    x = RADIX - 1 - x if int(sx) & 1 else x
    r = round(x)
    return [sx * RADIX + r, sy if r == 0 else x - r, sz if r == RADIX - 1 else x - r]


def _enc_sum(state):
    sx, sy, sz = state
    px, py = max(0, sz * 2), max(0, sy * -2)
    return (min(px, py) / max(max(px, py) - px * py, 1e-5) * (px - py) + (px - py)) * 0.5 + sx


def decode_slot(c0, c1) -> float:
    """c0, c1: gamma-space RGB in [0, 1] of a slot's first and second square → a value in [-1, 1]."""
    st = [0, 0, 0]
    for r, g, b in (c0, c1):
        st = _enc_add(st, g * 2)
        st = _enc_add(st, r * 2)
        st = _enc_add(st, b * 2)
    st[0] -= (POW - 1) / 2
    return _enc_sum(st) / ((POW - 1) / 2)


def decode_frame(buf: bytes) -> list[float]:
    """One 12×45 BGRA frame (a pixel per square, top row first) → layer 0's 270 slot values."""
    def rgb(x: int, y: int):
        i = (y * SQUARES + x) * 4
        return buf[i + 2] / 255, buf[i + 1] / 255, buf[i] / 255
    return [round(decode_slot(rgb(2 * c, row), rgb(2 * c + 1, row)), 4) for c in range(SQUARES // 2) for row in range(ROWS)]


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or next((str(p) for d in FFMPEG_DIRS if (p := d / "ffmpeg.exe").is_file()), None)


def command(ffmpeg: str, source: str) -> list[str]:
    """ffmpeg writing 12×45 BGRA frames to stdout. source: a video file, or a gfxcapture window selector."""
    if Path(source).is_file():
        # a recording: crop, even out compression noise around each centre, one sample per square (decode_all.py).
        # RGB before the blur: blurring the video's YUV gave a face header of 0.93, -0.94, 0.24 instead of 0.5, -0.5, 0.125
        inp = ["-re", "-stream_loop", "-1", "-i", source]
        vf = f"fps=30,crop=iw*{SQUARES}/80:ih:0:0,format=gbrp,avgblur=sizeX=3:sizeY=3,scale={SQUARES}:{ROWS}:flags=neighbor,format=bgra"
    else:
        # frames snap to the display's refresh: a cap of 30 got 26.6/s on a 60 Hz screen (a frame now and then
        # waits an extra refresh), 32 gets 29.9/s
        grab = f"gfxcapture={source}:capture_cursor=0:max_framerate=32:width=80:height=45:resize_mode=scale:scale_mode=point"
        inp = ["-f", "lavfi", "-i", f"{grab},hwdownload,format=bgra"]
        vf = f"crop={SQUARES}:{ROWS}:0:0"
    # passthrough: the default constant frame rate duplicates frames and costs about a frame (median 107 → 80 ms)
    return [ffmpeg, "-hide_banner", "-loglevel", "error", *inp, "-an", "-vf", vf, "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-"]


def pack(slots: list[float]) -> str:
    return base64.b64encode(PACK.pack(*(round(max(-1.0, min(1.0, v)) * 32767) for v in slots))).decode()


def unpack(text: str) -> list[float]:
    """Raises ValueError (binascii.Error, struct.error) for anything that isn't a packed frame."""
    return [round(x / 32767, 4) for x in PACK.unpack(base64.b64decode(text, validate=True))]


class ShaderMotion:
    def __init__(self, agent: "Agent"):
        self.agent = agent
        self._local = False  # this PC's UI has the preview open
        self._task: asyncio.Task | None = None  # actor: the capture; director: the repeated watch
        # Actor: director session id → when its watch runs out (monotonic)
        self._watchers: dict[str, float] = {}
        # Director: per actor, since the last log line: [frames, bytes, delays in ms]
        self._stats: dict[str, list] = {}

    def set(self, on: bool) -> None:
        """The local UI opened or closed the preview."""
        self._local = on
        if self.agent.config.role == "director":
            if on and self._task is None:
                self._task = asyncio.create_task(self._watch_loop())
            elif not on and self._task:
                self._task.cancel()
                self._task = None
                asyncio.create_task(self._tell(False))
        else:
            self._ensure()

    async def close(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _relay(self):
        impl = self.agent.relay.impl
        return None if impl.legacy or impl.status != "connected" else impl

    # ==== actor side ===============================================================================

    def watch(self, director: str, on: bool) -> None:
        if on:
            self._watchers[director] = time.monotonic() + WATCH_TTL_S
        else:
            self._watchers.pop(director, None)
        self._ensure()

    def drop(self, directors: list[str]) -> None:
        """The relay says these directors are gone (or never were)."""
        for director in directors:
            self._watchers.pop(director, None)

    def _watching(self) -> list[str]:
        now = time.monotonic()
        self._watchers = {d: until for d, until in self._watchers.items() if until > now}
        return list(self._watchers)

    def _wanted(self) -> bool:
        # A UI that went away without closing the preview (a closed tab) doesn't keep the capture running.
        return (self._local and self.agent.hub.has_clients()) or bool(self._watching())

    def _ensure(self) -> None:
        if self._task is None and self._wanted():
            self._task = asyncio.create_task(self._run())

    async def _send(self, slots: list[float] | None = None, problem: str | None = None) -> None:
        if self._local:
            self.agent.hub.event({"type": "shadermotion", "peerId": "self", "slots": slots,
                                  **({"problem": problem} if problem else {})})
        directors = self._watching()
        relay = self._relay() if directors else None
        if relay:
            now = relay.clock.server_now()
            data = {"slots": pack(slots)} if slots else {"problem": problem}
            try:
                await relay.send("shadermotion.frame", {**data, "t": None if now is None else round(now)}, {"ids": directors})
            except Exception:  # the connection just went; the relay loop reconnects
                pass

    async def _run(self) -> None:
        while self._wanted():
            argv, problem = await asyncio.to_thread(self._command)
            if argv:
                proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
                                                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    await self._read(proc)
                finally:
                    if proc.returncode is None:
                        proc.kill()
                    err = (await proc.stderr.read()).decode(errors="replace").strip()
                    await proc.wait()
                if err:
                    log.info("shadermotion: ffmpeg exited %s: %s", proc.returncode, err.splitlines()[-1])
                if not self._wanted():
                    break
                problem = "Capture stopped"  # the next round says why, if it can (VRChat closed, ...)
            await self._send(problem=problem)
            await asyncio.sleep(RETRY_S)
        self._task = None

    def _command(self) -> tuple[list[str] | None, str | None]:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return None, "ffmpeg wasn't found (PATH or C:\\ffmpeg\\bin)"
        source = os.environ.get("VRCAS_SHADERMOTION_SOURCE", "")
        if not source:
            if sys.platform != "win32":
                return None, "The live preview needs Windows"
            win = vrchat_window.find()
            if not win:
                return None, "VRChat isn't running"
            if win.mode == "minimized":
                return None, "VRChat is minimized"
            source = f"hwnd={win.hwnd}"
        return command(ffmpeg, source), None

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        frames = 0
        decode_s = 0.0
        stats_at = time.monotonic()
        while self._wanted():
            try:
                buf = await asyncio.wait_for(proc.stdout.readexactly(FRAME_BYTES), NO_FRAMES_S)
            except asyncio.TimeoutError:
                await self._send(problem=await asyncio.to_thread(self._no_frames))
                continue
            except asyncio.IncompleteReadError:
                return
            t = time.perf_counter()
            await self._send(decode_frame(buf))
            decode_s += time.perf_counter() - t
            frames += 1
            if (now := time.monotonic()) - stats_at >= STATS_S:
                log.info("shadermotion: %.1f frames/s to %d director(s)%s, decode + send %.2f ms each",
                         frames / (now - stats_at), len(self._watching()), " and this PC's UI" if self._local else "",
                         1000 * decode_s / frames)
                frames = 0
                decode_s = 0.0
                stats_at = now

    @staticmethod
    def _no_frames() -> str:
        win = vrchat_window.find() if sys.platform == "win32" and not os.environ.get("VRCAS_SHADERMOTION_SOURCE") else None
        return "VRChat is minimized" if win and win.mode == "minimized" else "No frames from the window"

    # ==== director side ============================================================================

    async def _watch_loop(self) -> None:
        stats_at = time.monotonic()
        try:
            while self.agent.hub.has_clients():  # a closed tab stops the watch too
                await self._tell(True)
                await asyncio.sleep(WATCH_EVERY_S)
                if (now := time.monotonic()) - stats_at >= STATS_S:
                    self._log_stats(now - stats_at)
                    stats_at = now
        finally:
            self._stats.clear()
        self._task = None
        self._local = False
        await self._tell(False)

    async def _tell(self, on: bool) -> None:
        relay = self._relay()
        ids = [s.id for s in relay.sessions.values() if s.role == "actor" and "shadermotion" in s.capabilities] if relay else []
        if ids:
            try:
                await relay.send("shadermotion.watch", {"on": on}, {"ids": ids})
            except Exception:  # the connection just went; the next round asks again
                pass

    def on_frame(self, env: dict) -> None:
        sender, data = env.get("from"), env.get("data") or {}
        if not self._local or not sender:
            return
        try:
            slots = unpack(data["slots"]) if data.get("slots") else None
        except (ValueError, struct.error):  # binascii.Error is a ValueError
            return
        problem = data.get("problem") or ("No frames" if slots is None else None)
        self.agent.hub.event({"type": "shadermotion", "peerId": sender, "slots": slots, **({"problem": problem} if problem else {})})
        stats = self._stats.setdefault(sender, [0, 0, []])
        stats[0] += 1
        stats[1] += len(json.dumps(env))
        relay = self._relay()
        now = relay.clock.server_now() if relay else None
        if now is not None and isinstance(data.get("t"), int):
            stats[2].append(now - data["t"])

    def _log_stats(self, seconds: float) -> None:
        relay = self._relay()
        for sender, (frames, size, delays) in self._stats.items():
            name = relay.sessions[sender].name if relay and sender in relay.sessions else sender
            delay = f", delay median {statistics.median(delays):.0f} ms, max {max(delays):.0f} ms" if delays else ""
            log.info("shadermotion from %s: %.1f frames/s, %.1f KB/s%s", name, frames / seconds, size / seconds / 1000, delay)
        self._stats.clear()
