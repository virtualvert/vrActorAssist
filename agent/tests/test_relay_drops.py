"""Why the agent lost the relay, in agent.log: close codes on a dropped connection, the exception of
every failed attempt to reconnect, and the keepalive both sides use."""

import asyncio
import logging

from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from agent.relay import error_text, span
from agent.relay_legacy import connect_kwargs

from .test_relay_legacy import SECRET, legacy_harness, make_agent, wait_for


def test_error_text():
    assert error_text(ConnectionClosedError(None, Close(1011, "keepalive ping timeout"))) == (
        "sent 1011 (internal error) keepalive ping timeout; no close frame received")
    assert error_text(ConnectionClosedError(Close(1012, ""), Close(1012, ""), True)) == (
        "received 1012 (service restart); then sent 1012 (service restart)")
    assert error_text(ConnectionClosedError(None, None)) == "no close frame received or sent"
    assert error_text(TimeoutError()) == "TimeoutError"
    assert error_text(TimeoutError("timed out during opening handshake")) == "TimeoutError: timed out during opening handshake"
    assert error_text(ConnectionRefusedError(111, "Connect call failed")) == "ConnectionRefusedError: [Errno 111] Connect call failed"
    assert error_text(InvalidStatus(Response(502, "Bad Gateway", {}))) == (
        "InvalidStatus: server rejected WebSocket connection: HTTP 502")
    assert [span(s) for s in (0.42, 41.4, 754, 7530)] == ["0.4 s", "41 s", "12 min", "2 h 05 min"]


def test_keepalive_tolerates_a_30_s_stall():
    kwargs = connect_kwargs("wss://relay.example/v2/ws")
    assert (kwargs["ping_interval"], kwargs["ping_timeout"]) == (30, 30)


def test_drop_and_failed_reconnects_are_logged(tmp_path, monkeypatch, caplog):
    """The relay goes away (it restarts: 1012) and doesn't come back for a while."""
    from server.app import create_app
    from server.settings import Settings

    (tmp_path / "relay").mkdir()
    (tmp_path / "relay" / "approved_actors.json").write_text('{"m-coda": {"name": "Coda"}}')
    app = create_app(Settings(secret=SECRET, data_dir=tmp_path / "relay", status_interval_s=None, echo_log=False))
    running = legacy_harness().RelayThread(app).__enter__()
    host = f"127.0.0.1:{running.port}"

    async def scenario():
        actor = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", host)
        try:
            await actor.start()
            await wait_for(lambda: actor.relay.status == "connected")
            await asyncio.to_thread(running.__exit__, None, None, None)
            await wait_for(lambda: any("Relay connection failed (attempt 2)" in e["text"] for e in actor.hub._logs), timeout=10)
            return [e["text"] for e in actor.hub._logs if e["level"] == "warning"]
        finally:
            await actor.relay.stop()

    with caplog.at_level(logging.INFO, logger="vrcas"):
        warnings = asyncio.run(scenario())
    drop = next(t for t in warnings if t.startswith("Lost connection"))
    assert drop.startswith(f"Lost connection to {host}: received 1012 (service restart)")
    assert "; connected " in drop and "; last message from the relay " in drop and drop.endswith(". Retrying in 1 s.")
    failed = [t for t in warnings if t.startswith("Relay connection failed")]
    assert failed[0].startswith("Relay connection failed: ConnectionRefusedError: ") and failed[0].endswith("Retrying in 2 s.")
    assert failed[1].startswith("Relay connection failed (attempt 2): ConnectionRefusedError: ") and failed[1].endswith("Retrying in 4 s.")
    # hub.log writes to the "vrcas" logger, which __main__.setup_logging sends to agent.log
    assert drop in caplog.text and failed[1] in caplog.text
