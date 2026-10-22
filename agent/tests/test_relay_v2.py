"""End to end on the v2 relay: v2 director, actor and camera agents with a scripted v0.3
director and v0.3 actor in the same session (spec §11.3)."""

import asyncio
import json
import time

import pytest

from agent.relay_legacy import ws_url
from agent.relay_v2 import cue_command, v2_url

from .test_relay_legacy import SECRET, legacy_harness, make_agent, wait_for


def test_v2_url():
    assert v2_url(ws_url("relay.example:5555")) == "ws://relay.example:5555/v2/ws"
    assert v2_url(ws_url("https://relay.example/")) == "wss://relay.example/v2/ws"
    assert v2_url(ws_url("ws://host/prefix")) == "ws://host/prefix/v2/ws"


@pytest.mark.parametrize("msg_type, data, command", [
    ("cue.go", {}, "*go"),
    ("cue.stop", {"at": 5}, "*stop"),
    ("cue.play", {"index": 3}, "*play:3"),
    ("soundpad.play", {"sound": {"selected": True}}, "*go"),
    ("soundpad.play", {"sound": {"index": 7}}, "*play:7"),
    ("soundpad.play", {"sound": {"path": "C:\\a.mp3"}}, None),
    ("soundpad.stop", {}, "*stop"),
])
def test_cue_command(msg_type, data, command):
    assert cue_command(msg_type, data) == command


@pytest.fixture
def relay(tmp_path):
    """The new relay in its own thread (so the scripted v0.3 clients may block)."""
    from server.app import create_app
    from server.settings import Settings

    harness = legacy_harness()
    app = create_app(Settings(secret=SECRET, data_dir=tmp_path / "relay", status_interval_s=None, echo_log=False))
    (tmp_path / "relay").mkdir()
    with harness.RelayThread(app) as running:
        yield running, app.state.relay


def legacy_client(url, label, name):
    return legacy_harness().LegacyClient(url, label, name)


async def read_until(client, prefix, timeout=5.0):
    """A scripted v0.3 client's frames up to one starting with prefix (read off the event loop)."""
    return await asyncio.to_thread(client.read_until, lambda f: f.startswith(prefix), timeout)


def peer(agent, name):
    return next((p for p in agent.snapshot()["peers"] if p["name"] == name), None)


def logged(agent, text):
    return any(text in e["text"] for e in agent.hub._logs)


