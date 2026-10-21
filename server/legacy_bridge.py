"""/ws for v0.3 clients: the pipe protocol, bridged to v2 sessions (spec §11).

v0.3 ↔ v0.3 traffic behaves exactly as on the v0.3 relay, quirks included (tests/golden/). On
top of that:
- v2 sessions take part: v2 actors are in USERS / STATUS / PENDING and receive cues sent by
  name; v2 directors are warned about like v0.3 ones. Camera sessions stay hidden from /ws.
- v0.3 messages are checked against the permission table (permissions.py) and translated for
  v2 recipients; v2 messages are translated for v0.3 recipients (`deliver`).
- A v2 message with `at` is held for a v0.3 actor until fire_at − RTT/2 (scheduling emulation).
- v0.3 ↔ v0.3 file transfers work as before. Files between v0.3 and v2 are translated by
  file_bridge.py (FILEREQ … FILEEND, BATCH_* ⇄ file.* and binary chunks).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from shared import APP_VERSION as LEGACY_VERSION
from shared import format_message, parse_message
from vrcas_protocol import Envelope

from . import permissions
from .file_bridge import FileBridge
from .permissions import LEGACY_NOTICE_TYPES, is_cue_text
from .sessions import Session
from .updates import compare_versions

if TYPE_CHECKING:
    from .relay import PendingEntry, Relay

FILE_TYPES = ("FILEREQ", "FILEACK", "FILEDENY", "FILESTART", "FILECHUNK", "FILEEND", "FILEOK", "FILEERR")
START_TYPES = ("cue.go", "cue.play", "soundpad.play")
STOP_TYPES = ("cue.stop", "soundpad.stop")


class Unsupported(Exception):
    """A v2 message a v0.3 client can't carry."""


# ---- v0.3 text ↔ v2 -------------------------------------------------------------------------


def parse_cue(command: str) -> tuple[str, dict] | None:
    """`*go` / `go` → ("cue.go", {}), `*play:3` → ("cue.play", {"index": 3}); else None."""
    cmd = command.strip().lower().lstrip("*").strip()
    if cmd in ("go", "stop"):
        return f"cue.{cmd}", {}
    if cmd.startswith("play:"):
        index = cmd[5:].strip()
        if index.isdigit() and int(index) > 0:
            return "cue.play", {"index": int(index)}
    return None


def osc_value_from_text(value: str) -> bool | int | float | str:
    """OSC_CUE carries text; v2's osc.param carries typed values (VRChat needs bool / int / float)."""
    lowered = value.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        number = float(lowered)
    except ValueError:
        return value
    return int(number) if lowered.lstrip("-").isdigit() else number


def osc_value_to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def clean(text: str) -> str:
    return str(text).replace("|", "/")


def cue_text(env: Envelope) -> str:
    """The v0.3 `*command` for a v2 cue or soundpad message. Raises Unsupported."""
    data = env.data
    if env.type == "cue.go":
        return "*go"
    if env.type in STOP_TYPES:
        return "*stop"
    if env.type == "cue.play":
        return f"*play:{int(data['index'])}"
    if env.type == "soundpad.play":
        sound = data.get("sound") or {}
        if data.get("lines") not in (None, "both") or data.get("volume") is not None or data.get("start_ms"):
            raise Unsupported("output lines, volume and start position need vrcActorSync 0.4")
        if sound.get("selected"):
            return "*go"
        if sound.get("index"):
            return f"*play:{int(sound['index'])}"
        raise Unsupported("v0.3 clients can only play the selected sound or a sound by number")
    raise Unsupported(f"{env.type} isn't available to v0.3 clients")


def to_legacy(env: Envelope, sender: Session, recipient: Session) -> str | None:
    """The frame a v0.3 client gets for a v2 message: None when there's nothing to show it
    (presence, acks, addon traffic). Raises Unsupported when it can't carry an action."""
    data = env.data
    if env.type == "chat.msg":
        return format_message("MSG", sender=clean(sender.name), text=data.get("text", ""))
    if env.type == "chat.priv":
        text = data.get("text", "")
        if is_cue_text(text):
            text = " " + text  # chat, not a command: a v0.3 actor runs private text starting with '*'
        return format_message("PRIV", sender=clean(sender.name), target=clean(recipient.name), text=text)
    if env.type in ("cue.go", "cue.stop", "cue.play", "soundpad.play", "soundpad.stop"):
        return format_message("PRIV", sender=clean(sender.name), target=clean(recipient.name), text=cue_text(env))
    if env.type == "osc.param":
        return format_message("OSC_CUE", target=clean(recipient.name), parameter=clean(data.get("parameter", "")),
                              value=clean(osc_value_to_text(data.get("value", ""))))
    if env.type.startswith(("soundpad.", "osc.cue.load")):
        raise Unsupported(f"{env.type} isn't available to v0.3 clients")
    return None


