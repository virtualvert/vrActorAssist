"""What an actor's machine does with cues: Soundpad playback and VRChat OSC parameters.

Soundpad goes through its named pipe (soundpad_pipe.py, spec §8.1) when Soundpad answers on it.
When it doesn't, cues fall back to soundpad.py (`Soundpad.exe -rc`), which can play and stop but
can't report anything back.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Callable

import soundpad

from .soundpad_pipe import (
    Playback,
    SoundpadError,
    SoundpadPipe,
    SoundpadTimeout,
    SoundpadUnavailable,
    as_int,
)

if TYPE_CHECKING:
    from .config import Config

try:
    from pythonosc import udp_client
except ImportError:  # optional dependency
    udp_client = None

POLL_PLAYING_S = 0.25
POLL_IDLE_S = 1.0
# How long after a play command to watch for the start, and how many position steps to use
MEASURE_FOR_S = 3.0
MEASURE_STEPS = 3
LATENCY_SAMPLES = 5


def osc_address(parameter: str) -> str:
    """`RecIcon` → /avatar/parameters/RecIcon; a leading slash means a full address."""
    return parameter if parameter.startswith("/") else f"/avatar/parameters/{parameter}"


def osc_value(value: Any) -> Any:
    """VRChat needs typed values: bool for toggles, numbers for floats/ints. Text (the v0.3
    OSC_CUE) is converted; values that are already typed (v2 osc.param) pass through."""
    if not isinstance(value, str):
        return value
    lowered = value.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        number = float(lowered)
    except ValueError:
        return value
    return int(number) if lowered.lstrip("-").isdigit() else number


def parse_cue(command: str) -> tuple[str, int | None] | None:
    """`*go` → ("go", None), `*stop` → ("stop", None), `*play:5` → ("play", 5); else None."""
    cmd = command.strip().lower().lstrip("*")
    if cmd in ("go", "stop"):
        return cmd, None
    if cmd.startswith("play:"):
        index = cmd[5:].strip()
        if index.isdigit() and int(index) > 0:
            return "play", int(index)
    return None


class ActorRuntime:
    def __init__(
        self,
        config: "Config",
        changed: Callable[[], None] = lambda: None,
        log: Callable[[str, str], None] = lambda level, text: None,
        pipe_factory: Callable[[], SoundpadPipe] | None = None,
    ):
        self._config = config
        self._changed = changed
        self._log = log
        self._pipe_factory = pipe_factory or (SoundpadPipe if soundpad.is_windows() else None)
        self._soundpad_path: str | None = None
        self._soundpad_checked = False
        self._osc_client: Any = None
        self._osc_target: tuple[str, int] | None = None
        self._pipe: SoundpadPipe | None = None
        self._poll_task: asyncio.Task | None = None
        self._measure_task: asyncio.Task | None = None
        self._playback: Playback | None = None
        self._title: str | None = None
        self._wake_poll = asyncio.Event()  # a cue just ran: poll now instead of after the idle wait
        # Measured start latencies in ms (command → audio), newest last (spec §8.2.3)
        self.start_latencies: deque[float] = deque(maxlen=LATENCY_SAMPLES)

    # ---- lifecycle ------------------------------------------------------------

    async def refresh(self) -> None:
        """Re-read the Soundpad settings: find Soundpad.exe off the event loop (auto-detect can
        walk Program Files) and open or close the pipe client."""
        soundpad.set_soundpad_path(self._config.soundpad.path or None)
        if soundpad.is_windows():
            self._soundpad_path = await asyncio.to_thread(soundpad.get_soundpad_path)
        self._soundpad_checked = True
        wanted = self._pipe_factory is not None and self._config.role == "actor" and self._config.soundpad.enabled
        if wanted and self._pipe is None:
            self._pipe = self._pipe_factory()
            self._pipe.start()
            self._poll_task = asyncio.get_running_loop().create_task(self._poll(self._pipe))
        elif not wanted:
            await self.close()

    async def close(self) -> None:
        for task in (self._poll_task, self._measure_task):
            if task:
                task.cancel()
        self._poll_task = self._measure_task = None
        pipe, self._pipe = self._pipe, None
        self._playback = None
        if pipe is not None:
            await asyncio.to_thread(pipe.close)

    # ---- state for the UI -------------------------------------------------------

    @property
    def live_status(self) -> str | None:
        """Soundpad's real play status, or None when only the command line (or nothing) is there."""
        return self._playback.status if self._pipe_live() and self._playback else None

    @property
    def start_latency_ms(self) -> float | None:
        return statistics.median(self.start_latencies) if self.start_latencies else None

    def _pipe_live(self) -> bool:
        return self._pipe is not None and self._pipe.connected and self._pipe.info is not None

    def soundpad_state(self) -> dict:
        sp = self._config.soundpad
        state = {"enabled": sp.enabled, "info": None, "playback": None}
        if not sp.enabled:
            return {**state, "state": "disabled", "detail": "Cues are received, but nothing plays."}
        if self._pipe_live():
            info = self._pipe.info
            playback = self._playback
            return {
                **state,
                "state": "ready",
                "detail": "Connected through Soundpad's remote-control pipe."
                + ("" if info.rc_supported else f" Remote control {info.rc_version} is older than 1.1.2, so some commands may fail."),
                "info": {"version": info.version, "rcVersion": info.rc_version, "trial": info.trial},
                "playback": None
                if playback is None
                else {
                    "status": playback.status,
                    "positionMs": playback.position_ms,
                    "durationMs": playback.duration_ms,
                    "title": self._title if playback.status != "STOPPED" else None,
                },
            }
        if not soundpad.is_windows():
            return {**state, "state": "simulated", "detail": "Soundpad only runs on Windows, so cues are simulated here."}
        if not self._soundpad_checked:
            return {**state, "state": "missing", "detail": "Looking for Soundpad…"}
        reason = (self._pipe.last_error if self._pipe else None) or "Soundpad isn't answering on its remote-control pipe"
        if self._soundpad_path:
            return {
                **state,
                "state": "fallback",
                "detail": f"{reason}. Cues fall back to {self._soundpad_path} -rc, which can't report playback.",
            }
        return {**state, "state": "missing", "detail": f"{reason}, and Soundpad.exe wasn't found. Start Soundpad, or set its path in Settings → Actor."}

    def osc_state(self) -> dict:
        osc = self._config.osc
        return {"enabled": osc.enabled, "host": osc.host, "port": osc.port, "ready": osc.enabled and udp_client is not None}

    # ---- cues -------------------------------------------------------------------

    async def run_cue(self, command: str) -> tuple[bool, str | None]:
        """Execute *go / *stop / *play:N. Returns (ok, error message)."""
        if not self._config.soundpad.enabled:
            return True, None
        cue = parse_cue(command)
        if cue is None:
            return False, f"Unknown command: {command}"
        if self._pipe is not None:
            try:
                return await self._pipe_cue(self._pipe, *cue)
            except SoundpadUnavailable:
                pass  # nothing was sent, so the command line can try
            except (SoundpadTimeout, SoundpadError) as exc:
                self._changed()
                return False, str(exc)
        if not soundpad.is_windows():
            return True, None  # soundpad.py would only print "simulating"
        return await asyncio.to_thread(soundpad.execute_command, command, "")

    async def _pipe_cue(self, pipe: SoundpadPipe, action: str, index: int | None) -> tuple[bool, str | None]:
        if action == "stop":
            self._cancel_measure()
            await pipe.stop()
            await self._read_playback(pipe)
            return True, None
        if action == "go":
            reply = await pipe.play_selected()
        else:
            reply = await pipe.play(index)
        self._title = None
        self._cancel_measure()
        self._measure_task = asyncio.get_running_loop().create_task(self._measure_start(pipe, reply.sent_at, index))
        self._wake_poll.set()
        return True, None

    def _cancel_measure(self) -> None:
        if self._measure_task:
            self._measure_task.cancel()
            self._measure_task = None

    async def _measure_start(self, pipe: SoundpadPipe, sent_at: float, index: int | None) -> None:
        """Time from the play command to audio, for spec §8.2.3.

        GetPlayStatus says PLAYING within a few ms, before any audio. The position stays 0 for a
        while and then moves in steps about 140 ms apart, so the start is read off the moments the
        position changes: start = (time of the change − command time) − position.
        """
        try:
            if index is not None:
                sounds = await pipe.sounds(index, index)
                self._title = sounds[0].title if sounds else None
            playing_ms = None
            steps: list[tuple[float, int]] = []
            last_position = None
            while time.perf_counter() - sent_at < MEASURE_FOR_S and len(steps) < MEASURE_STEPS:
                status = await pipe.acall("GetPlayStatus()")
                if status.text == "PLAYING":
                    if playing_ms is None:
                        playing_ms = (status.sent_at - sent_at) * 1000
                        await self._read_playback(pipe)
                elif playing_ms is not None and status.text == "STOPPED":
                    break  # a short sound ended, or someone stopped it
                if playing_ms is None:
                    continue
                read = await pipe.acall("GetPlaybackPositionInMs()")
                position = as_int(read.text)
                if last_position is not None and position > 0 and position != last_position:
                    steps.append(((read.sent_at - sent_at) * 1000, position))
                last_position = position
        except (SoundpadUnavailable, SoundpadTimeout, SoundpadError) as exc:
            self._log("warning", f"Soundpad start timing stopped: {exc}")
            return
        if playing_ms is None:
            self._log("warning", f"Soundpad didn't report PLAYING within {MEASURE_FOR_S:g} s of the command")
            return
        if not steps:
            self._log("info", f"Soundpad: PLAYING after {playing_ms:.0f} ms; the sound ended before its position moved")
            return
        start_ms = statistics.median(t - position for t, position in steps)
        self.start_latencies.append(start_ms)
        self._log(
            "info",
            f"Soundpad start: PLAYING after {playing_ms:.0f} ms, first position after {steps[0][0]:.0f} ms, "
            f"audio ≈{start_ms:.0f} ms after the command (median of the last {len(self.start_latencies)}: "
            f"{self.start_latency_ms:.0f} ms)",
        )

    # ---- status polling ---------------------------------------------------------

    async def _poll(self, pipe: SoundpadPipe) -> None:
        was_live: bool | None = None
        while True:
            try:
                await self._read_playback(pipe)
            except (SoundpadUnavailable, SoundpadTimeout, SoundpadError):
                if self._playback is not None:
                    self._playback = None
                    self._changed()
            live = self._pipe_live()
            if live != was_live:
                self._announce(pipe, live, first=was_live is None)
                was_live = live
                self._changed()
            playing = self._playback is not None and self._playback.status != "STOPPED"
            try:
                await asyncio.wait_for(self._wake_poll.wait(), POLL_PLAYING_S if playing else POLL_IDLE_S)
            except asyncio.TimeoutError:
                pass
            self._wake_poll.clear()

    async def _read_playback(self, pipe: SoundpadPipe) -> None:
        playback = await pipe.playback()
        previous = self._playback
        if playback.status == "SEEKING" and previous is not None:
            # The position reads 0 or the old value mid-seek; keep what we had
            playback = Playback("SEEKING", previous.position_ms, previous.duration_ms)
        if playback != previous:
            self._playback = playback
            self._changed()

    def _announce(self, pipe: SoundpadPipe, live: bool, first: bool) -> None:
        if live and pipe.info:
            info = pipe.info
            edition = {True: "trial", False: "full version"}.get(info.trial, "edition unknown")
            self._log("success", f"Soundpad {info.version} connected (remote control {info.rc_version}, {edition})")
            if not info.rc_supported:
                self._log("warning", f"Soundpad's remote control is {info.rc_version}; 1.1.2 or newer is needed for every command.")
            return
        fallback = "Cues fall back to Soundpad.exe -rc" if self._soundpad_path else "Cues can't play"
        if first:
            self._log("info", f"{pipe.last_error}. {fallback} until Soundpad answers.")
        else:
            self._log("warning", f"Lost Soundpad's pipe: {pipe.last_error}. {fallback} until it's back.")

    # ---- OSC --------------------------------------------------------------------

    def send_osc(self, parameter: str, value: Any) -> tuple[bool, str]:
        osc = self._config.osc
        address = osc_address(parameter)
        if not osc.enabled:
            return False, f"Skipped {address}={value} (OSC is off)"
        if udp_client is None:
            return False, f"Skipped {address}={value} (python-osc isn't installed)"
        target = (osc.host, osc.port)
        if self._osc_client is None or self._osc_target != target:
            self._osc_client = udp_client.SimpleUDPClient(*target)
            self._osc_target = target
        try:
            self._osc_client.send_message(address, osc_value(value))
        except OSError as exc:
            return False, f"OSC send failed: {exc}"
        return True, f"{address} ← {value}"


def platform_note() -> str:
    return "Windows" if sys.platform == "win32" else sys.platform
