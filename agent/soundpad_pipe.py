"""Soundpad remote control over its named pipe (spec §8.1, Appendix A).

One worker thread owns the pipe and runs one request at a time, at least 2 ms apart (Leppsoft's
reference client warns that back-to-back requests can break the pipe). Callers on any thread
or on the asyncio loop queue requests and wait for the reply.

The pipe itself sits behind `Transport`, so tests can swap in an in-memory Soundpad.
Behaviour notes come from tools/soundpad_probe.py runs against Soundpad 4.0.35 (RC 1.1.2).
"""

from __future__ import annotations

import asyncio
import queue
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, Protocol

PIPE_PATH = r"\\.\pipe\sp_remote_control"
MIN_GAP_S = 0.002
TIMEOUT_S = 2.0
LIST_TIMEOUT_S = 10.0
BACKOFF_START_S = 0.5
BACKOFF_MAX_S = 10.0
# How often a waiting request looks for Soundpad's answer. Answers usually take ~0.1 ms.
POLL_S = 0.0002
MIN_RC_VERSION = (1, 1, 2)
PLAY_STATUSES = ("STOPPED", "PLAYING", "PAUSED", "SEEKING")
LIST_COMMANDS = ("GetSoundlist", "GetCategories", "GetCategory")


class SoundpadUnavailable(Exception):
    """The pipe isn't open, so the command was not sent."""


class SoundpadTimeout(Exception):
    """The command was sent but Soundpad didn't answer in time; it may or may not have run."""


class SoundpadError(Exception):
    """Soundpad answered with something other than R-200."""


class NotSent(OSError):
    """Writing the command failed, so Soundpad never saw it."""


class Transport(Protocol):
    def request(self, command: str, timeout: float) -> str:
        """Send one command and return the whole answer. Raises NotSent, TimeoutError or OSError."""

    def close(self) -> None: ...


_XML_ROOT = re.compile(rb"<([A-Za-z_][\w.-]*)[^>]*?(/?)>")


def answer_complete(data: bytes) -> bool:
    """Short answers arrive in one write; XML is complete once its root element closes."""
    text = data.lstrip()
    if not text.startswith(b"<"):
        return bool(text)
    root = _XML_ROOT.search(text)
    if root is None:
        return False
    if root.group(2) == b"/":
        return True
    return text.rstrip().endswith(b"</" + root.group(1) + b">")


class WindowsPipeTransport:
    """The real pipe. Reads by polling PeekNamedPipe, so a hung Soundpad can't block the worker."""

    def __init__(self, path: str = PIPE_PATH):
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        peek = kernel32.PeekNamedPipe
        peek.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ]
        peek.restype = wintypes.BOOL
        self._ctypes = ctypes
        self._peek = peek
        self._file = open(path, "r+b", buffering=0)
        self._handle = msvcrt.get_osfhandle(self._file.fileno())

    def _available(self) -> int:
        avail = self._ctypes.c_ulong(0)
        if not self._peek(self._handle, None, 0, None, self._ctypes.byref(avail), None):
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        return avail.value

    def request(self, command: str, timeout: float) -> str:
        try:
            self._file.write(command.encode("utf-8"))
        except OSError as exc:
            raise NotSent(str(exc)) from exc
        deadline = time.perf_counter() + timeout
        data = bytearray()
        while True:
            pending = self._available()
            if pending:
                data += self._file.read(pending)
                continue
            if answer_complete(data):
                return data.decode("utf-8", errors="replace").strip()
            if time.perf_counter() > deadline:
                raise TimeoutError(f"no answer to {command} within {timeout:g} s")
            time.sleep(POLL_S)

    def close(self) -> None:
        self._file.close()


def open_windows_pipe() -> Transport:
    if sys.platform != "win32":
        raise OSError("Soundpad's pipe only exists on Windows")
    return WindowsPipeTransport()


@dataclass(frozen=True)
class Reply:
    text: str
    sent_at: float  # time.perf_counter() just before the command was written
    ms: float


@dataclass(frozen=True)
class SoundpadInfo:
    version: str
    rc_version: str
    trial: bool | None

    @property
    def rc_supported(self) -> bool:
        return version_tuple(self.rc_version) >= MIN_RC_VERSION


