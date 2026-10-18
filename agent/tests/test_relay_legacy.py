"""End-to-end against the real v0.3 relay (server_ws.py) running in-process."""

import asyncio
import socket
import time

import pytest
import uvicorn

from agent.config import ConfigStore
from agent.core import Agent, CallError
from agent.relay_legacy import ws_url

SECRET = "test-secret"


def test_ws_url_normalisation():
    assert ws_url("relay.example:5555") == "ws://relay.example:5555/ws"
    assert ws_url("https://relay.example/") == "wss://relay.example/ws"
    assert ws_url("http://10.0.0.2:5555") == "ws://10.0.0.2:5555/ws"
    assert ws_url("wss://relay.example/ws") == "wss://relay.example/ws"
    assert ws_url("wss://relay.example/ws?secret=x") == "wss://relay.example/ws"
    assert ws_url("ws://host/prefix") == "ws://host/prefix/ws"
    with pytest.raises(ValueError):
        ws_url("  ")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def relay(tmp_path, monkeypatch):
    import server_ws

    monkeypatch.setattr(server_ws, "APPROVED_FILE", tmp_path / "approved.json")
    monkeypatch.setattr(server_ws, "LOG_FILE", tmp_path / "server.log")
    monkeypatch.setattr(server_ws, "SERVER_SECRET", SECRET)
    monkeypatch.setattr(server_ws, "approved_actors", {})
    monkeypatch.setattr(server_ws, "pending_actors", {})
    monkeypatch.setattr(server_ws, "clients", {})
    return server_ws.app


def make_agent(tmp_path, monkeypatch, name, role, machine_id, url, secret=""):
    monkeypatch.setenv("VRCAS_MACHINE_ID", machine_id)
    store = ConfigStore(tmp_path / name)
    cfg = store.config
    cfg.role, cfg.name, cfg.server_url, cfg.secret = role, name, url, secret
    return Agent(store)


async def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


def test_director_and_actor_flow(relay, tmp_path, monkeypatch):
    async def scenario():
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(relay, host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        await wait_for(lambda: server.started)
        url = f"127.0.0.1:{port}"

        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "machine-director", url, SECRET)
        actor = make_agent(tmp_path, monkeypatch, "Coda", "actor", "machine-actor", url)
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "connected")

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
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_wrong_secret_stops_retrying(relay, tmp_path, monkeypatch):
    async def scenario():
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(relay, host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        await wait_for(lambda: server.started)
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m1", f"127.0.0.1:{port}", "wrong")
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "error")
            assert "secret" in director.relay.detail.lower()
            await asyncio.sleep(1.5)
            assert director.relay.status == "error"  # no reconnect loop
        finally:
            await director.shutdown()
            server.should_exit = True
            await task

    asyncio.run(scenario())
