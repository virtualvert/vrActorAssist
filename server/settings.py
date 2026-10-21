"""Relay settings and its log file."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_PORT = 5555
DEFAULT_SECRET = "vractor-secret-change-me"
# The v0.3 relay kept its files next to server_ws.py; so does this one unless told otherwise.
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1]


@dataclass
class Settings:
    secret: str = DEFAULT_SECRET
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    # /ws for v0.3 clients (spec §11.1: `legacy.enabled`, on by default)
    legacy_enabled: bool = True
    # Ping and status broadcast every 10 s (None turns the loop off, for tests)
    status_interval_s: float | None = 10.0
    status_grace_s: float = 2.0
    # No pong for this long: shown as timed out
    ping_timeout_s: float = 60.0
    # A /v2/ws client must say hello within this time
    hello_timeout_s: float = 10.0
    # Largest v2 text frame; file chunks are binary frames, up to max_chunk_bytes after their header
    max_frame_bytes: int = 256 * 1024
    max_chunk_bytes: int = 256 * 1024
    # File transfers one session may have open at once
    max_open_transfers: int = 16
    echo_log: bool = True

    @property
    def approved_file(self) -> Path:
        return self.data_dir / "approved_actors.json"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "server.log"

    @property
    def manifest_file(self) -> Path:
        return self.data_dir / "update_manifest.json"


class Log:
    """Same format and file as the v0.3 relay: `[YYYY-MM-DD HH:MM:SS] message`."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def __call__(self, message: str) -> None:
        entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        if self.settings.echo_log:
            print(entry, flush=True)
        try:
            with open(self.settings.log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except OSError:
            pass
