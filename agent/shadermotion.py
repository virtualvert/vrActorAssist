"""ShaderMotion preview (prototype, Windows): the ShaderMotion strip in this actor's VRChat window,
decoded live while a UI has the preview open.

ffmpeg's gfxcapture (Windows.Graphics.Capture) scales the window on the GPU to ShaderMotion's 80×45
grid with point sampling, which picks each square's centre pixel, so only 80×45 pixels leave the GPU.
Layer 0 is the 12 left columns: 270 slots (humanoid, then the face block), sent to the UI as
"shadermotion" events (peerId "self"), every frame (about 30 a second), or with the reason there are none.

VRCAS_SHADERMOTION_SOURCE (testing): a video file to play instead of VRChat (looped, at its own
speed), or a gfxcapture window selector such as "window_title=SMTEST".
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

from . import vrchat_window

log = logging.getLogger("vrcas")

SQUARES = 12  # layer 0: 6 slot columns of 2 squares
ROWS = 45
FRAME_BYTES = SQUARES * ROWS * 4  # BGRA
NO_FRAMES_S = 1.0
RETRY_S = 2.0
STATS_S = 10.0
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
        # a recording: crop, even out compression noise around each centre, one sample per square (decode_all.py)
        inp = ["-re", "-stream_loop", "-1", "-i", source]
        vf = f"fps=30,crop=iw*{SQUARES}/80:ih:0:0,avgblur=sizeX=3:sizeY=3,scale={SQUARES}:{ROWS}:flags=neighbor,format=bgra"
    else:
        # frames snap to the display's refresh: a cap of 30 got 26.6/s on a 60 Hz screen (a frame now and then
        # waits an extra refresh), 32 gets 29.9/s
        grab = f"gfxcapture={source}:capture_cursor=0:max_framerate=32:width=80:height=45:resize_mode=scale:scale_mode=point"
        inp = ["-f", "lavfi", "-i", f"{grab},hwdownload,format=bgra"]
        vf = f"crop={SQUARES}:{ROWS}:0:0"
    # passthrough: the default constant frame rate duplicates frames and costs about a frame (median 107 → 80 ms)
    return [ffmpeg, "-hide_banner", "-loglevel", "error", *inp, "-an", "-vf", vf, "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-"]


class ShaderMotion:
    def __init__(self, emit: Callable[[dict], None], viewers: Callable[[], bool]):
        self._emit = emit
        self._viewers = viewers
        self._task: asyncio.Task | None = None

    def set(self, on: bool) -> None:
        if on and self._task is None:
            self._task = asyncio.create_task(self._run())
        elif not on and self._task:
            self._task.cancel()
            self._task = None

    async def close(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _send(self, slots: list[float] | None = None, problem: str | None = None) -> None:
        self._emit({"type": "shadermotion", "peerId": "self", "slots": slots, **({"problem": problem} if problem else {})})

    async def _run(self) -> None:
        # A UI that went away without closing the preview (a closed tab) doesn't keep the capture running.
        while self._viewers():
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
                problem = "Capture stopped"  # the next round says why, if it can (VRChat closed, ...)
                if err:
                    log.info("shadermotion: ffmpeg exited %s: %s", proc.returncode, err.splitlines()[-1])
            if problem:
                self._send(problem=problem)
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
        while self._viewers():
            try:
                buf = await asyncio.wait_for(proc.stdout.readexactly(FRAME_BYTES), NO_FRAMES_S)
            except asyncio.TimeoutError:
                self._send(problem=await asyncio.to_thread(self._no_frames))
                continue
            except asyncio.IncompleteReadError:
                return
            t = time.perf_counter()
            self._send(decode_frame(buf))
            decode_s += time.perf_counter() - t
            frames += 1
            if (now := time.monotonic()) - stats_at >= STATS_S:
                log.info("shadermotion: %.1f frames/s, decode %.2f ms each", frames / (now - stats_at), 1000 * decode_s / frames)
                frames = 0
                decode_s = 0.0
                stats_at = now

    @staticmethod
    def _no_frames() -> str:
        win = vrchat_window.find() if sys.platform == "win32" and not os.environ.get("VRCAS_SHADERMOTION_SOURCE") else None
        return "VRChat is minimized" if win and win.mode == "minimized" else "No frames from the window"
