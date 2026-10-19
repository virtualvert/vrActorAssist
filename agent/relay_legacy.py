"""Connection to a v0.3.x relay (server_ws.py) over its pipe-delimited protocol on /ws.

This lets the new app work with today's server. The legacy protocol only tells us actor
names (USERS), latency (STATUS, directors only) and pending approvals (PENDING), so the
roster is thinner than with the v2 relay: other directors are inferred from chat, and
camera operators are invisible to everyone else until the v2 relay lands.
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
from websockets.exceptions import ConnectionClosed, InvalidURI, WebSocketException

from shared import format_message, get_machine_id, get_platform_id, parse_message

from . import APP_VERSION

if TYPE_CHECKING:
    from .core import Agent

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0
COUNTDOWN_S = 3.0
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


@dataclass
class RemoteActor:
    name: str
    latency_ms: int | None = None
    timed_out: bool = False


class LegacyRelay:
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
        self.countdown_ends: float | None = None
        self.self_playing_until = 0.0
        self._ws = None
        self._task: asyncio.Task | None = None
        self._countdown_task: asyncio.Task | None = None
        # VRCAS_MACHINE_ID lets several agents share one PC (testing); normally it's per machine.
        self._machine_id = os.environ.get("VRCAS_MACHINE_ID") or get_machine_id()

    # ---- lifecycle --------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
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
        self._reset(detail)

    async def restart(self) -> None:
        await self.stop("Reconnecting…")
        self.start()

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

    async def _run(self) -> None:
        backoff = BACKOFF_START_S
        cfg = self.agent.config
        try:
            url = ws_url(cfg.server_url)
        except ValueError as exc:
            self._set("error", str(exc))
            return
        self.host = host_of(url)
        while True:
            self._set("connecting", f"Connecting to {self.host}…")
            fatal = None
            try:
                fatal = await self._session(url)
                backoff = BACKOFF_START_S
            except asyncio.CancelledError:
                raise
            except (OSError, WebSocketException, InvalidURI, asyncio.TimeoutError) as exc:
                self.agent.hub.log("warning", f"Relay connection failed: {exc}")
            if fatal:
                self._reset(fatal, status="error")
                return
            self._reset(f"Lost connection to {self.host}. Retrying in {int(backoff)} s…", status="connecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    async def _session(self, url: str) -> str | None:
        """One connection. Returns a message when we must not reconnect (e.g. bad secret)."""
        cfg = self.agent.config
        kwargs = {"open_timeout": 10, "ping_interval": 30, "ping_timeout": 10, "max_size": 2**24}
        if url.startswith("wss://"):
            kwargs["ssl"] = ssl_context()
        async with connect(url, **kwargs) as ws:
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
        hub = self.agent.hub
        hub.traffic(self._peer_id(sender), ["self"], "stop" if "stop" in command else "cue")
        ok, error = await self.agent.actor.run_cue(command)
        self.agent.last_cue = {"command": command, "at": int(time.time() * 1000), "ok": ok}
        if ok:
            await self.send(format_message("ACK", actor=clean(self.agent.config.name), command=command, status="OK"))
            self.self_playing_until = 0.0 if "stop" in command else time.monotonic() + CUE_FLASH_S
            state = self.agent.actor.soundpad_state()["state"]
            note = {"simulated": " (simulated)", "disabled": " (Soundpad is off)", "fallback": " (via Soundpad.exe -rc)"}.get(state, "")
            hub.log("success", f"{command} from {sender}{note}")
        else:
            hub.log("error", f"{command} failed: {error}")
        self.agent.changed()
        asyncio.get_running_loop().call_later(CUE_FLASH_S + 0.1, self.agent.changed)

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
        await self._send_cue("*go" if command == "go" else "*stop")

    async def _countdown(self) -> None:
        try:
            await asyncio.sleep(COUNTDOWN_S)
            self._countdown_task = None
            self.countdown_ends = None
            await self._send_cue("*go")
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
