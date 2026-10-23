# Why someone dropped, in server.log: close codes on every disconnect, the relay's own keepalive
# timeouts, pings still unanswered at status time, slow round trips, a status loop that ran late.

import asyncio
import json
import time
from contextlib import ExitStack

import pytest
import uvicorn
from fastapi.testclient import TestClient
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
from websockets.asyncio.client import connect

from legacy_client import free_port
from relay_helpers import SECRET, FakeClock, connect_legacy, connect_v2, make_relay
from server.keepalive import protocol_class
from server.relay import close_text, span
from server.settings import Throttle

APPROVED = {"m-coda": {"name": "Coda"}}


@pytest.fixture
def stack():
    with ExitStack() as s:
        yield s


def relay_client(stack, tmp_path, approved=None, **kwargs):
    app = make_relay(tmp_path, approved, **kwargs)
    return stack.enter_context(TestClient(app)), app.state.relay


def log_of(tmp_path) -> str:
    path = tmp_path / "server.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def wait_for_log(tmp_path, text: str, timeout: float = 5.0) -> str:
    """The server.log line containing text (the relay writes it from its own thread)."""
    end = time.monotonic() + timeout
    while True:
        line = next((line for line in log_of(tmp_path).splitlines() if text in line), None)
        if line is not None:
            return line
        if time.monotonic() > end:
            raise AssertionError(f"{text!r} not in server.log:\n{log_of(tmp_path)}")
        time.sleep(0.02)


# ---- wording -------------------------------------------------------------------------------------


def test_close_text_and_span():
    assert close_text(1000) == "1000 normal closure"
    assert close_text(1005) == "1005 connection lost, no close frame"
    assert close_text(1011, "keepalive ping timeout") == "1011 keepalive ping timeout"
    assert close_text(4403) == "4403 removed by the relay"
    assert close_text(3999) == "3999 unknown close code"
    assert [span(s) for s in (0.42, 41.4, 754, 7530)] == ["0.4 s", "41 s", "12 min", "2 h 05 min"]


def test_throttle_counts_what_it_skips():
    throttle = Throttle()
    assert throttle("a", 60, now=1000.0) == "a"
    assert throttle("b", 60, now=1030.0) is None
    assert throttle("c", 60, now=1059.0) is None
    line = throttle("d", 60, now=1061.0)
    assert line.startswith("d (+2 not logged since ") and line.endswith(")")
    assert throttle("e", 60, now=1200.0) == "e"


# ---- close codes on disconnect --------------------------------------------------------------------


def test_v2_disconnect_logs_code_and_reason(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.ws.close(1001, "window closed")
    line = wait_for_log(tmp_path, "Client disconnected: Mira")
    assert "(1001 window closed; last message " in line and "; connected " in line


def test_v03_disconnect_logs_code(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, APPROVED)
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    coda.ws.close(1000)
    line = wait_for_log(tmp_path, "Client disconnected: Coda")
    assert "(1000 normal closure; last message " in line


@pytest.mark.parametrize("kind", ["v2", "legacy"])
def test_replaced_connection_says_the_relay_closed_it(tmp_path, stack, kind):
    """Manick, 2026-10-22: the agent reconnected while the relay still held its old connection."""
    client, _ = relay_client(stack, tmp_path, APPROVED)
    if kind == "v2":
        old = connect_v2(client, stack, "actor", "Coda", "m-coda", expect="welcome")
        connect_v2(client, stack, "actor", "Coda", "m-coda", expect="welcome")
        assert old.until("denied")["data"]["reason"] == "Reconnected from another location"
        code = 4403
    else:
        old = connect_legacy(client, stack, "actor", "Coda", "m-coda")
        connect_legacy(client, stack, "actor", "Coda", "m-coda")
        old.until("MSG|SERVER|Reconnected from another location")
        code = 1000
    wait_for_log(tmp_path, "Disconnecting old connection for 'Coda'")
    old.ws.close()
    line = wait_for_log(tmp_path, "Client disconnected: Coda")
    assert f"({code} Reconnected from another location, closed by the relay; last message " in line


# ---- uvicorn's keepalive and lost connections (a real server) ---------------------------------------


def test_protocol_class_hooks_this_uvicorn():
    """If uvicorn reshapes its WebSocket protocol, keepalive timeouts show up as 1005 again."""
    cls = protocol_class()
    assert isinstance(cls, type) and issubclass(cls, WebSocketsSansIOProtocol)


async def serve(app, **config):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           ws=protocol_class(), **config))
    task = asyncio.create_task(server.serve())
    end = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < end and not task.done(), "relay didn't start"
        await asyncio.sleep(0.01)
    return server, task, port


