"""Connection to a v2 relay over JSON envelopes on /v2/ws (spec §5).

Same surface as relay_legacy.LegacyRelay; agent/relay.py picks one per connection. On a v2 relay
the roster is complete (directors, actors, cameras, each with a session id), approvals go by
machine id, and cues carry the targets' session ids in one message. Scheduling (`at`) isn't
used yet: Play in 3s is a local countdown, then cue.go (Phase 2 adds the agent-side scheduler).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from shared import get_platform_id

from . import APP_VERSION
from .relay_legacy import _peer, connect_kwargs, machine_id, perform_cue, version_tuple
from vrcas_protocol import make, now_ms

if TYPE_CHECKING:
    from .core import Agent

# What an actor's agent can do (the director UI shows controls per capability)
ACTOR_CAPABILITIES = ["soundpad", "osc", "files"]
CUE_TYPES = {"cue.go", "cue.stop", "cue.play", "soundpad.play", "soundpad.stop"}


class V2Unavailable(Exception):
    """The relay has no /v2/ws (a v0.3 relay answers 403): use the v0.3 protocol."""


def v2_url(legacy_ws_url: str) -> str:
    """relay_legacy.ws_url() gives .../ws; the v2 endpoint sits next to it at .../v2/ws."""
    return legacy_ws_url[: -len("/ws")] + "/v2/ws"


def cue_command(msg_type: str, data: dict) -> str | None:
    """The `*command` the actor runtime executes for a v2 cue, or None if it can't yet."""
    if msg_type == "cue.go":
        return "*go"
    if msg_type in ("cue.stop", "soundpad.stop"):
        return "*stop"
    if msg_type == "cue.play" and isinstance(data.get("index"), int):
        return f"*play:{data['index']}"
    if msg_type == "soundpad.play":
        sound = data.get("sound") or {}
        if sound.get("selected"):
            return "*go"
        if isinstance(sound.get("index"), int):
            return f"*play:{sound['index']}"
    return None


@dataclass
class RemoteSession:
    id: str
    name: str
    role: str
    legacy: bool = False
    latency_ms: int | None = None
    timed_out: bool = False
    capabilities: list[str] = field(default_factory=list)


