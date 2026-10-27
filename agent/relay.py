"""The agent's relay connection: protocol v2 when the relay has /v2/ws, else the v0.3 protocol.

Every connection attempt tries /v2/ws first. A v0.3 relay answers it with 403, and the same
attempt continues on /ws in compatibility mode (relay_legacy.py), so a relay that gets upgraded
is picked up at the next reconnect. This class owns the reconnect loop and the countdown shown
in the UI; the protocol objects own everything they learn from the relay. On a v2 relay Play in 3s
is one cue for server time now + 3 s (relay_v2.py); on a v0.3 relay it's a local countdown, then Go.

agent.log gets every dropped connection with its close codes (a keepalive timeout, the relay
restarting, a connection cut without a close frame), how long it lasted and how long the relay
had been silent, and every failed attempt to connect with the exception.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from websockets.exceptions import ConnectionClosed, InvalidURI, WebSocketException

from .relay_legacy import LegacyRelay, host_of, ws_url
from .relay_v2 import V2Relay, V2Unavailable, v2_url

if TYPE_CHECKING:
    from .core import Agent

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0
COUNTDOWN_MS = 3000


def error_text(exc: BaseException) -> str:
    """A relay connection problem for the log: a close in websockets' own words ("sent 1011
    (internal error) keepalive ping timeout; no close frame received"), anything else as its type
    and text (a TimeoutError or an SSL EOF says little without the type)."""
    if isinstance(exc, ConnectionClosed):
        return str(exc)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def span(seconds: float) -> str:
    """A duration for the log: '0.4 s', '41 s', '12 min', '2 h 05 min'."""
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f} s"
    if seconds < 120:
        return f"{seconds:.0f} s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


class Relay:
    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.v2 = V2Relay(agent)
        self.v03 = LegacyRelay(agent)
        self.impl: V2Relay | LegacyRelay = self.v2
        self.host = ""
        # What the UI's countdown shows: {"endsAt": wall-clock ms, "durationMs": ms}
        self.countdown: dict | None = None
        self._task: asyncio.Task | None = None
        self._countdown_task: asyncio.Task | None = None
        self._announced: str | None = None

    # ---- what the UI shows (from whichever protocol is in use) -------------

    @property
    def legacy(self) -> bool:
        return self.impl.legacy

    @property
    def status(self) -> str:
        return self.impl.status

    @property
    def detail(self) -> str:
        return self.impl.detail

    @property
    def server_version(self) -> str | None:
        return self.impl.server_version

    @property
    def pending(self) -> list[dict]:
        return self.impl.pending

    @property
    def offline(self) -> list[dict]:
        return self.impl.offline

    @property
    def self_playing_until(self) -> float:
        return self.impl.self_playing_until

    def peers(self) -> list[dict]:
        return self.impl.peers()

    def target_ids(self) -> list[str]:
        return self.impl.target_ids()

    def set_targets(self, ids: list[str]) -> None:
        self.impl.set_targets(ids)

    def clear_targets(self) -> None:
        self.v2.clear_targets()
        self.v03.clear_targets()

    async def approve(self, pending_id: str) -> None:
        await self.impl.approve(pending_id)

    async def deny(self, pending_id: str) -> None:
        await self.impl.deny(pending_id)

    async def forget(self, peer_id: str) -> None:
        await self.impl.forget(peer_id)

    async def chat(self, text: str) -> None:
        await self.impl.chat(text)

    # ---- lifecycle --------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._announced = None
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self, detail: str = "Disconnected") -> None:
        task, self._task = self._task, None
        self._cancel_countdown()
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.impl._reset(detail)

    async def restart(self) -> None:
        await self.stop("Reconnecting…")
        self.start()

    def _use(self, impl: V2Relay | LegacyRelay) -> None:
        if impl is not self.impl:
            self.impl._reset("Not connected")
            self.impl = impl

    async def _run(self) -> None:
        backoff = BACKOFF_START_S
        failures = 0  # attempts in a row that didn't connect
        try:
            legacy_url = ws_url(self.agent.config.server_url)
        except ValueError as exc:
            self.impl._set("error", str(exc))
            return
        self.host = self.v2.host = self.v03.host = host_of(legacy_url)
        while True:
            self.impl._set("connecting", f"Connecting to {self.host}…")
            fatal = None
            try:
                fatal = await self._attempt(legacy_url)
                backoff, failures = BACKOFF_START_S, 0
            except ConnectionClosed as exc:  # we were connected; the connection ended
                backoff, failures = BACKOFF_START_S, 0
                self._log_drop(exc, backoff)
            except (OSError, WebSocketException, InvalidURI, asyncio.TimeoutError) as exc:
                failures += 1
                attempt = f" (attempt {failures})" if failures > 1 else ""
                self.agent.hub.log("warning", f"Relay connection failed{attempt}: {error_text(exc)}. "
                                   f"Retrying in {int(backoff)} s.")
            if fatal:
                self.impl._reset(fatal, status="error")
                return
            self.impl._reset(f"Lost connection to {self.host}. Retrying in {int(backoff)} s…", status="connecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    def _log_drop(self, exc: ConnectionClosed, retry_s: float) -> None:
        impl, now = self.impl, time.monotonic()
        parts = [error_text(exc)]
        if impl.opened_at is not None:
            parts.append(f"connected {span(now - impl.opened_at)}")
            parts.append(f"last message from the relay {span(now - impl.last_message_at)} ago")
        self.agent.hub.log("warning", f"Lost connection to {self.host}: {'; '.join(parts)}. Retrying in {int(retry_s)} s.")

    async def _attempt(self, legacy_url: str) -> str | None:
        self._use(self.v2)
        try:
            return await self.v2._session(v2_url(legacy_url))
        except V2Unavailable:
            if self._announced != "legacy":
                self._announced = "legacy"
                self.agent.hub.log("info", f"{self.host} is a v0.3 relay (no /v2/ws); using compatibility mode.")
            self._use(self.v03)
            self.v03._set("connecting", f"Connecting to {self.host} (compatibility mode)…")
            return await self.v03._session(legacy_url)

    # ---- director cues ----------------------------------------------------

    async def cue(self, command: str) -> None:
        impl = self.impl
        lead = self.agent.config.director.lead_ms
        if command == "countdown":
            if self.countdown is not None:
                return
            if not impl.legacy and impl.status == "connected" and impl.clock.synced:
                await impl.send_go(COUNTDOWN_MS, countdown=True)
                return
            # A v0.3 relay (or no clock yet): count down here, then Go
            self.show_countdown(time.time() * 1000 + COUNTDOWN_MS, COUNTDOWN_MS)
            self._countdown_task = asyncio.get_running_loop().create_task(self._countdown())
            self.agent.hub.log("info", "⏱ Playing in 3 seconds…")
            return
        if command == "stop" and self._countdown_task is not None:
            self._cancel_countdown()
            self.agent.hub.log("info", "■ Countdown cancelled")
        if command == "go":
            await impl.send_go(lead)
        else:
            await impl.send_cue("stop")

    async def _countdown(self) -> None:
        try:
            await asyncio.sleep(COUNTDOWN_MS / 1000)
            self._countdown_task = None
            self.clear_countdown()
            await self.impl.send_go(0)
        except asyncio.CancelledError:
            pass
        finally:
            self.agent.changed()

    def _cancel_countdown(self) -> None:
        if self._countdown_task is not None:
            self._countdown_task.cancel()
        self._countdown_task = None
        self.clear_countdown()

    # ---- the countdown in the UI (director: Play in 3s; actor: a cue more than 1 s ahead) ----

    def show_countdown(self, ends_at_ms: float, duration_ms: int) -> None:
        self.countdown = {"endsAt": int(ends_at_ms), "durationMs": int(duration_ms)}
        self.agent.changed()

    def clear_countdown(self) -> None:
        if self.countdown is not None:
            self.countdown = None
            self.agent.changed()
