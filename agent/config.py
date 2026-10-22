"""Persistent agent settings: role, profile, UI preferences and per-feature options.

Stored as JSON in the data dir. Unknown keys are ignored and bad values fall back to
defaults, so a hand-edited or older file never stops the app from starting.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROLES = ("director", "actor", "camera")
THEMES = ("system", "dark", "light")
SCALE_MIN = 0.75
SCALE_MAX = 2.0
CONFIG_FILE = "config.json"
PORTABLE_FLAG = "portable.flag"
PORTABLE_DIR = "vrcActorSync-data"
APP_DIR = "vrcActorSync"


def clamp_scale(value: Any) -> float:
    """Keep the UI scale in range, on a 5% grid (same rule as the web UI)."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    if scale != scale:  # NaN
        return 1.0
    return round(min(SCALE_MAX, max(SCALE_MIN, scale)) * 20) / 20


@dataclass
class Prefs:
    theme: str = "system"
    scale: float = 1.0
    vr_mode: bool = False
    reduce_motion: bool = False


LINES = ("both", "speakers", "mic")


@dataclass
class SoundpadConfig:
    enabled: bool = True
    path: str = ""
    # Output line when the director doesn't pick one (spec §8.1.4)
    default_lines: str = "both"
    # Add received files to Soundpad (full version only), so the director can play them (§8.4)
    auto_add_received: bool = True
    # Start Soundpad.exe when its pipe isn't there (§8.1.1)
    auto_launch: bool = False
    # Send scheduled starts early by the measured start latency (§8.2.3)
    auto_compensate_latency: bool = True
    # The last measured start latencies in ms, newest last (their median is used)
    start_latencies: list[float] = field(default_factory=list)


LATENCY_SAMPLES = 5
LEAD_MAX_MS = 2000


@dataclass
class DirectorConfig:
    # GO is sent for server time now + lead_ms so every actor starts together (§8.2.2); 0 = at once
    lead_ms: int = 300


@dataclass
class OscConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 9000


@dataclass
class FilesConfig:
    # Where received files go; empty = Documents/vrcActorSync (agent/files.py)
    receive_dir: str = ""
    # Accept offers without asking, and replace files with the same name (the v0.3 rule)
    auto_accept: bool = False


