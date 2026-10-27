"""The soundpad addon over the relay (spec §8.1.2, §8.1.6).

Actors: answer soundpad.* from directors (each action gets a soundpad.ack), send their sound list
on request (and again when it changes), and publish soundpad.state to the directors and assistants
on v2: at most twice a second while playing, on any other change, and every 10 s.

Directors: keep each actor's last state and sound list for the UI. Lists reach the page as a
separate "sounds" event, not in the state snapshot, since they can hold thousands of entries.

soundpad.calibrate (§8.2.3): the actor starts a speakers-only test play from its action queue (a
quick job), then measures the start, stops the play after 1.5 s and answers with the start
latency outside the queue, so a cue that arrives meanwhile isn't held up.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from vrcas_protocol import validate

from .actor_runtime import CALIBRATE_PLAY_S, PlayError
from .scheduler import Timing
from .sounds import pages

if TYPE_CHECKING:
    from .core import Agent

TICK_S = 0.25
MIN_GAP_S = 0.5
HEARTBEAT_S = 10.0
LINES_TEXT = {"both": "both lines", "speakers": "speakers only", "mic": "mic only"}


class SoundpadRemote:
    def __init__(self, agent: "Agent"):
        self.agent = agent
        # actor side
        self._task: asyncio.Task | None = None
        self._sent: dict | None = None
        self._sent_position = 0
        self._sent_at = 0.0
        self._directors: set[str] = set()
        self.subscribers: set[str] = set()
        # director side: session id → state (+ when it arrived), sound lists, calibrated start latency
        self.states: dict[str, tuple[dict, int]] = {}
        self.lists: dict[str, dict] = {}
        self.latencies: dict[str, int] = {}
        self._pages: dict[str, list[dict]] = {}
        self._calibrating: asyncio.Task | None = None

    @property
    def runtime(self):
        return self.agent.actor

    def _relay(self):
        impl = self.agent.relay.impl
        if impl.legacy or impl.status != "connected":
            return None
        return impl

    # ==== actor side ===============================================================================

    def start(self) -> None:
        """Connected over v2 as an actor: start publishing."""
        if self._task is None and self.agent.config.role == "actor":
            self.runtime.on_list_changed = self._list_changed
            self._sent, self._sent_at = None, 0.0
            self._task = asyncio.get_running_loop().create_task(self._publish_loop())

    def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
        self.subscribers.clear()
        self._directors.clear()
        self.states.clear()
        self.lists.clear()
        self.latencies.clear()
        self._pages.clear()

    def _director_ids(self) -> list[str]:
        relay = self._relay()
        if relay is None:
            return []
        return [s.id for s in relay.sessions.values()
                if s.role in ("director", "assistant") and not s.legacy and s.id != relay.session_id]

    async def _publish_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(TICK_S)
                await self.publish()
        except asyncio.CancelledError:
            pass

    async def publish(self, force: bool = False) -> None:
        relay = self._relay()
        targets = self._director_ids()
        if relay is None or not targets:
            return
        if set(targets) - self._directors:
            force = True  # a director joined: they get the state now, not at the next heartbeat
        self._directors = set(targets)
        state = self.runtime.state_for_directors()
        now = time.monotonic()
        steady = {k: v for k, v in state.items() if k != "position_ms"}
        moving = state.get("status") == "PLAYING" and state.get("position_ms", 0) != self._sent_position
        due = force or steady != self._sent or (moving and now - self._sent_at >= MIN_GAP_S) or now - self._sent_at >= HEARTBEAT_S
        if not due:
            return
        try:
            await relay.send("soundpad.state", state, {"ids": targets})
        except RuntimeError:
            return
        self._sent, self._sent_position, self._sent_at = steady, state.get("position_ms", 0), now

    def _list_changed(self) -> None:
        targets = [i for i in self._director_ids() if i in self.subscribers]
        if targets:
            asyncio.get_running_loop().create_task(self._send_list(targets))

    async def _send_list(self, targets: list[str], reply_to: str | None = None) -> None:
        relay = self._relay()
        if relay is None:
            return
        try:
            sounds, categories = await self.runtime.sound_list()
        except PlayError as exc:
            await relay._send("soundpad.ack", {"status": exc.code, "error": str(exc), "command": "soundpad.list.request"},
                              {"ids": targets}, reply_to=reply_to)
            return
        for page in pages(sounds, categories):
            await relay.send("soundpad.list", page, {"ids": targets})

    async def on_actor_message(self, env: dict, sender_name: str, timing: Timing | None = None) -> None:
        """A soundpad.* action from a director or assistant (the relay checked who may send it).
        `timing`: it was scheduled (`at`) and is running now."""
        relay = self._relay()
        msg_type = env.get("type")
        sender = env.get("from") or ""
        try:
            payload = validate(msg_type, env.get("data") if isinstance(env.get("data"), dict) else {})
        except ValueError as exc:
            await self._ack(env, "invalid", f"Bad {msg_type}: {exc}"[:400])
            return
        hub = self.agent.hub
        runtime = self.runtime
        if msg_type == "soundpad.list.request":
            self.subscribers.add(sender)
            await self._send_list([sender], reply_to=env.get("id"))
            return
        if msg_type == "soundpad.calibrate":
            sound = payload.sound.model_dump(exclude_none=True) if payload.sound else None
            status, error = await runtime.calibrate(sound)
            if status != "ok":
                hub.log("warning", f"Calibration from {sender_name} didn't start: {error}")
                await self._ack(env, status, error)
                return
            hub.log("info", f"Calibrating the start latency for {sender_name} (speakers only)…")
            self._calibrating = asyncio.get_running_loop().create_task(self._finish_calibration(env, sender_name))
            return
        hub.traffic(sender or "server", ["self"], "stop" if msg_type == "soundpad.stop" else "cue")
        if msg_type == "soundpad.play":
            sound = payload.sound.model_dump(exclude_none=True)
            status, error = await runtime.play_sound(sound, payload.lines, payload.volume, payload.start_ms)
            what = self._describe(sound)
            lines = LINES_TEXT.get(payload.lines or self.agent.config.soundpad.default_lines, "")
            self.agent.last_cue = {"command": "*play", "at": int(time.time() * 1000), "ok": status == "ok"}
            if status == "ok":
                if relay is not None:
                    relay.self_playing_until = time.monotonic() + 1.5
                hub.log("success", f"▶ {what} from {sender_name} ({lines})")
            else:
                hub.log("warning", f"{what} from {sender_name} didn't play: {error}")
            if timing is not None:
                hub.log("info", f"⏱ {what} {timing.text(start=True)}")
        elif msg_type == "soundpad.stop":
            ok, error = await runtime.run_cue("*stop")
            status = "ok" if ok else "error"
            self.agent.last_cue = {"command": "*stop", "at": int(time.time() * 1000), "ok": ok}
            if relay is not None:
                relay.self_playing_until = 0.0
            hub.log("success" if ok else "warning", f"■ Stop from {sender_name}" + ("" if ok else f" failed: {error}"))
        else:
            action, value = self._control(msg_type, payload)
            status, error = await runtime.control(action, value)
            if status == "ok":
                hub.log("info", f"{sender_name}: {self._control_text(action, value)}")
            else:
                hub.log("warning", f"{sender_name}: {self._control_text(action, value)} failed: {error}")
        await self._ack(env, status, error, late_ms=timing.late_ms if timing else None)
        self.agent.changed()
        await self.publish(force=True)

    async def _finish_calibration(self, env: dict | None, sender_name: str) -> int | None:
        """Wait for the test play's start to be measured, stop it after CALIBRATE_PLAY_S, and
        answer with the start latency (median of the last plays, now saved in the config)."""
        runtime = self.runtime
        started = time.monotonic()
        measured = await runtime.calibration_result()
        await asyncio.sleep(max(0.0, CALIBRATE_PLAY_S - (time.monotonic() - started)))
        relay = self._relay()
        if relay is not None:
            relay._actions.put(runtime.stop_calibration)
        else:
            await runtime.stop_calibration()
        median = runtime.start_latency_ms
        hub = self.agent.hub
        if measured is None or median is None:
            error = "Soundpad's position didn't move, so the start couldn't be measured (try a longer sound)"
            hub.log("warning", f"Calibration: {error}")
            if env is not None:
                await self._ack(env, "error", error)
            return None
        hub.log("success", f"Start latency {measured:.0f} ms this time; {median:.0f} ms over the last "
                           f"{len(runtime.start_latencies)} plays (scheduled starts are sent that much earlier)")
        if env is not None:
            await self._ack(env, "ok", None, start_latency_ms=round(median))
        self.agent.changed()
        return round(median)

    async def calibrate_here(self) -> int | None:
        """The actor's own Calibrate button: the same test play, without a director."""
        status, error = await self.runtime.calibrate(None)
        if status != "ok":
            raise PlayError(status, error or "Calibration didn't start")
        self.agent.hub.log("info", "Calibrating the start latency (speakers only)…")
        return await self._finish_calibration(None, "you")

    @staticmethod
    def _control(msg_type: str, payload: Any) -> tuple[str, Any]:
        if msg_type == "soundpad.pause":
            return ("pause" if payload.paused else "resume"), None
        if msg_type == "soundpad.mute":
            return ("mute" if payload.muted else "unmute"), None
        if msg_type == "soundpad.volume":
            return "volume", payload.value
        return msg_type.split(".", 1)[1], payload.ms  # seek, jump

    @staticmethod
    def _control_text(action: str, value: Any) -> str:
        return {
            "pause": "pause", "resume": "resume", "mute": "mute", "unmute": "unmute",
            "volume": f"volume {value}", "seek": f"seek to {value} ms", "jump": f"jump {value:+} ms" if isinstance(value, int) else "jump",
        }.get(action, action)

    def _describe(self, sound: dict) -> str:
        if sound.get("selected"):
            return "Your selected sound"
        if sound.get("index"):
            listed = self.runtime.cache.by_index(sound["index"])
            return listed.title if listed else f"Sound {sound['index']}"
        if sound.get("key"):
            listed = self.runtime.cache.by_key(sound["key"])
            return listed.title if listed else "A sound"
        if sound.get("category"):
            return f"{sound['category']} #{sound.get('position', 1)}"
        if sound.get("sha256"):
            path = self.runtime.received_lookup(str(sound["sha256"]))
            return path.replace("\\", "/").rsplit("/", 1)[-1] if path else "A received file"
        return str(sound.get("path", "A sound")).replace("\\", "/").rsplit("/", 1)[-1]

    async def _ack(self, env: dict, status: str, error: str | None, *, late_ms: int | None = None,
                   start_latency_ms: int | None = None) -> None:
        relay = self._relay()
        if relay is None or not env.get("from"):
            return
        ack: dict[str, Any] = {"status": status, "command": env.get("type")}
        if error:
            ack["error"] = error[:500]
        if late_ms is not None:
            ack["late_ms"] = late_ms
        if start_latency_ms is not None:
            ack["start_latency_ms"] = min(5000, max(0, start_latency_ms))
        try:
            await relay._send("soundpad.ack", ack, {"ids": [env["from"]]}, reply_to=env.get("id"))
        except RuntimeError:
            pass

    # ==== director side =============================================================================

    def on_director_message(self, env: dict, sender_name: str) -> None:
        msg_type = env.get("type")
        sender = env.get("from") or ""
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        if msg_type == "soundpad.state":
            try:
                validate("soundpad.state", data)
            except ValueError:
                return
            self.states[sender] = (data, int(time.time() * 1000))
            self.agent.changed()
        elif msg_type == "soundpad.list":
            try:
                page = validate("soundpad.list", data)
            except ValueError:
                return
            got = self._pages.setdefault(sender, [])
            if page.first == 1:
                got.clear()
            got.append(page.model_dump())
            if page.last:
                sounds = [{"index": s["index"], "key": s["key"], "title": s["title"], "durationMs": s["duration_ms"]}
                          for p in got for s in p["sounds"]]
                categories = [{"index": c["index"], "name": c["name"]} for c in got[0]["categories"]] if got else []
                self.lists[sender] = {"type": "sounds", "peerId": sender, "sounds": sounds, "categories": categories,
                                      "total": page.total, "at": int(time.time() * 1000)}
                self._pages.pop(sender, None)
                self.agent.hub.event(self.lists[sender])
        elif msg_type == "soundpad.ack":
            status = str(data.get("status", ""))
            if status not in ("ok", ""):
                command = str(data.get("command") or "soundpad").replace("soundpad.", "")
                self.agent.hub.log("warning", f"{sender_name}: {command} — {data.get('error') or status}")
            latency = data.get("start_latency_ms")
            if data.get("command") == "soundpad.calibrate" and isinstance(latency, int) and not isinstance(latency, bool):
                self.latencies[sender] = latency
                self.agent.hub.log("success", f"{sender_name}: start latency {latency} ms")
                self.agent.changed()

    def forget_missing(self, present: set[str]) -> None:
        for sid in [s for s in self.states if s not in present]:
            self.states.pop(sid, None)
            self.lists.pop(sid, None)
            self.latencies.pop(sid, None)

    def peer_view(self, session_id: str) -> dict | None:
        """A remote actor's Soundpad for the UI (camelCase; `at` is when the state arrived)."""
        entry = self.states.get(session_id)
        if entry is None:
            return None
        s, at = entry
        return {
            "available": bool(s.get("available")),
            "status": s.get("status"),
            "positionMs": s.get("position_ms", 0),
            "durationMs": s.get("duration_ms", 0),
            "title": s.get("title"),
            "index": s.get("index"),
            "key": s.get("key"),
            "lines": s.get("lines"),
            "volume": s.get("volume"),
            "muted": s.get("muted"),
            "detail": s.get("detail", ""),
            # None from apps that don't say (older builds)
            "autoAddReceived": s.get("auto_add_received"),
            "trial": s.get("trial"),
            "at": at,
            "startLatencyMs": self.latencies.get(session_id),
        }