def test_mixed_session(relay, tmp_path, monkeypatch):
    running, state = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        actor = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", url)
        camera = make_agent(tmp_path, monkeypatch, "Cam", "camera", "m-cam", url)
        old_dir = old_actor = None
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "connected")
            conn = director.snapshot()["connection"]
            assert conn["legacy"] is False and conn["serverVersion"] == "0.4.0-dev"

            # A v0.3 director joins too
            old_dir = legacy_client(running.url, "old", "Old")
            old_dir.send(f"REGISTER|Old|m-old|director|{SECRET}|0.3.3|windows-x64")
            got = await read_until(old_dir, "PENDING|")
            assert "MSG|SERVER|⚠ Warning: Mira is already connected" in got
            await wait_for(lambda: peer(director, "Old") is not None)
            assert peer(director, "Old")["role"] == "director"

            # v2 actor and camera wait for approval; the v2 director approves both
            await actor.start()
            await camera.start()
            await wait_for(lambda: actor.relay.status == "pending" and camera.relay.status == "pending")
            await wait_for(lambda: len(director.snapshot()["pending"]) == 2)
            for p in list(director.snapshot()["pending"]):
                await director.handle_call("approve", {"id": p["id"]})
            await wait_for(lambda: actor.relay.status == "connected" and camera.relay.status == "connected")

            # A v0.3 actor joins and is approved from the v2 director
            old_actor = legacy_client(running.url, "lex", "Lex")
            old_actor.send("REGISTER|Lex|m-lex|actor||0.3.3|windows-x64")
            assert (await read_until(old_actor, "DENIED|"))[-1] == "DENIED|Pending approval"
            await wait_for(lambda: [p["name"] for p in director.snapshot()["pending"]] == ["Lex"])
            await director.handle_call("approve", {"id": director.snapshot()["pending"][0]["id"]})
            assert (await read_until(old_actor, "USERS|"))[:2] == ["APPROVED", "VERSION|ok|0.3.3|"]

            # Who sees whom: the v2 director sees everyone, cameras included...
            await wait_for(lambda: all(peer(director, n) for n in ("Old", "Coda", "Cam", "Lex")))
            assert {p["name"]: p["role"] for p in director.snapshot()["peers"] if not p["self"]} == {
                "Old": "director", "Coda": "actor", "Cam": "camera", "Lex": "actor"}
            assert sorted(director.snapshot()["targets"]) == sorted([peer(director, "Coda")["id"], peer(director, "Lex")["id"]])
            await wait_for(lambda: peer(camera, "Mira") is not None and peer(actor, "Lex") is not None)
            # ...the v0.3 director sees the actors but never the camera
            earlier = await asyncio.to_thread(old_dir.drain)
            old_dir.send("REFRESH")
            refreshed = await read_until(old_dir, "PENDING|")
            assert refreshed == ["USERS|Coda,Lex", "PENDING|[]"]
            assert not any("Cam" in f for f in got + earlier + refreshed)

            # Go and Stop reach both kinds of actor
            await director.handle_call("cue", {"command": "go"})
            await wait_for(lambda: actor.last_cue is not None)
            assert actor.last_cue["command"] == "*go" and actor.last_cue["ok"]
            assert (await read_until(old_actor, "PRIV|"))[-1] == "PRIV|Mira|Lex|*go"
            old_actor.send("ACK|Lex|*go|OK")
            await director.handle_call("cue", {"command": "stop"})
            await wait_for(lambda: actor.last_cue["command"] == "*stop")
            assert (await read_until(old_actor, "PRIV|"))[-1] == "PRIV|Mira|Lex|*stop"

            # Play in 3s: a local countdown, then Go
            actor.last_cue = None
            started = time.monotonic()
            await director.handle_call("cue", {"command": "countdown"})
            assert director.snapshot()["countdown"]["durationMs"] == 3000
            await wait_for(lambda: actor.last_cue is not None, timeout=6)
            assert time.monotonic() - started >= 2.9 and actor.last_cue["command"] == "*go"
            assert (await read_until(old_actor, "PRIV|", timeout=6))[-1] == "PRIV|Mira|Lex|*go"

            # Chat both ways
            await director.handle_call("sendChat", {"text": "Places, everyone"})
            assert (await read_until(old_actor, "MSG|Mira|"))[-1] == "MSG|Mira|Places, everyone"
            await wait_for(lambda: logged(actor, "Places, everyone"))
            old_dir.send("MSG|Old|From the booth")
            await wait_for(lambda: logged(director, "From the booth") and logged(camera, "From the booth"))

            # The v0.3 director cues the v2 actor by name: *play:N and an OSC parameter
            old_dir.send("PRIV|Old|Coda|*play:3")
            await wait_for(lambda: actor.last_cue and actor.last_cue["command"] == "*play:3")
            old_dir.send("OSC_CUE|Coda|RecIcon|true")
            await wait_for(lambda: logged(actor, "/avatar/parameters/RecIcon ← True"))

            # v0.3 ↔ v0.3 file transfer still works through the new relay
            sha = "3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7"
            old_dir.send("BATCH_START|Lex|1|4")
            old_dir.send(f"FILEREQ|Old|Lex|line.wav|4|{sha}")
            got = await read_until(old_actor, "FILEREQ|")
            assert "BATCH_START|Lex|1|4" in got
            old_actor.send("FILEACK|line.wav|1|C:/cues")
            assert (await read_until(old_dir, "FILEACK|"))[-1] == "FILEACK|line.wav|1|C:/cues"
            for frame in ("FILESTART|line.wav|1|65536", "FILECHUNK|line.wav|0|ZGF0YQ==", f"FILEEND|line.wav|{sha}"):
                old_dir.send(frame)
                assert (await read_until(old_actor, frame.split("|")[0]))[-1] == frame
            old_actor.send("FILEOK|line.wav|C:/cues/line.wav")
            assert (await read_until(old_dir, "FILEOK|"))[-1] == "FILEOK|line.wav|C:/cues/line.wav"
            old_dir.send("BATCH_END|Lex|1|0")
            assert (await read_until(old_actor, "BATCH_END|"))[-1] == "BATCH_END|Lex|1|0"
            assert state.transfers == {}

            # Only directors cue: the actor's agent refuses, and a hand-made cue from the
            # actor's connection is rejected by the relay
            with pytest.raises(Exception):
                await actor.handle_call("cue", {"command": "go"})
            await actor.relay.v2._send("cue.go", {}, to={"ids": [peer(actor, "Lex")["id"]]})
            await wait_for(lambda: logged(actor, "can't send cue.go"))

            # Forgetting the v2 actor ends its session until it asks again
            await director.handle_call("forget", {"id": peer(director, "Coda")["id"]})
            await wait_for(lambda: actor.relay.status == "error")
            assert "director" in actor.relay.detail.lower()
            await wait_for(lambda: peer(director, "Coda") is None)
            assert "m-coda" not in json.loads((tmp_path / "relay" / "approved_actors.json").read_text())
        finally:
            for c in (old_dir, old_actor):
                if c is not None:
                    c.close()
            for agent in (camera, actor, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_wrong_secret_on_v2(relay, tmp_path, monkeypatch):
    running, _ = relay

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m1", f"127.0.0.1:{running.port}", "wrong")
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "error")
            assert director.relay.detail == "Wrong director secret"
            assert director.snapshot()["connection"]["legacy"] is False
            await asyncio.sleep(1.5)
            assert director.relay.status == "error"  # no reconnect loop
        finally:
            await director.shutdown()

    asyncio.run(scenario())


