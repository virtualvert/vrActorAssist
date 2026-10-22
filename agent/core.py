"""The agent: owns config, the relay connection and local runtimes, and answers UI calls."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import webbrowser
from typing import Any, Callable

from . import APP_VERSION
from .actor_runtime import ActorRuntime
from .config import ROLES, THEMES, ConfigStore, clamp_scale
import soundpad

from vrcas_protocol import validate

from .actor_runtime import PlayError
from .config import LINES, clamp_lead
from .files import Files, received_path
from .folders import FolderError, Folders, pick_folder
from .hub import Hub
from .relay import Relay
from .shell import open_folder
from .soundpad_remote import LINES_TEXT, SoundpadRemote

MAX_SEND_ITEMS = 500
# Cues and Soundpad controls repeated with the same arguments this soon are dropped (Agent._repeated)
REPEATABLE_CALLS = {"cue", "play", "playIndex", "transport", "calibrate"}
REPEAT_S = 0.15
DELAY_LIMIT_MS = 10_000
NO_CLOCK = {"synced": False, "offsetMs": None, "rttMs": None}


class CallError(Exception):
    """A UI request that can't be done; the message is shown to the user."""


class Agent:
    def __init__(self, store: ConfigStore):
        self.store = store
        self.hub = Hub(self.snapshot)
        self.actor = ActorRuntime(store.config, changed=self.changed, log=self.hub.log)
        # Folders opened in this run (Normalize folder, Send files); file access stays inside them
        self.folders = Folders()
        self.files = Files(self)
        self.soundpad = SoundpadRemote(self)
        self.actor.received_lookup = lambda sha256: received_path(store.folder, sha256)
        self.actor.on_latency = self._latency_measured
        self.relay = Relay(self)
        self.last_cue: dict | None = None
        # Director: the sound GO plays on an actor instead of their selected one, by peer id
        # ({sound, label, lines}); kept until cleared, in memory only (Phase 2 M3)
        self.armed: dict[str, dict] = {}
        self._last_control: tuple[str, float] | None = None
        # Set by the launcher: returns a fresh one-time URL for the local UI.
        self.ui_url: Callable[[], str] | None = None

    @property
    def config(self):
        return self.store.config

    @property
    def log_dir(self) -> Path:
        """Where __main__.setup_logging writes agent.log."""
        return self.store.folder / "logs"

    def changed(self) -> None:
        self.hub.state_changed()

    def _latency_measured(self, latencies: list[float]) -> None:
        """The actor measured a start: keep the last few in the config (§8.2.3)."""
        self.config.soundpad.start_latencies = latencies
        self.store.save()
        self.changed()

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if self.store.migrated:
            self.hub.log("info", "Imported your settings from the v0.3 client.")
        await self.actor.refresh()
        if self.ready_to_connect():
            self.relay.start()
        self.changed()

    async def shutdown(self) -> None:
        self.hub.log("info", "Closing vrcActorSync")
        await self.relay.stop("App closed")
        await self.actor.close()

    def ready_to_connect(self) -> bool:
        cfg = self.config
        return bool(cfg.role and cfg.server_url and cfg.name and (cfg.role != "director" or cfg.secret))

    # ---- state for the UI ---------------------------------------------------

    def snapshot(self) -> dict:
        cfg = self.config
        relay = self.relay
        now = time.monotonic()
        # Soundpad's real status when the pipe is up; otherwise a short flash after each cue
        live = self.actor.live_status
        playing = cfg.role == "actor" and (live in ("PLAYING", "SEEKING") if live else now < relay.self_playing_until)
        peers: list[dict] = []
        if cfg.role:
            peers.append(
                {
                    "id": "self",
                    "name": cfg.name or "You",
                    "role": cfg.role,
                    "status": "online",
                    "latencyMs": None,
                    "activity": "playing" if playing else "idle",
                    "self": True,
                    "caps": [],
                    "soundpad": None,
                    "delayMs": None,
                    "lastLateMs": None,
                }
            )
            if relay.status == "connected":
                peers.extend(relay.peers())
        v2 = not relay.legacy and relay.status == "connected"
        return {
            "appVersion": APP_VERSION,
            "demo": False,
            "logDir": str(self.log_dir),
            "role": cfg.role,
            "prefs": {
                "theme": cfg.prefs.theme,
                "scale": cfg.prefs.scale,
                "vrMode": cfg.prefs.vr_mode,
                "reduceMotion": cfg.prefs.reduce_motion,
            },
            "profile": {"name": cfg.name, "serverUrl": cfg.server_url, "hasSecret": bool(cfg.secret)},
            "connection": {
                "status": relay.status,
                "detail": relay.detail,
                "host": relay.host,
                "serverVersion": relay.server_version,
                "legacy": relay.legacy,
            },
            "peers": peers,
            "pending": list(relay.pending) if cfg.role == "director" and relay.status == "connected" else [],
            "offline": list(relay.offline) if cfg.role == "director" and relay.status == "connected" else [],
            "targets": relay.target_ids() if cfg.role == "director" else [],
            "countdown": relay.countdown,
            "clock": relay.impl.clock.view() if v2 else dict(NO_CLOCK),
            "actor": (
                {
                    "soundpad": self.actor.soundpad_state(),
                    "osc": self.actor.osc_state(),
                    "lastCue": self.last_cue,
                    "files": self.files.receiver.view(),
                    "timing": {**self.actor.timing_state(), "delayMs": relay.impl.delay_ms if v2 else 0},
                }
                if cfg.role == "actor"
                else None
            ),
            "director": (
                {"files": self.files.sender.view(), "leadMs": cfg.director.lead_ms, "armed": dict(self.armed)}
                if cfg.role == "director"
                else None
            ),
            "camera": (
                {
                    "obs": {"connected": False, "detail": "OBS control isn't built yet. It arrives with the OBS addon."},
                    "recording": False,
                    "recordingSince": None,
                }
                if cfg.role == "camera"
                else None
            ),
        }

    # ---- UI calls -----------------------------------------------------------

    async def handle_call(self, name: str, args: dict[str, Any]) -> None:
        handler = getattr(self, f"_call_{name}", None)
        if handler is None:
            raise CallError(f"Unknown request: {name}")
        if self._repeated(name, args or {}):
            return
        await handler(args or {})
        self.changed()

    def _repeated(self, name: str, args: dict) -> bool:
        """The same cue or Soundpad control again within REPEAT_S of the last one: a held key or a
        double click, so it's dropped. A stream of them stays one (laptop run, M2: a stuck key sent
        ~350 plays 35–40 ms apart)."""
        if name not in REPEATABLE_CALLS:
            return False
        key = name + json.dumps(args, sort_keys=True, default=str)
        now = time.monotonic()
        last, self._last_control = self._last_control, (key, now)
        return last is not None and last[0] == key and now - last[1] < REPEAT_S

    async def _call_setRole(self, args: dict) -> None:
        role = args.get("role")
        if role not in ROLES:
            raise CallError("Unknown role")
        if role == self.config.role:
            return
        was_online = self.relay.running
        self.config.role = role
        self.store.save()
        self.last_cue = None
        self.armed.clear()
        self.relay.clear_targets()
        self.hub.log("info", f"Role set to {role}")
        await self.actor.refresh()  # opens or closes Soundpad's pipe
        if was_online:
            await self.relay.restart()

    async def _call_setPrefs(self, args: dict) -> None:
        prefs = self.config.prefs
        if args.get("theme") in THEMES:
            prefs.theme = args["theme"]
        if "scale" in args:
            prefs.scale = clamp_scale(args["scale"])
        if "vrMode" in args:
            prefs.vr_mode = bool(args["vrMode"])
        if "reduceMotion" in args:
            prefs.reduce_motion = bool(args["reduceMotion"])
        self.store.save()

    async def _call_setProfile(self, args: dict) -> None:
        cfg = self.config
        if isinstance(args.get("name"), str):
            cfg.name = args["name"].replace("|", "/").strip()[:40]
        if isinstance(args.get("serverUrl"), str):
            cfg.server_url = args["serverUrl"].strip()
        if isinstance(args.get("secret"), str) and args["secret"]:
            cfg.secret = args["secret"]
        self.store.save()

    async def _call_connect(self, args: dict) -> None:
        cfg = self.config
        if not cfg.role:
            raise CallError("Pick a role first")
        if not cfg.server_url:
            raise CallError("Enter the relay server address")
        if not cfg.name:
            raise CallError("Enter your name")
        if cfg.role == "director" and not cfg.secret:
            raise CallError("Directors need the secret from the server owner")
        await self.relay.restart()

    async def _call_disconnect(self, args: dict) -> None:
        await self.relay.stop("Disconnected")
        self.hub.log("info", "Disconnected")

    async def _call_sendChat(self, args: dict) -> None:
        text = str(args.get("text", "")).strip()
        if text:
            await self._relay_action(self.relay.chat(text))

    async def _call_cue(self, args: dict) -> None:
        self._require_director()
        command = args.get("command")
        if command not in ("go", "stop", "countdown"):
            raise CallError("Unknown cue")
        await self._relay_action(self.relay.cue(command))

    async def _call_setTargets(self, args: dict) -> None:
        self._require_director()
        ids = args.get("ids", [])
        self.relay.set_targets([i for i in ids if isinstance(i, str)])

    async def _call_approve(self, args: dict) -> None:
        self._require_director()
        await self._relay_action(self.relay.approve(str(args.get("id", ""))))

    async def _call_deny(self, args: dict) -> None:
        self._require_director()
        await self._relay_action(self.relay.deny(str(args.get("id", ""))))

    async def _call_forget(self, args: dict) -> None:
        self._require_director()
        await self._relay_action(self.relay.forget(str(args.get("id", ""))))

    async def _call_setActorLocal(self, args: dict) -> None:
        cfg = self.config
        if "soundpadEnabled" in args:
            cfg.soundpad.enabled = bool(args["soundpadEnabled"])
        if "oscEnabled" in args:
            cfg.osc.enabled = bool(args["oscEnabled"])
        if isinstance(args.get("soundpadPath"), str):
            cfg.soundpad.path = args["soundpadPath"].strip()
        if isinstance(args.get("receiveDir"), str):
            folder = args["receiveDir"].strip()
            if folder and not Path(folder).expanduser().is_absolute():
                raise CallError("Use the full path of the folder")
            cfg.files.receive_dir = folder
        if "autoAcceptFiles" in args:
            cfg.files.auto_accept = bool(args["autoAcceptFiles"])
        if args.get("defaultLines") in LINES:
            cfg.soundpad.default_lines = args["defaultLines"]
        if "autoAddReceived" in args:
            cfg.soundpad.auto_add_received = bool(args["autoAddReceived"])
        if "autoLaunch" in args:
            cfg.soundpad.auto_launch = bool(args["autoLaunch"])
        if "autoCompensateLatency" in args:
            cfg.soundpad.auto_compensate_latency = bool(args["autoCompensateLatency"])
        self.store.save()
        await self.actor.refresh()

    async def _call_setDirectorLocal(self, args: dict) -> None:
        self._require_director()
        if "leadMs" in args:
            self.config.director.lead_ms = clamp_lead(args["leadMs"])
            lead = self.config.director.lead_ms
            self.hub.log("info", f"GO lead time: {lead} ms" if lead else "GO lead time: 0 (GO goes out at once)")
        self.store.save()

    async def _call_detectSoundpad(self, args: dict) -> None:
        path = await asyncio.to_thread(soundpad.find_soundpad_exe)
        if not path:
            raise CallError("Soundpad.exe wasn't found in Program Files or Steam. Enter its location by hand.")
        self.config.soundpad.path = path
        self.store.save()
        await self.actor.refresh()
        self.hub.log("info", f"Soundpad found: {path}")
        self.hub.toast("success", "Soundpad found")

    # ---- Soundpad on actors (spec §8.1) ---------------------------------------

    def _v2_actors(self, args: dict, what: str):
        """The v2 relay connection and the actor session ids in args["ids"]."""
        self._require_director()
        relay = self.relay.impl
        if relay.status != "connected":
            raise CallError("Not connected to the relay")
        if relay.legacy:
            raise CallError(f"{what} needs the v0.4 relay; this one is v0.3")
        ids = [i for i in args.get("ids", []) if isinstance(i, str) and getattr(relay.sessions.get(i), "role", "") == "actor"]
        if not ids:
            raise CallError("Pick an actor first")
        return relay, ids

    def _names(self, relay, ids: list[str]) -> str:
        return ", ".join(relay.sessions[i].name for i in ids)

    async def _call_play(self, args: dict) -> None:
        relay, ids = self._v2_actors(args, "Playing a chosen sound")
        data: dict[str, Any] = {"sound": args.get("sound")}
        if args.get("lines") is not None:
            data["lines"] = args["lines"]
        if args.get("volume") is not None:
            data["volume"] = args["volume"]
        if args.get("startMs"):
            data["start_ms"] = args["startMs"]
        try:
            validate("soundpad.play", data)
        except ValueError as exc:
            raise CallError(f"Can't play that: {exc}") from exc
        await self._relay_action(relay.send("soundpad.play", data, {"ids": ids}))
        label = str(args.get("label") or "sound")[:120]
        lines = LINES_TEXT.get(str(data.get("lines")), "their default line")
        self.hub.log("success", f"▶ {label} → {self._names(relay, ids)} ({lines})")
        self.hub.traffic("self", ids, "cue")

    async def _call_playIndex(self, args: dict) -> None:
        self._require_director()
        index = args.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise CallError("Enter a sound number from 1 up")
        impl = self.relay.impl
        if impl.status != "connected":
            raise CallError("Not connected to the relay")
        ids = [i for i in args.get("ids", []) if isinstance(i, str)]
        if impl.legacy:
            names = await impl.send_play_index(ids, index)
            if not names:
                raise CallError("Pick an actor first")
            self.hub.log("success", f"▶ Sound {index} → {', '.join(names)}")
            self.hub.traffic("self", [f"actor:{n}" for n in names], "cue")
            return
        relay, ids = self._v2_actors(args, "Play #N")
        await self._relay_action(relay.send("cue.play", {"index": index}, {"ids": ids}))
        self.hub.log("success", f"▶ Sound {index} → {self._names(relay, ids)}")
        self.hub.traffic("self", ids, "cue")

    async def _call_transport(self, args: dict) -> None:
        relay, ids = self._v2_actors(args, "Soundpad controls")
        action, value = args.get("action"), args.get("value")
        messages = {
            "pause": ("soundpad.pause", {"paused": True}),
            "resume": ("soundpad.pause", {"paused": False}),
            "mute": ("soundpad.mute", {"muted": True}),
            "unmute": ("soundpad.mute", {"muted": False}),
            "volume": ("soundpad.volume", {"value": value}),
            "seek": ("soundpad.seek", {"ms": value}),
            "jump": ("soundpad.jump", {"ms": value}),
            "stop": ("soundpad.stop", {}),
        }
        if action not in messages:
            raise CallError("Unknown Soundpad control")
        msg_type, data = messages[action]
        try:
            validate(msg_type, data)
        except ValueError as exc:
            raise CallError(f"Can't {action}: {exc}") from exc
        await self._relay_action(relay.send(msg_type, data, {"ids": ids}))
        self.hub.traffic("self", ids, "stop" if action == "stop" else "cue")

    async def _call_requestSounds(self, args: dict) -> None:
        relay, ids = self._v2_actors({"ids": [args.get("id")]}, "The sound list")
        cached = self.soundpad.lists.get(ids[0])
        if cached:
            self.hub.event(cached)  # show the last list right away; a fresh one follows
        await self._relay_action(relay.send("soundpad.list.request", {}, {"ids": ids}))

    # ---- timing (spec §8.2) and armed sounds -----------------------------------

    def _peer_name(self, peer_id: str) -> str:
        return next((p["name"] for p in self.relay.peers() if p["id"] == peer_id), "That actor")

    async def _call_arm(self, args: dict) -> None:
        """Arm a sound for one actor: GO then plays it on them instead of their selected sound."""
        self._require_director()
        impl = self.relay.impl
        if impl.status != "connected":
            raise CallError("Not connected to the relay")
        actor_id, sound, lines = str(args.get("id", "")), args.get("sound"), args.get("lines")
        if lines is not None and lines not in LINES:
            raise CallError("Unknown output line")
        try:
            payload = validate("soundpad.play", {"sound": sound, **({"lines": lines} if lines else {})})
        except ValueError as exc:
            raise CallError(f"Can't arm that: {exc}") from exc
        ref = payload.sound.model_dump(exclude_none=True)
        if not ref:
            raise CallError("Pick a sound to arm")
        reason = impl.can_arm(actor_id, ref, lines)
        if reason:
            raise CallError(reason)
        label = str(args.get("label") or "").strip()[:120] or (f"Sound {ref['index']}" if "index" in ref else "A sound")
        self.armed[actor_id] = {"sound": ref, "label": label, "lines": lines}
        self.hub.log("info", f"Armed for GO: {label} on {self._peer_name(actor_id)}" + (f" ({LINES_TEXT[lines]})" if lines else ""))

    async def _call_disarm(self, args: dict) -> None:
        self._require_director()
        actor_id = str(args.get("id", ""))
        if self.armed.pop(actor_id, None) is not None:
            self.hub.log("info", f"Cleared the armed sound on {self._peer_name(actor_id)}: GO plays their selected sound")

    async def _call_setDelay(self, args: dict) -> None:
        """A per-actor delay (§8.2.3), stored by the relay and applied by the actor."""
        self._require_director()
        ms = args.get("ms")
        if isinstance(ms, bool) or not isinstance(ms, int) or not -DELAY_LIMIT_MS <= ms <= DELAY_LIMIT_MS:
            raise CallError(f"Enter a delay between −{DELAY_LIMIT_MS} and {DELAY_LIMIT_MS} ms")
        await self._relay_action(self.relay.impl.set_delay(str(args.get("id", "")), ms))

    async def _call_calibrate(self, args: dict) -> None:
        """Measure an actor's start latency with a speakers-only test play (§8.2.3). Directors name
        the actor (`id`); an actor calibrates its own Soundpad."""
        if self.config.role == "actor" and not args.get("id"):
            try:
                await self.soundpad.calibrate_here()
            except PlayError as exc:
                raise CallError(str(exc)) from exc
            return
        relay, ids = self._v2_actors({"ids": [args.get("id")]}, "Calibration")
        session = relay.sessions[ids[0]]
        if "soundpad.calibrate" not in session.capabilities:
            raise CallError(f"{session.name}'s app is too old to calibrate")
        data: dict[str, Any] = {}
        if isinstance(args.get("sound"), dict):
            data["sound"] = args["sound"]
        try:
            validate("soundpad.calibrate", data)
        except ValueError as exc:
            raise CallError(f"Can't calibrate with that sound: {exc}") from exc
        await self._relay_action(relay.send("soundpad.calibrate", data, {"ids": ids}))
        self.hub.log("info", f"Calibrating {session.name}'s start latency (a short speakers-only play)…")
        self.hub.traffic("self", ids, "cue")

    async def _call_pickReceiveDir(self, args: dict) -> None:
        try:
            folder = await pick_folder()
        except FolderError as exc:
            raise CallError(str(exc)) from exc
        if folder:
            self.config.files.receive_dir = folder
            self.store.save()

    # ---- files (spec §8.4) ----------------------------------------------------

    async def _call_sendFiles(self, args: dict) -> None:
        self._require_director()
        relay = self.relay.impl
        if relay.legacy or relay.status != "connected":
            raise CallError("Sending files needs a connection to a v2 relay")
        folder = str(args.get("folder", ""))
        items = args.get("items")
        if not isinstance(items, list) or not items:
            raise CallError("Pick at least one file and who gets it")
        if len(items) > MAX_SEND_ITEMS:
            raise CallError(f"At most {MAX_SEND_ITEMS} files at once")
        per_actor: dict[str, list[Path]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise CallError("Bad file list")
            actor_id = str(item.get("actorId", ""))
            session = relay.sessions.get(actor_id)
            if session is None or session.role != "actor":
                raise CallError("One of the actors isn't connected any more")
            # v0.3 actors receive through the relay's bridge (Phase 2 M1b)
            if "files" not in session.capabilities and not session.legacy:
                raise CallError(f"{session.name}'s app is too old to receive files")
            try:
                path = await asyncio.to_thread(self.folders.send_source, folder, str(item.get("path", "")))
            except FolderError as exc:
                raise CallError(str(exc)) from exc
            per_actor.setdefault(actor_id, []).append(path)
        for actor_id, paths in per_actor.items():
            # One file name once per actor: the receiver keeps only one file with that name
            names = [p.name for p in paths]
            if len(set(names)) != len(names):
                dupes = sorted({n for n in names if names.count(n) > 1})
                raise CallError(f"{relay.sessions[actor_id].name} would get two files named {dupes[0]}")
        for actor_id, paths in per_actor.items():
            self.files.sender.start(actor_id, relay.sessions[actor_id].name, paths)
            self.hub.log("info", f"Sending {len(paths)} file{'s' if len(paths) != 1 else ''} to {relay.sessions[actor_id].name}")

    async def _call_cancelBatch(self, args: dict) -> None:
        self._require_director()
        await self.files.sender.cancel(str(args.get("id", "")))

    async def _call_answerFile(self, args: dict) -> None:
        await self.files.receiver.answer(
            str(args.get("transferId", "")),
            bool(args.get("accept")),
            rest=bool(args.get("rest")),
            always=bool(args.get("always")),
        )

    async def _call_camera(self, args: dict) -> None:
        raise CallError("Roll and Cut need the OBS addon, which isn't built yet.")

    async def _call_openBrowser(self, args: dict) -> None:
        if self.ui_url is None:
            raise CallError("Browser access isn't available")
        url = self.ui_url()
        await asyncio.to_thread(webbrowser.open, url)

    async def _call_openLogFolder(self, args: dict) -> None:
        folder = self.log_dir
        if not folder.is_dir():
            raise CallError(f"There's no log folder yet: {folder}")
        try:
            await asyncio.to_thread(open_folder, folder)
        except OSError as exc:
            raise CallError(f"Couldn't open {folder}: {exc}") from exc

    def _require_director(self) -> None:
        if self.config.role != "director":
            raise CallError("Only directors can do that")

    async def _relay_action(self, action) -> None:
        if self.relay.status != "connected":
            action.close()
            raise CallError("Not connected to the relay")
        try:
            await action
        except RuntimeError as exc:
            raise CallError(str(exc)) from exc