@dataclass(frozen=True)
class Playback:
    status: str
    position_ms: int
    duration_ms: int


@dataclass(frozen=True)
class Sound:
    index: int
    url: str
    title: str
    artist: str
    duration_s: int | None
    added_on: str
    last_played_on: str
    play_count: int
    tag: str


@dataclass(frozen=True)
class Category:
    index: int
    name: str
    type: str
    hidden: bool


def version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for part in text.strip().split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def as_int(text: str, default: int = 0) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def parse_duration(text: str) -> int | None:
    """Soundpad lists durations as m:ss (or h:mm:ss), whole seconds only."""
    try:
        seconds = 0
        for part in text.split(":"):
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        return None


def parse_soundlist(xml: str) -> list[Sound]:
    root = ET.fromstring(xml)
    return [
        Sound(
            index=as_int(el.get("index", "")),
            url=el.get("url", ""),
            title=el.get("title", ""),
            artist=el.get("artist", ""),
            duration_s=parse_duration(el.get("duration", "")),
            added_on=el.get("addedOn", ""),
            last_played_on=el.get("lastPlayedOn", ""),
            play_count=as_int(el.get("playCount", "")),
            tag=el.get("tag", ""),
        )
        for el in root.iter("Sound")
    ]


def parse_categories(xml: str) -> list[Category]:
    root = ET.fromstring(xml)
    return [
        Category(
            index=as_int(el.get("index", "")),
            name=el.get("name", ""),
            type=el.get("type", ""),
            hidden=el.get("hidden", "").lower() == "true",
        )
        for el in root.iter("Category")
    ]


def lines_args(render: bool, capture: bool) -> str:
    return f"{str(render).lower()}, {str(capture).lower()}"


class _Job:
    __slots__ = ("command", "timeout", "future")

    def __init__(self, command: str, timeout: float):
        self.command = command
        self.timeout = timeout
        self.future: Future[Reply] = Future()


