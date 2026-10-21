"""Relay state and the operations both endpoints share (approve, deny, forget, status loop).

Every change is announced twice: in v0.3 terms to /ws sessions (legacy_bridge.LegacyBridge, in
the exact order the v0.3 relay used) and as presence.roster to /v2/ws sessions (router.Router).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from shared import APP_VERSION as LEGACY_VERSION

from . import SERVER_VERSION
from .legacy_bridge import LegacyBridge
from .router import Router
from .sessions import Approvals, Registry, Session
from .settings import Log, Settings
from .timesync import Clock
from .updates import find_update, load_manifest

__all__ = ["LEGACY_VERSION", "SERVER_VERSION", "PendingEntry", "Relay"]


@dataclass(eq=False)
class PendingEntry:
    """A machine waiting for approval. `session` is None after a forget, until it reconnects."""

    name: str
    role: str = "actor"
    session: Session | None = None


class Relay:
    def __init__(self, settings: Settings | None = None, clock: Clock | None = None):
        self.settings = settings or Settings()
        self.log = Log(self.settings)
        self.clock = clock or Clock()
        self.registry = Registry()
        self.approvals = Approvals(self.settings.approved_file, self.log)
        self.pending: dict[str, PendingEntry] = {}
        # v0.3 file transfers: filename → (director session, actor session)
        self.transfers: dict[str, tuple[Session, Session]] = {}
        self.bridge = LegacyBridge(self)
        self.router = Router(self)
        self._status_task: asyncio.Task | None = None

    # ---- lifecycle --------------------------------------------------------------------------

    def start(self) -> None:
        if self.settings.status_interval_s and self._status_task is None:
            self._status_task = asyncio.get_running_loop().create_task(self._status_loop())

    async def stop(self) -> None:
        task, self._status_task = self._status_task, None
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ---- updates ----------------------------------------------------------------------------

    def update_for(self, role: str, platform: str, version: str) -> dict:
        return find_update(load_manifest(self.settings.manifest_file, self.log), role, platform, version)

    # ---- approvals (from a v0.3 or v2 director) -----------------------------------------------

    async def approve(self, machine_id: str) -> None:
        entry = self.pending.pop(machine_id, None)
        if entry is None:
            return
        self.approvals.add(machine_id, entry.name, entry.role if entry.role in ("actor", "camera") else None)
        session = entry.session
        if session is not None and session in self.registry:
            session.approved = True
            if session.legacy:
                await self.bridge.send_welcome(session)
            else:
                await self.router.send_welcome(session)
        self.log(f"{entry.role.capitalize()} approved by director: {entry.name}")
        await self.bridge.after_approve(entry)
        await self.router.roster_changed()

    async def deny(self, machine_id: str) -> None:
        entry = self.pending.pop(machine_id, None)
        if entry is None:
            return
        self.log(f"{entry.role.capitalize()} denied by director: {entry.name}")
        session = entry.session
        if session is not None:
            if session.legacy:
                await self.bridge.send_denied(session, "Denied by director")
            else:
                await self.router.send_denied(session, "Denied by director")
        await self.bridge.send_pending_list()
        await self.router.roster_changed()

    async def forget(self, machine_id: str, name: str) -> None:
        """Remove an approval; the machine has to be approved again (it goes back to pending)."""
        info = self.approvals.get(machine_id)
        if not info:
            return
        role = info.get("role", "actor")
        self.approvals.remove(machine_id)
        self.log(f"{role.capitalize()} forgotten by name: {name}")
        await self.bridge.notify_forgotten(machine_id)
        for session in self.registry:
            if not session.legacy and session.machine_id == machine_id and session.role in ("actor", "camera") and session.approved:
                session.approved = False
                session.retired = True
                await self.router.send_forgotten(session)
        self.pending[machine_id] = PendingEntry(name=name, role=role)
        await self.bridge.send_user_list()
        await self.bridge.send_pending_list()
        await self.router.roster_changed()

    async def replace_old_connections(self, session: Session) -> None:
        """A known machine connected again: drop its older connection in the same role. The v0.3
        relay did this for actors only, and still announces the old one as "left" afterwards."""
        for old in self.registry:
            if old is session or old.machine_id != session.machine_id:
                continue
            if session.legacy and old.role != "actor":
                continue
            if not session.legacy and old.perm_role != session.perm_role:
                continue
            self.log(f"Disconnecting old connection for '{old.name}'")
            if old.legacy:
                await self.bridge.send_replaced(old)
            else:
                old.retired = True
                await self.router.send_denied(old, "Reconnected from another location")
            self.registry.remove(old)

    # ---- latency ------------------------------------------------------------------------------

    def record_pong(self, session: Session, rtt_ms: int | None = None) -> None:
        """A PONG (v0.3) or time.pong (v2) arrived: same rolling average as the v0.3 relay."""
        now = time.time()
        session.last_ping_received = now
        if rtt_ms is None:
            if session.last_ping_sent <= 0:
                return
            rtt_ms = int((now - session.last_ping_sent) * 1000)
        if session.latency_ms > 0:
            session.latency_ms = int((session.latency_ms + rtt_ms) / 2)
        else:
            session.latency_ms = rtt_ms

    async def _status_loop(self) -> None:
        settings = self.settings
        while True:
            await asyncio.sleep(settings.status_interval_s)
            await self.bridge.ping_actors()
            await self.router.ping_sessions()
            await asyncio.sleep(settings.status_grace_s)
            now = time.time()
            for session in self.registry.approved():
                tracked = session.role == "actor" if session.legacy else True
                if tracked and session.last_ping_received > 0 and now - session.last_ping_received > settings.ping_timeout_s:
                    session.latency_ms = -1  # timed out
            await self.bridge.send_actor_status()
            await self.router.send_latency()
