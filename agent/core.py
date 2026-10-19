"""The agent: owns config, the relay connection and local runtimes, and answers UI calls."""

from __future__ import annotations

import asyncio
import time
import webbrowser
from typing import Any, Callable

from . import APP_VERSION
from .actor_runtime import ActorRuntime
from .config import ROLES, THEMES, ConfigStore, clamp_scale
from .hub import Hub
from .relay_legacy import LegacyRelay

COUNTDOWN_MS = 3000


class CallError(Exception):
    """A UI request that can't be done; the message is shown to the user."""


class Agent:
    def __init__(self, store: ConfigStore):
        self.store = store
        self.hub = Hub(self.snapshot)
        self.actor = ActorRuntime(store.config, changed=self.changed, log=self.hub.log)
        self.relay = LegacyRelay(self)
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
                "legacy": True,
            },
            "peers": peers,
            "pending": list(relay.pending) if cfg.role == "director" and relay.status == "connected" else [],
            "targets": sorted(f"actor:{n}" for n in relay.targets if n in relay.actors) if cfg.role == "director" else [],
            "countdown": countdown,
            "actor": (
                {"soundpad": self.actor.soundpad_state(), "osc": self.actor.osc_state(), "lastCue": self.last_cue}
                if cfg.role == "actor"
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
        self.relay.targets.clear()
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
        self.store.save()
        await self.actor.refresh()

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
