"""The agent: owns config, the relay connection and local runtimes, and answers UI calls."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
import webbrowser
from typing import Any, Callable

from . import APP_VERSION
from .actor_runtime import ActorRuntime
from .config import ROLES, THEMES, ConfigStore, clamp_scale
import soundpad

from vrcas_protocol import validate

from .config import LINES
from .files import Files, received_path
from .folders import FolderError, Folders, pick_folder
from .hub import Hub
from .relay import Relay
from .soundpad_remote import LINES_TEXT, SoundpadRemote

COUNTDOWN_MS = 3000
MAX_SEND_ITEMS = 500


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
        self.relay = Relay(self)
        self.last_cue: dict | None = None
        # Set by the launcher: returns a fresh one-time URL for the local UI.
        self.ui_url: Callable[[], str] | None = None

    @property
    def config(self):
        return self.store.config

    def changed(self) -> None:
        self.hub.state_changed()

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
                }
            )
            if relay.status == "connected":
                peers.extend(relay.peers())
        countdown = None
        if relay.countdown_ends is not None:
            countdown = {"endsAt": int(relay.countdown_ends * 1000), "durationMs": COUNTDOWN_MS}
        return {
            "appVersion": APP_VERSION,
            "demo": False,
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
            "targets": relay.target_ids() if cfg.role == "director" else [],
            "countdown": countdown,
            "actor": (
                {
                    "soundpad": self.actor.soundpad_state(),
                    "osc": self.actor.osc_state(),
                    "lastCue": self.last_cue,
                    "files": self.files.receiver.view(),
                }
                if cfg.role == "actor"
                else None
            ),
            "director": {"files": self.files.sender.view()} if cfg.role == "director" else None,
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
        await handler(args or {})
        self.changed()

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
        self.store.save()
        await self.actor.refresh()

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
