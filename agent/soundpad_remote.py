"""The soundpad addon over the relay (spec §8.1.2, §8.1.6).

Actors: answer soundpad.* from directors (each action gets a soundpad.ack), send their sound list
on request (and again when it changes), and publish soundpad.state to the directors and assistants
on v2: at most twice a second while playing, on any other change, and every 10 s.

Directors: keep each actor's last state and sound list for the UI. Lists reach the page as a
separate "sounds" event, not in the state snapshot, since they can hold thousands of entries.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from vrcas_protocol import validate

from .actor_runtime import PlayError
from .sounds import pages

if TYPE_CHECKING:
    from .core import Agent

TICK_S = 0.25
MIN_GAP_S = 0.5
HEARTBEAT_S = 10.0
ACTIONS = ("soundpad.play", "soundpad.stop", "soundpad.pause", "soundpad.seek", "soundpad.jump", "soundpad.volume",
           "soundpad.mute", "soundpad.list.request", "soundpad.calibrate")
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
        # director side: session id → state (+ when it arrived), sound lists
        self.states: dict[str, tuple[dict, int]] = {}
        self.lists: dict[str, dict] = {}
        self._pages: dict[str, list[dict]] = {}

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

    async def on_actor_message(self, env: dict, sender_name: str) -> None:
        """A soundpad.* action from a director or assistant (the relay checked who may send it)."""
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
            await self._ack(env, "unsupported", "Calibration arrives with timing (Phase 2 M3)")
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
        await self._ack(env, status, error)
        self.agent.changed()
        await self.publish(force=True)

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
        return "A received file" if sound.get("sha256") else str(sound.get("path", "A sound")).replace("\\", "/").rsplit("/", 1)[-1]

    async def _ack(self, env: dict, status: str, error: str | None) -> None:
        relay = self._relay()
        if relay is None or not env.get("from"):
            return
        ack: dict[str, Any] = {"status": status, "command": env.get("type")}
        if error:
            ack["error"] = error[:500]
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

    def forget_missing(self, present: set[str]) -> None:
        for sid in [s for s in self.states if s not in present]:
            self.states.pop(sid, None)
            self.lists.pop(sid, None)

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
            "at": at,
        }