async def open_session(port: int, kind: str):
    """A director on /v2/ws or /ws that has been let in. The client sends no pings of its own."""
    path = "/v2/ws" if kind == "v2" else "/ws"
    ws = await connect(f"ws://127.0.0.1:{port}{path}", ping_interval=None, open_timeout=5)
    if kind == "v2":
        hello = {"role": "director", "name": "Mira", "machine_id": "m-dir", "version": "0.4.0-dev", "secret": SECRET}
        await ws.send(json.dumps({"v": 2, "id": "h", "type": "hello", "to": "server", "data": hello}))
        while json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] != "welcome":
            pass
    else:
        await ws.send(f"REGISTER|Mira|m-dir|director|{SECRET}|0.3.3|windows-x64")
        while await asyncio.wait_for(ws.recv(), 5) != "APPROVED":
            pass
    return ws


@pytest.mark.parametrize("kind", ["v2", "legacy"])
def test_relay_keepalive_timeout_is_logged_as_1011(tmp_path, kind):
    async def scenario():
        app = make_relay(tmp_path)
        server, task, port = await serve(app, ws_ping_interval=0.2, ws_ping_timeout=0.3)
        try:
            ws = await open_session(port, kind)
            ws.transport.pause_reading()  # stops answering the relay's pings, as a stalled network would
            await asyncio.to_thread(wait_for_log, tmp_path, "Client disconnected: Mira")
            ws.transport.abort()
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())
    line = wait_for_log(tmp_path, "Client disconnected: Mira")
    assert "(1011 keepalive ping timeout: the relay's ping got no pong; last message " in line


def test_cut_connection_is_logged_as_1005(tmp_path):
    async def scenario():
        app = make_relay(tmp_path)
        server, task, port = await serve(app)
        try:
            ws = await open_session(port, "v2")
            ws.transport.abort()  # TCP closed with no close frame
            await asyncio.to_thread(wait_for_log, tmp_path, "Client disconnected: Mira")
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())
    assert "(1005 connection lost, no close frame; last message " in wait_for_log(tmp_path, "Client disconnected: Mira")


# ---- the status loop: missed and slow pongs, a late loop -------------------------------------------


def test_missed_and_slow_v2_pongs(tmp_path, stack):
    clock = FakeClock(10_000)
    client, relay = relay_client(stack, tmp_path, clock=clock, health_log_every_s=0)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    session = next(iter(relay.registry))

    client.portal.call(relay.router.ping_sessions)
    ping = d.until("time.ping")
    relay._check_pong(session, time.time())
    line = wait_for_log(tmp_path, "No pong from director 'Mira' within ")
    assert ", last message " in line
    relay._check_pong(session, time.time())  # still missing: no second line for the same stall
    assert log_of(tmp_path).count("No pong from") == 1

    clock.now = 14_300
    d.send("time.pong", {"t0": 10_000, "t1": 0, "t2": 0}, reply_to=ping["id"])
    d.sync()
    assert "Director 'Mira' answered again: round trip 4300 ms, " in wait_for_log(tmp_path, "answered again")
    assert session.missed_pongs == 0

    # In time for the status, but slow
    client.portal.call(relay.router.ping_sessions)
    ping = d.until("time.ping")
    clock.now += 2_500
    d.send("time.pong", {"t0": ping["data"]["t0"], "t1": 0, "t2": 0}, reply_to=ping["id"])
    d.sync()
    relay._check_pong(session, time.time())
    assert "Slow round trip to director 'Mira': 2500 ms" in log_of(tmp_path)
    assert log_of(tmp_path).count("No pong from") == 1


def test_missed_v03_pong_and_rate_limit(tmp_path, stack):
    client, relay = relay_client(stack, tmp_path, APPROVED)
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")  # its test client never answers PING
    session = next(s for s in relay.registry if s.name == "Coda")

    client.portal.call(relay.bridge.ping_actors)
    relay._check_pong(session, time.time())
    wait_for_log(tmp_path, "No pong from actor 'Coda' within ")
    coda.send("PONG")
    coda.sync()
    assert "Actor 'Coda' answered again: round trip " in log_of(tmp_path)

    # A second stall within the minute: neither its start nor its end is logged, only counted
    client.portal.call(relay.bridge.ping_actors)
    relay._check_pong(session, time.time())
    coda.send("PONG")
    coda.sync()
    assert log_of(tmp_path).count("No pong from") == 1 and log_of(tmp_path).count("answered again") == 1
    session.health.last -= 61  # a minute later
    client.portal.call(relay.bridge.ping_actors)
    relay._check_pong(session, time.time())
    starts = [line for line in log_of(tmp_path).splitlines() if "No pong from actor 'Coda'" in line]
    assert len(starts) == 2 and "(+1 not logged since " in starts[1]


def test_late_status_loop_is_logged(tmp_path):
    relay = make_relay(tmp_path).state.relay
    relay._check_lag(0.4)
    assert "Status loop" not in log_of(tmp_path)
    relay._check_lag(3.24)
    relay._check_lag(5.0)  # within the minute: counted, not logged
    assert log_of(tmp_path).count("Status loop ran 3.2 s late: the relay itself was stalled") == 1
    assert "5.0 s late" not in log_of(tmp_path)
