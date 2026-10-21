"""Helpers for relay tests: an in-process relay, v2 and v0.3 test clients, a fake clock."""

from __future__ import annotations

import asyncio
import itertools
import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient

from server.app import create_app
from server.settings import Settings
from server.timesync import Clock

SECRET = "test-secret"
_ids = itertools.count()


class FakeClock(Clock):
    """Server time that only moves when a test says so."""

    def __init__(self, now: int = 1_800_000_000_000):
        self.now = now
        self._waiters: list[tuple[int, asyncio.Future]] = []

    def now_ms(self) -> int:
        return self.now

    async def sleep_until(self, ms: int) -> None:
        if ms <= self.now:
            return
        future = asyncio.get_running_loop().create_future()
        self._waiters.append((ms, future))
        await future

    async def advance(self, ms: int) -> None:
        self.now += ms
        due = [(t, f) for t, f in self._waiters if t <= self.now]
        self._waiters = [(t, f) for t, f in self._waiters if t > self.now]
        for _, future in sorted(due, key=lambda w: w[0]):
            if not future.done():
                future.set_result(None)
        for _ in range(5):  # let the woken tasks run
            await asyncio.sleep(0)

    @property
    def waiting(self) -> list[int]:
        return sorted(t for t, f in self._waiters if not f.done())


def make_relay(tmp_path: Path, approved: dict | None = None, manifest: dict | None = None,
               clock: Clock | None = None, **settings: Any):
    if approved is not None:
        (tmp_path / "approved_actors.json").write_text(json.dumps(approved))
    if manifest is not None:
        (tmp_path / "update_manifest.json").write_text(json.dumps(manifest))
    options = dict(secret=SECRET, data_dir=tmp_path, status_interval_s=None, echo_log=False)
    options.update(settings)
    return create_app(Settings(**options), clock=clock)


class V2:
    """A /v2/ws client on a TestClient connection."""

    def __init__(self, ws, label: str):
        self.ws = ws
        self.label = label
        self.session_id: str | None = None
        self.seen: list[dict] = []

    def send(self, msg_type: str, data: dict | None = None, to: Any = "server", **extra: Any) -> str:
        msg_id = f"{self.label}-{next(_ids)}"
        env = {"v": 2, "id": msg_id, "type": msg_type, "to": to, "data": data or {}}
        env.update(extra)
        self.ws.send_text(json.dumps(env))
        return msg_id

    def recv(self) -> dict:
        env = json.loads(self.ws.receive_text())
        self.seen.append(env)
        return env

    def until(self, match: str | Callable[[dict], bool]) -> dict:
        """Read until a message matches (a type, or a predicate). Returns it; skipped ones are in .seen."""
        test = (lambda e: e["type"] == match) if isinstance(match, str) else match
        while True:
            env = self.recv()
            if test(env):
                return env

    def collect_until(self, match: str | Callable[[dict], bool]) -> list[dict]:
        start = len(self.seen)
        self.until(match)
        return self.seen[start:]

    def sync(self) -> list[dict]:
        """Everything the relay sent us before it answered a time.ping we send now."""
        ping = self.send("time.ping", {"t0": 0})
        return self.collect_until(lambda e: e["type"] == "time.pong" and e.get("reply_to") == ping)

    def roster(self) -> dict:
        return self.until("presence.roster")["data"]

    def next_chunk(self) -> bytes:
        """The next binary frame (a file chunk); envelopes on the way are kept in .seen."""
        while True:
            message = self.ws.receive()
            if message.get("bytes") is not None:
                return message["bytes"]
            if message.get("text") is not None:
                self.seen.append(json.loads(message["text"]))


def connect_v2(client: TestClient, stack: ExitStack, role: str, name: str, machine_id: str, *, secret: str | None = None,
               version: str = "0.4.0-dev", platform: str = "windows-x64", capabilities: list[str] | None = None,
               expect: str | None = "auto") -> V2:
    ws = stack.enter_context(client.websocket_connect("/v2/ws"))
    c = V2(ws, name)
    hello = {"role": role, "name": name, "machine_id": machine_id, "version": version, "platform": platform,
             "capabilities": capabilities or []}
    if role in ("director", "assistant"):
        hello["secret"] = SECRET if secret is None else secret
    c.send("hello", hello)
    if expect == "auto":
        expect = "welcome" if role in ("director", "assistant") else None
    if expect:
        env = c.until(expect)
        if expect == "welcome":
            c.session_id = env["data"]["session_id"]
    return c


class Legacy:
    """A /ws client on a TestClient connection (PING/STATUS frames are skipped)."""

    def __init__(self, ws, name: str):
        self.ws = ws
        self.name = name
        self.seen: list[str] = []
        self._marks = itertools.count()

    def send(self, text: str) -> None:
        self.ws.send_text(text)

    def recv(self) -> str:
        while True:
            text = self.ws.receive_text()
            if text != "PING" and not text.startswith("STATUS|"):
                self.seen.append(text)
                return text

    def until(self, prefix: str) -> str:
        while True:
            text = self.recv()
            if text.startswith(prefix):
                return text

    def collect_until(self, prefix: str) -> list[str]:
        start = len(self.seen)
        self.until(prefix)
        return self.seen[start:]

    def sync(self) -> list[str]:
        """What arrived before a marker chat line we send now (approved clients only)."""
        marker = f"MSG|{self.name}|~mark {next(self._marks)}"
        self.send(marker)
        return self.collect_until(marker)


def connect_legacy(client: TestClient, stack: ExitStack, role: str, name: str, machine_id: str, *,
                   secret: str = "", version: str = "0.3.3", platform: str = "windows-x64", expect: str | None = "auto") -> Legacy:
    ws = stack.enter_context(client.websocket_connect("/ws"))
    c = Legacy(ws, name)
    if role == "director" and not secret:
        secret = SECRET
    c.send(f"REGISTER|{name}|{machine_id}|{role}|{secret}|{version}|{platform}")
    if expect == "auto":
        expect = "PENDING|" if role == "director" else "USERS|"
    if expect:
        c.until(expect)
    return c
