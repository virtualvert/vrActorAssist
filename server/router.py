"""/v2/ws: handshake, permission checks, routing by `to`, presence and clock sync (spec §5, §6).

The relay reads `data` only for the core types it handles or translates for v0.3 clients;
everything else is routed as is, after the permission table (permissions.py).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from vrcas_protocol import Envelope, IdsTarget, RoleTarget, make, parse, validate
from vrcas_protocol.messages import (
    ApprovalForget,
    Hello,
    PendingRequest,
    PresenceLatency,
    LatencyEntry,
    PresenceRoster,
    RosterSession,
    TimePong,
    Welcome,
)

from . import SERVER_VERSION, permissions
from .permissions import DIRECTION
from .sessions import Session
from .timesync import pong, rtt_ms
from .updates import compare_versions_v2

if TYPE_CHECKING:
    from .relay import Relay

# Close codes (4000–4999 are free for applications)
CLOSE_BAD_HELLO = 4400
CLOSE_BAD_SECRET = 4401
CLOSE_REMOVED = 4403
CLOSE_HELLO_TIMEOUT = 4408

_UNSAFE_NAME = re.compile(r"[|\x00-\x1f\x7f]")


def clean_name(name: str) -> str:
    """Names also travel in v0.3 pipe messages, so no '|' and no control characters."""
    return _UNSAFE_NAME.sub("/", name).strip() or "Unnamed"


def frame(env: Envelope) -> str:
    return json.dumps(env.wire(), ensure_ascii=False, separators=(",", ":"))


class Router:
    def __init__(self, relay: "Relay"):
        self.relay = relay

    @property
    def log(self):
        return self.relay.log

    # ---- the /v2/ws endpoint ------------------------------------------------------------------

    async def endpoint(self, websocket: WebSocket) -> None:
        relay = self.relay
        await websocket.accept()
        session = Session(kind="v2", websocket=websocket)
        relay.registry.add(session)
        self.log(f"v2 client connected from {websocket.client}")
        try:
            try:
                first = await asyncio.wait_for(self._receive(session), relay.settings.hello_timeout_s)
            except asyncio.TimeoutError:
                await self._send(session, "denied", {"reason": "No hello received"})
                await session.close(CLOSE_HELLO_TIMEOUT)
                return
            if first is None:
                await session.close(CLOSE_BAD_HELLO)
                return
            if not await self._hello(session, first[0]):
                return
            while True:
                received = await self._receive(session)
                if received is not None:
                    await self._dispatch(session, *received)
        except WebSocketDisconnect:
            self.log(f"Client disconnected: {session.name}")
        except Exception as e:  # one bad session must not take the relay down
            self.log(f"Error ({session.name}): {e!r}")
        finally:
            await self._cleanup(session)

    async def _receive(self, session: Session) -> tuple[Envelope, int] | None:
        """One frame as (envelope, receive time). None when the frame was rejected."""
        message = await session.websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        received_ms = self.relay.clock.now_ms()
        text = message.get("text")
        if text is None:
            await self._error(session, "unsupported", "Binary frames arrive with the files addon")
            return None
        if len(text.encode("utf-8")) > self.relay.settings.max_frame_bytes:
            await self._error(session, "invalid", "Message too large")
            return None
        try:
            env = parse(text)
        except ValueError as exc:
            await self._error(session, "invalid", f"Not a v2 envelope: {_short(exc)}", reply_to=_id_of(text))
            return None
        env.from_ = session.id or None  # never what the client claims
        if env.ts is None:
            env.ts = received_ms
        return env, received_ms

    async def _hello(self, session: Session, env: Envelope) -> bool:
        relay = self.relay
        if env.type != "hello":
            await self._error(session, "invalid", "Send hello first", reply_to=env.id)
            await session.close(CLOSE_BAD_HELLO)
            return False
        try:
            hello = Hello.model_validate(env.data)
        except ValueError as exc:
            await self._error(session, "invalid", f"Bad hello: {_short(exc)}", reply_to=env.id)
            await session.close(CLOSE_BAD_HELLO)
            return False
        session.name = clean_name(hello.name)
        session.machine_id = hello.machine_id
        session.role = hello.role
        session.version = hello.version
        session.platform = hello.platform
        session.capabilities = list(hello.capabilities)
        self.log(f"Registration (v2): {session.name} ({session.role}), machine_id={session.machine_id[:8]}..., "
                 f"version={session.version or '?'}, platform={session.platform or 'unknown'}")

        if session.role in DIRECTION:
            secret = hello.secret or ""
            if not hmac.compare_digest(secret.encode(), relay.settings.secret.encode()):
                self.log(f"{session.role.capitalize()} '{session.name}' failed auth")
                await self.send_denied(session, "Invalid secret", CLOSE_BAD_SECRET)
                return False
            session.approved = True
            self.log(f"{session.role.capitalize()} '{session.name}' authenticated")
            await self._join(session)
        elif session.machine_id in relay.approvals:
            await relay.replace_old_connections(session)
            session.approved = True
            session.name = relay.approvals.get(session.machine_id).get("name", session.name)
            self.log(f"{session.role.capitalize()} '{session.name}' auto-approved (known machine_id)")
            await self._join(session)
        else:
            from .relay import PendingEntry

            entry = relay.pending.get(session.machine_id)
            if entry is None:
                relay.pending[session.machine_id] = PendingEntry(name=session.name, role=session.role, session=session)
                self.log(f"{session.role.capitalize()} '{session.name}' pending approval")
            else:
                entry.session, entry.role = session, session.role
            relay.registry.assign_id(session)
            await self._send(session, "approval.pending", {})
            if entry is None:
                await relay.bridge.v2_pending()
            await self.roster_changed()
        return True

    async def _join(self, session: Session) -> None:
        await self.send_welcome(session)
        await self.relay.bridge.v2_joined(session)
        await self.roster_changed()

    async def send_welcome(self, session: Session) -> None:
        relay = self.relay
        relay.registry.assign_id(session)
        status, message = compare_versions_v2(session.version, SERVER_VERSION)
        if status != "ok":
            self.log(f"Version mismatch: {session.role} '{session.name}' v{session.version} vs relay v{SERVER_VERSION} ({status})")
        delay = relay.approvals.delay_ms(session.machine_id) if session.role in ("actor", "camera") else 0
        await self._send(session, "welcome", Welcome(
            session_id=session.id,
            name=session.name,
            role=session.role,
            server_version=SERVER_VERSION,
            version_status=status,
            version_message=message,
            server_time=relay.clock.now_ms(),
            delay_ms=delay,
        ))
        update = relay.update_for(session.role, session.platform, session.version)
        if update:
            await self._send(session, "update.available", update)
            self.log(f"Update available for {session.role} '{session.name}': v{update['latest_version']}")

    # ---- after the handshake ------------------------------------------------------------------------

    async def _dispatch(self, session: Session, env: Envelope, received_ms: int) -> None:
        relay = self.relay
        env.from_ = session.id
        if not session.approved:
            if env.type == "time.ping":
                await self._time_ping(session, env, received_ms)
            else:
                await self._error(session, "not_approved", "Wait for a director to approve you", env)
            return
        roles = permissions.rule(env.type)
        if roles is None:
            await self._error(session, "unknown_type", f"Unknown message type {env.type}", env)
            return
        if session.perm_role not in roles:
            self.log(f"Rejected {env.type} from {session.role} '{session.name}'")
            await self._error(session, "forbidden", f"A {session.role} can't send {env.type}", env)
            return
        try:
            payload = validate(env.type, env.data)
        except ValueError as exc:
            await self._error(session, "invalid", f"Bad {env.type}: {_short(exc)}", env)
            return

        if env.type == "hello":
            await self._error(session, "invalid", "Already registered", env)
        elif env.type == "time.ping":
            await self._time_ping(session, env, received_ms)
        elif env.type == "time.pong":
            self._time_pong(session, env, payload)
        elif env.type == "approval.approve":
            await relay.approve(payload.machine_id)
        elif env.type == "approval.deny":
            await relay.deny(payload.machine_id)
        elif env.type == "approval.forget":
            await self._forget(session, env, payload)
        elif env.type == "actor.settings":
            await self._actor_settings(session, env, payload)
        elif env.type.startswith("cuelist."):
            await self._error(session, "unsupported", "Cue list storage isn't built yet", env)
        else:
            await self.route(session, env)

    async def route(self, sender: Session, env: Envelope) -> None:
        if env.to == "server":
            await self._error(sender, "invalid", f"{env.type} needs a target (to)", env)
            return
        recipients, missing = self._resolve(sender, env.to)
        text = frame(env)
        unsupported: list[str] = []
        for recipient in recipients:
            if recipient.legacy:
                if not await self.relay.bridge.deliver(env, sender, recipient):
                    unsupported.append(recipient.id)
            else:
                await recipient.send_text(text)
        if missing:
            await self._error(sender, "unknown_target", "Not connected: " + ", ".join(missing), env, ids=missing)
        if unsupported:
            names = ", ".join(r.name for r in recipients if r.id in unsupported)
            await self._error(sender, "unsupported", f"{names} use{'s' if len(unsupported) == 1 else ''} a v0.3 client, "
                              f"which can't do {env.type} like this", env, ids=unsupported)

    def _resolve(self, sender: Session, to: Any) -> tuple[list[Session], list[str]]:
        approved = [s for s in self.relay.registry.approved() if s.id]
        if to == "all":
            return [s for s in approved if s is not sender], []
        if isinstance(to, RoleTarget):
            return [s for s in approved if s is not sender and s.perm_role == to.role], []
        if isinstance(to, IdsTarget):
            by_id = {s.id: s for s in approved}
            found, missing = [], []
            for session_id in dict.fromkeys(to.ids):
                (found if session_id in by_id else missing).append(by_id.get(session_id, session_id))
            return found, missing
        return [], []

    async def from_legacy(self, sender: Session, msg_type: str, data: dict, to: Any) -> None:
        """A v0.3 message, translated, for the v2 sessions it concerns (v0.3 ones got the original)."""
        try:
            validate(msg_type, data)
        except ValueError as exc:
            self.log(f"Not passing {msg_type} from '{sender.name}' to v2 clients: {_short(exc)}")
            return
        env = make(msg_type, data, to=to, from_=sender.id or None, ts=self.relay.clock.now_ms())
        v2 = [s for s in self.relay.registry.approved() if not s.legacy and s.id and s is not sender]
        if to == "all":
            recipients = v2
        elif isinstance(to, dict) and "role" in to:
            roles = DIRECTION if to["role"] == "director" else {to["role"]}
            recipients = [s for s in v2 if s.perm_role in roles]
        else:
            ids = set(to.get("ids", []))
            recipients = [s for s in v2 if s.id in ids]
        text = frame(env)
        for recipient in recipients:
            await recipient.send_text(text)

    # ---- core requests ------------------------------------------------------------------------------

    async def _time_ping(self, session: Session, env: Envelope, received_ms: int) -> None:
        try:
            t0 = int(env.data["t0"])
        except (KeyError, TypeError, ValueError):
            await self._error(session, "invalid", "time.ping needs t0", env)
            return
        await self._send(session, "time.pong", pong(t0, received_ms, self.relay.clock.now_ms()), reply_to=env.id)

    def _time_pong(self, session: Session, env: Envelope, payload: TimePong) -> None:
        """The answer to our own time.ping: its round trip is this session's latency."""
        if session.ping_id is None or env.reply_to != session.ping_id:
            return
        session.ping_id = None
        rtt = rtt_ms(payload.t0, payload.t1, payload.t2, self.relay.clock.now_ms())
        self.relay.record_pong(session, rtt)

    async def _forget(self, session: Session, env: Envelope, payload: ApprovalForget) -> None:
        relay = self.relay
        machine_id = payload.machine_id
        if payload.id:
            target = relay.registry.by_id(payload.id)
            if target is None or target.perm_role not in ("actor", "camera"):
                await self._error(session, "unknown_target", f"No actor or camera {payload.id}", env, ids=[payload.id])
                return
            machine_id = target.machine_id
        if not machine_id or machine_id not in relay.approvals:
            await self._error(session, "unknown_target", "That machine isn't approved", env)
            return
        await relay.forget(machine_id, relay.approvals.get(machine_id).get("name", ""))

    async def _actor_settings(self, session: Session, env: Envelope, payload) -> None:
        relay = self.relay
        target = relay.registry.by_id(payload.id)
        if target is None or target.perm_role not in ("actor", "camera") or target.machine_id not in relay.approvals:
            await self._error(session, "unknown_target", f"No approved actor or camera {payload.id}", env, ids=[payload.id])
            return
        fields: dict[str, Any] = {}
        if payload.delay_ms is not None:
            fields["delay_ms"] = payload.delay_ms
        renamed = False
        if payload.display_name:
            name = clean_name(payload.display_name)
            renamed = name != target.name
            fields["name"] = target.name = name
        relay.approvals.update(target.machine_id, **fields)
        self.log(f"Settings for '{target.name}' by '{session.name}': {fields}")
        if renamed and target.role == "actor":
            await relay.bridge.renamed()
        await self.roster_changed()

    # ---- presence -----------------------------------------------------------------------------------

    def _entry(self, s: Session) -> RosterSession:
        return RosterSession(
            id=s.id,
            name=s.name,
            role=s.perm_role,
            legacy=s.legacy,
            version=s.version,
            platform=s.platform,
            capabilities=s.capabilities,
            latency_ms=s.latency_ms if s.latency_ms > 0 else None,
            timed_out=s.latency_ms == -1,
            delay_ms=self.relay.approvals.delay_ms(s.machine_id) if s.perm_role in ("actor", "camera") else 0,
        )

    def roster_for(self, recipient: Session) -> PresenceRoster:
        relay = self.relay
        sessions = [self._entry(s) for s in relay.registry.approved() if s.id]
        pending: list[PendingRequest] = []
        if recipient.perm_role in DIRECTION:
            pending = [
                PendingRequest(machine_id=mid, name=info.name, role=info.role,
                               legacy=info.session is not None and info.session.legacy)
                for mid, info in relay.pending.items()
            ]
        return PresenceRoster(sessions=sessions, pending=pending)

    async def roster_changed(self) -> None:
        for s in self.relay.registry.approved():
            if not s.legacy and s.id:
                await self._send(s, "presence.roster", self.roster_for(s))

    async def ping_sessions(self) -> None:
        now = time.time()
        for s in self.relay.registry.approved():
            if not s.legacy and s.id:
                env = make("time.ping", {"t0": self.relay.clock.now_ms()}, to={"ids": [s.id]}, from_="server")
                s.ping_id = env.id
                s.last_ping_sent = now
                await s.send_text(frame(env))

    async def send_latency(self) -> None:
        relay = self.relay
        entries = [
            LatencyEntry(id=s.id, latency_ms=s.latency_ms if s.latency_ms > 0 else None, timed_out=s.latency_ms == -1)
            for s in relay.registry.approved() if s.id
        ]
        for s in relay.registry.approved():
            if not s.legacy and s.id and s.perm_role in DIRECTION:
                await self._send(s, "presence.latency", PresenceLatency(sessions=entries))

    # ---- sending ------------------------------------------------------------------------------------

    async def _send(self, session: Session, msg_type: str, data: dict | BaseModel, reply_to: str | None = None) -> None:
        to = {"ids": [session.id]} if session.id else "all"
        env = make(msg_type, data, to=to, from_="server", reply_to=reply_to, ts=self.relay.clock.now_ms())
        await session.send_text(frame(env))

    async def _error(self, session: Session, code: str, message: str, env: Envelope | None = None, *,
                     reply_to: str | None = None, ids: list[str] | None = None) -> None:
        data: dict[str, Any] = {"code": code, "message": message}
        if env is not None:
            data["type"] = env.type
            reply_to = env.id
        if ids:
            data["ids"] = ids
        await self._send(session, "error", data, reply_to=reply_to)

    async def send_denied(self, session: Session, reason: str, code: int = CLOSE_REMOVED) -> None:
        await self._send(session, "denied", {"reason": reason})
        await session.close(code)

    async def send_forgotten(self, session: Session) -> None:
        await self._send(session, "approval.forgotten", {})
        await session.close(CLOSE_REMOVED)

    async def _cleanup(self, session: Session) -> None:
        relay = self.relay
        relay.registry.remove(session)
        for machine_id, info in list(relay.pending.items()):
            if info.session is session:
                del relay.pending[machine_id]
        if session.approved and not session.retired:
            await relay.bridge.v2_left(session)
        await self.roster_changed()


def _short(exc: Exception) -> str:
    text = str(exc).splitlines()
    return "; ".join(line.strip() for line in text[:3])


def _id_of(text: str) -> str | None:
    try:
        value = json.loads(text).get("id")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and len(value) <= 64 else None
