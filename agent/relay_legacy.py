"""Compatibility mode: the v0.3 pipe protocol on /ws, for relays without /v2/ws (spec §5.6).

agent/relay.py uses this when a relay answers /v2/ws with 403 or 404. The v0.3 protocol only
tells us actor names (USERS), latency (STATUS, directors only) and pending approvals (PENDING),
so the roster is thinner than on a v2 relay: other directors are inferred from chat, and camera
operators are invisible to everyone else.
"""

from __future__ import annotations

import asyncio
import os
import re
import ssl
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from shared import format_message, get_machine_id, get_platform_id, parse_message

from . import APP_VERSION

if TYPE_CHECKING:
    from .core import Agent

CUE_FLASH_S = 3.0
# The relay parses versions as integers, so send "0.4.0" rather than "0.4.0-dev".
WIRE_VERSION = APP_VERSION.split("-")[0]

WARN_EXISTING = re.compile(r"Warning: (.+) is already connected")
WARN_NEW = re.compile(r"Warning: (.+) has connected as another director")


def ws_url(server_url: str) -> str:
    """Normalise what people type (host:port, http(s)://, ws(s)://) into the relay's /ws URL."""
    url = server_url.strip()
    if not url:
        raise ValueError("No relay server set")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif not url.startswith(("ws://", "wss://")):
        url = "ws://" + url
    url = url.split("?", 1)[0].rstrip("/")
    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    path = "/" + path if path else ""
    if not path.endswith("/ws"):
        path += "/ws"
    return f"{scheme}://{host}{path}"


def host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0]


def ssl_context() -> ssl.SSLContext:
    """Same trust settings as the v0.3 clients: the relay often sits behind Caddy with a
    self-signed certificate, so verification is off (certifi only avoids Windows CA lookups)."""
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def clean(text: str) -> str:
    """The pipe protocol can't carry '|' inside fields."""
    return text.replace("|", "/").strip()


def version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.split("-")[0].split("."))
    except ValueError:
        return (0,)


def connect_kwargs(url: str) -> dict:
    kwargs = {"open_timeout": 10, "ping_interval": 30, "ping_timeout": 10, "max_size": 2**24}
    if url.startswith("wss://"):
        kwargs["ssl"] = ssl_context()
    return kwargs


async def perform_cue(relay, command: str, sender: str, sender_peer: str) -> tuple[bool, str | None]:
    """Run a cue (`*go`, `*stop`, `*play:N`) on this actor's machine and show it in the UI.
    Shared by both protocols; each one acknowledges the cue its own way."""
    agent = relay.agent
    hub = agent.hub
    hub.traffic(sender_peer, ["self"], "stop" if "stop" in command else "cue")
    ok, error = await agent.actor.run_cue(command)
    agent.last_cue = {"command": command, "at": int(time.time() * 1000), "ok": ok}
    if ok:
        relay.self_playing_until = 0.0 if "stop" in command else time.monotonic() + CUE_FLASH_S
        state = agent.actor.soundpad_state()["state"]
        note = {"simulated": " (simulated)", "disabled": " (Soundpad is off)", "fallback": " (via Soundpad.exe -rc)"}.get(state, "")
        hub.log("success", f"{command} from {sender}{note}")
    else:
        hub.log("error", f"{command} failed: {error}")
    agent.changed()
    asyncio.get_running_loop().call_later(CUE_FLASH_S + 0.1, agent.changed)
    return ok, error


@dataclass
class RemoteActor:
    name: str
    latency_ms: int | None = None
    timed_out: bool = False


def machine_id() -> str:
    # VRCAS_MACHINE_ID lets several agents share one PC (testing); normally it's per machine.
    return os.environ.get("VRCAS_MACHINE_ID") or get_machine_id()


