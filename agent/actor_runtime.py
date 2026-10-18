"""What an actor's machine does with cues: Soundpad playback and VRChat OSC parameters.

Soundpad still goes through soundpad.py (Soundpad.exe -rc) for now; the named-pipe client
from the design spec (§8.1) replaces it once the Windows probe results are in.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any

import soundpad

if TYPE_CHECKING:
    from .config import Config

try:
    from pythonosc import udp_client
except ImportError:  # optional dependency
    udp_client = None


def osc_address(parameter: str) -> str:
    """`RecIcon` → /avatar/parameters/RecIcon; a leading slash means a full address."""
    return parameter if parameter.startswith("/") else f"/avatar/parameters/{parameter}"


def osc_value(value: str) -> Any:
    """VRChat needs typed values: bool for toggles, numbers for floats/ints."""
    lowered = value.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        number = float(lowered)
    except ValueError:
        return value
    return int(number) if lowered.lstrip("-").isdigit() else number


class ActorRuntime:
    def __init__(self, config: "Config"):
        self._config = config
        self._soundpad_path: str | None = None
        self._soundpad_checked = False
        self._osc_client: Any = None
        self._osc_target: tuple[str, int] | None = None

    async def refresh(self) -> None:
        """Look up Soundpad.exe off the event loop (auto-detect can walk Program Files)."""
        soundpad.set_soundpad_path(self._config.soundpad.path or None)
        if soundpad.is_windows():
            self._soundpad_path = await asyncio.to_thread(soundpad.get_soundpad_path)
        self._soundpad_checked = True

    def soundpad_state(self) -> dict:
        sp = self._config.soundpad
        if not sp.enabled:
            return {"enabled": False, "state": "disabled", "detail": "Cues are received, but nothing plays."}
        if not soundpad.is_windows():
            return {"enabled": True, "state": "simulated", "detail": "Soundpad only runs on Windows, so cues are simulated here."}
        if not self._soundpad_checked:
            return {"enabled": True, "state": "missing", "detail": "Looking for Soundpad.exe…"}
        if self._soundpad_path:
            return {"enabled": True, "state": "ready", "detail": f"Using {self._soundpad_path}"}
        return {"enabled": True, "state": "missing", "detail": "Soundpad.exe not found. Set its path in Settings → Actor."}

    def osc_state(self) -> dict:
        osc = self._config.osc
        return {"enabled": osc.enabled, "host": osc.host, "port": osc.port, "ready": osc.enabled and udp_client is not None}

    async def run_cue(self, command: str) -> tuple[bool, str | None]:
        """Execute *go / *stop / *play:N. Returns (ok, error message)."""
        if not self._config.soundpad.enabled:
            return True, None
        if not soundpad.is_windows():
            return True, None  # soundpad.py would only print "simulating"
        return await asyncio.to_thread(soundpad.execute_command, command, "")

    def send_osc(self, parameter: str, value: str) -> tuple[bool, str]:
        osc = self._config.osc
        address = osc_address(parameter)
        if not osc.enabled:
            return False, f"Skipped {address}={value} (OSC is off)"
        if udp_client is None:
            return False, f"Skipped {address}={value} (python-osc isn't installed)"
        target = (osc.host, osc.port)
        if self._osc_client is None or self._osc_target != target:
            self._osc_client = udp_client.SimpleUDPClient(*target)
            self._osc_target = target
        try:
            self._osc_client.send_message(address, osc_value(value))
        except OSError as exc:
            return False, f"OSC send failed: {exc}"
        return True, f"{address} ← {value}"


def platform_note() -> str:
    return "Windows" if sys.platform == "win32" else sys.platform
