"""Timing end to end (spec §8.2, Phase 2 M3): director and actor agents through the v2 relay, with
a scripted v0.3 actor. Fire times are read from the actors' server-time log lines, as on the laptop."""

import asyncio
import re
import time

import pytest

from agent.core import CallError
from agent.scheduler import DEFAULT_START_LATENCY_MS

from .helpers import SECRET, join_scripted_actor, logged, make_agent, read_until, wait_for

M2_CAPS = ["soundpad", "soundpad.lines", "soundpad.position", "soundpad.list", "soundpad.add", "osc", "files"]
KEY = "0123456789abcdef"


def record(agent):
    """Every envelope the agent receives, with the agent's server time at receipt."""
    got = []
    v2 = agent.relay.v2
    original = v2._on_message

    async def wrapped(env):
        got.append((v2.clock.server_now(), env))
        return await original(env)

    v2._on_message = wrapped
    return got


def of_type(got, msg_type):
    return [(t, env) for t, env in got if env.get("type") == msg_type]


def fired(agent, what="*go"):
    """The server times (ms of the day) in the agent's '⏱ <what> sent HH:MM:SS.mmm' log lines."""
    out = []
    for entry in agent.hub._logs:
        m = re.match(rf"⏱ {re.escape(what)} sent (\d\d):(\d\d):(\d\d)\.(\d{{3}}) server time", entry["text"])
        if m:
            h, mi, s, ms = map(int, m.groups())
            out.append(((h * 60 + mi) * 60 + s) * 1000 + ms)
    return out


async def start_session(director, *actors):
    """Director online, every actor approved, every clock synced."""
    await director.start()
    for actor in actors:
        await actor.start()
    await wait_for(lambda: len(director.snapshot()["pending"]) == len(actors), timeout=8)
    for p in list(director.snapshot()["pending"]):
        await director.handle_call("approve", {"id": p["id"]})
    await wait_for(lambda: all(a.relay.status == "connected" for a in actors), timeout=8)
    await wait_for(lambda: all(a.relay.v2.clock.synced for a in (director, *actors)), timeout=5)
    await wait_for(lambda: len(director.snapshot()["targets"]) == len(actors))


def peer_id(director, name):
    return next(p["id"] for p in director.snapshot()["peers"] if p["name"] == name)