class SoundpadPipe:
    def __init__(
        self,
        connect: Callable[[], Transport] = open_windows_pipe,
        *,
        timeout: float = TIMEOUT_S,
        list_timeout: float = LIST_TIMEOUT_S,
        min_gap: float = MIN_GAP_S,
        backoff_start: float = BACKOFF_START_S,
        backoff_max: float = BACKOFF_MAX_S,
    ):
        self._connect = connect
        self._timeout = timeout
        self._list_timeout = list_timeout
        self._min_gap = min_gap
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._backoff = 0.0  # the first reconnect after a drop is immediate
        self._retry_at = 0.0
        self._last_answer = 0.0
        self._transport: Transport | None = None
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self.info: SoundpadInfo | None = None
        self.last_error: str | None = "Not connected yet"

    # ---- lifecycle (any thread) ---------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="soundpad-pipe", daemon=True)
            self._thread.start()

    def close(self, wait: float = 1.0) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            self._jobs.put(None)
            thread.join(wait)

    @property
    def connected(self) -> bool:
        return self._transport is not None

    # ---- requests -----------------------------------------------------------

    def _timeout_for(self, command: str) -> float:
        return self._list_timeout if command.startswith(LIST_COMMANDS) else self._timeout

    def submit(self, command: str, timeout: float | None = None) -> Future[Reply]:
        if self._thread is None:
            raise SoundpadUnavailable("The Soundpad client isn't running")
        job = _Job(command, timeout if timeout is not None else self._timeout_for(command))
        self._jobs.put(job)
        return job.future

    def call(self, command: str, timeout: float | None = None) -> Reply:
        """Blocking request from any thread except the worker."""
        future = self.submit(command, timeout)
        return future.result()

    async def acall(self, command: str, timeout: float | None = None) -> Reply:
        return await asyncio.wrap_future(self.submit(command, timeout))

    async def text(self, command: str) -> str:
        return (await self.acall(command)).text

    async def action(self, command: str) -> Reply:
        """An action command; anything but R-200 raises SoundpadError."""
        reply = await self.acall(command)
        if not reply.text.startswith("R-200"):
            raise SoundpadError(f"Soundpad answered {reply.text or 'nothing'} to {command}")
        return reply

    # ---- typed helpers (asyncio) -----------------------------------------------

    async def play(self, index: int, render: bool | None = None, capture: bool | None = None) -> Reply:
        """Play by All-sounds index. Without lines this is the legacy one-argument form."""
        if render is None and capture is None:
            return await self.action(f"DoPlaySound({int(index)})")
        return await self.action(f"DoPlaySound({int(index)}, {lines_args(bool(render), bool(capture))})")

    async def play_selected(self) -> Reply:
        return await self.action("DoPlaySelectedSound()")

    async def stop(self, seek_wait: float = 0.25) -> Reply:
        # Stopping mid-seek once made the next play start at the seek target (spec §8.1.2)
        deadline = time.monotonic() + seek_wait
        while await self.text("GetPlayStatus()") == "SEEKING" and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        return await self.action("DoStopSound()")

    async def play_from_category(self, category: int, position: int, render: bool = True, capture: bool = True) -> Reply:
        """DoPlaySoundFromCategory: `category` is the category's index, `position` 1-based within it."""
        return await self.action(f"DoPlaySoundFromCategory({int(category)}, {int(position)}, {lines_args(render, capture)})")

    async def seek(self, ms: int) -> Reply:
        return await self.action(f"DoSeekMs({int(ms)})")

    async def jump(self, ms: int) -> Reply:
        return await self.action(f"DoJumpMs({int(ms)})")

    async def set_paused(self, paused: bool) -> bool:
        """Pause or resume only when needed (DoTogglePause flips). Returns whether anything changed."""
        status = await self.text("GetPlayStatus()")
        if (paused and status == "PLAYING") or (not paused and status == "PAUSED"):
            await self.action("DoTogglePause()")
            return True
        return False

    async def muted(self) -> bool | None:
        return {"1": True, "0": False}.get(await self.text("IsMuted()"))

    async def set_muted(self, muted: bool) -> bool:
        """Mute or unmute only when needed (DoToggleMute flips). Returns whether anything changed."""
        if await self.muted() == muted:
            return False
        await self.action("DoToggleMute()")
        return True

    async def playback(self) -> Playback:
        """Status plus position and duration. Soundpad keeps the last sound's numbers after a stop,
        so a stopped player reports 0 for both."""
        status = await self.text("GetPlayStatus()")
        if status not in PLAY_STATUSES:
            raise SoundpadError(f"Unexpected play status {status!r}")
        if status == "STOPPED":
            return Playback(status, 0, 0)
        position = as_int(await self.text("GetPlaybackPositionInMs()"))
        duration = as_int(await self.text("GetPlaybackDurationInMs()"))
        return Playback(status, position, duration)

    async def volume(self) -> int:
        return as_int(await self.text("GetVolume()"), -1)

    async def set_volume(self, value: int) -> Reply:
        """0–100. Changes what the audience hears too, not only the speakers (spec §8.1.5)."""
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("Volume must be a whole number from 0 to 100")
        return await self.action(f"SetVolume({value})")

    async def sound_count(self) -> int:
        return as_int(await self.text("GetSoundFileCount()"), -1)

    async def sounds(self, first: int | None = None, last: int | None = None) -> list[Sound]:
        if first is None:
            command = "GetSoundlist()"
        elif last is None:
            command = f"GetSoundlist({int(first)})"
        else:
            command = f"GetSoundlist({int(first)}, {int(last)})"
        text = await self.text(command)
        try:
            return parse_soundlist(text)
        except ET.ParseError as exc:
            raise SoundpadError(f"{command} didn't return XML: {text[:80]!r}") from exc

    async def categories(self) -> list[Category]:
        text = await self.text("GetCategories(false, false)")
        try:
            return parse_categories(text)
        except ET.ParseError as exc:
            raise SoundpadError(f"GetCategories didn't return XML: {text[:80]!r}") from exc

    async def add_sound(self, path: str, wait: float = 5.0) -> int:
        """Add a file to All sounds and return its new index. Soundpad answers R-200 before the
        sound is listed, so this waits for the count to grow."""
        if self.info and self.info.trial:
            raise SoundpadError("The Soundpad trial can't add sounds; add it to Soundpad by hand")
        if '"' in path:
            raise ValueError("Soundpad can't add a path that contains a double quote")
        before = await self.sound_count()
        await self.action(f'DoAddSound("{path}")')
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            count = await self.sound_count()
            if count > before:
                return count
            await asyncio.sleep(0.05)
        raise SoundpadError(f"Soundpad accepted {path} but didn't list it within {wait:g} s")

    # ---- worker thread --------------------------------------------------------

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                break
            if not job.future.set_running_or_notify_cancel():
                continue
            try:
                job.future.set_result(self._execute(job.command, job.timeout))
            except BaseException as exc:  # noqa: BLE001 - handed to the caller
                job.future.set_exception(exc)
        self._drop("Closed")
        self.last_error = "Closed"

    def _execute(self, command: str, timeout: float) -> Reply:
        for attempt in (1, 2):
            transport = self._ensure_connected(force=attempt == 2)
            try:
                return self._send(transport, command, timeout)
            except NotSent as exc:
                # Typically a handle left over from before Soundpad restarted: reconnect once
                self._drop(f"Soundpad's pipe closed ({exc})")
                if attempt == 2:
                    raise SoundpadUnavailable(self.last_error) from exc
            except TimeoutError as exc:
                self._drop(f"Soundpad isn't responding ({command} got no answer within {timeout:g} s)")
                raise SoundpadTimeout(self.last_error) from exc
            except OSError as exc:
                self._drop(f"Soundpad's pipe broke during {command} ({exc})")
                raise SoundpadTimeout(self.last_error) from exc
        raise AssertionError("unreachable")

    def _send(self, transport: Transport, command: str, timeout: float) -> Reply:
        gap = self._last_answer + self._min_gap - time.perf_counter()
        if gap > 0:
            time.sleep(gap)
        sent_at = time.perf_counter()
        try:
            text = transport.request(command, timeout)
        finally:
            self._last_answer = time.perf_counter()
        return Reply(text, sent_at, (self._last_answer - sent_at) * 1000)

    def _ensure_connected(self, force: bool = False) -> Transport:
        if self._transport is not None:
            return self._transport
        now = time.monotonic()
        if not force and now < self._retry_at:
            raise SoundpadUnavailable(self.last_error)
        try:
            transport = self._connect()
        except OSError as exc:
            self._backoff = min(max(self._backoff * 2, self._backoff_start), self._backoff_max)
            self._retry_at = time.monotonic() + self._backoff
            self.last_error = "Soundpad isn't running (its remote-control pipe isn't open)"
            raise SoundpadUnavailable(self.last_error) from exc
        try:
            self.info = self._handshake(transport)
        except (OSError, TimeoutError) as exc:
            transport.close()
            self._backoff = min(max(self._backoff * 2, self._backoff_start), self._backoff_max)
            self._retry_at = time.monotonic() + self._backoff
            self.last_error = f"Soundpad's pipe opened but the handshake failed ({exc})"
            raise SoundpadUnavailable(self.last_error) from exc
        self._transport = transport
        self._backoff = 0.0
        self.last_error = None
        return transport

    def _handshake(self, transport: Transport) -> SoundpadInfo:
        alive = self._send(transport, "IsAlive()", self._timeout).text
        if not alive.startswith("R-200"):
            raise OSError(f"IsAlive() answered {alive!r}")
        version = self._send(transport, "GetVersion()", self._timeout).text
        rc_version = self._send(transport, "GetRemoteControlVersion()", self._timeout).text
        trial = self._send(transport, "IsTrial()", self._timeout).text
        return SoundpadInfo(version, rc_version, {"1": True, "0": False}.get(trial))

    def _drop(self, reason: str) -> None:
        transport, self._transport = self._transport, None
        if transport is not None:
            try:
                transport.close()
            except OSError:
                pass
            self._retry_at = 0.0  # reconnect right away the first time
        self.last_error = reason
