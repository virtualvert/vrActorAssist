"""The agent's relay connection: protocol v2 when the relay has /v2/ws, else the v0.3 protocol.

Every connection attempt tries /v2/ws first. A v0.3 relay answers it with 403, and the same
attempt continues on /ws in compatibility mode (relay_legacy.py), so a relay that gets upgraded
is picked up at the next reconnect. This class owns the reconnect loop and the Play-in-3s
countdown; the protocol objects own everything they learn from the relay.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from websockets.exceptions import InvalidURI, WebSocketException

from .relay_legacy import LegacyRelay, host_of, ws_url
from .relay_v2 import V2Relay, V2Unavailable, v2_url

if TYPE_CHECKING:
    from .core import Agent

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0
COUNTDOWN_S = 3.0


class Relay:
    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.v2 = V2Relay(agent)
        self.v03 = LegacyRelay(agent)
        self.impl: V2Relay | LegacyRelay = self.v2
        self.host = ""
        self.countdown_ends: float | None = None
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
                backoff = BACKOFF_START_S
            except asyncio.CancelledError:
                raise
            except (OSError, WebSocketException, InvalidURI, asyncio.TimeoutError) as exc:
                self.agent.hub.log("warning", f"Relay connection failed: {exc}")
            if fatal:
                self.impl._reset(fatal, status="error")
                return
            self.impl._reset(f"Lost connection to {self.host}. Retrying in {int(backoff)} s…", status="connecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

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
        if command == "countdown":
            if self._countdown_task is None:
                self.countdown_ends = time.time() + COUNTDOWN_S
                self._countdown_task = asyncio.get_running_loop().create_task(self._countdown())
                self.agent.hub.log("info", "⏱ Playing in 3 seconds…")
                self.agent.changed()
            return
        if command == "stop" and self._countdown_task is not None:
            self._cancel_countdown()
            self.agent.hub.log("info", "■ Countdown cancelled")
        await self.impl.send_cue("go" if command == "go" else "stop")

    async def _countdown(self) -> None:
        try:
            await asyncio.sleep(COUNTDOWN_S)
            self._countdown_task = None
            self.countdown_ends = None
            await self.impl.send_cue("go")
        except asyncio.CancelledError:
            pass
        finally:
            self.agent.changed()

    def _cancel_countdown(self) -> None:
        if self._countdown_task is not None:
            self._countdown_task.cancel()
        self._countdown_task = None
        self.countdown_ends = None
        self.agent.changed()
