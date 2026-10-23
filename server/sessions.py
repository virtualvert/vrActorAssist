"""Connected sessions (v2 and v0.3), session ids, approvals and per-actor settings."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .permissions import legacy_role
from .settings import Throttle


@dataclass(eq=False)
class Session:
    """One connection. `kind` is "legacy" (/ws, pipe protocol) or "v2" (/v2/ws, JSON envelopes)."""

    kind: str
    websocket: Any
    id: str = ""
    name: str = "Unknown"
    machine_id: str = ""
    # As registered. v0.3 clients may send any string; `perm_role` is what the permission table sees.
    role: str = "actor"
    approved: bool = False
    version: str = ""
    platform: str = ""
    capabilities: list[str] = field(default_factory=list)
    # Latency as the v0.3 relay tracked it: round trip of the last pings (rolling), -1 = timed out
    last_ping_sent: float = 0.0
    last_ping_received: float = 0.0
    latency_ms: int = 0
    # v2: id and t0 of the relay's outstanding time.ping
    ping_id: str | None = None
    # Set when the relay replaced or removed this session, so its own cleanup stays quiet
    retired: bool = False
    # v0.3 actors: cues held back until their fire time (scheduling emulation, spec §11.3)
    held: list[tuple[asyncio.Task, str]] = field(default_factory=list)
    # Link health for server.log (relay.py): when it connected and last sent anything (time.time()),
    # status rounds in a row without a pong, and the rate limit on slow-link lines
    connected_at: float = field(default_factory=time.time)
    last_received: float = 0.0
    missed_pongs: int = 0
    stall_logged: bool = False
    health: Throttle = field(default_factory=Throttle)
    # "4403 Reconnected from another location" once the relay has closed this connection
    closed_by_relay: str = ""

    @property
    def legacy(self) -> bool:
        return self.kind == "legacy"

    @property
    def perm_role(self) -> str:
        return legacy_role(self.role) if self.legacy else self.role

    async def send_text(self, text: str) -> bool:
        try:
            await self.websocket.send_text(text)
            return True
        except Exception:
            return False

    async def send_bytes(self, data: bytes) -> bool:
        try:
            await self.websocket.send_bytes(data)
            return True
        except Exception:
            return False

    async def close(self, code: int = 1000, why: str = "") -> None:
        """`why` is for server.log only; the close frame carries just the code, as before."""
        self.closed_by_relay = f"{code} {why}".strip()
        try:
            await self.websocket.close(code=code)
        except Exception:
            pass


class Registry:
    """All connections in the order they connected (v0.3 USERS lists follow it)."""

    def __init__(self) -> None:
        self._sessions: dict[Session, None] = {}
        # (machine_id, role) → session id: a machine that reconnects keeps its id while the relay runs
        self._ids: dict[tuple[str, str], str] = {}

    def add(self, session: Session) -> None:
        self._sessions[session] = None

    def remove(self, session: Session) -> None:
        self._sessions.pop(session, None)

    def __contains__(self, session: Session) -> bool:
        return session in self._sessions

    def __iter__(self) -> Iterator[Session]:
        return iter(list(self._sessions))

    def __len__(self) -> int:
        return len(self._sessions)

    def approved(self) -> list[Session]:
        return [s for s in self if s.approved]

    def by_id(self, session_id: str) -> Session | None:
        return next((s for s in self if s.approved and s.id == session_id), None)

    def assign_id(self, session: Session) -> str:
        """Session ids map to machine ids (spec §5.2). Reuse the machine's id unless another live
        session holds it (two directors on one PC, a test setup)."""
        key = (session.machine_id, session.perm_role)
        current = self._ids.get(key)
        in_use = {s.id for s in self if s is not session and s.id}
        if current is None or current in in_use:
            current = self._new_id(in_use)
            self._ids[key] = current
        session.id = current
        return current

    def _new_id(self, in_use: set[str]) -> str:
        taken = in_use | set(self._ids.values())
        while True:
            candidate = "s_" + secrets.token_hex(4)
            if candidate not in taken:
                return candidate


class Approvals:
    """approved_actors.json: machine_id → {name, approved_at, role?, delay_ms?}.

    The v0.3 relay wrote only name and approved_at; it ignores the extra keys, so the file still
    works if the old relay is started again.
    """

    def __init__(self, path: Path, log: Callable[[str], None]):
        self.path = path
        self.log = log
        self.entries: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.entries, indent=2))
        except Exception as e:
            self.log(f"Error saving approved: {e}")

    def __contains__(self, machine_id: str) -> bool:
        return machine_id in self.entries

    def get(self, machine_id: str) -> dict:
        return self.entries.get(machine_id, {})

    def add(self, machine_id: str, name: str, role: str | None = None) -> None:
        entry = {"name": name, "approved_at": datetime.now().isoformat()}
        if role and role != "actor":
            entry["role"] = role
        self.entries[machine_id] = entry
        self.save()

    def remove(self, machine_id: str) -> None:
        if self.entries.pop(machine_id, None) is not None:
            self.save()

    def update(self, machine_id: str, **fields: Any) -> None:
        entry = self.entries.get(machine_id)
        if entry is None:
            return
        entry.update({k: v for k, v in fields.items() if v is not None})
        self.save()

    def find_by_name(self, name: str) -> str | None:
        for machine_id, info in self.entries.items():
            if info.get("name") == name:
                return machine_id
        return None

    def delay_ms(self, machine_id: str) -> int:
        value = self.get(machine_id).get("delay_ms", 0)
        return value if isinstance(value, int) else 0