def test_delay_moves_one_actor_150_ms(relay, tmp_path, monkeypatch):
    """Two actors, one at +150 ms: their fire times are 150 ± 20 ms apart (spec §19)."""
    running, _ = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        nova = make_agent(tmp_path, monkeypatch, "Nova", "actor", "m-nova", url)
        vega = make_agent(tmp_path, monkeypatch, "Vega", "actor", "m-vega", url)
        try:
            await start_session(director, nova, vega)
            assert director.snapshot()["clock"]["synced"] and nova.snapshot()["clock"]["rttMs"] is not None

            await director.handle_call("setDelay", {"id": peer_id(director, "Nova"), "ms": 150})
            await wait_for(lambda: nova.relay.v2.delay_ms == 150)
            nova_peer = next(p for p in director.snapshot()["peers"] if p["name"] == "Nova")
            assert nova_peer["delayMs"] == 150 and nova.snapshot()["actor"]["timing"]["delayMs"] == 150
            with pytest.raises(CallError):
                await director.handle_call("setDelay", {"id": nova_peer["id"], "ms": 20_000})

            for _ in range(3):
                await director.handle_call("cue", {"command": "go"})
                await asyncio.sleep(0.6)
            await wait_for(lambda: len(fired(nova)) == 3 and len(fired(vega)) == 3)
            gaps = [n - v for n, v in zip(fired(nova), fired(vega))]
            assert all(130 <= g <= 170 for g in gaps), gaps
            # Both start 60 ms early (the default start latency) and say when the sound is due
            assert logged(nova, f"−{DEFAULT_START_LATENCY_MS} ms start latency") and logged(nova, "+150 ms delay")
            assert logged(director, "server time (+300 ms)")
            # On time: the acks carry late_ms and nobody was late
            await wait_for(lambda: len(director.relay.v2.late) == 2)
            assert all(v <= 20 for v in director.relay.v2.late.values())
            assert not logged(director, "ms late")
        finally:
            for agent in (vega, nova, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_play_in_3s_and_stop_at_1s_cancel_everywhere(relay, tmp_path, monkeypatch):
    running, _ = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        nova = make_agent(tmp_path, monkeypatch, "Nova", "actor", "m-nova", url)
        lex = None
        try:
            await start_session(director, nova)
            lex = await join_scripted_actor(running, director)
            await wait_for(lambda: len(director.snapshot()["targets"]) == 2)

            # The countdown shows on the director and on the actor, from one server time
            await director.handle_call("cue", {"command": "countdown"})
            countdown = director.snapshot()["countdown"]
            assert countdown["durationMs"] == 3000 and 2800 < countdown["endsAt"] - time.time() * 1000 <= 3000
            await wait_for(lambda: nova.snapshot()["countdown"] is not None)
            assert abs(nova.snapshot()["countdown"]["endsAt"] - countdown["endsAt"]) < 120  # minus its 60 ms start latency
            await asyncio.sleep(1.0)
            await director.handle_call("cue", {"command": "stop"})
            await wait_for(lambda: nova.snapshot()["countdown"] is None and director.snapshot()["countdown"] is None)
            assert (await read_until(lex, "PRIV|"))[-1] == "PRIV|Mira|Lex|*stop"
            await asyncio.sleep(2.5)  # past the cancelled cue's time
            assert nova.last_cue["command"] == "*stop" and fired(nova) == []
            assert logged(nova, "cancelled 1 scheduled cue") and logged(director, "countdown cancelled")
            assert not any("*go" in f for f in await asyncio.to_thread(lex.drain))

            # Uncancelled, it plays after 3 s on both kinds of actor
            started = time.monotonic()
            await director.handle_call("cue", {"command": "countdown"})
            assert (await read_until(lex, "PRIV|", timeout=6))[-1] == "PRIV|Mira|Lex|*go"
            await wait_for(lambda: fired(nova), timeout=6)
            assert time.monotonic() - started >= 2.85
            await wait_for(lambda: director.snapshot()["countdown"] is None)
        finally:
            if lex is not None:
                lex.close()
            for agent in (nova, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_armed_sounds_go_with_one_at(relay, tmp_path, monkeypatch):
    """GO with two armed actors, one unarmed and a v0.3 actor armed by number; then a disarm."""
    running, _ = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        nova = make_agent(tmp_path, monkeypatch, "Nova", "actor", "m-nova", url)
        vega = make_agent(tmp_path, monkeypatch, "Vega", "actor", "m-vega", url)
        coda = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", url)
        lex = None
        got = {a: record(a) for a in (nova, vega, coda)}
        try:
            await start_session(director, nova, vega, coda)
            lex = await join_scripted_actor(running, director)
            await wait_for(lambda: len(director.snapshot()["targets"]) == 4)
            ids = {n: peer_id(director, n) for n in ("Nova", "Vega", "Coda", "Lex")}

            await director.handle_call("arm", {"id": ids["Nova"], "sound": {"key": KEY}, "label": "Scene 4 - Nova", "lines": "speakers"})
            await director.handle_call("arm", {"id": ids["Vega"], "sound": {"sha256": "ab" * 32}, "label": "Scene 4 - Vega.wav"})
            with pytest.raises(CallError, match="by its number"):
                await director.handle_call("arm", {"id": ids["Lex"], "sound": {"key": KEY}, "label": "x"})
            await director.handle_call("arm", {"id": ids["Lex"], "sound": {"index": 3}, "label": "Sound 3"})
            armed = director.snapshot()["director"]["armed"]
            assert armed[ids["Nova"]] == {"sound": {"key": KEY}, "label": "Scene 4 - Nova", "lines": "speakers"}
            assert armed[ids["Lex"]] == {"sound": {"index": 3}, "label": "Sound 3", "lines": None}
            assert set(armed) == {ids["Nova"], ids["Vega"], ids["Lex"]}

            await director.handle_call("cue", {"command": "go"})
            await wait_for(lambda: of_type(got[nova], "soundpad.play") and of_type(got[vega], "soundpad.play") and of_type(got[coda], "cue.go"))
            nova_play = of_type(got[nova], "soundpad.play")[-1][1]["data"]
            vega_play = of_type(got[vega], "soundpad.play")[-1][1]["data"]
            coda_go = of_type(got[coda], "cue.go")[-1][1]["data"]
            assert nova_play["sound"] == {"key": KEY} and nova_play["lines"] == "speakers"
            assert vega_play["sound"] == {"sha256": "ab" * 32} and "lines" not in vega_play
            assert nova_play["at"] == vega_play["at"] == coda_go["at"]  # one at for everyone
            assert of_type(got[nova], "cue.go") == [] and of_type(got[coda], "soundpad.play") == []
            assert (await read_until(lex, "PRIV|"))[-1] == "PRIV|Mira|Lex|*play:3"
            # Armed sounds stay armed after GO
            assert len(director.snapshot()["director"]["armed"]) == 3

            await director.handle_call("disarm", {"id": ids["Nova"]})
            assert ids["Nova"] not in director.snapshot()["director"]["armed"]
            await asyncio.sleep(0.4)
            await director.handle_call("cue", {"command": "go"})
            await wait_for(lambda: of_type(got[nova], "cue.go"))
            assert "at" in of_type(got[nova], "cue.go")[-1][1]["data"]
        finally:
            if lex is not None:
                lex.close()
            for agent in (coda, vega, nova, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_older_builds_are_held_by_the_director(relay, tmp_path, monkeypatch):
    """A v0.4 actor without `schedule` would play an `at` cue at once: it gets the cue without `at`,
    sent when it's due (its delay included)."""
    running, _ = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        old = make_agent(tmp_path, monkeypatch, "Old", "actor", "m-old", url)
        old.relay.v2.capabilities = list(M2_CAPS)
        got = record(old)
        try:
            await start_session(director, old)
            await director.handle_call("setDelay", {"id": peer_id(director, "Old"), "ms": 200})
            await wait_for(lambda: next(p for p in director.snapshot()["peers"] if p["name"] == "Old")["delayMs"] == 200)
            await director.handle_call("cue", {"command": "go"})
            sent_at = director.relay.v2.clock.server_now()
            await wait_for(lambda: of_type(got, "cue.go"))
            arrived, env = of_type(got, "cue.go")[0]
            assert "at" not in env["data"]
            # at = sent + 300; held until at + 200 − the trip there
            assert 450 <= arrived - sent_at <= 560, arrived - sent_at
            # A Stop cancels a held cue that hasn't gone out
            await director.handle_call("cue", {"command": "go"})
            await director.handle_call("cue", {"command": "stop"})
            await asyncio.sleep(0.8)
            assert len(of_type(got, "cue.go")) == 1 and logged(director, "1 held cue cancelled")
        finally:
            for agent in (old, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_late_and_far_cues(relay, tmp_path, monkeypatch):
    running, _ = relay
    url = f"127.0.0.1:{running.port}"

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        nova = make_agent(tmp_path, monkeypatch, "Nova", "actor", "m-nova", url)
        try:
            await start_session(director, nova)
            nid = peer_id(director, "Nova")
            now = round(director.relay.v2.clock.server_now())
            # Arrives after its time: plays at once, and the director hears how late
            await director.relay.v2._send("cue.go", {"at": now - 250}, to={"ids": [nid]})
            await wait_for(lambda: logged(director, "Nova started"))
            assert director.relay.v2.late[nid] >= 180 and fired(nova)
            # Two minutes ahead: refused (a wrong clock, not a cue)
            await director.relay.v2._send("cue.go", {"at": now + 120_000}, to={"ids": [nid]})
            await wait_for(lambda: logged(director, "Scheduled too far ahead"))
            assert nova.relay.v2.scheduler.pending() == []
        finally:
            for agent in (nova, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_lead_zero_sends_go_at_once(tmp_path, monkeypatch):
    agent = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", "127.0.0.1:9", "s")

    async def scenario():
        await agent.handle_call("setDirectorLocal", {"leadMs": 0})
        assert agent.snapshot()["director"]["leadMs"] == 0 and agent.config.director.lead_ms == 0
        await agent.handle_call("setDirectorLocal", {"leadMs": 99_999})
        assert agent.snapshot()["director"]["leadMs"] == 2000
        with pytest.raises(CallError):
            await agent.handle_call("arm", {"id": "s_1", "sound": {"index": 1}})  # not connected

    asyncio.run(scenario())


def test_calibrate_from_the_director_and_on_the_actor(relay, tmp_path, monkeypatch, windows_cli):
    """soundpad.calibrate: a speakers-only test play, measured, stopped after 1.5 s, saved in the
    actor's config, answered with start_latency_ms (the fake Soundpad's audio starts after 60 ms)."""
    from agent import actor_runtime
    from agent.config import ConfigStore
    from agent.soundpad_pipe import SoundpadPipe

    from .test_soundpad_addon import FullSoundpad

    monkeypatch.setattr(actor_runtime, "POLL_IDLE_S", 0.1)
    monkeypatch.setattr(actor_runtime, "CALIBRATE_PLAY_S", 0.8)
    running, _ = relay
    url = f"127.0.0.1:{running.port}"
    fake = FullSoundpad(sounds=["intro", "scene 4 - diego", "outro"])

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        coda = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", url)
        coda.actor._pipe_factory = lambda: SoundpadPipe(fake.connect)
        old = make_agent(tmp_path, monkeypatch, "Old", "actor", "m-old", url)
        old.relay.v2.capabilities = list(M2_CAPS)
        try:
            await start_session(director, coda, old)
            cid = peer_id(director, "Coda")
            await wait_for(lambda: next(p for p in director.snapshot()["peers"] if p["id"] == cid)["soundpad"])
            assert coda.snapshot()["actor"]["timing"] == {"startLatencyMs": DEFAULT_START_LATENCY_MS, "measured": False,
                                                          "samples": 0, "autoCompensate": True, "delayMs": 0}

            await director.handle_call("calibrate", {"id": cid, "sound": {"index": 2}})
            await wait_for(lambda: "DoPlaySound(2, true, false)" in fake.plays)  # speakers only
            sp = lambda: next(p for p in director.snapshot()["peers"] if p["id"] == cid)["soundpad"]  # noqa: E731
            await wait_for(lambda: sp()["startLatencyMs"] is not None, timeout=5)
            assert 40 <= sp()["startLatencyMs"] <= 90
            await wait_for(lambda: fake.status == "STOPPED", timeout=3)  # the test play ends by itself
            timing = coda.snapshot()["actor"]["timing"]
            assert timing["measured"] and timing["samples"] == 1
            saved = ConfigStore(tmp_path / "Coda").config.soundpad.start_latencies
            assert len(saved) == 1 and 40 <= saved[0] <= 90
            # Scheduled starts now go out early by the measured latency
            assert coda.actor.compensation_ms() == round(coda.actor.start_latency_ms) and abs(coda.actor.start_latency_ms - saved[0]) < 0.1

            # The actor's own button: no sound named → the one last played by number
            await coda.handle_call("calibrate", {})
            assert fake.plays[-1] == "DoPlaySound(2, true, false)"
            assert coda.snapshot()["actor"]["timing"]["samples"] == 2

            # Turning compensation off: scheduled starts go out at their time
            await coda.handle_call("setActorLocal", {"autoCompensateLatency": False})
            assert coda.actor.compensation_ms() == 0 and not coda.snapshot()["actor"]["timing"]["autoCompensate"]

            with pytest.raises(CallError, match="too old to calibrate"):
                await director.handle_call("calibrate", {"id": peer_id(director, "Old")})
        finally:
            for agent in (old, coda, director):
                await agent.shutdown()

    asyncio.run(scenario())
