"""Relay state and the operations both endpoints share (approve, deny, forget, status loop).

Every change is announced twice: in v0.3 terms to /ws sessions (legacy_bridge.LegacyBridge, in
the exact order the v0.3 relay used) and as presence.roster to /v2/ws sessions (router.Router).

server.log also gets what's needed to tell why someone dropped: every disconnect with its close
code, how long the client had been silent and how long it was connected; pings still unanswered
when the status goes out and round trips over slow_rtt_ms (once a minute per session at most);
and a status loop that ran late, which means the relay itself stalled rather than the network.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from shared import APP_VERSION as LEGACY_VERSION

from . import SERVER_VERSION
from .keepalive import TIMED_OUT
from .legacy_bridge import LegacyBridge
from .router import Router
from .sessions import Approvals, Registry, Session
from .settings import Log, Settings, Throttle
from .timesync import Clock
from .transfers import Transfers
from .updates import find_update, load_manifest

__all__ = ["LEGACY_VERSION", "SERVER_VERSION", "PendingEntry", "Relay", "close_text", "span"]

# What a close code means (RFC 6455 §7.4.1, and router.py's own 44xx codes)
CLOSE_NAMES = {
    1000: "normal closure",
    1001: "going away",
    1002: "protocol error",
    1003: "unsupported data",
    1005: "connection lost, no close frame",
    1006: "connection lost, no close frame",
    1007: "invalid data",
    1008: "policy violation",
    1009: "message too big",
    1011: "internal error",
    1012: "service restart",
    4400: "bad hello",
    4401: "wrong secret",
    4403: "removed by the relay",
    4408: "no hello in time",
}


def close_text(code: int | None, reason: str | None = None) -> str:
    """'1011 keepalive ping timeout', '1000 normal closure', '1005 connection lost, no close frame'."""
    if code is None:
        return "no close code"
    return f"{code} {reason or CLOSE_NAMES.get(code, 'unknown close code')}"


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
        # v2 file transfers (transfers.py)
        self.files = Transfers(self)
        self.bridge = LegacyBridge(self)
        self.router = Router(self)
        self._status_task: asyncio.Task | None = None
        self._lag = Throttle()

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

    async def forget(self, machine_id: str, name: str, requeue_offline: bool = True) -> None:
        """Remove an approval; the machine has to be approved again (it goes back to pending, as on
        the v0.3 relay). A v2 director's forget passes requeue_offline=False: a machine with no
        connection then just goes, instead of waiting in pending for nobody."""
        info = self.approvals.get(machine_id)
        if not info:
            return
        role = info.get("role", "actor")
        self.approvals.remove(machine_id)
        self.log(f"{role.capitalize()} forgotten by name: {name}")
        await self.bridge.notify_forgotten(machine_id)
        connected = False
        for session in self.registry:
            if session.machine_id == machine_id and session.role in ("actor", "camera"):
                connected = True
            if not session.legacy and session.machine_id == machine_id and session.role in ("actor", "camera") and session.approved:
                session.approved = False
                session.retired = True
                await self.router.send_forgotten(session)
        if connected or requeue_offline:
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
        previous = session.last_ping_received or session.connected_at
        session.last_ping_received = now
        if rtt_ms is None:
            if session.last_ping_sent <= 0:
                return
            rtt_ms = int((now - session.last_ping_sent) * 1000)
        self._pong_health(session, rtt_ms, now - previous)
        if session.latency_ms > 0:
            session.latency_ms = int((session.latency_ms + rtt_ms) / 2)
        else:
            session.latency_ms = rtt_ms

    async def _status_loop(self) -> None:
        settings = self.settings
        while True:
            started = time.monotonic()
            await asyncio.sleep(settings.status_interval_s)
            self._check_lag(time.monotonic() - started - settings.status_interval_s)
            await self.bridge.ping_actors()
            await self.router.ping_sessions()
            await asyncio.sleep(settings.status_grace_s)
            now = time.time()
            for session in self.registry.approved():
                tracked = session.role == "actor" if session.legacy else True
                if tracked:
                    self._check_pong(session, now)
                if tracked and session.last_ping_received > 0 and now - session.last_ping_received > settings.ping_timeout_s:
                    session.latency_ms = -1  # timed out
            await self.bridge.send_actor_status()
            await self.router.send_latency()

    # ---- link health in server.log -------------------------------------------------------------

    def disconnected(self, session: Session, code: int | None, reason: str | None = None) -> None:
        """The "Client disconnected" line: how it closed, when the client last sent anything, and
        how long it was connected. A long silence before a 1005 or a keepalive timeout means the
        network stalled; a short one, that the connection was cut."""
        now = time.time()
        scope = getattr(session.websocket, "scope", None) or {}
        if session.closed_by_relay:
            how = f"{session.closed_by_relay}, closed by the relay"
        elif scope.get(TIMED_OUT):
            how = "1011 keepalive ping timeout: the relay's ping got no pong"
        else:
            how = close_text(code, reason)
        parts = [how]
        if session.last_received:
            parts.append(f"last message {span(now - session.last_received)} ago")
        parts.append(f"connected {span(now - session.connected_at)}")
        self.log(f"Client disconnected: {session.name} ({'; '.join(parts)})")

    def _health(self, session: Session, text: str) -> bool:
        """A slow-link line, at most one per session per health_log_every_s. Returns whether it was logged."""
        line = session.health(text, self.settings.health_log_every_s)
        if line:
            self.log(line)
        return line is not None

    def _check_pong(self, session: Session, now: float) -> None:
        """Status time: is this round's ping still unanswered? Logged once per run of misses."""
        sent = session.last_ping_sent
        if sent <= 0 or session.last_ping_received >= sent:
            return
        session.missed_pongs += 1
        if session.missed_pongs == 1:
            heard = f", last message {span(now - session.last_received)} ago" if session.last_received else ""
            session.stall_logged = self._health(
                session, f"No pong from {session.role} '{session.name}' within {span(now - sent)}{heard}")

    def _pong_health(self, session: Session, rtt_ms: int, since_last_s: float) -> None:
        if session.missed_pongs:
            if session.stall_logged:  # the end of a stall whose start is in the log
                self.log(f"{session.role.capitalize()} '{session.name}' answered again: round trip {rtt_ms} ms, "
                         f"{span(since_last_s)} since its last pong")
            session.missed_pongs, session.stall_logged = 0, False
        elif rtt_ms > self.settings.slow_rtt_ms:
            self._health(session, f"Slow round trip to {session.role} '{session.name}': {rtt_ms} ms")

    def _check_lag(self, late_s: float) -> None:
        if late_s > self.settings.loop_lag_s:
            line = self._lag(f"Status loop ran {late_s:.1f} s late: the relay itself was stalled", self.settings.health_log_every_s)
            if line:
                self.log(line)