class LegacyBridge:
    def __init__(self, relay: "Relay"):
        self.relay = relay
        self.files = FileBridge(relay)

    @property
    def log(self):
        return self.relay.log

    # ---- the /ws endpoint (the v0.3 handler) ---------------------------------------------------

    async def endpoint(self, websocket: WebSocket) -> None:
        relay = self.relay
        await websocket.accept()
        session = Session(kind="legacy", websocket=websocket)
        relay.registry.add(session)
        self.log(f"Client connected from {websocket.client}")
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg_type, msg_data = parse_message(data)
                except (ValueError, IndexError):
                    # Bad numeric field (e.g. FILECHUNK|f|x|...) - drop it instead of disconnecting
                    self.log(f"Malformed message from '{session.name}': {data[:80]!r}")
                    continue
                if not msg_type:
                    continue
                if msg_type == "REGISTER":
                    if not await self._register(session, msg_data):
                        return
                    continue
                if not session.approved:
                    await session.send_text(format_message("DENIED", reason="Not approved"))
                    continue
                if msg_type == "PONG" or data == "PONG":
                    relay.record_pong(session)
                    continue
                v2_type = permissions.legacy_type(msg_type, msg_data)
                if v2_type and not permissions.allowed(session.perm_role, v2_type):
                    self.log(f"Rejected {msg_type} from non-director '{session.name}' ({session.role})")
                    if msg_type in LEGACY_NOTICE_TYPES:
                        await session.send_text(format_message("MSG", sender="SERVER",
                            text=f"Permission denied: only the director can send {msg_type}"))
                    continue
                await self._handle(session, msg_type, msg_data, data)
        except WebSocketDisconnect:
            self.log(f"Client disconnected: {session.name}")
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            await self._cleanup(session)

    async def _register(self, session: Session, msg_data: dict) -> bool:
        """REGISTER, as the v0.3 relay handled it. Returns False when the connection was closed."""
        relay = self.relay
        name = msg_data.get("name", "Unknown")
        machine_id = msg_data.get("machine_id", "")
        role = msg_data.get("role", "actor")
        provided_secret = msg_data.get("secret", "")

        session.name = name
        session.machine_id = machine_id
        session.role = role
        session.version = msg_data.get("version", "")
        session.platform = msg_data.get("platform", "")
        session.capabilities = ["legacy"]

        self.log(f"Registration: {name} ({role}), machine_id={machine_id[:8]}..., version={session.version or 'legacy'}, platform={session.platform or 'unknown'}")

        if role == "director":
            if provided_secret == relay.settings.secret:
                session.approved = True
                relay.registry.assign_id(session)
                self.log(f"Director '{name}' authenticated")
                await session.send_text(format_message("APPROVED"))
                await self._send_version_and_update(session, "director")
                existing = [d for d in self.directors() if d is not session]
                if existing:
                    await session.send_text(format_message("MSG", sender="SERVER",
                        text=f"⚠ Warning: {', '.join(d.name for d in existing)} is already connected"))
                    self.log(f"Director '{name}' warned about existing directors")
                    for d in existing:
                        if d.legacy:
                            await d.send_text(format_message("MSG", sender="SERVER",
                                text=f"⚠ Warning: {name} has connected as another director"))
                await self.send_user_list()
                await self.send_pending_list()
                await relay.router.roster_changed()
                return True
            self.log(f"Director '{name}' failed auth")
            await session.send_text(format_message("DENIED", reason="Invalid secret"))
            await session.close()
            return False

        if machine_id in relay.approvals:
            await relay.replace_old_connections(session)
            session.approved = True
            session.name = relay.approvals.get(machine_id).get("name", name)
            relay.registry.assign_id(session)
            self.log(f"Actor '{session.name}' auto-approved (known machine_id)")
            await self.send_welcome(session)
            if session.perm_role != "camera":
                await self.broadcast(format_message("MSG", sender="SERVER", text=f"{session.name} joined"))
            await self.send_user_list()
            await relay.router.roster_changed()
        elif machine_id in relay.pending:
            # Already pending - update the connection (may have reconnected)
            relay.pending[machine_id].session = session
            relay.registry.assign_id(session)
            await session.send_text(format_message("DENIED", reason="Pending approval"))
            await relay.router.roster_changed()
        else:
            from .relay import PendingEntry

            relay.pending[machine_id] = PendingEntry(name=name, role=permissions.legacy_role(role), session=session)
            relay.registry.assign_id(session)
            await session.send_text(format_message("DENIED", reason="Pending approval"))
            self.log(f"Actor '{name}' pending approval")
            await self.send_pending_list()
            await relay.router.roster_changed()
        return True

    async def _handle(self, session: Session, msg_type: str, msg_data: dict, data: str) -> None:
        relay = self.relay
        if msg_type == "MSG":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            await self.broadcast(format_message("MSG", sender=sender, text=text))
            if text:
                await relay.router.from_legacy(session, "chat.msg", {"text": text}, "all")

        elif msg_type == "PRIV":
            sender = msg_data.get("sender", "Unknown")
            target = msg_data.get("target", "")
            text = msg_data.get("text", "")
            found = False
            for s in relay.registry:
                if s.name == target and s.approved and s.perm_role != "camera":
                    if s.legacy:
                        if await s.send_text(format_message("PRIV", sender=sender, target=target, text=text)):
                            found = True
                    else:
                        found = True
                        await self._priv_to_v2(session, s, text)
            if not found and session.role == "director":
                await session.send_text(format_message("MSG", sender="SERVER", text=f"Actor '{target}' not found"))

        elif msg_type == "CMD":
            command = msg_data.get("command", "")
            await self.broadcast(format_message("CMD", command=command))
            cue = parse_cue(command)
            if cue:
                await relay.router.from_legacy(session, cue[0], cue[1], {"role": "actor"})
            else:
                self.log(f"CMD {command!r} has no v2 equivalent; v2 actors don't get it")

        elif msg_type in FILE_TYPES:
            await self._file(session, msg_type, msg_data, data)

        elif msg_type in ("BATCH_START", "BATCH_END", "BATCH_CANCEL"):
            target = msg_data.get("target", "")
            s = self._first_actor(target)
            if s is not None and s.legacy:
                await s.send_text(data)
            elif s is not None:
                await self.files.legacy_batch(session, s, msg_type, msg_data)

        elif msg_type == "APPROVE":
            machine_id = msg_data.get("machine_id")
            if machine_id:
                await relay.approve(machine_id)

        elif msg_type == "DENY":
            machine_id = msg_data.get("machine_id")
            if machine_id:
                await relay.deny(machine_id)

        elif msg_type == "FORGET_NAME":
            name = msg_data.get("name", "")
            machine_id = relay.approvals.find_by_name(name)
            if machine_id:
                await relay.forget(machine_id, name)

        elif msg_type == "REFRESH":
            await self.send_user_list()
            if session.role == "director":
                await self.send_pending_list()

        elif msg_type == "OSC_CUE":
            target = msg_data.get("target", "")
            s = self._first_actor(target) if target else None
            if s is not None:
                if s.legacy:
                    await s.send_text(data)
                else:
                    await relay.router.from_legacy(session, "osc.param", {
                        "parameter": msg_data.get("parameter", ""),
                        "value": osc_value_from_text(msg_data.get("value", "")),
                    }, {"ids": [s.id]})

        elif msg_type == "ACK":
            # The v0.3 relay never passed ACKs on; v2 directors get them as cue.ack
            command = msg_data.get("command", "")
            await relay.router.from_legacy(session, "cue.ack", {"command": command, "ok": msg_data.get("status") == "OK"},
                                           {"role": "director"})

    async def _priv_to_v2(self, sender: Session, recipient: Session, text: str) -> None:
        if is_cue_text(text):
            cue = parse_cue(text)
            if cue is None:
                self.log(f"{text!r} from '{sender.name}' has no v2 equivalent; not sent to '{recipient.name}'")
                return
            await self.relay.router.from_legacy(sender, cue[0], cue[1], {"ids": [recipient.id]})
        else:
            await self.relay.router.from_legacy(sender, "chat.priv", {"text": text}, {"ids": [recipient.id]})

    async def _file(self, session: Session, msg_type: str, msg_data: dict, data: str) -> None:
        transfers = self.relay.transfers
        filename = msg_data.get("filename", "")
        if msg_type == "FILEREQ":
            s = self._first_actor(msg_data.get("target", ""))
            if s is None:
                return
            if not s.legacy:
                await self.files.legacy_request(session, s, msg_data)
                return
            transfers[filename] = (session, s)
            await s.send_text(data)
        elif msg_type in ("FILESTART", "FILECHUNK", "FILEEND") and await self.files.legacy_data(session, msg_type, msg_data):
            return  # a file on its way to a v2 actor
        elif msg_type in ("FILEACK", "FILEDENY", "FILEOK", "FILEERR") and await self.files.legacy_actor_reply(session, msg_type, msg_data):
            return  # a v0.3 actor answering a v2 director
        elif filename in transfers:
            director, actor = transfers[filename]
            if msg_type in ("FILEACK", "FILEDENY", "FILEOK", "FILEERR"):
                await director.send_text(data)
                if msg_type in ("FILEOK", "FILEERR", "FILEDENY"):
                    del transfers[filename]
            elif msg_type in ("FILESTART", "FILECHUNK", "FILEEND"):
                await actor.send_text(data)

    def _first_actor(self, name: str) -> Session | None:
        """The v0.3 relay routed files, batches and OSC to the first approved actor with that name."""
        return next((s for s in self.relay.registry if s.name == name and s.approved and s.role == "actor"), None)

    async def _cleanup(self, session: Session) -> None:
        relay = self.relay
        relay.registry.remove(session)
        for machine_id, info in list(relay.pending.items()):
            if info.session is session:
                del relay.pending[machine_id]
        self.cancel_held(session)
        asyncio.create_task(relay.files.session_gone(session))
        if session.approved and session.role == "actor":
            asyncio.create_task(self.send_user_list())
            if session.name:
                asyncio.create_task(self.broadcast(format_message("MSG", sender="SERVER", text=f"{session.name} left")))
        asyncio.create_task(relay.router.roster_changed())

    # ---- what v0.3 clients are sent -------------------------------------------------------------

    def directors(self) -> list[Session]:
        """Connected directors of both kinds (the v0.3 multi-director warning covers v2 too)."""
        return [s for s in self.relay.registry if s.role == "director" and s.approved]

    def legacy_sessions(self) -> list[Session]:
        return [s for s in self.relay.registry if s.legacy and s.approved]

    def actors(self) -> list[Session]:
        """Approved actors of both kinds, in connection order (v0.3 USERS / STATUS)."""
        return [s for s in self.relay.registry if s.role == "actor" and s.approved]

    async def broadcast(self, message: str) -> None:
        """To every approved v0.3 client. Like the v0.3 relay, one that fails is dropped."""
        for s in self.legacy_sessions():
            if not await s.send_text(message):
                self.relay.registry.remove(s)

    async def send_to_directors(self, message: str) -> None:
        for s in self.legacy_sessions():
            if s.role == "director":
                await s.send_text(message)

    async def send_user_list(self) -> None:
        await self.broadcast(format_message("USERS", user_list=",".join(s.name for s in self.actors())))

    async def send_pending_list(self) -> None:
        pending = [{"machine_id": mid, "name": info.name} for mid, info in self.relay.pending.items() if info.role != "camera"]
        await self.send_to_directors(format_message("PENDING", actors_json=json.dumps(pending)))

    async def send_actor_status(self) -> None:
        actors = [{"name": s.name, "latency_ms": s.latency_ms, "last_seen": s.last_ping_received} for s in self.actors()]
        await self.send_to_directors(format_message("STATUS", actors_json=json.dumps(actors)))

    async def ping_actors(self) -> None:
        now = time.time()
        for s in self.legacy_sessions():
            if s.role == "actor":
                s.last_ping_sent = now
                await s.send_text("PING")

    async def send_welcome(self, session: Session) -> None:
        """APPROVED, then VERSION and UPDATE as the v0.3 relay sent them to a newly approved actor."""
        await session.send_text(format_message("APPROVED"))
        await self._send_version_and_update(session, "actor")

    async def _send_version_and_update(self, session: Session, role: str) -> None:
        if session.version:
            v_status, v_msg = compare_versions(session.version, LEGACY_VERSION)
            await session.send_text(format_message("VERSION", status=v_status, server_version=LEGACY_VERSION, message=v_msg))
            if v_status != "ok":
                self.log(f"Version mismatch: {role} '{session.name}' v{session.version} vs server v{LEGACY_VERSION} ({v_status})")
        update = self.relay.update_for(role, session.platform, session.version)
        if update:
            await session.send_text(format_message("UPDATE", **update))
            self.log(f"Update available for {role} '{session.name}': v{update['latest_version']}")

    async def send_denied(self, session: Session, reason: str) -> None:
        await session.send_text(format_message("DENIED", reason=reason))
        await session.close()

    async def send_replaced(self, session: Session) -> None:
        await session.send_text(format_message("MSG", sender="SERVER", text="Reconnected from another location"))
        await session.close()

    async def notify_forgotten(self, machine_id: str) -> None:
        for s in self.relay.registry:
            if s.legacy and s.machine_id == machine_id and s.role == "actor":
                await s.send_text(format_message("MSG", sender="SERVER", text="You have been forgotten. Reconnect to request approval."))
                break

    async def after_approve(self, entry: "PendingEntry") -> None:
        if entry.role != "camera":
            await self.broadcast(format_message("MSG", sender="SERVER", text=f"{entry.name} joined"))
        await self.send_user_list()
        await self.send_pending_list()

    # ---- v2 sessions coming and going, as v0.3 clients see them -----------------------------------

    async def v2_joined(self, session: Session) -> None:
        if session.role == "actor":
            await self.broadcast(format_message("MSG", sender="SERVER", text=f"{session.name} joined"))
            await self.send_user_list()
        elif session.role == "director":
            others = [d for d in self.directors() if d is not session]
            for d in others:
                if d.legacy:
                    await d.send_text(format_message("MSG", sender="SERVER", text=f"⚠ Warning: {session.name} has connected as another director"))

    async def v2_pending(self) -> None:
        await self.send_pending_list()

    async def v2_left(self, session: Session) -> None:
        if session.role == "actor":
            await self.send_user_list()
            await self.broadcast(format_message("MSG", sender="SERVER", text=f"{session.name} left"))

    async def renamed(self) -> None:
        await self.send_user_list()

    # ---- v2 → v0.3 delivery, with scheduling emulation -------------------------------------------

    async def deliver(self, env: Envelope, sender: Session, recipient: Session) -> bool:
        """Send a v2 message to a v0.3 client. Returns False if it's an action the client can't
        carry (the sender gets `unsupported`). Messages with nothing to show are skipped."""
        if env.type.startswith("file."):
            return await self.files.deliver(env, sender, recipient)
        try:
            text = to_legacy(env, sender, recipient)
        except (Unsupported, KeyError, TypeError, ValueError):
            return False
        if text is None:
            return True
        at = env.data.get("at")
        if env.type in STOP_TYPES and at is None:
            self.cancel_held(recipient, START_TYPES)
        if isinstance(at, int) and not isinstance(at, bool) and env.type in START_TYPES + STOP_TYPES + ("osc.param",):
            self._hold(recipient, env.type, at, text)
        else:
            await recipient.send_text(text)
        return True

    def send_at_ms(self, recipient: Session, at: int) -> int:
        """When to send a cue scheduled for `at` (server ms) so it arrives on time:
        fire_at − RTT/2, with fire_at = at + the actor's delay_ms (spec §8.2.3, §11.3)."""
        rtt = recipient.latency_ms if recipient.latency_ms > 0 else 0
        return at + self.relay.approvals.delay_ms(recipient.machine_id) - rtt // 2

    def _hold(self, recipient: Session, msg_type: str, at: int, text: str) -> None:
        send_at = self.send_at_ms(recipient, at)
        task = asyncio.get_running_loop().create_task(self._send_held(recipient, msg_type, send_at, text))
        recipient.held.append((task, msg_type))
        task.add_done_callback(lambda t: self._forget_held(recipient, t))

    async def _send_held(self, recipient: Session, msg_type: str, send_at: int, text: str) -> None:
        await self.relay.clock.sleep_until(send_at)
        if msg_type in STOP_TYPES:
            self.cancel_held(recipient, START_TYPES, keep=asyncio.current_task())
        late = self.relay.clock.now_ms() - send_at
        if late > 20:
            self.log(f"Held {msg_type} for '{recipient.name}' sent {late} ms late")
        await recipient.send_text(text)

    @staticmethod
    def _forget_held(recipient: Session, task: asyncio.Task) -> None:
        recipient.held = [(t, kind) for t, kind in recipient.held if t is not task]

    @staticmethod
    def cancel_held(session: Session, types: tuple[str, ...] | None = None, keep: asyncio.Task | None = None) -> None:
        for task, kind in list(session.held):
            if task is not keep and (types is None or kind in types):
                task.cancel()
