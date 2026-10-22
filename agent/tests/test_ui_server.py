"""Quitting with a UI socket open (Ctrl-C, or the desktop window closing) is quiet.

The UI server runs as the desktop window runs it: uvicorn in a "ui-server" thread. Nothing may
be raised in that thread or logged at error level, and the agent's own shutdown must still run.
"""

import asyncio
import logging
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from websockets.client import ClientProtocol
from websockets.protocol import State
from websockets.uri import parse_uri

from agent.__main__ import ui_server
from agent.config import ConfigStore
from agent.core import Agent
from agent.web import COOKIE, Security, create_app


def wait_for(condition, what: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.01)


class UISocket:
    """A page's /ui/ws over a plain socket, so the test decides when the page reads."""

    def __init__(self, port: int, cookie: str):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.sock.settimeout(5)
        self.sock.connect(("127.0.0.1", port))
        self.ws = ClientProtocol(parse_uri(f"ws://127.0.0.1:{port}/ui/ws"))
        request = self.ws.connect()
        request.headers["Origin"] = f"http://127.0.0.1:{port}"
        request.headers["Cookie"] = f"{COOKIE}={cookie}"
        self.ws.send_request(request)
        self.flush()
        while self.ws.state is State.CONNECTING:
            self.ws.receive_data(self.sock.recv(256))  # the handshake answer, and little more

    def flush(self) -> None:
        self.sock.sendall(b"".join(self.ws.data_to_send()))

    def close(self, code: int = 1001) -> None:
        self.ws.send_close(code)
        self.flush()

    def read_until_closed(self) -> None:
        with self.sock:
            while data := self.sock.recv(65536):
                self.ws.receive_data(data)
        self.ws.receive_eof()


@pytest.fixture
def ui(tmp_path, caplog, monkeypatch):
    raised: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: raised.append(args.exc_value))

    listener = socket.socket()
    # Accepted sockets inherit it: a small send buffer lets a page that stops reading hold up our writes.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    security = Security(port)
    agent = Agent(ConfigStore(tmp_path))
    server = ui_server(create_app(agent, security, tmp_path / "no-web-build"), port)

    # uvicorn's loggers don't propagate to the root logger, where caplog listens.
    caplog.set_level(logging.INFO)
    uvicorn_log = logging.getLogger("uvicorn")
    uvicorn_log.addHandler(caplog.handler)

    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[listener])), name="ui-server", daemon=True)
    thread.start()
    wait_for(lambda: server.started or not thread.is_alive(), "the UI server")
    assert server.started

    def login() -> str:
        origin = f"http://127.0.0.1:{port}"
        res = httpx.post(f"{origin}/api/session", json={"token": security.new_open_token()}, headers={"Origin": origin})
        return res.cookies[COOKIE]

    def quit_and_wait(page: UISocket) -> None:
        server.should_exit = True  # what Ctrl-C (or the window's `closed` callback) does
        wait_for(lambda: not server.servers[0].is_serving() or not thread.is_alive(), "the shutdown to start")
        try:
            page.read_until_closed()
        finally:
            thread.join(10)
            assert raised == []  # a server that died leaves the page waiting: report why
        assert not thread.is_alive()

    def assert_quiet() -> None:
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
        # the lifespan shutdown ran: Agent.shutdown() logs this first
        assert any("Closing vrcActorSync" in r.getMessage() for r in caplog.records)

    yield SimpleNamespace(agent=agent, server=server, port=port, login=login, quit_and_wait=quit_and_wait, assert_quiet=assert_quiet)

    uvicorn_log.removeHandler(caplog.handler)
    if thread.is_alive():
        server.should_exit = server.force_exit = True
        thread.join(5)
    listener.close()


def test_quitting_with_a_ui_socket_open_is_quiet(ui):
    page = UISocket(ui.port, ui.login())
    wait_for(lambda: ui.agent.hub._clients, "the UI socket to join the hub")

    ui.quit_and_wait(page)

    assert page.ws.close_rcvd is not None and page.ws.close_rcvd.code == 1012  # uvicorn's "service restart"
    ui.assert_quiet()


def test_quitting_just_as_the_ui_closes_is_quiet(ui):
    """The page's close frame is in but its connection isn't gone when the server shuts down.

    On Windows the gap is the proactor sending our close reply; here the page stops reading, so the
    reply waits behind earlier events. uvicorn's shutdown used to send a second close frame:
    InvalidState ("connection is closing") ended the ui-server thread and skipped the agent's shutdown.
    """
    page = UISocket(ui.port, ui.login())
    wait_for(lambda: ui.agent.hub._clients, "the UI socket to join the hub")
    (connection,) = ui.server.server_state.connections
    loop = ui.server.servers[0].get_loop()
    for _ in range(40):  # events the page doesn't read
        loop.call_soon_threadsafe(ui.agent.hub.event, {"type": "filler", "data": "x" * 50_000})
    wait_for(lambda: connection.transport.get_write_buffer_size() > 0, "our writes to back up")

    page.close()
    wait_for(lambda: not ui.agent.hub._clients, "the UI socket's handler to see the close")
    assert ui.server.server_state.connections == {connection}  # closing, not gone

    ui.quit_and_wait(page)

    ui.assert_quiet()
