"""Helpers shared by the agent tests: scripted v0.3 clients, relays, agents, waiting."""

import asyncio
import importlib.util
import time
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path

import uvicorn

from agent.config import ConfigStore
from agent.core import Agent

SECRET = "test-secret"

PORT = 47999  # the local UI server's port in tests (agent/web.py checks Host and Origin against it)
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"


@cache
def legacy_harness():
    """tests/legacy_client.py (frozen v0.3.3 relay, scripted v0.3 client), loaded by path."""
    path = Path(__file__).resolve().parents[2] / "tests" / "legacy_client.py"
    spec = importlib.util.spec_from_file_location("vrcas_legacy_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def login(client, security):
    res = client.post("/api/session", json={"token": security.new_open_token()}, headers={"Origin": ORIGIN})
    assert res.status_code == 200
    return res


def logged(agent, text):
    return any(text in e["text"] for e in agent.hub._logs)


def legacy_client(url, label, name):
    return legacy_harness().LegacyClient(url, label, name)


async def read_until(client, prefix, timeout=5.0):
    """A scripted v0.3 client's frames up to one starting with prefix (read off the event loop)."""
    return await asyncio.to_thread(client.read_until, lambda f: f.startswith(prefix), timeout)


@asynccontextmanager
async def serve(app):
    """An ASGI app on a free local port, on the running event loop. Yields the port."""
    port = legacy_harness().free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    await wait_for(lambda: server.started)
    try:
        yield port
    finally:
        server.should_exit = True
        await task


async def join_scripted_actor(running, director, name="Lex", machine_id="m-lex"):
    """A scripted v0.3 actor registers and the director approves it. Returns the client."""
    lex = legacy_client(running.url, name.lower(), name)
    lex.send(f"REGISTER|{name}|{machine_id}|actor||0.3.3|windows-x64")
    await read_until(lex, "DENIED|")
    await wait_for(lambda: director.snapshot()["pending"])
    await director.handle_call("approve", {"id": director.snapshot()["pending"][0]["id"]})
    await read_until(lex, "USERS|")
    return lex