def test_reconnects_after_relay_restart(tmp_path, monkeypatch):
    """The agent keeps retrying with backoff and comes back on v2 when the relay returns."""
    from server.app import create_app
    from server.settings import Settings

    harness = legacy_harness()
    port = harness.free_port()
    settings = Settings(secret=SECRET, data_dir=tmp_path, status_interval_s=None, echo_log=False)

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m1", f"127.0.0.1:{port}", SECRET)
        try:
            with harness.RelayThread(create_app(settings), port=port):
                await director.start()
                await wait_for(lambda: director.relay.status == "connected")
            await wait_for(lambda: director.relay.status == "connecting")
            with harness.RelayThread(create_app(settings), port=port):
                await wait_for(lambda: director.relay.status == "connected", timeout=8)
                assert director.snapshot()["connection"]["legacy"] is False
        finally:
            await director.shutdown()

    asyncio.run(scenario())


def test_a_slow_cue_doesnt_hold_up_the_connection(relay, tmp_path, monkeypatch):
    """Cues run in order but off the receive loop: while Soundpad takes its time, chat (and the
    relay's pings) still get through (laptop run, M2 finding B)."""
    running, _ = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        actor = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", url)
        ran: list[tuple[str, float]] = []

        async def slow_cue(command):
            if command == "*go":
                await asyncio.sleep(1.5)
            ran.append((command, time.monotonic()))
            return True, None

        try:
            await director.start()
            await actor.start()
            await wait_for(lambda: director.snapshot()["pending"])
            await director.handle_call("approve", {"id": director.snapshot()["pending"][0]["id"]})
            await wait_for(lambda: actor.relay.status == "connected" and director.snapshot()["targets"])
            monkeypatch.setattr(actor.actor, "run_cue", slow_cue)
            director.config.director.lead_ms = 0  # GO at once: this is about the queue, not scheduling

            sent = time.monotonic()
            await director.handle_call("cue", {"command": "go"})
            await director.handle_call("cue", {"command": "stop"})
            await director.handle_call("sendChat", {"text": "Still with us?"})
            await wait_for(lambda: logged(actor, "Still with us?"))
            assert time.monotonic() - sent < 1.0 and ran == []  # the chat came while Go was still running
            await wait_for(lambda: len(ran) == 2, timeout=5)
            assert [c for c, _ in ran] == ["*go", "*stop"]
        finally:
            for agent in (actor, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_director_forgets_an_offline_actor(relay, tmp_path, monkeypatch):
    """Approved machines that have left are listed for directors and can be forgotten (tester prep S4)."""
    running, state = relay
    state.approvals.add("m-coda", "Coda")
    state.approvals.add("m-cam", "Cam", "camera")

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", f"127.0.0.1:{running.port}", SECRET)
        try:
            await director.start()
            await wait_for(lambda: len(director.snapshot()["offline"]) == 2)
            offline = {m["id"]: m for m in director.snapshot()["offline"]}
            assert offline["offline:m-coda"]["name"] == "Coda" and offline["offline:m-coda"]["role"] == "actor"
            assert offline["offline:m-cam"]["role"] == "camera" and offline["offline:m-cam"]["approvedAt"]
            await director.handle_call("forget", {"id": "offline:m-coda"})
            await wait_for(lambda: [m["id"] for m in director.snapshot()["offline"]] == ["offline:m-cam"])
            assert director.snapshot()["pending"] == []
            assert logged(director, "Forgot Coda")
            assert "m-coda" not in json.loads((tmp_path / "relay" / "approved_actors.json").read_text())
        finally:
            await director.shutdown()

    asyncio.run(scenario())
