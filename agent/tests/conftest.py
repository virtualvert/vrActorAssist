import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Tests import `agent`, `shared`, `soundpad` and `server_ws` from the repository root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import soundpad  # noqa: E402

from agent.config import ConfigStore  # noqa: E402
from agent.core import Agent  # noqa: E402
from agent.web import Security, create_app as create_ui_app  # noqa: E402

from .helpers import HOST, PORT, SECRET, legacy_harness  # noqa: E402


@pytest.fixture
def env(tmp_path):
    """The local UI server on a TestClient, not logged in: (client, security, agent)."""
    security = Security(PORT)
    agent = Agent(ConfigStore(tmp_path / "config"))
    app = create_ui_app(agent, security, tmp_path / "no-web-build")
    with TestClient(app, base_url=f"http://{HOST}") as client:
        yield client, security, agent


@pytest.fixture
def relay(tmp_path):
    """The new relay in its own thread (so the scripted v0.3 clients may block). Yields (running, relay state)."""
    from server.app import create_app
    from server.settings import Settings

    app = create_app(Settings(secret=SECRET, data_dir=tmp_path / "relay", status_interval_s=None, echo_log=False))
    (tmp_path / "relay").mkdir()
    with legacy_harness().RelayThread(app) as running:
        yield running, app.state.relay


@pytest.fixture
def windows_cli(monkeypatch):
    """Pretend to be on Windows with Soundpad.exe found, and record -rc calls."""
    from agent import actor_runtime

    calls = []
    monkeypatch.setattr(soundpad, "is_windows", lambda: True)
    monkeypatch.setattr(soundpad, "get_soundpad_path", lambda: r"C:\Program Files\Soundpad\Soundpad.exe")
    monkeypatch.setattr(actor_runtime, "command_line", lambda command: calls.append(command) or (True, None))
    return calls


@pytest.fixture
def anyio_backend():
    return "asyncio"  # for @pytest.mark.anyio: asyncio only, not trio