@dataclass
class Config:
    role: str | None = None
    name: str = ""
    server_url: str = ""
    secret: str = ""
    prefs: Prefs = field(default_factory=Prefs)
    soundpad: SoundpadConfig = field(default_factory=SoundpadConfig)
    osc: OscConfig = field(default_factory=OscConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    director: DirectorConfig = field(default_factory=DirectorConfig)

    @classmethod
    def from_dict(cls, data: Any) -> "Config":
        if not isinstance(data, dict):
            return cls()
        cfg = cls()
        role = data.get("role")
        cfg.role = role if role in ROLES else None
        cfg.name = _str(data.get("name"))
        cfg.server_url = _str(data.get("server_url"))
        cfg.secret = _str(data.get("secret"))

        prefs = data.get("prefs") if isinstance(data.get("prefs"), dict) else {}
        theme = prefs.get("theme")
        cfg.prefs = Prefs(
            theme=theme if theme in THEMES else "system",
            scale=clamp_scale(prefs.get("scale", 1.0)),
            vr_mode=bool(prefs.get("vr_mode", False)),
            reduce_motion=bool(prefs.get("reduce_motion", False)),
        )

        sp = data.get("soundpad") if isinstance(data.get("soundpad"), dict) else {}
        lines = sp.get("default_lines")
        cfg.soundpad = SoundpadConfig(
            enabled=bool(sp.get("enabled", True)),
            path=_str(sp.get("path")),
            default_lines=lines if lines in LINES else "both",
            auto_add_received=bool(sp.get("auto_add_received", True)),
            auto_launch=bool(sp.get("auto_launch", False)),
            auto_compensate_latency=bool(sp.get("auto_compensate_latency", True)),
            start_latencies=_latencies(sp.get("start_latencies")),
        )

        osc = data.get("osc") if isinstance(data.get("osc"), dict) else {}
        cfg.osc = OscConfig(
            enabled=bool(osc.get("enabled", True)),
            host=_str(osc.get("host")) or "127.0.0.1",
            port=_port(osc.get("port"), 9000),
        )

        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        cfg.files = FilesConfig(receive_dir=_str(files.get("receive_dir")), auto_accept=bool(files.get("auto_accept", False)))

        director = data.get("director") if isinstance(data.get("director"), dict) else {}
        cfg.director = DirectorConfig(lead_ms=clamp_lead(director.get("lead_ms", 300)))
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def clamp_lead(value: Any) -> int:
    """GO lead time in ms: 0 (at once) to LEAD_MAX_MS."""
    if isinstance(value, bool):
        return 300
    try:
        lead = int(value)
    except (TypeError, ValueError):
        return 300
    return min(LEAD_MAX_MS, max(0, lead))


def _latencies(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    good = [float(v) for v in value if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 5000]
    return good[-LATENCY_SAMPLES:]


def _port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


def exe_dir() -> Path:
    """Folder of the frozen executable, or the repo root when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    if os.environ.get("VRCAS_PORTABLE") == "1":
        return True
    return (exe_dir() / PORTABLE_FLAG).exists()


def data_dir(portable: bool | None = None) -> Path:
    """Where config, logs and window storage live.

    Order: VRCAS_DATA_DIR, then portable (next to the exe), then the per-user app folder.
    """
    override = os.environ.get("VRCAS_DATA_DIR")
    if override:
        return Path(override)
    if portable if portable is not None else is_portable():
        return exe_dir() / PORTABLE_DIR
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_DIR


def migrate_legacy(folder: Path, role: str | None = None) -> Config | None:
    """Build a config from the v0.3 client files (actor_config.json / director_config.json).

    The role comes from `role` (--role), else from whichever file exists, so an existing actor
    opens straight into the actor view. With both present the user picks the role on first
    launch. The director secret comes along only while the role is director or still open.
    """
    actor = _read_json(folder / "actor_config.json")
    director = _read_json(folder / "director_config.json")
    if actor is None and director is None:
        return None
    cfg = Config()
    if role in ROLES:
        cfg.role = role
    elif actor is not None and director is None:
        cfg.role = "actor"
    elif director is not None and actor is None:
        cfg.role = "director"
    if director:
        cfg.server_url = _str(director.get("server_url"))
        if cfg.role in (None, "director"):
            cfg.secret = _str(director.get("secret"))
    if actor:
        cfg.server_url = _str(actor.get("server_url")) or cfg.server_url
        cfg.name = _str(actor.get("actor_name"))
        cfg.soundpad = SoundpadConfig(
            enabled=bool(actor.get("soundpad_enabled", True)),
            path=_str(actor.get("soundpad_path")),
        )
        cfg.osc = OscConfig(
            enabled=bool(actor.get("osc_enabled", True)),
            host=_str(actor.get("vrchat_osc_host")) or "127.0.0.1",
            port=_port(actor.get("vrchat_osc_port"), 9000),
        )
        cfg.files = FilesConfig(
            receive_dir=_str(actor.get("receive_dir")),
            auto_accept=bool(actor.get("auto_accept_files", False)),
        )
    return cfg


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class ConfigStore:
    """Loads once, saves atomically on every change."""

    def __init__(self, folder: Path, legacy_folder: Path | None = None, role: str | None = None):
        self.folder = folder
        self.path = folder / CONFIG_FILE
        self.migrated = False
        self.config = self._load(legacy_folder, role)

    def _load(self, legacy_folder: Path | None, role: str | None) -> Config:
        data = _read_json(self.path)
        if data is not None:
            return Config.from_dict(data)
        if legacy_folder is not None:
            legacy = migrate_legacy(legacy_folder, role)
            if legacy is not None:
                self.migrated = True
                self.config = legacy
                self.save()
                return legacy
        return Config()

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.config.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
