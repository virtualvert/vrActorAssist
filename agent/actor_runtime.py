"""What an actor's machine does with cues: Soundpad playback and VRChat OSC parameters.

Soundpad goes through its named pipe (soundpad_pipe.py, spec §8.1) when Soundpad answers on it.
When it doesn't, cues fall back to soundpad.py (`Soundpad.exe -rc`), which can play and stop but
can't report anything back.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import soundpad

from .scheduler import DEFAULT_START_LATENCY_MS
from .sounds import SoundCache, normal_path, sound_key
from .soundpad_pipe import (
    Playback,
    Sound,
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
# Volume, mute and the sound count are read this often (they change rarely)
LEVELS_EVERY_S = 5.0
# How long to wait for PLAYING before seeking to a start position
SEEK_WAIT_S = 0.5
# soundpad.calibrate: how long the speakers-only test play runs before it's stopped (§8.2.3)
CALIBRATE_PLAY_S = 1.5
# Output lines → DoPlaySound(index, render, capture) (spec §8.1.4)
LINES = {"both": (True, True), "speakers": (True, False), "mic": (False, True)}


class PlayError(Exception):
    """A soundpad.* request that can't be done; `code` goes into soundpad.ack's status."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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


RC_WAIT_S = 5.0


def command_line(command: str) -> tuple[bool, str | None]:
    """A cue through `Soundpad.exe -rc`, for when Soundpad runs but its pipe can't be used.

    Unlike soundpad.py (shared with the v0.3 clients) this never kills the process: when Soundpad
    isn't running, `-rc` starts it and stays running as Soundpad, and a timeout kill closed it again
    (laptop run, M2). The agent doesn't use the command line while Soundpad is closed anyway.
    """
    cue = parse_cue(command)
    if cue is None:
        return False, f"Unknown command: {command}"
    exe = soundpad.get_soundpad_path()
    if not exe:
        return False, "Soundpad.exe wasn't found. Set its location in Settings → Actor."
    action, index = cue
    rc = {"go": "DoPlaySelectedSound()", "stop": "DoStopSound()"}.get(action) or f"DoPlaySound({index})"
    try:
        proc = subprocess.Popen([exe, "-rc", rc], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as exc:
        return False, f"Couldn't run Soundpad.exe: {exc}"
    try:
        code = proc.wait(timeout=RC_WAIT_S)
    except subprocess.TimeoutExpired:
        return False, f"Soundpad.exe -rc didn't finish within {RC_WAIT_S:g} s"
    return (True, None) if code == 0 else (False, f"Soundpad.exe -rc failed (code {code})")


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
        # Measured start latencies in ms (command → audio), newest last (spec §8.2.3); kept in the config
        self.start_latencies: deque[float] = deque(config.soundpad.start_latencies, maxlen=LATENCY_SAMPLES)
        # The sound list as last read, what we last started, and the slow-changing levels
        self.cache = SoundCache()
        self.current: dict | None = None
        self.volume_level: int | None = None
        self.is_muted: bool | None = None
        self._levels_at = 0.0
        self._launched = False
        self._calibration: dict | None = None
        # Set by the agent: the list changed (count), sha256 → path of received files, a start was measured
        self.on_list_changed: Callable[[], None] = lambda: None
        self.received_lookup: Callable[[str], str | None] = lambda sha256: None
        self.on_latency: Callable[[list[float]], None] = lambda latencies: None

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

    def compensation_ms(self) -> int:
        """How much earlier scheduled Soundpad starts are sent (§8.2.3): the measured start latency,
        60 ms until there is one, 0 with auto_compensate_latency off."""
        if not self._config.soundpad.auto_compensate_latency:
            return 0
        measured = self.start_latency_ms
        return DEFAULT_START_LATENCY_MS if measured is None else round(measured)

    def timing_state(self) -> dict:
        """For the UI (ActorLocal.timing, without the relay's part)."""
        measured = self.start_latency_ms
        return {
            "startLatencyMs": DEFAULT_START_LATENCY_MS if measured is None else round(measured),
            "measured": measured is not None,
            "samples": len(self.start_latencies),
            "autoCompensate": self._config.soundpad.auto_compensate_latency,
        }

    def _pipe_live(self) -> bool:
        return self._pipe is not None and self._pipe.connected and self._pipe.info is not None

    def soundpad_state(self) -> dict:
        sp = self._config.soundpad
        state = {
            "enabled": sp.enabled,
            "info": None,
            "playback": None,
            "volume": self.volume_level if self._pipe_live() else None,
            "muted": self.is_muted if self._pipe_live() else None,
            "defaultLines": sp.default_lines,
            "autoAddReceived": sp.auto_add_received,
            "autoLaunch": sp.auto_launch,
            "path": sp.path,
        }
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
                    "title": self._current_title() if playback.status != "STOPPED" else None,
                    "lines": (self.current or {}).get("lines") if playback.status != "STOPPED" else None,
                },
            }
        if not soundpad.is_windows():
            return {**state, "state": "simulated", "detail": "Soundpad only runs on Windows, so cues are simulated here."}
        if not self._soundpad_checked:
            return {**state, "state": "missing", "detail": "Looking for Soundpad…"}
        if self._soundpad_closed():
            fix = "until it's back" if sp.auto_launch else "until it's started (or turn on “Start Soundpad when it isn't running”)"
            return {**state, "state": "closed", "detail": f"Soundpad isn't running, so cues can't play {fix}."}
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
            self._pipe.reconnect_now()
            try:
                return await self._pipe_cue(self._pipe, *cue)
            except SoundpadUnavailable:
                if self._soundpad_closed():
                    # `-rc` would start Soundpad (and v0.3's timeout then killed it): don't
                    self._changed()
                    if cue[0] == "stop":
                        return True, None  # nothing plays
                    launching = self._maybe_launch()
                    return False, "Soundpad isn't running" + ("; starting it now" if launching else "")
                # otherwise nothing was sent, so the command line can try
            except (SoundpadTimeout, SoundpadError) as exc:
                self._changed()
                return False, str(exc)
        if not soundpad.is_windows():
            return True, None  # soundpad.py would only print "simulating"
        return await asyncio.to_thread(command_line, command)

    def _soundpad_closed(self) -> bool:
        """Soundpad isn't running: its pipe doesn't exist (Windows only)."""
        return soundpad.is_windows() and self._pipe is not None and not self._pipe_live() and self._pipe.missing

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
        self._started(pipe, reply.sent_at, index, None, "both")
        return True, None

    def _started(self, pipe: SoundpadPipe, sent_at: float, index: int | None, sound: Sound | None, lines: str) -> None:
        """A play command went out: remember what plays, and time its start."""
        self._title = sound.title if sound else None
        self.current = {"index": index, "key": sound_key(sound.url) if sound else None, "lines": lines}
        self._cancel_measure()
        lookup = index if sound is None else None  # the title is read once playback starts
        self._measure_task = asyncio.get_running_loop().create_task(self._measure_start(pipe, sent_at, lookup))
        self._wake_poll.set()

    def _current_title(self) -> str | None:
        return self._title

    # ---- the rest of the soundpad addon (spec §8.1) ------------------------------------

    def _live_pipe(self) -> SoundpadPipe:
        if self._pipe is None or not self._pipe_live():
            if not soundpad.is_windows():
                raise PlayError("soundpad_offline", "Soundpad only runs on Windows")
            reason = (self._pipe.last_error if self._pipe else None) or "Soundpad isn't answering on its remote-control pipe"
            raise PlayError("soundpad_offline", reason)
        return self._pipe

    async def play_sound(self, ref: dict, lines: str | None = None, volume: int | None = None,
                         start_ms: int | None = None) -> tuple[str, str | None]:
        """soundpad.play. Returns (status, error): "ok", or an error code with a message."""
        sp = self._config.soundpad
        if not sp.enabled:
            return "skipped", "Soundpad is off on this computer"
        lines = lines or sp.default_lines
        simple = lines == "both" and volume is None and not start_ms
        if simple and (ref.get("selected") or isinstance(ref.get("index"), int)) and not self._pipe_live():
            # What the command line (or the simulation) can do as well
            ok, error = await self.run_cue("*go" if ref.get("selected") else f"*play:{ref['index']}")
            if ok:
                return "ok", None
            return ("soundpad_offline" if self._soundpad_closed() else "error"), error
        try:
            pipe = self._live_pipe()
            if volume is not None:
                await pipe.set_volume(volume)
                self.volume_level = volume
            render, capture = LINES[lines]
            if ref.get("category"):
                categories = await pipe.categories()
                wanted = str(ref["category"]).casefold()
                category = next((c for c in categories if c.name.casefold() == wanted), None)
                if category is None:
                    raise PlayError("not_found", f"There's no category {ref['category']!r} in this actor's Soundpad")
                reply = await pipe.play_from_category(category.index, int(ref.get("position") or 1), render, capture)
                self._started(pipe, reply.sent_at, None, None, lines)
            else:
                index = await self._resolve(pipe, ref)
                if index is None:
                    if lines != "both":
                        raise PlayError("unsupported", "Soundpad plays the selected sound on both lines; pick a sound to choose the line")
                    reply = await pipe.play_selected()
                    self._started(pipe, reply.sent_at, None, None, lines)
                else:
                    reply = await pipe.play(index, render, capture)
                    self._started(pipe, reply.sent_at, index, self.cache.by_index(index), lines)
            if start_ms:
                await self._seek_after_start(pipe, int(start_ms))
            return "ok", None
        except PlayError as exc:
            return exc.code, str(exc)
        except SoundpadUnavailable as exc:
            return "soundpad_offline", str(exc)
        except SoundpadTimeout as exc:
            return "timeout", str(exc)
        except SoundpadError as exc:
            if "R-404" in str(exc):
                return "not_in_soundpad", "That sound number isn't in this actor's Soundpad"
            return "error", str(exc)
        finally:
            self._changed()

    async def calibrate(self, ref: dict | None) -> tuple[str, str | None]:
        """soundpad.calibrate: a speakers-only test play whose start is measured like any other
        (§8.2.3). Without a sound: the one last played by number, else sound 1 (the selected sound
        can't be played on the speakers line alone). Returns (status, error); the measurement
        comes from calibration_result(), and stop_calibration() ends the play."""
        if not self._config.soundpad.enabled:
            return "skipped", "Soundpad is off on this computer"
        ref = ref or {}
        try:
            pipe = self._live_pipe()
            if ref.get("selected") or ref.get("category"):
                raise PlayError("unsupported", "Calibrate with a sound from the list or a sound number")
            index = await self._resolve(pipe, ref) if ref else ((self.current or {}).get("index") or 1)
            reply = await pipe.play(index, True, False)
            self._started(pipe, reply.sent_at, index, self.cache.by_index(index), "speakers")
            self._calibration = self.current
            return "ok", None
        except PlayError as exc:
            return exc.code, str(exc)
        except SoundpadUnavailable as exc:
            return "soundpad_offline", str(exc)
        except SoundpadTimeout as exc:
            return "timeout", str(exc)
        except SoundpadError as exc:
            if "R-404" in str(exc):
                return "not_in_soundpad", "That sound number isn't in this actor's Soundpad"
            return "error", str(exc)
        finally:
            self._changed()

    async def calibration_result(self) -> float | None:
        """The start latency measured for the test play just started (None if it couldn't be)."""
        task = self._measure_task
        if task is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(task), MEASURE_FOR_S + 1)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

    async def stop_calibration(self) -> None:
        """End the test play, unless something else started playing since."""
        if self._calibration is not None and self.current is self._calibration:
            self._calibration = None
            await self.run_cue("*stop")

    async def _resolve(self, pipe: SoundpadPipe, ref: dict) -> int | None:
        """A sound reference → All-sounds index (None: the selected sound). Spec §8.1.3."""
        if ref.get("selected"):
            return None
        if isinstance(ref.get("index"), int):
            return ref["index"]  # *play:N semantics: whatever is at that number now
        if ref.get("key"):
            sound = await self._find(pipe, key=ref["key"])
            if sound is None:
                raise PlayError("not_in_soundpad", "That sound isn't in this actor's Soundpad any more")
            return sound.index
        path = ref.get("path")
        if ref.get("sha256"):
            path = self.received_lookup(str(ref["sha256"]))
            if not path:
                raise PlayError("not_found", "This actor hasn't received that file")
        if not path:
            raise PlayError("invalid", "The request doesn't say which sound to play")
        sound = await self._find(pipe, path=path)
        if sound is not None:
            return sound.index
        name = Path(path.replace("\\", "/")).name
        if not os.path.isfile(path):
            raise PlayError("not_found", f"{name} isn't on this actor's PC")
        if not self._config.soundpad.auto_add_received:
            raise PlayError("not_in_soundpad", f"{name} isn't in Soundpad; add it there, or turn on adding received files")
        if pipe.info and pipe.info.trial:
            raise PlayError("trial_limit", f"The Soundpad trial can't add sounds; add {name} to Soundpad by hand")
        index = await pipe.add_sound(path)
        await self._refresh_cache(pipe)
        self._log("info", f"Added {name} to Soundpad (sound {index})")
        return index

    async def _refresh_cache(self, pipe: SoundpadPipe) -> None:
        self.cache.load(await pipe.sounds())

    async def _find(self, pipe: SoundpadPipe, key: str | None = None, path: str | None = None) -> Sound | None:
        """Look a sound up in the cached list, refreshing it when the count changed. Before its index
        is used, Soundpad must still list the same file there (index drift guard, §8.1.3)."""
        if await pipe.sound_count() != self.cache.count:
            await self._refresh_cache(pipe)
            fresh = True
        else:
            fresh = False
        lookup = (lambda: self.cache.by_key(key)) if key else (lambda: self.cache.by_path(path or ""))
        sound = lookup()
        if sound is None or fresh:
            return sound
        listed = await pipe.sounds(sound.index, sound.index)
        if listed and normal_path(listed[0].url) == normal_path(sound.url):
            return sound
        await self._refresh_cache(pipe)  # the sounds were reordered
        return lookup()

    async def _seek_after_start(self, pipe: SoundpadPipe, start_ms: int) -> None:
        deadline = time.monotonic() + SEEK_WAIT_S
        while await pipe.text("GetPlayStatus()") != "PLAYING" and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        await pipe.seek(start_ms)

    async def control(self, action: str, value: Any = None) -> tuple[str, str | None]:
        """pause / resume / seek / jump / volume / mute / unmute. Returns (status, error)."""
        if not self._config.soundpad.enabled:
            return "skipped", "Soundpad is off on this computer"
        try:
            pipe = self._live_pipe()
            if action in ("pause", "resume"):
                await pipe.set_paused(action == "pause")
            elif action == "seek":
                await pipe.seek(int(value))
            elif action == "jump":
                await pipe.jump(int(value))
            elif action == "volume":
                await pipe.set_volume(int(value))
                self.volume_level = int(value)
            elif action in ("mute", "unmute"):
                await pipe.set_muted(action == "mute")
                self.is_muted = action == "mute"
            else:
                raise PlayError("invalid", f"Unknown action {action}")
            self._wake_poll.set()
            return "ok", None
        except PlayError as exc:
            return exc.code, str(exc)
        except SoundpadUnavailable as exc:
            return "soundpad_offline", str(exc)
        except SoundpadTimeout as exc:
            return "timeout", str(exc)
        except (SoundpadError, ValueError) as exc:
            return "error", str(exc)
        finally:
            self._changed()

    async def sound_list(self) -> tuple[list[Sound], list[dict]]:
        """The whole All-sounds list and the visible categories, read fresh. Raises PlayError."""
        try:
            pipe = self._live_pipe()
            await self._refresh_cache(pipe)
            categories = [{"index": c.index, "name": c.name} for c in await pipe.categories() if not c.hidden]
        except (SoundpadUnavailable, SoundpadTimeout, SoundpadError) as exc:
            raise PlayError("soundpad_offline", str(exc)) from exc
        return self.cache.sounds, categories

    def state_for_directors(self) -> dict:
        """soundpad.state (spec §8.1.6)."""
        sp = self._config.soundpad
        if not sp.enabled:
            return {"available": False, "detail": "Soundpad is off on this computer"}
        if not self._pipe_live():
            return {"available": False, "detail": self.soundpad_state()["detail"]}
        playback = self._playback
        state: dict[str, Any] = {"available": True, "status": playback.status if playback else None}
        if self.volume_level is not None and 0 <= self.volume_level <= 100:
            state["volume"] = self.volume_level
        if self.is_muted is not None:
            state["muted"] = self.is_muted
        if playback is not None and playback.status != "STOPPED":
            state.update(position_ms=playback.position_ms, duration_ms=playback.duration_ms)
            current = self.current or {}
            for key in ("index", "key", "lines"):
                if current.get(key) is not None:
                    state[key] = current[key]
            if self._current_title():
                state["title"] = self._current_title()[:300]
        return state

    def on_file_received(self, path: str) -> None:
        """Add a received file to Soundpad (full version, when turned on), unless it's there already."""
        sp = self._config.soundpad
        if not (sp.enabled and sp.auto_add_received and self._config.role == "actor" and self._pipe_live()):
            return
        if self._pipe.info and self._pipe.info.trial:
            self._log("info", f"Soundpad trial: add {Path(path).name} to Soundpad by hand to play it")
            return
        asyncio.get_running_loop().create_task(self._add_received(self._pipe, path))

    async def _add_received(self, pipe: SoundpadPipe, path: str) -> None:
        try:
            if await self._find(pipe, path=path) is not None:
                return  # an updated file keeps its entry (same path)
            index = await pipe.add_sound(path)
            await self._refresh_cache(pipe)
            self._log("success", f"Added {Path(path).name} to Soundpad (sound {index})")
        except (SoundpadUnavailable, SoundpadTimeout, SoundpadError, ValueError) as exc:
            self._log("warning", f"Couldn't add {Path(path).name} to Soundpad: {exc}")

    def _cancel_measure(self) -> None:
        if self._measure_task:
            self._measure_task.cancel()
            self._measure_task = None

    async def _measure_start(self, pipe: SoundpadPipe, sent_at: float, index: int | None) -> float | None:
        """Time from the play command to audio, for spec §8.2.3.

        GetPlayStatus says PLAYING within a few ms, before any audio. The position stays 0 for a
        while and then moves in steps about 140 ms apart, so the start is read off the moments the
        position changes: start = (time of the change − command time) − position.
        """
        try:
            if index is not None:
                sounds = await pipe.sounds(index, index)
                self._title = sounds[0].title if sounds else None
                if sounds and self.current is not None and self.current.get("index") == index:
                    self.current["key"] = sound_key(sounds[0].url)
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
            return None
        if playing_ms is None:
            self._log("warning", f"Soundpad didn't report PLAYING within {MEASURE_FOR_S:g} s of the command")
            return None
        if not steps:
            self._log("info", f"Soundpad: PLAYING after {playing_ms:.0f} ms; the sound ended before its position moved")
            return None
        start_ms = statistics.median(t - position for t, position in steps)
        if not 0 <= start_ms <= 5000:
            self._log("info", f"Soundpad start: ignored an implausible measurement ({start_ms:.0f} ms)")
            return None
        self.start_latencies.append(start_ms)
        self.on_latency([round(v, 1) for v in self.start_latencies])
        self._log(
            "info",
            f"Soundpad start: PLAYING after {playing_ms:.0f} ms, first position after {steps[0][0]:.0f} ms, "
            f"audio ≈{start_ms:.0f} ms after the command (median of the last {len(self.start_latencies)}: "
            f"{self.start_latency_ms:.0f} ms)",
        )
        return start_ms

    # ---- status polling ---------------------------------------------------------

    async def _poll(self, pipe: SoundpadPipe) -> None:
        was_live: bool | None = None
        while True:
            try:
                await self._read_playback(pipe)
                if time.monotonic() - self._levels_at >= LEVELS_EVERY_S:
                    await self._read_levels(pipe)
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

    async def _read_levels(self, pipe: SoundpadPipe) -> None:
        """Volume, mute and the sound count, every few seconds (they change rarely)."""
        self._levels_at = time.monotonic()
        volume, muted, count = await pipe.volume(), await pipe.muted(), await pipe.sound_count()
        if (volume, muted) != (self.volume_level, self.is_muted):
            self.volume_level, self.is_muted = volume, muted
            self._changed()
        if count != self.cache.count and self.cache.count != -1:
            self.cache.count = -2  # stale: the next lookup reads the list again
            self.on_list_changed()

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
        self._levels_at = 0.0  # read volume, mute and count again once it's back
        closed = self._soundpad_closed()
        fallback = "Cues fall back to Soundpad.exe -rc" if self._soundpad_path and not closed else "Cues can't play"
        self._maybe_launch()
        if first:
            self._log("info", f"{pipe.last_error}. {fallback} until Soundpad answers.")
        else:
            self._log("warning", f"Lost Soundpad's pipe: {pipe.last_error}. {fallback} until it's back.")

    def _maybe_launch(self) -> bool:
        """Start Soundpad.exe once per run when its pipe isn't there and auto_launch is on (§8.1.1).
        The only way this app starts Soundpad. Returns whether it started it now."""
        sp = self._config.soundpad
        if self._launched or not sp.auto_launch or not soundpad.is_windows() or not self._soundpad_path:
            return False
        self._launched = True
        try:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([self._soundpad_path], creationflags=flags, close_fds=True)
            self._log("info", f"Starting Soundpad ({self._soundpad_path})…")
            return True
        except OSError as exc:
            self._log("warning", f"Couldn't start Soundpad: {exc}")
            return False

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
