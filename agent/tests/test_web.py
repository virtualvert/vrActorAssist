from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.config import ConfigStore
from agent.core import Agent
from agent.web import COOKIE, Security, create_app

PORT = 47999
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"


@pytest.fixture
def env(tmp_path):
    security = Security(PORT)
    agent = Agent(ConfigStore(tmp_path))
    app = create_app(agent, security, Path(tmp_path) / "no-web-build")
    with TestClient(app, base_url=f"http://{HOST}") as client:
        yield client, security, agent


def login(client, security):
    res = client.post("/api/session", json={"token": security.new_open_token()}, headers={"Origin": ORIGIN})
    assert res.status_code == 200
    return res


def test_foreign_host_is_rejected(env):
    client, _, _ = env
    assert client.get("/api/ping", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/ping", headers={"Host": "127.0.0.1:1234"}).status_code == 403
    assert client.get("/api/ping").json()["app"] == "vrcActorSync"


def test_tokens_work_once_and_need_our_origin(env):
    client, security, _ = env
    token = security.new_open_token()
    assert client.post("/api/session", json={"token": token}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).status_code == 200
    assert client.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).status_code == 401
    assert client.post("/api/session", json={"token": "made-up"}, headers={"Origin": ORIGIN}).status_code == 401


def test_state_needs_a_session(env):
    client, security, _ = env
    assert client.get("/api/state").status_code == 401
    login(client, security)
    state = client.get("/api/state").json()
    assert state["role"] is None
    assert state["connection"]["status"] == "disconnected"
    # Unknown until a relay answers; only a v0.3 relay turns compatibility mode on
    assert state["connection"]["legacy"] is False


def test_secret_never_reaches_the_ui(env):
    client, security, agent = env
    agent.config.secret = "hunter2"
    login(client, security)
    body = client.get("/api/state").text
    assert "hunter2" not in body
    assert client.get("/api/state").json()["profile"]["hasSecret"] is True


def test_socket_checks_origin_and_session(env):
    client, security, _ = env
    with pytest.raises(Exception):
        with client.websocket_connect("/ui/ws", headers={"Origin": "http://evil.example", "Host": HOST}) as ws:
            ws.receive_text()
    with client.websocket_connect("/ui/ws", headers={"Origin": ORIGIN, "Host": HOST}) as ws:
        with pytest.raises(Exception):
            ws.receive_text()  # closed with 4401: no session cookie yet


def test_socket_calls_update_state(env):
    client, security, agent = env
    session = login(client, security).cookies[COOKIE]
    headers = {"Origin": ORIGIN, "Host": HOST, "Cookie": f"{COOKIE}={session}"}
    with client.websocket_connect("/ui/ws", headers=headers) as ws:
        first = ws.receive_json()
        assert first["type"] == "logs"
        assert ws.receive_json()["type"] == "state"
        ws.send_json({"id": 1, "call": "setRole", "args": {"role": "actor"}})
        ws.send_json({"id": 2, "call": "setPrefs", "args": {"theme": "light", "scale": 1.4, "vrMode": True}})
        ws.send_json({"id": 3, "call": "cue", "args": {"command": "go"}})
        results = {}
        while len(results) < 3:
            msg = ws.receive_json()
            if msg["type"] == "result":
                results[msg["id"]] = msg
        assert results[1]["ok"] and results[2]["ok"]
        assert not results[3]["ok"] and "director" in results[3]["error"]
    assert agent.config.role == "actor"
    assert agent.config.prefs.scale == 1.4
    assert ConfigStore(agent.store.folder).config.prefs.theme == "light"


def test_cookie_is_http_only_and_strict(env):
    client, security, _ = env
    res = login(client, security)
    header = res.headers["set-cookie"].lower()
    assert COOKIE in header and "httponly" in header and "samesite=strict" in header
