"""Connection to a v2 relay over JSON envelopes on /v2/ws (spec §5).

Same surface as relay_legacy.LegacyRelay; agent/relay.py picks one per connection. On a v2 relay
the roster is complete (directors, actors, cameras, each with a session id), approvals go by
machine id, and cues carry the targets' session ids in one message.

Timing (§8.2, Phase 2 M3): every agent syncs its clock with the relay (timesync.py). Directors
send GO for server time now + lead and Play in 3s for now + 3 s (cues.py plans who gets what);
actors run an action with `at` at at + their delay − their start latency (scheduler.py), and a
Stop without `at` cancels whatever is still waiting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from shared import get_platform_id

from . import APP_VERSION
from .cues import armable, describe, plan_go
from .relay_legacy import ActionQueue, _peer, connect_kwargs, machine_id, perform_cue, version_tuple
from .scheduler import LATE_MS, MAX_AHEAD_MS, FirePlan, Scheduler, Timing, server_time
from .timesync import ClockSync, run_pings
from vrcas_protocol import make, now_ms

if TYPE_CHECKING:
    from .core import Agent

# What an actor's agent can do (the director UI shows controls per capability). Fixed per build;
# whether Soundpad is up right now comes in soundpad.state (Phase 2 decision D7). `schedule`:
# actions with `at` start at that server time (an older build would run them at once).
ACTOR_CAPABILITIES = ["soundpad", "soundpad.lines", "soundpad.position", "soundpad.list", "soundpad.add",
                      "soundpad.calibrate", "osc", "files", "schedule"]
CUE_TYPES = {"cue.go", "cue.stop", "cue.play"}
SOUNDPAD_ACTIONS = {"soundpad.play", "soundpad.stop", "soundpad.pause", "soundpad.seek", "soundpad.jump",
                    "soundpad.volume", "soundpad.mute", "soundpad.list.request", "soundpad.calibrate"}
SOUNDPAD_REPORTS = {"soundpad.state", "soundpad.list", "soundpad.ack"}
# Actions that may carry `at` (§5.3); starts get the start-latency term, stops cancel what waits
SCHEDULABLE = {"cue.go", "cue.stop", "cue.play", "soundpad.play", "soundpad.stop", "soundpad.pause", "osc.param"}
START_TYPES = {"cue.go", "cue.play", "soundpad.play"}
STOP_TYPES = {"cue.stop", "soundpad.stop"}
# A start this far ahead shows a countdown on the actor (Play in 3s; not GO's 300 ms)
COUNTDOWN_FROM_MS = 1000


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


def scheduled_at(msg_type: str, data: dict) -> int | None:
    """The `at` of an action that may be scheduled, if it has a usable one."""
    at = data.get("at")
    if msg_type in SCHEDULABLE and isinstance(at, int) and not isinstance(at, bool):
        return at
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
    delay_ms: int = 0


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
        # Director: approved actors and cameras that aren't connected ({id: "offline:<machine id>", name, role, approvedAt})
        self.offline: list[dict] = []
        self.targets: set[str] = set()
        self.self_playing_until = 0.0
        # This connection's clock and the actions waiting for their time (§8.2)
        self.clock = ClockSync()
        self.scheduler = Scheduler(self.clock)
        # Actor: our own delay (welcome, then our roster entry). Director: the last late start per actor
        self.delay_ms = 0
        self.late: dict[str, int] = {}
        # Director: the actors of the last scheduled GO, so a Stop reaches them even if unticked since
        self._go_ids: set[str] = set()
        self._seen_actors: set[str] = set()
        self._ws = None
        self._machine_id = machine_id()
        self._actions = ActionQueue()
        self._pings: asyncio.Task | None = None
        # For agent/relay.py's "Lost connection" line (time.monotonic())
        self.opened_at: float | None = None
        self.last_message_at = 0.0
        # What an actor announces in hello (tests pretend to be older builds by changing it)
        self.capabilities = list(ACTOR_CAPABILITIES)

    # ---- connection -------------------------------------------------------

    def _reset(self, detail: str, status: str = "disconnected") -> None:
        self._actions.clear()
        if self._pings is not None:
            self._pings.cancel()
            self._pings = None
        if self.scheduler.cancel():
            self.agent.relay.clear_countdown()
        self.clock.reset()
        self._go_ids.clear()
        self.late.clear()
        if self.status == "connected":
            self.agent.files.reset(detail)
        self.agent.soundpad.stop()
        self.status = status
        self.detail = detail
        self.server_version = None
        self.session_id = None
        self.sessions.clear()
        self.pending.clear()
        self.offline.clear()
        self._ws = None
        self.agent.changed()

    def _set(self, status: str, detail: str) -> None:
        self.status = status
        self.detail = detail
        self.agent.changed()

    async def _session(self, url: str) -> str | None:
        """One connection. Returns a message when we must not reconnect. Raises V2Unavailable
        when the relay doesn't speak v2, and ConnectionClosed (with the close codes) when the
        connection ends."""
        self.opened_at = None
        try:
            async with connect(url, **connect_kwargs(url)) as ws:
                self.opened_at = self.last_message_at = time.monotonic()
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
            "capabilities": self.capabilities if cfg.role == "actor" else [],
        }
        if cfg.role == "director":
            hello["secret"] = cfg.secret
        await self._send("hello", hello)
        while True:
            raw = await ws.recv()
            self.last_message_at = time.monotonic()
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

    async def _send(self, msg_type: str, data: dict, to: Any = "server", reply_to: str | None = None) -> str:
        """Returns the message id (a relay error names it in reply_to)."""
        if self._ws is None:
            raise RuntimeError("Not connected to the relay")
        now = self.clock.server_now()
        env = make(msg_type, data, to=to, reply_to=reply_to, ts=None if now is None else round(now))
        await self._ws.send(json.dumps(env.wire(), ensure_ascii=False))
        return env.id

    async def send(self, msg_type: str, data: dict, to: Any) -> str:
        return await self._send(msg_type, data, to)

    async def send_frame(self, frame: bytes) -> None:
        """A binary frame (a file chunk, spec §5.7)."""
        if self._ws is None:
            raise RuntimeError("Not connected to the relay")
        await self._ws.send(frame)

    async def _ping(self) -> str:
        return await self._send("time.ping", {"t0": now_ms()})

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
            if isinstance(data.get("server_time"), int):
                self.clock.seed(data["server_time"])
            if isinstance(data.get("delay_ms"), int):
                self.delay_ms = data["delay_ms"]
            first = self.status != "connected"
            self._set("connected", f"Connected as {role}")
            if self._pings is None:
                self._pings = asyncio.get_running_loop().create_task(run_pings(self.clock, self._ping))
            self.agent.soundpad.start()
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
        elif msg_type == "time.pong":
            if env.get("from") == "server" and isinstance(data.get("t1"), int) and isinstance(data.get("t2"), int):
                was = self.clock.synced
                self.clock.received(env.get("reply_to"), data["t1"], data["t2"])
                if self.clock.synced and not was:
                    offset = self.clock.wall_offset_ms() or 0
                    where = ("in step with the relay's" if abs(offset) < 50 else
                             f"{abs(offset) / 1000:.3f} s {'behind' if offset > 0 else 'ahead of'} the relay's")
                    logging.getLogger("vrcas").info("Clock synced with the relay: round trip %.0f ms; this PC's clock is %s",
                                                    self.clock.rtt_ms or 0, where)
                    self.agent.changed()
        elif msg_type == "chat.msg":
            hub.log("chat", str(data.get("text", "")), sender.name if sender else "?")
            hub.traffic(env.get("from") or "server", ["self"], "chat")
        elif msg_type == "chat.priv":
            hub.log("chat", f"(private) {data.get('text', '')}", sender.name if sender else "?")
        elif msg_type in CUE_TYPES:
            if role == "actor":
                self._on_action(env, msg_type, data, lambda timing: self._run_cue(env, msg_type, data, sender_name, timing))
        elif msg_type in SOUNDPAD_ACTIONS:
            if role == "actor":
                self._on_action(env, msg_type, data, lambda timing: self.agent.soundpad.on_actor_message(env, sender_name, timing))
        elif msg_type in SOUNDPAD_REPORTS:
            if role == "director":
                self._note_late(env, data, sender_name)
                self.agent.soundpad.on_director_message(env, sender.name if sender else "An actor")
        elif msg_type == "osc.param":
            if role == "actor":
                self._on_action(env, msg_type, data, lambda timing: self._send_osc(env, data, timing))
        elif isinstance(msg_type, str) and msg_type.startswith("file."):
            await self.agent.files.on_message(env, sender.name if sender else "the director")
        elif msg_type == "cue.ack":
            self._note_late(env, data, sender_name)
            if not data.get("ok", True):
                hub.log("warning", f"{sender_name}: {data.get('command', 'cue')} failed: {data.get('error') or 'unknown error'}")
        elif msg_type == "error":
            # A refused file offer also ends that file (relays before Phase 2 M1b send only this). Other
            # errors about file messages are races at the end of a transfer, already shown in its result.
            if self.agent.files.sender.on_error(env.get("reply_to"), str(data.get("message") or data.get("code") or "")):
                pass
            elif str(data.get("type") or "").startswith("file."):
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
            delay = entry.get("delay_ms")
            sessions[entry["id"]] = RemoteSession(
                id=entry["id"],
                name=str(entry.get("name", "?")),
                role=str(entry.get("role", "actor")),
                legacy=bool(entry.get("legacy")),
                latency_ms=latency if isinstance(latency, int) and latency > 0 else None,
                timed_out=bool(entry.get("timed_out")),
                capabilities=[c for c in entry.get("capabilities", []) if isinstance(c, str)],
                delay_ms=delay if isinstance(delay, int) and not isinstance(delay, bool) else 0,
            )
        own = sessions.get(self.session_id or "")
        if own is not None and own.delay_ms != self.delay_ms:
            self.agent.hub.log("info", f"The director set your delay to {own.delay_ms:+d} ms" if own.delay_ms else "The director set your delay back to 0")
            self.delay_ms = own.delay_ms
        self.sessions = sessions
        self.agent.soundpad.forget_missing(set(sessions))
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
        self.offline = [
            {
                "id": f"offline:{m['machine_id']}",
                "name": str(m.get("name", "?")),
                "role": "camera" if m.get("role") == "camera" else "actor",
                "approvedAt": m["approved_at"] if isinstance(m.get("approved_at"), str) else None,
            }
            for m in data.get("offline", [])
            if isinstance(m, dict) and m.get("machine_id")
        ]
        self.agent.changed()

    # ---- actor: actions, now or at their time ---------------------------------------------------

    def _on_action(self, env: dict, msg_type: str, data: dict, job: Callable[[Timing | None], Awaitable[None]]) -> None:
        """A cue, soundpad.* or osc.param for this actor. With `at` it waits in the scheduler and
        joins the action queue when it's due, so a Stop that comes meanwhile can cancel it (a job
        that waited inside the queue would hold the Stop up). Runs on the receive loop, so
        scheduling and cancelling keep the order the messages came in."""
        at = scheduled_at(msg_type, data)
        if at is None:
            if msg_type in STOP_TYPES:
                self._cancel_waiting()
            self._actions.put(lambda: job(None))
            return
        plan = FirePlan(at, self.delay_ms, self.agent.actor.compensation_ms() if msg_type in START_TYPES else 0)
        ahead = self.clock.until(plan.fire_ms)
        if ahead is not None and ahead > MAX_AHEAD_MS:
            self.agent.hub.log("warning", f"Ignored a cue scheduled {ahead / 1000:.0f} s ahead (more than {MAX_AHEAD_MS // 1000} s)")
            self._actions.put(lambda: self._refuse(env, msg_type, f"Scheduled too far ahead ({ahead / 1000:.0f} s)"))
            return

        def due(_fire) -> None:
            if msg_type in STOP_TYPES:
                self._cancel_waiting()
            elif msg_type in START_TYPES and not self.scheduler.pending("cue"):
                self.agent.relay.clear_countdown()

            async def run() -> None:
                now = self.clock.server_now()
                await job(Timing(plan, plan.fire_ms if now is None else now))

            self._actions.put(run)

        self.scheduler.at(plan.fire_ms, due, group="cue")
        if msg_type in START_TYPES and ahead is not None and ahead >= COUNTDOWN_FROM_MS:
            sent = env.get("ts")
            total = at - sent if isinstance(sent, int) and 0 < at - sent <= MAX_AHEAD_MS else ahead
            ends = self.clock.to_wall(plan.fire_ms)
            if ends is not None:
                self.agent.relay.show_countdown(ends, round(total))

    def _cancel_waiting(self) -> None:
        """A Stop: nothing that's still waiting for its time runs (§8.2.2)."""
        gone = self.scheduler.cancel("cue")
        self.agent.relay.clear_countdown()
        if gone:
            self.agent.hub.log("info", f"■ Stop: cancelled {len(gone)} scheduled cue{'s' if len(gone) != 1 else ''}")

    async def _refuse(self, env: dict, msg_type: str, error: str) -> None:
        if not env.get("from"):
            return
        reply = {"to": {"ids": [env["from"]]}, "reply_to": env.get("id")}
        if msg_type.startswith("soundpad."):
            await self._send("soundpad.ack", {"status": "invalid", "error": error, "command": msg_type}, **reply)
        elif msg_type.startswith("cue."):
            await self._send("cue.ack", {"command": msg_type, "ok": False, "error": error}, **reply)

    async def _send_osc(self, env: dict, data: dict, timing: Timing | None = None) -> None:
        ok, text = self.agent.actor.send_osc(str(data.get("parameter", "")), data.get("value", ""))
        when = f" · {timing.text(start=False)}" if timing else ""
        self.agent.hub.log("success" if ok else "warning", f"[OSC] {text}{when}")
        self.agent.hub.traffic(env.get("from") or "server", ["self"], "cue")

    async def _run_cue(self, env: dict, msg_type: str, data: dict, sender: str, timing: Timing | None = None) -> None:
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
        if timing is not None:
            self.agent.hub.log("info", f"⏱ {command} {timing.text(start=msg_type in START_TYPES)}")
        if reply:
            ack = self._ack(ack_type, command, ok, error)
            if timing is not None:
                ack["late_ms"] = timing.late_ms
            await self._send(ack_type, ack, **reply)

    @staticmethod
    def _ack(ack_type: str, command: str, ok: bool, error: str | None) -> dict:
        ack: dict[str, Any] = {"status": "ok" if ok else "error"} if ack_type == "soundpad.ack" else {"command": command, "ok": ok}
        if error:
            ack["error"] = error
        return ack

    # ---- director actions -------------------------------------------------

    def _actors(self) -> list[RemoteSession]:
        return [s for s in self.sessions.values() if s.role == "actor" and s.id != self.session_id]

    def _targeted(self) -> list[RemoteSession]:
        return sorted((s for s in self._actors() if s.id in self.targets and not s.timed_out), key=lambda s: s.name.lower())

    async def send_go(self, lead_ms: int, countdown: bool = False) -> None:
        """GO (or Play in 3s with lead 3000) to the targeted actors, all for one server time (§8.2.2):
        armed actors play their sound, the others their selected one (cues.py)."""
        actors = self._targeted()
        if not actors:
            self.agent.hub.log("warning", f"{'Countdown' if countdown else '*go'} not sent — no actors targeted")
            return
        now = self.clock.server_now() if self.clock.synced else None
        at = round(now + lead_ms) if now is not None and lead_ms > 0 else None
        armed = self.agent.armed
        plan = plan_go(actors, armed, at, self.clock.rtt_ms)
        for send in plan.sends:
            if send.hold_until is None:
                await self._send(send.type, send.data, to={"ids": send.ids})
            else:
                self.scheduler.at(send.hold_until, lambda _f, s=send: asyncio.get_running_loop().create_task(self._send_held(s)), group="held")
        self._go_ids = {s.id for s in actors} if at is not None else set()
        if countdown and at is not None:
            ends = self.clock.to_wall(at)
            if ends is not None:
                self.agent.relay.show_countdown(ends, lead_ms)
            self.scheduler.at(at, lambda _f: self.agent.relay.clear_countdown(), group="countdown")
        parts = [s.name + (f" ({describe(armed[s.id])})" if s.id in armed else "") for s in actors]
        when = f" for {server_time(at)} server time (+{lead_ms} ms)" if at is not None else ""
        self.agent.hub.log("info" if countdown else "success", f"{'⏱ Play in 3s' if countdown else '▶ GO'} → {', '.join(parts)}{when}")
        for name in plan.fallbacks:
            self.agent.hub.log("warning", f"{name}'s app can't play the armed sound; it got GO (its selected sound)")
        self.agent.hub.traffic("self", [s.id for s in actors], "cue")

    async def _send_held(self, send) -> None:
        """An older build's part of a GO, sent without `at` now that it's due."""
        try:
            await self._send(send.type, send.data, to={"ids": send.ids})
        except RuntimeError:
            return
        logging.getLogger("vrcas").info("Sent %s to %s (held for an app without scheduling) at %s server time",
                                        send.type, ", ".join(send.names), server_time(self.clock.server_now() or 0))

    async def send_cue(self, kind: str) -> None:
        if kind == "go":
            await self.send_go(0)
            return
        # Stop: also reaches the actors of a GO that's still waiting, even if unticked since
        held = self.scheduler.cancel("held")
        counting = self.scheduler.cancel("countdown")
        if counting:
            self.agent.relay.clear_countdown()
        ids = {s.id for s in self._targeted()} | (self._go_ids & {s.id for s in self._actors()})
        self._go_ids = set()
        if not ids:
            self.agent.hub.log("warning", "*stop not sent — no actors targeted")
            return
        actors = sorted((self.sessions[i] for i in ids), key=lambda s: s.name.lower())
        await self._send("cue.stop", {}, to={"ids": [s.id for s in actors]})
        note = " (countdown cancelled)" if counting else ""
        if held:
            note += f" ({len(held)} held cue{'s' if len(held) != 1 else ''} cancelled)"
        self.agent.hub.log("info", f"■ STOP → {', '.join(s.name for s in actors)}{note}")
        self.agent.hub.traffic("self", [s.id for s in actors], "stop")

    def _note_late(self, env: dict, data: dict, sender_name: str) -> None:
        """A scheduled start's ack says how late it ran; past LATE_MS the director is told."""
        late = data.get("late_ms")
        sender = env.get("from")
        if not isinstance(late, int) or isinstance(late, bool) or not sender:
            return
        self.late[sender] = late
        if late > LATE_MS:
            self.agent.hub.log("warning", f"{sender_name} started {late} ms late")
        self.agent.changed()

    def can_arm(self, actor_id: str, sound: dict, lines: str | None) -> str | None:
        """Why this sound can't be armed on that actor, or None."""
        s = self.sessions.get(actor_id)
        if s is None or s.role != "actor":
            return "That actor isn't connected"
        return armable(s, sound, lines)

    async def set_delay(self, actor_id: str, delay_ms: int) -> None:
        s = self.sessions.get(actor_id)
        if s is None or s.role != "actor":
            raise RuntimeError("That actor isn't connected")
        await self._send("actor.settings", {"id": actor_id, "delay_ms": delay_ms})
        self.agent.hub.log("info", f"{s.name}'s delay: {delay_ms:+d} ms" if delay_ms else f"{s.name}'s delay: 0 (starts with everyone)")

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
        """A connected peer by session id, or an approved machine that has left ("offline:<machine id>")."""
        if peer_id.startswith("offline:"):
            name = next((m["name"] for m in self.offline if m["id"] == peer_id), "a machine")
            await self._send("approval.forget", {"machine_id": peer_id.removeprefix("offline:")})
        else:
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
            sp = self.agent.soundpad.peer_view(s.id) if s.role == "actor" else None
            playing = bool(sp and sp["available"] and sp["status"] in ("PLAYING", "SEEKING"))
            out.append(_peer(s.id, s.name, role, status="timeout" if s.timed_out else "online", latency=s.latency_ms,
                             caps=s.capabilities, soundpad=sp, activity="playing" if playing else "idle",
                             delay=s.delay_ms if s.role == "actor" else None, late=self.late.get(s.id)))
        return out