class V2Relay:
    legacy = False

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.status = "disconnected"
        self.detail = "Not connected"
        self.host = ""
        self.server_version: str | None = None
        self.session_id: str | None = None
        self.sessions: dict[str, RemoteSession] = {}
        self.pending: list[dict] = []
        self.targets: set[str] = set()
        self.self_playing_until = 0.0
        self._seen_actors: set[str] = set()
        self._ws = None
        self._machine_id = machine_id()

    # ---- connection -------------------------------------------------------

    def _reset(self, detail: str, status: str = "disconnected") -> None:
        if self.status == "connected":
            self.agent.files.reset(detail)
        self.status = status
        self.detail = detail
        self.server_version = None
        self.session_id = None
        self.sessions.clear()
        self.pending.clear()
        self._ws = None
        self.agent.changed()

    def _set(self, status: str, detail: str) -> None:
        self.status = status
        self.detail = detail
        self.agent.changed()

    async def _session(self, url: str) -> str | None:
        """One connection. Returns a message when we must not reconnect. Raises V2Unavailable
        when the relay doesn't speak v2."""
        try:
            async with connect(url, **connect_kwargs(url)) as ws:
                return await self._converse(ws)
        except InvalidStatus as exc:  # only raised by the opening handshake
            if exc.response.status_code in (403, 404):
                raise V2Unavailable(str(exc)) from exc
            raise

    async def _converse(self, ws) -> str | None:
        cfg = self.agent.config
        self._ws = ws
        self.agent.hub.log("info", f"Connected to {self.host}, registering as {cfg.role}…")
        hello: dict[str, Any] = {
            "role": cfg.role or "actor",
            "name": cfg.name.strip() or "Unnamed",
            "machine_id": self._machine_id,
            "version": APP_VERSION,
            "platform": get_platform_id(),
            "capabilities": ACTOR_CAPABILITIES if cfg.role == "actor" else [],
        }
        if cfg.role == "director":
            hello["secret"] = cfg.secret
        await self._send("hello", hello)
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    await self.agent.files.on_chunk(raw)
                    continue
                try:
                    env = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(env, dict):
                    fatal = await self._on_message(env)
                    if fatal:
                        return fatal
        except ConnectionClosed:
            pass
        return None

    async def _send(self, msg_type: str, data: dict, to: Any = "server", reply_to: str | None = None) -> None:
        if self._ws is None:
            raise RuntimeError("Not connected to the relay")
        env = make(msg_type, data, to=to, reply_to=reply_to)
        await self._ws.send(json.dumps(env.wire(), ensure_ascii=False))

    async def send(self, msg_type: str, data: dict, to: Any) -> None:
        await self._send(msg_type, data, to)

    async def send_frame(self, frame: bytes) -> None:
        """A binary frame (a file chunk, spec §5.7)."""
        if self._ws is None:
            raise RuntimeError("Not connected to the relay")
        await self._ws.send(frame)

    # ---- incoming ---------------------------------------------------------

    async def _on_message(self, env: dict) -> str | None:
        hub = self.agent.hub
        role = self.agent.config.role
        msg_type = env.get("type")
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        sender = self.sessions.get(env.get("from") or "")
        sender_name = sender.name if sender else "the director"

        if msg_type == "welcome":
            self.session_id = data.get("session_id")
            self.server_version = data.get("server_version")
            first = self.status != "connected"
            self._set("connected", f"Connected as {role}")
            if first:
                hub.log("success", f"Connected to {self.host} as {role} (v2 relay {self.server_version})")
                if role != "director":
                    hub.toast("success", "Approved — you're on the network")
            status = data.get("version_status")
            if status == "unsupported":
                hub.log("error", data.get("version_message") or "This app version isn't supported by the relay")
            elif status == "warning" and data.get("version_message"):
                hub.log("info", data["version_message"])
        elif msg_type == "approval.pending":
            self._set("pending", "Waiting for the director to approve you")
            hub.log("warning", "Waiting for director approval…")
        elif msg_type == "denied":
            reason = data.get("reason", "")
            hub.log("error", f"Relay refused the connection: {reason}")
            if "secret" in reason.lower():
                return "Wrong director secret"
            if "another location" in reason.lower():
                return "Replaced by a newer connection from this computer"
            return reason or "Connection refused"
        elif msg_type == "approval.forgotten":
            hub.toast("warning", "The director removed you. Connect again to ask for approval.")
            hub.log("warning", "The director removed you from the session.")
            return "Removed by the director — connect again to request approval"
        elif msg_type == "update.available":
            latest = data.get("latest_version", "")
            if version_tuple(latest) > version_tuple(APP_VERSION):
                hub.log("info", f"vrcActorSync v{latest} is available.")
        elif msg_type == "presence.roster":
            self._on_roster(data)
        elif msg_type == "presence.latency":
            for entry in data.get("sessions", []):
                s = self.sessions.get(entry.get("id")) if isinstance(entry, dict) else None
                if s:
                    s.latency_ms = entry.get("latency_ms")
                    s.timed_out = bool(entry.get("timed_out"))
            self.agent.changed()
        elif msg_type == "time.ping":
            now = now_ms()
            await self._send("time.pong", {"t0": data.get("t0", 0), "t1": now, "t2": now}, reply_to=env.get("id"))
        elif msg_type == "chat.msg":
            hub.log("chat", str(data.get("text", "")), sender.name if sender else "?")
            hub.traffic(env.get("from") or "server", ["self"], "chat")
        elif msg_type == "chat.priv":
            hub.log("chat", f"(private) {data.get('text', '')}", sender.name if sender else "?")
        elif msg_type in CUE_TYPES:
            if role == "actor":
                await self._run_cue(env, msg_type, data, sender_name)
        elif msg_type == "osc.param":
            if role == "actor":
                ok, text = self.agent.actor.send_osc(str(data.get("parameter", "")), data.get("value", ""))
                hub.log("success" if ok else "warning", f"[OSC] {text}")
                hub.traffic(env.get("from") or "server", ["self"], "cue")
        elif isinstance(msg_type, str) and msg_type.startswith("file."):
            await self.agent.files.on_message(env, sender.name if sender else "the director")
        elif msg_type == "cue.ack":
            if not data.get("ok", True):
                hub.log("warning", f"{sender_name}: {data.get('command', 'cue')} failed: {data.get('error') or 'unknown error'}")
        elif msg_type == "error":
            # Errors about file messages are races at the end of a transfer, already shown in its result
            if str(data.get("type") or "").startswith("file."):
                logging.getLogger("vrcas").info("Relay about %s: %s", data.get("type"), data.get("message"))
            else:
                hub.log("warning", f"Relay: {data.get('message') or data.get('code')}")
        return None

    def _on_roster(self, data: dict) -> None:
        sessions: dict[str, RemoteSession] = {}
        for entry in data.get("sessions", []):
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            latency = entry.get("latency_ms")
            sessions[entry["id"]] = RemoteSession(
                id=entry["id"],
                name=str(entry.get("name", "?")),
                role=str(entry.get("role", "actor")),
                legacy=bool(entry.get("legacy")),
                latency_ms=latency if isinstance(latency, int) and latency > 0 else None,
                timed_out=bool(entry.get("timed_out")),
                capabilities=[c for c in entry.get("capabilities", []) if isinstance(c, str)],
            )
        self.sessions = sessions
        for s in sessions.values():
            if s.role == "actor" and s.id not in self._seen_actors:
                # Same default as the v0.3 director: new actors receive cues until unticked.
                self._seen_actors.add(s.id)
                self.targets.add(s.id)
        self.pending = [
            {"id": f"pending:{p.get('machine_id', '')}", "name": str(p.get("name", "?"))}
            for p in data.get("pending", [])
            if isinstance(p, dict)
        ]
        self.agent.changed()

    async def _run_cue(self, env: dict, msg_type: str, data: dict, sender: str) -> None:
        command = cue_command(msg_type, data)
        reply = {"to": {"ids": [env["from"]]}, "reply_to": env.get("id")} if env.get("from") else None
        ack_type = "soundpad.ack" if msg_type.startswith("soundpad.") else "cue.ack"
        if command is None:
            error = f"{msg_type} with {json.dumps(data)} isn't supported by this version yet"
            self.agent.hub.log("warning", error)
            if reply:
                await self._send(ack_type, self._ack(ack_type, msg_type, False, error), **reply)
            return
        ok, error = await perform_cue(self, command, sender, env.get("from") or "server")
        if reply:
            await self._send(ack_type, self._ack(ack_type, command, ok, error), **reply)

    @staticmethod
    def _ack(ack_type: str, command: str, ok: bool, error: str | None) -> dict:
        ack: dict[str, Any] = {"status": "ok" if ok else "error"} if ack_type == "soundpad.ack" else {"command": command, "ok": ok}
        if error:
            ack["error"] = error
        return ack

    # ---- director actions -------------------------------------------------

    def _actors(self) -> list[RemoteSession]:
        return [s for s in self.sessions.values() if s.role == "actor" and s.id != self.session_id]

    async def send_cue(self, kind: str) -> None:
        actors = sorted((s for s in self._actors() if s.id in self.targets and not s.timed_out), key=lambda s: s.name.lower())
        label = "*go" if kind == "go" else "*stop"
        if not actors:
            self.agent.hub.log("warning", f"{label} not sent — no actors targeted")
            return
        ids = [s.id for s in actors]
        await self._send("cue.go" if kind == "go" else "cue.stop", {}, to={"ids": ids})
        symbol = "▶" if kind == "go" else "■"
        self.agent.hub.log("success" if kind == "go" else "info", f"{symbol} {kind.upper()} → {', '.join(s.name for s in actors)}")
        self.agent.hub.traffic("self", ids, "cue" if kind == "go" else "stop")

    def set_targets(self, ids: list[str]) -> None:
        actors = {s.id for s in self._actors()}
        self.targets = {i for i in ids if i in actors}
        self.agent.changed()

    def clear_targets(self) -> None:
        self.targets.clear()

    def target_ids(self) -> list[str]:
        actors = {s.id for s in self._actors()}
        return sorted(i for i in self.targets if i in actors)

    async def approve(self, pending_id: str) -> None:
        mid = pending_id.removeprefix("pending:")
        name = next((p["name"] for p in self.pending if p["id"] == pending_id), mid[:8])
        await self._send("approval.approve", {"machine_id": mid})
        self.agent.hub.log("success", f"Approved {name}")

    async def deny(self, pending_id: str) -> None:
        await self._send("approval.deny", {"machine_id": pending_id.removeprefix("pending:")})
        self.agent.hub.log("info", "Denied a join request")

    async def forget(self, peer_id: str) -> None:
        name = self.sessions[peer_id].name if peer_id in self.sessions else peer_id
        await self._send("approval.forget", {"id": peer_id})
        self.agent.hub.log("info", f"Forgot {name} — they need approval again")

    async def chat(self, text: str) -> None:
        await self._send("chat.msg", {"text": text}, to="all")
        # The relay doesn't echo chat back to its sender
        self.agent.hub.log("chat", text, self.agent.config.name or "You")
        self.agent.hub.traffic("self", ["server"], "chat")

    # ---- roster for the UI --------------------------------------------------

    def peers(self) -> list[dict]:
        order = {"director": 0, "assistant": 0, "actor": 1, "camera": 2}
        out = []
        for s in sorted(self.sessions.values(), key=lambda s: (order.get(s.role, 3), s.name.lower())):
            if s.id == self.session_id:
                continue
            # The UI has no assistant role yet; assistants direct too
            role = "director" if s.role == "assistant" else s.role
            out.append(_peer(s.id, s.name, role, status="timeout" if s.timed_out else "online", latency=s.latency_ms,
                             caps=s.capabilities))
        return out
