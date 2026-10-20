# Scheduling emulation for v0.3 actors (spec §11.3): a v2 action with `at` is held by the relay
# until fire_at − RTT/2, where fire_at = at + the actor's delay_ms. Runs on a fake clock.

import asyncio

import pytest

from relay_helpers import FakeClock
from server.relay import Relay
from server.sessions import Session
from server.settings import Settings
from vrcas_protocol import make

T = 1_800_000_000_000


class FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        pass


def setup(tmp_path, latency_ms=100, delay_ms=0):
    clock = FakeClock(T)
    relay = Relay(Settings(data_dir=tmp_path, status_interval_s=None, echo_log=False), clock)
    director = Session(kind="v2", websocket=FakeWS(), id="s_dir", name="Mira", role="director", approved=True,
                       machine_id="m-dir")
    actor = Session(kind="legacy", websocket=FakeWS(), id="s_coda", name="Coda", role="actor", approved=True,
                    machine_id="m-coda", latency_ms=latency_ms)
    v2_actor = Session(kind="v2", websocket=FakeWS(), id="s_ari", name="Ari", role="actor", approved=True,
                       machine_id="m-ari")
    relay.approvals.entries["m-coda"] = {"name": "Coda", "delay_ms": delay_ms}
    for s in (director, actor, v2_actor):
        relay.registry.add(s)
    return relay, clock, director, actor, v2_actor


def run(coro):
    return asyncio.run(coro)


async def send(relay, director, msg_type, data, to=("s_coda",)):
    env = make(msg_type, data, to={"ids": list(to)}, from_=director.id, ts=relay.clock.now_ms())
    await relay.router.route(director, env)
    await asyncio.sleep(0)


@pytest.mark.parametrize("latency_ms, delay_ms, expected_send_at", [
    (100, 0, T + 1000 - 50),
    (100, 150, T + 1000 + 150 - 50),
    (0, 0, T + 1000),            # latency not measured yet
    (-1, 0, T + 1000),           # timed out: no correction
    (60, -200, T + 1000 - 200 - 30),
])
def test_held_until_fire_at_minus_half_rtt(tmp_path, latency_ms, delay_ms, expected_send_at):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path, latency_ms, delay_ms)
        await send(relay, director, "cue.go", {"at": T + 1000})
        assert actor.websocket.sent == []
        assert clock.waiting == [expected_send_at]
        await clock.advance(expected_send_at - T - 1)
        assert actor.websocket.sent == []
        await clock.advance(1)
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*go"]
        assert actor.held == []

    run(scenario())


def test_past_at_is_sent_at_once(tmp_path):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path)
        await send(relay, director, "cue.play", {"index": 2, "at": T - 500})
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*play:2"]

    run(scenario())


def test_without_at_nothing_is_held(tmp_path):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path)
        await send(relay, director, "cue.go", {})
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*go"] and clock.waiting == []

    run(scenario())


def test_stop_cancels_a_held_go(tmp_path):
    """Play in 3s, then Stop during the countdown: the v0.3 actor never starts."""
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path)
        await send(relay, director, "cue.go", {"at": T + 3000})
        await clock.advance(1000)
        await send(relay, director, "cue.stop", {})
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*stop"]
        await clock.advance(5000)
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*stop"]
        assert actor.held == []

    run(scenario())


def test_scheduled_stop_cancels_only_later_starts(tmp_path):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path, latency_ms=0)
        await send(relay, director, "cue.go", {"at": T + 100})
        await send(relay, director, "cue.stop", {"at": T + 500})
        await send(relay, director, "cue.play", {"index": 4, "at": T + 900})
        await clock.advance(100)
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*go"]
        await clock.advance(400)
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*go", "PRIV|Mira|Coda|*stop"]
        await clock.advance(1000)
        assert actor.websocket.sent == ["PRIV|Mira|Coda|*go", "PRIV|Mira|Coda|*stop"]

    run(scenario())


def test_osc_param_is_held_too(tmp_path):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path, latency_ms=40)
        await send(relay, director, "osc.param", {"parameter": "Wave", "value": True, "at": T + 200})
        await clock.advance(179)
        assert actor.websocket.sent == []
        await clock.advance(1)
        assert actor.websocket.sent == ["OSC_CUE|Coda|Wave|true"]

    run(scenario())


def test_v2_actors_get_at_unchanged(tmp_path):
    """v2 agents schedule themselves (Phase 2); the relay passes `at` straight through."""
    async def scenario():
        relay, clock, director, actor, ari = setup(tmp_path)
        await send(relay, director, "cue.go", {"at": T + 1000}, to=("s_coda", "s_ari"))
        assert len(ari.websocket.sent) == 1 and '"at":1800000001000' in ari.websocket.sent[0]
        assert actor.websocket.sent == []

    run(scenario())


def test_disconnect_drops_held_cues(tmp_path):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path)
        await send(relay, director, "cue.go", {"at": T + 1000})
        task = actor.held[0][0]
        relay.bridge.cancel_held(actor)
        await asyncio.sleep(0)
        assert task.cancelled()
        await clock.advance(2000)
        assert actor.websocket.sent == []

    run(scenario())


def test_unsupported_scheduled_action_is_not_held(tmp_path):
    async def scenario():
        relay, clock, director, actor, _ = setup(tmp_path)
        await send(relay, director, "soundpad.play", {"sound": {"path": "C:\\a.mp3"}, "at": T + 1000})
        assert actor.held == [] and clock.waiting == []
        assert '"code":"unsupported"' in director.websocket.sent[-1]

    run(scenario())