class LegacyRelay:
    """One protocol of agent/relay.py's Relay, which owns the reconnect loop and the countdown."""

    legacy = True

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.status = "disconnected"
        self.detail = "Not connected"
        self.host = ""
        self.server_version: str | None = None
        self.actors: dict[str, RemoteActor] = {}
        self.directors: set[str] = set()
        self.pending: list[dict] = []
        self.targets: set[str] = set()
        self.self_playing_until = 0.0
        self._ws = None
        self._machine_id = machine_id()

    # ---- connection -------------------------------------------------------

    def _reset(self, detail: str, status: str = "disconnected") -> None:
        self.status = status
        self.detail = detail
        self.server_version = None
        self.actors.clear()
        self.directors.clear()
        self.pending.clear()
        self._ws = None
        self.agent.changed()

    def _set(self, status: str, detail: str) -> None:
        self.status = status
        self.detail = detail
        self.agent.changed()

    async def _session(self, url: str) -> str | None:
        """One connection. Returns a message when we must not reconnect (e.g. bad secret)."""
        cfg = self.agent.config
        async with connect(url, **connect_kwargs(url)) as ws:
            self._ws = ws
            self.agent.hub.log("info", f"Connected to {self.host}, registering as {cfg.role}…")
            await ws.send(
                format_message(
                    "REGISTER",
                    name=clean(cfg.name) or "Unnamed",
                    machine_id=self._machine_id,
                    role=cfg.role or "actor",
                    secret=clean(cfg.secret) if cfg.role == "director" else "",
                    version=WIRE_VERSION,
                    platform=get_platform_id(),
                )
            )
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    fatal = await self._on_message(raw)
                    if fatal:
                        return fatal
            except ConnectionClosed:
                pass
        return None

    async def send(self, text: str) -> None:
        if self._ws is None:
            raise RuntimeError("Not connected to the relay")
        await self._ws.send(text)

    # ---- incoming ---------------------------------------------------------

    async def _on_message(self, data: str) -> str | None:
        hub = self.agent.hub
        role = self.agent.config.role
        if data == "PING":
            await self.send("PONG")
            return None
        msg_type, msg = parse_message(data)

        if msg_type == "APPROVED":
            first = self.status != "connected"
            self._set("connected", f"Connected as {role}")
            if first:
                hub.log("success", f"Connected to {self.host} as {role}")
                if role != "director":
                    hub.toast("success", "Approved — you're on the network")
        elif msg_type == "DENIED":
            reason = msg.get("reason", "")
            if "Pending" in reason:
                self._set("pending", "Waiting for the director to approve you")
                hub.log("warning", "Waiting for director approval…")
            elif "Not approved" in reason:
                pass
            else:
                hub.log("error", f"Relay refused the connection: {reason}")
                return "Wrong director secret" if "secret" in reason.lower() else reason or "Connection refused"
        elif msg_type == "VERSION":
            self.server_version = msg.get("server_version") or None
            if msg.get("status") == "unsupported":
                hub.log("error", msg.get("message", "Version not supported"))
            elif msg.get("status") == "warning":
                hub.log("info", f"Relay v{self.server_version} speaks the v0.3 protocol; using compatibility mode.")
            self.agent.changed()
        elif msg_type == "UPDATE":
            latest = msg.get("latest_version", "")
            if version_tuple(latest) > version_tuple(APP_VERSION):
                hub.log("info", f"vrcActorSync v{latest} is available.")
        elif msg_type == "MSG":
            return self._on_chat(msg.get("sender", ""), msg.get("text", ""))
        elif msg_type == "PRIV":
            await self._on_private(msg.get("sender", ""), msg.get("text", ""))
        elif msg_type == "CMD":
            if role == "actor":
                await self._run_cue(msg.get("command", ""), "the director")
        elif msg_type == "USERS":
            self._on_users([u for u in msg.get("users", []) if u])
        elif msg_type == "STATUS":
            self._on_status(msg.get("actors", []))
        elif msg_type == "PENDING":
            self.pending = [
                {"id": f"pending:{a.get('machine_id', '')}", "name": a.get("name", "?")}
                for a in msg.get("actors", [])
                if isinstance(a, dict)
            ]
            self.agent.changed()
        elif msg_type == "OSC_CUE":
            if role == "actor":
                ok, text = self.agent.actor.send_osc(msg.get("parameter", ""), msg.get("value", ""))
                hub.log("success" if ok else "warning", f"[OSC] {text}")
                hub.traffic("server", ["self"], "cue")
        elif msg_type == "FILEREQ":
            filename = msg.get("filename", "")
            await self.send(format_message("FILEDENY", filename=filename, reason="File transfer isn't in the v0.4 preview yet"))
            hub.log("warning", f"Declined {filename}: file transfer isn't in the v0.4 preview yet. Use the v0.3 actor client for files.")
        return None

    def _on_chat(self, sender: str, text: str) -> str | None:
        hub = self.agent.hub
        if sender == "SERVER":
            if "forgotten" in text.lower():
                hub.toast("warning", "The director removed you. Connect again to ask for approval.")
                hub.log("warning", text)
                return "Removed by the director — connect again to request approval"
            for pattern in (WARN_EXISTING, WARN_NEW):
                match = pattern.search(text)
                if match:
                    self.directors.update(n.strip() for n in match.group(1).split(","))
                    self.agent.changed()
            hub.log("info", text.replace("⚠ ", ""))
            return None
        if sender and sender not in self.actors and sender != self.agent.config.name:
            # USERS only lists actors, so anyone else who talks is most likely a director.
            self.directors.add(sender)
            self.agent.changed()
        hub.log("chat", text, sender)
        hub.traffic(self._peer_id(sender), ["self"] if sender != self.agent.config.name else [], "chat")
        return None

    async def _on_private(self, sender: str, text: str) -> None:
        if self.agent.config.role == "actor" and text.startswith("*"):
            if sender and sender not in self.actors:
                self.directors.add(sender)
            await self._run_cue(text, sender or "the director")
            return
        self.agent.hub.log("chat", f"(private) {text}", sender)

    async def _run_cue(self, command: str, sender: str) -> None:
        ok, _ = await perform_cue(self, command, sender, self._peer_id(sender))
        if ok:
            await self.send(format_message("ACK", actor=clean(self.agent.config.name), command=command, status="OK"))

    def _on_users(self, names: list[str]) -> None:
        own = self.agent.config.name
        current = set(names) - {own}
        for gone in set(self.actors) - current:
            self.actors.pop(gone, None)
            self.targets.discard(gone)
        for name in current - set(self.actors):
            self.actors[name] = RemoteActor(name)
            # Same default as the v0.3 director: new actors receive cues until unticked.
            self.targets.add(name)
        self.directors -= current
        self.agent.changed()

    def _on_status(self, entries: list) -> None:
        own = self.agent.config.name
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("name") in (None, own):
                continue
            name = entry["name"]
            actor = self.actors.get(name)
            if actor is None:
                actor = self.actors[name] = RemoteActor(name)
                self.targets.add(name)
            latency = entry.get("latency_ms")
            actor.timed_out = latency == -1
            actor.latency_ms = latency if isinstance(latency, int) and latency > 0 else None
        self.agent.changed()

    # ---- director actions -------------------------------------------------

    async def send_cue(self, kind: str) -> None:
        """Go or Stop to the targeted actors: one `PRIV *go` / `*stop` each, like the v0.3 director."""
        await self._send_cue("*go" if kind == "go" else "*stop")

    async def _send_cue(self, command: str) -> None:
        names = [n for n in sorted(self.targets) if n in self.actors and not self.actors[n].timed_out]
        if not names:
            self.agent.hub.log("warning", f"{command} not sent — no actors targeted")
            return
        sender = clean(self.agent.config.name) or "Director"
        for name in names:
            await self.send(format_message("PRIV", sender=sender, target=name, text=command))
        symbol = "▶" if command == "*go" else "■"
        self.agent.hub.log("success" if command == "*go" else "info", f"{symbol} {command[1:].upper()} → {', '.join(names)}")
        self.agent.hub.traffic("self", [f"actor:{n}" for n in names], "cue" if command == "*go" else "stop")

    def set_targets(self, ids: list[str]) -> None:
        self.targets = {i.split(":", 1)[1] for i in ids if i.startswith("actor:") and i.split(":", 1)[1] in self.actors}
        self.agent.changed()

    def clear_targets(self) -> None:
        self.targets.clear()

    def target_ids(self) -> list[str]:
        return sorted(f"actor:{n}" for n in self.targets if n in self.actors)

    async def approve(self, pending_id: str) -> None:
        machine_id = pending_id.removeprefix("pending:")
        name = next((p["name"] for p in self.pending if p["id"] == pending_id), machine_id[:8])
        await self.send(f"APPROVE|{machine_id}")
        self.agent.hub.log("success", f"Approved {name}")

    async def deny(self, pending_id: str) -> None:
        machine_id = pending_id.removeprefix("pending:")
        await self.send(f"DENY|{machine_id}")
        self.agent.hub.log("info", "Denied a join request")

    async def forget(self, actor_id: str) -> None:
        name = actor_id.removeprefix("actor:")
        await self.send(f"FORGET_NAME|{clean(name)}")
        self.agent.hub.log("info", f"Forgot {name} — they need approval again")

    async def chat(self, text: str) -> None:
        await self.send(format_message("MSG", sender=clean(self.agent.config.name) or "Unnamed", text=text))
        self.agent.hub.traffic("self", ["server"], "chat")

    # ---- roster for the UI --------------------------------------------------

    def _peer_id(self, name: str) -> str:
        if name in self.actors:
            return f"actor:{name}"
        if name in self.directors:
            return f"director:{name}"
        return "server"

    def peers(self) -> list[dict]:
        out = []
        for name in sorted(self.directors):
            out.append(_peer(f"director:{name}", name, "director"))
        for actor in sorted(self.actors.values(), key=lambda a: a.name.lower()):
            out.append(
                _peer(
                    f"actor:{actor.name}",
                    actor.name,
                    "actor",
                    status="timeout" if actor.timed_out else "online",
                    latency=actor.latency_ms,
                )
            )
        return out


def _peer(pid: str, name: str, role: str, status: str = "online", latency: int | None = None) -> dict:
    return {"id": pid, "name": name, "role": role, "status": status, "latencyMs": latency, "activity": "idle", "self": False}
