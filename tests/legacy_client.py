"""Scripted v0.3 client and the golden legacy session (spec §11.5).

The golden session drives a relay's /ws endpoint the way v0.3.3 directors and actors do
(register, approve, go / stop, *play:N, OSC_CUE, batch file transfer, forget, version and
update replies, and the quirks of the v0.3 relay) and records every frame each client receives.
tests/golden/legacy_session.txt was recorded from the frozen v0.3.3 relay
(tests/legacy_relay/server_ws_v033.py); the new relay must reproduce it byte for byte.

Re-record (only when the v0.3 behaviour itself is meant to change, which it shouldn't):

    .venv/bin/python tests/legacy_client.py --record

The client is built on shared.py and the `websockets` sync client (an agent dependency, so no
extra install), rather than websocket-client as the spec suggested.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

LEGACY_RELAY = Path(__file__).resolve().parent / "legacy_relay" / "server_ws_v033.py"
GOLDEN = Path(__file__).resolve().parent / "golden" / "legacy_session.txt"

SECRET = "golden-secret"
MANIFEST = {
    "latest_version": "0.3.3",
    "release_notes": "Golden notes",
    "assets": {
        "actor-windows-x64": {"url": "https://example.invalid/actor.exe", "sha256": "aa11"},
        "director-linux-x64": {"url": "https://example.invalid/director", "sha256": "dd22"},
    },
}
CLOSED = "<closed>"
QUIET_S = 0.25  # how long an unapproved client must stay silent to count as drained
TIMEOUT_S = 5.0


# ---- relays ---------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def prepare_data_dir(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "update_manifest.json").write_text(json.dumps(MANIFEST))
    return data_dir


def load_v033_relay(data_dir: Path, secret: str = SECRET):
    """A fresh copy of the frozen v0.3.3 relay module (its state lives in module globals), with
    its files in data_dir and the 10 s status/ping loop off. Returns the module; use .app."""
    spec = importlib.util.spec_from_file_location(f"server_ws_v033_{uuid.uuid4().hex}", LEGACY_RELAY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.APPROVED_FILE = data_dir / "approved_actors.json"
    module.LOG_FILE = data_dir / "server.log"
    module.MANIFEST_FILE = data_dir / "update_manifest.json"
    module.SERVER_SECRET = secret
    module.approved_actors = module.load_approved()

    async def no_status_loop():
        pass

    module.status_broadcast_loop = no_status_loop
    return module


class RelayThread:
    """Runs an ASGI app with uvicorn on 127.0.0.1 in a background thread."""

    def __init__(self, app, port: int | None = None):
        self.port = port or free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws"

    def __enter__(self) -> "RelayThread":
        self.thread.start()
        end = time.monotonic() + TIMEOUT_S
        while not self.server.started:
            if time.monotonic() > end or not self.thread.is_alive():
                raise RuntimeError("relay didn't start")
            time.sleep(0.01)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(TIMEOUT_S)


# ---- one legacy connection --------------------------------------------------------------------


class LegacyClient:
    """One v0.3 connection. Answers PING with PONG like the real clients; PING and STATUS (which
    carries timestamps) never enter a transcript."""

    def __init__(self, url: str, label: str, name: str):
        self.ws = connect(url, open_timeout=TIMEOUT_S, max_size=2**24)
        self.label = label
        self.name = name
        self.approved = False
        self.closed = False

    def send(self, text: str) -> None:
        try:
            self.ws.send(text)
        except ConnectionClosed:
            pass  # the relay closed us; the next recv() reports it

    def recv(self, timeout: float) -> str:
        """Next frame (CLOSED once the relay closed us). Raises TimeoutError."""
        if self.closed:
            raise TimeoutError
        while True:
            try:
                frame = self.ws.recv(timeout=timeout)
            except ConnectionClosed:
                self.closed = True
                return CLOSED
            if isinstance(frame, bytes):
                frame = frame.decode("utf-8", errors="replace")
            if frame == "PING":
                self.ws.send("PONG")
                continue
            if frame.startswith("STATUS|"):
                continue
            if frame == "APPROVED":
                self.approved = True
            return frame

    def read_all(self, prefixes: list[str], timeout: float = TIMEOUT_S) -> list[str]:
        """Read until a frame starting with each prefix was seen, in any order (a prefix listed
        twice needs two frames)."""
        remaining = list(prefixes)

        def done(frame: str) -> bool:
            for i, prefix in enumerate(remaining):
                if frame.startswith(prefix):
                    del remaining[i]
                    break
            return not remaining

        return self.read_until(done, timeout) if remaining else []

    def read_until(self, done: Callable[[str], bool], timeout: float = TIMEOUT_S) -> list[str]:
        frames: list[str] = []
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError(f"{self.label}: timed out; got {frames}")
            frame = self.recv(left)
            frames.append(frame)
            if done(frame) or frame == CLOSED:
                return frames

    def drain(self, quiet: float = QUIET_S) -> list[str]:
        frames: list[str] = []
        while True:
            try:
                frame = self.recv(quiet)
            except TimeoutError:
                return frames
            frames.append(frame)
            if frame == CLOSED:
                return frames

    def close(self) -> None:
        self.closed = True
        self.ws.close()


# ---- recorded session -------------------------------------------------------------------------


class Session:
    """Runs steps one at a time and records, per step, what each client received.

    After each step a marker MSG is broadcast and every approved client is read up to it. The
    relay handles one connection's frames in order, so the marker comes from the step's sender
    when that sender is approved; otherwise the sender is probed (REFRESH → DENIED|Not approved)
    and the stagehand (the first director) sends the marker. Unapproved clients are read until
    they stay quiet, after the approved ones, so everything due to them was already sent.
    """

    def __init__(self, url: str):
        self.url = url
        self.clients: dict[str, LegacyClient] = {}
        self.lines: list[str] = []
        self.stagehand: LegacyClient | None = None
        self._markers = 0

    def connect(self, label: str, name: str) -> LegacyClient:
        client = LegacyClient(self.url, label, name)
        self.clients[label] = client
        return client

    def register(self, label: str, name: str, machine_id: str, role: str, secret: str = "", version: str | None = None,
                 platform: str = "windows-x64", expect: dict[str, list[str]] | None = None, unordered: bool = False) -> None:
        if label not in self.clients or self.clients[label].closed:
            self.connect(label, name)
        fields = [name, machine_id, role, secret]
        if version is not None:
            fields += [version, platform]
        self.step(label, "REGISTER|" + "|".join(fields), expect=expect, unordered=unordered)

    def step(self, label: str, text: str, expect: dict[str, list[str]] | None = None, unordered: bool = False) -> None:
        """Send one frame. `expect` lists, per client, frame prefixes to wait for before the
        marker: needed for the register reply and for what the relay sends from background tasks
        (a closed connection's USERS / "left"), which a marker can overtake."""
        sender = self.clients[label]
        self.lines.append(f"## {label} → {text}")
        sender.send(text)
        self._settle(sender, expect or {}, unordered)

    def close(self, label: str, expect: dict[str, list[str]] | None = None) -> None:
        self.lines.append(f"## {label} closes")
        self.clients[label].close()
        self._settle(None, expect or {}, unordered=True)

    def _settle(self, sender: LegacyClient | None, expect: dict[str, list[str]], unordered: bool) -> None:
        got: dict[str, list[str]] = {label: [] for label in self.clients}
        for label, prefixes in expect.items():
            got[label] += self.clients[label].read_all(prefixes)
        if sender is not None and not sender.closed and sender.approved:
            marker_from = sender
        else:
            if sender is not None and not sender.closed:
                sender.send("REFRESH")
                got[sender.label] += sender.read_until(lambda f: f == "DENIED|Not approved")
            marker_from = self.stagehand
        if self.stagehand is None and sender is not None and sender.approved:
            self.stagehand = sender
        if marker_from is not None and not marker_from.closed:
            self._markers += 1
            marker = f"MSG|{marker_from.name}|~sync {self._markers}"
            marker_from.send(marker)
            for client in self.clients.values():
                if client.approved and not client.closed:
                    got[client.label] += client.read_until(lambda f: f == marker)
        for client in self.clients.values():
            if not client.closed and not (client.approved and marker_from is not None):
                got[client.label] += client.drain()
        for label, frames in got.items():
            for frame in sorted(frames) if unordered else frames:
                self.lines.append(f"{label:<6} ← {frame}")

    def transcript(self) -> str:
        return "\n".join(self.lines) + "\n"

    def close_all(self) -> None:
        for client in self.clients.values():
            if not client.closed:
                client.close()


def golden_session(url: str) -> str:
    """The v0.3.3 behaviour every /ws client relies on. Returns the transcript."""
    s = Session(url)
    try:
        _golden_steps(s)
    finally:
        s.close_all()
    return s.transcript()


def _golden_steps(s: Session) -> None:
    # Directors: secret auth, version + update replies, multi-director warnings
    s.register("dir", "Mira", "m-dir", "director", SECRET, "0.3.3", expect={"dir": ["PENDING|"]})
    s.register("bad", "Nope", "m-bad", "director", "wrong-secret", "0.3.3", expect={"bad": ["DENIED|"]})

    # New actors wait for approval; the director approves or denies them
    s.register("coda", "Coda", "m-coda", "actor", "", "0.3.2", expect={"coda": ["DENIED|"], "dir": ["PENDING|"]})
    s.step("coda", "MSG|Coda|anyone there?")
    s.step("dir", "APPROVE|m-coda")
    s.register("ari", "Ari", "m-ari", "actor", "", "0.3.3", expect={"ari": ["DENIED|"], "dir": ["PENDING|"]})
    s.step("dir", "APPROVE|m-ari")
    s.register("old", "Oldie", "m-old", "actor", "", None, expect={"old": ["DENIED|"], "dir": ["PENDING|"]})
    s.step("dir", "APPROVE|m-old")
    s.register("eve", "Eve", "m-eve", "actor", "", "0.3.3", expect={"eve": ["DENIED|"], "dir": ["PENDING|"]})
    s.step("dir", "DENY|m-eve")
    s.step("dir", "APPROVE|m-unknown")

    # Cues
    s.step("dir", "CMD|go")
    s.step("dir", "CMD|stop|extra")
    s.step("dir", "PRIV|Mira|Coda|*go")
    s.step("dir", "PRIV|Mira|Coda|*stop")
    s.step("dir", "PRIV|Mira|Ari|*play:3")
    s.step("dir", "PRIV|Mira|Nobody|*go")
    s.step("coda", "ACK|Coda|*go|OK")
    s.step("dir", "OSC_CUE|Coda|RecIcon|true")
    s.step("dir", "OSC_CUE|Nobody|RecIcon|true")

    # Only directors may cue or push files; approval messages from actors are ignored
    s.step("coda", "CMD|go")
    s.step("coda", "PRIV|Coda|Ari|*go")
    s.step("coda", "OSC_CUE|Ari|Wave|1")
    s.step("coda", "FILEREQ|Coda|Ari|evil.exe|4|00")
    s.step("coda", "APPROVE|m-x")
    s.step("coda", "FORGET_NAME|Ari")

    # Chat
    s.step("coda", "MSG|Coda|line?")
    s.step("dir", "MSG|Mira|Places ¡Acción! 🎬 a|b")
    s.step("coda", "PRIV|Coda|Mira|need a minute")
    s.step("ari", "PRIV|Ari|Coda|hi *wave*")
    s.step("coda", "FILECHUNK|x.wav|notanumber|zz")

    # Batch file transfer: one file accepted, one declined
    s.step("dir", "BATCH_START|Coda|2|10")
    s.step("dir", "FILEREQ|Mira|Coda|line1.wav|4|3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7")
    s.step("coda", "FILEACK|line1.wav|1|C:/cues")
    s.step("dir", "FILESTART|line1.wav|1|65536")
    s.step("dir", "FILECHUNK|line1.wav|0|ZGF0YQ==")
    s.step("dir", "FILEEND|line1.wav|3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7")
    s.step("coda", "FILEOK|line1.wav|C:/cues/line1.wav")
    s.step("dir", "FILEREQ|Mira|Coda|line2.wav|6|00ff")
    s.step("coda", "FILEDENY|line2.wav|Declined by actor")
    s.step("dir", "BATCH_END|Coda|1|1")
    s.step("coda", "FILEACK|line2.wav|1|C:/cues")
    # A cancelled batch; the actor reports the abandoned file
    s.step("dir", "BATCH_START|Ari|1|4")
    s.step("dir", "FILEREQ|Mira|Ari|sfx.wav|4|00")
    s.step("dir", "BATCH_CANCEL|Ari|Cancelled by director")
    s.step("ari", "FILEERR|sfx.wav|Cancelled")
    s.step("dir", "FILEREQ|Mira|Nobody|ghost.wav|4|00")

    # Second director (older, so it's offered an update) and REFRESH
    s.register("dir2", "Bo", "m-dir2", "director", SECRET, "0.3.2", platform="linux-x64", expect={"dir2": ["PENDING|"]})
    s.step("dir", "REFRESH")
    s.step("coda", "REFRESH")

    # A known actor reconnecting from another socket replaces the old one
    # The old connection's own cleanup then says "Coda left" (a v0.3 quirk), from a background
    # task, so its order against the new connection's frames isn't fixed.
    joined_left = ["MSG|SERVER|Coda joined", "USERS|", "USERS|", "MSG|SERVER|Coda left"]
    s.register("coda2", "Coda", "m-coda", "actor", "", "0.3.2", unordered=True, expect={
        "coda2": ["APPROVED", "VERSION|", "UPDATE|"] + joined_left,
        "coda": ["MSG|SERVER|Reconnected from another location", "<closed>"],
        "dir": joined_left, "ari": joined_left, "old": joined_left, "dir2": joined_left,
    })
    s.step("dir", "PRIV|Mira|Coda|*go")

    # Forget: the actor is told, drops off USERS and must be approved again
    s.step("dir", "FORGET_NAME|Ari")
    # A forgotten actor stays connected (and receives broadcasts) until it hangs up itself
    left = ["USERS|", "MSG|SERVER|Ari left"]
    s.close("ari", expect={"dir": left, "coda2": left, "old": left, "dir2": left})
    s.register("ari2", "Ari", "m-ari", "actor", "", "0.3.3", expect={"ari2": ["DENIED|"]})
    s.step("dir", "APPROVE|m-ari")
    s.step("dir", "FORGET_NAME|Nobody")

    # Leaving
    left = ["USERS|", "MSG|SERVER|Oldie left"]
    s.close("old", expect={"dir": left, "coda2": left, "ari2": left, "dir2": left})
    s.close("dir2")
    s.step("dir", "MSG|Mira|wrap")


def main(argv: list[str]) -> int:
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record", action="store_true", help=f"record {GOLDEN.relative_to(ROOT)} from the frozen v0.3.3 relay")
    parser.add_argument("--url", help="run the session against a running relay's /ws URL and print the transcript")
    args = parser.parse_args(argv)
    if args.url:
        print(golden_session(args.url), end="")
        return 0
    if not args.record:
        parser.print_help()
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        module = load_v033_relay(prepare_data_dir(Path(tmp)))
        with RelayThread(module.app) as relay:
            transcript = golden_session(relay.url)
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(transcript, encoding="utf-8")
    print(f"Wrote {GOLDEN} ({transcript.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
