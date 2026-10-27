"""End-to-end against the real v0.3 relay (the released server_ws.py) running in-process."""

import asyncio

import pytest

from agent.core import CallError
from agent.relay_legacy import ws_url

from .helpers import SECRET, legacy_harness, make_agent, serve, wait_for


def test_ws_url_normalisation():
    assert ws_url("relay.example:5555") == "ws://relay.example:5555/ws"
    assert ws_url("https://relay.example/") == "wss://relay.example/ws"
    assert ws_url("http://10.0.0.2:5555") == "ws://10.0.0.2:5555/ws"
    assert ws_url("wss://relay.example/ws") == "wss://relay.example/ws"
    assert ws_url("wss://relay.example/ws?secret=x") == "wss://relay.example/ws"
    assert ws_url("ws://host/prefix") == "ws://host/prefix/ws"
    # No scheme and no port: a relay behind HTTPS (Caddy, Tailscale Funnel)
    assert ws_url("relay.example") == "wss://relay.example/ws"
    assert ws_url("relay.example/ws") == "wss://relay.example/ws"
    assert ws_url(" relay.example/ ") == "wss://relay.example/ws"
    assert ws_url("10.0.0.2:5555/ws") == "ws://10.0.0.2:5555/ws"
    assert ws_url("[::1]:5599") == "ws://[::1]:5599/ws"
    with pytest.raises(ValueError):
        ws_url("  ")


@pytest.fixture
def relay(tmp_path):
    """The released v0.3.3 relay (frozen copy in tests/legacy_relay/): it has no /v2/ws."""
    return legacy_harness().load_v033_relay(tmp_path / "relay", SECRET).app


@pytest.mark.anyio
async def test_director_and_actor_flow(relay, tmp_path, monkeypatch):
    async with serve(relay) as port:
        url = f"127.0.0.1:{port}"

        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "machine-director", url, SECRET)
        actor = make_agent(tmp_path, monkeypatch, "Coda", "actor", "machine-actor", url)
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "connected")
            # The v0.3 relay has no /v2/ws: the agent fell back to compatibility mode
            assert director.snapshot()["connection"]["legacy"] is True
            assert any("compatibility mode" in e["text"] for e in director.hub._logs)

            await actor.start()
            await wait_for(lambda: actor.relay.status == "pending")
            await wait_for(lambda: len(director.snapshot()["pending"]) == 1)
            pending = director.snapshot()["pending"][0]
            assert pending["name"] == "Coda"

            await director.handle_call("approve", {"id": pending["id"]})
            await wait_for(lambda: actor.relay.status == "connected")
            await wait_for(lambda: any(p["id"] == "actor:Coda" for p in director.snapshot()["peers"]))
            assert director.snapshot()["targets"] == ["actor:Coda"]

            await director.handle_call("cue", {"command": "go"})
            await wait_for(lambda: actor.last_cue is not None)
            assert actor.last_cue["command"] == "*go" and actor.last_cue["ok"]
            assert any(p["self"] and p["activity"] == "playing" for p in actor.snapshot()["peers"])

            # Armed by number (the only kind a v0.3 relay carries): GO sends *play:N
            snap = director.snapshot()
            assert snap["clock"] == {"synced": False, "offsetMs": None, "rttMs": None} and actor.snapshot()["actor"]["timing"]["delayMs"] == 0
            with pytest.raises(CallError, match="by its number"):
                await director.handle_call("arm", {"id": "actor:Coda", "sound": {"key": "0123456789abcdef"}})
            with pytest.raises(CallError, match="v0.4 relay"):
                await director.handle_call("setDelay", {"id": "actor:Coda", "ms": 100})
            await director.handle_call("arm", {"id": "actor:Coda", "sound": {"index": 4}, "label": "Sound 4"})
            await asyncio.sleep(0.2)
            await director.handle_call("cue", {"command": "go"})
            await wait_for(lambda: actor.last_cue["command"] == "*play:4")
            await director.handle_call("disarm", {"id": "actor:Coda"})
            await asyncio.sleep(0.2)
            await director.handle_call("cue", {"command": "go"})
            await wait_for(lambda: actor.last_cue["command"] == "*go")

            # Untargeted actors don't get cues.
            await director.handle_call("setTargets", {"ids": []})
            actor.last_cue = None
            await director.handle_call("cue", {"command": "stop"})
            await asyncio.sleep(0.3)
            assert actor.last_cue is None

            # Chat reaches the other side, and the actor learns who the director is.
            await director.handle_call("sendChat", {"text": "Places, everyone"})
            await wait_for(lambda: any(p["id"] == "director:Mira" for p in actor.snapshot()["peers"]))

            # Only directors can cue.
            with pytest.raises(CallError):
                await actor.handle_call("cue", {"command": "go"})

            # Forgetting disconnects the actor until it asks again.
            await director.handle_call("forget", {"id": "actor:Coda"})
            await wait_for(lambda: actor.relay.status == "error")
            assert "director" in actor.relay.detail.lower()
        finally:
            await actor.shutdown()
            await director.shutdown()


@pytest.mark.anyio
async def test_wrong_secret_stops_retrying(relay, tmp_path, monkeypatch):
    async with serve(relay) as port:
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m1", f"127.0.0.1:{port}", "wrong")
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "error")
            assert "secret" in director.relay.detail.lower()
            await asyncio.sleep(1.5)
            assert director.relay.status == "error"  # no reconnect loop
        finally:
            await director.shutdown()


def test_log_folder(tmp_path, monkeypatch):
    """Settings → About shows where agent.log is and opens it (tester prep S1)."""
    from agent import core

    opened = []
    monkeypatch.setattr(core, "open_folder", opened.append)
    actor = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", "")
    logs = tmp_path / "Coda" / "logs"
    assert actor.snapshot()["logDir"] == str(logs)

    async def scenario():
        with pytest.raises(CallError, match="no log folder yet"):
            await actor.handle_call("openLogFolder", {})
        logs.mkdir(parents=True)
        await actor.handle_call("openLogFolder", {})
        assert opened == [logs]

    asyncio.run(scenario())
