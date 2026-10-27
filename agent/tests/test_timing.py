"""Clock sync and the scheduler (spec §8.2.1, §8.2.3) on a fake clock, plus the real timers."""

import asyncio
import time

import pytest

from agent.scheduler import FirePlan, LoopTimers, Scheduler, server_time, sleep_until
from agent.timesync import ClockSync, run_pings, sample

SERVER_AHEAD = 9000  # the laptop's clock runs ~9 s behind the relay's


class FakeTime:
    """One fake clock for ClockSync (local ms) and the scheduler's timers."""

    def __init__(self, start=1000.0):
        self.ms = start
        self.timers: list[list] = []  # [due_ms, fn, cancelled]

    def now(self):
        return self.ms

    def wall(self):
        return 1_800_000_000_000 + self.ms

    def call_later(self, delay_s, fn):
        entry = [self.ms + delay_s * 1000, fn, False]
        self.timers.append(entry)

        class Handle:
            def cancel(_self):
                entry[2] = True

        return Handle()

    def advance(self, ms):
        end = self.ms + ms
        while True:
            due = sorted((t for t in self.timers if not t[2] and t[0] <= end), key=lambda t: t[0])
            if not due:
                break
            entry = due[0]
            entry[2] = True
            self.ms = max(self.ms, entry[0])
            entry[1]()
        self.ms = end


def exchange(clock, fake, ping_id, out_ms=20.0, back_ms=20.0, hold_ms=1.0):
    """One ping/pong with the given one-way times; the relay's clock is SERVER_AHEAD ahead."""
    clock.sent(ping_id)
    t0 = fake.ms
    t1 = t0 + out_ms + SERVER_AHEAD
    t2 = t1 + hold_ms
    fake.ms = t0 + out_ms + hold_ms + back_ms
    return clock.received(ping_id, int(t1), int(t2))


# ---- clock sync -----------------------------------------------------------------------------------


def test_sample_math_symmetric_and_asymmetric():
    s = sample(1000, 1000 + 20 + 5000, 1000 + 22 + 5000, 1042)
    assert (s.offset_ms, s.rtt_ms) == (5000, 40)
    # 30 ms out, 10 ms back: the offset is off by half the difference
    s = sample(1000, 6030, 6030, 1040)
    assert (s.offset_ms, s.rtt_ms) == (5010, 40)


def test_lowest_round_trip_wins_and_only_8_are_kept():
    fake = FakeTime()
    clock = ClockSync(now=fake.now, wall=fake.wall)
    assert not clock.synced and clock.server_now() is None
    # Noisy samples: (out, back). The quick one is the most accurate.
    for i, (out, back) in enumerate([(40, 25), (90, 30), (12, 11), (60, 61), (35, 80), (25, 25), (50, 20), (70, 75)]):
        exchange(clock, fake, f"p{i}", out, back)
    assert clock.synced and len(clock.samples) == 8
    assert clock.rtt_ms == 12 + 11 and clock.offset_ms == SERVER_AHEAD + 0.5
    # A 9th sample pushes the oldest out; the best one stays until it's pushed out too
    exchange(clock, fake, "p8", 45, 45)
    assert len(clock.samples) == 8 and clock.rtt_ms == 23
    for i in range(9, 16):
        exchange(clock, fake, f"p{i}", 45, 45)
    assert clock.rtt_ms == 90 and clock.offset_ms == SERVER_AHEAD


def test_pongs_for_unknown_pings_are_ignored_and_welcome_seeds():
    fake = FakeTime()
    clock = ClockSync(now=fake.now, wall=fake.wall)
    assert clock.received("nobody", 5, 6) is None and clock.received(None, 5, 6) is None
    clock.seed(int(fake.ms + SERVER_AHEAD - 30))  # welcome: the relay's time, one trip ago
    assert not clock.synced and clock.offset_ms == SERVER_AHEAD - 30
    assert clock.server_now() == fake.ms + SERVER_AHEAD - 30
    exchange(clock, fake, "p1")
    assert clock.synced and clock.offset_ms == SERVER_AHEAD
    clock.reset()
    assert not clock.synced and clock.offset_ms is None


def test_conversions_and_view():
    fake = FakeTime()
    clock = ClockSync(now=fake.now, wall=fake.wall)
    exchange(clock, fake, "p1", 10, 10, 0)
    now = clock.server_now()
    assert now == fake.ms + SERVER_AHEAD
    assert clock.to_local(now + 300) == fake.ms + 300
    assert clock.until(now + 300) == 300 and clock.until(now - 50) == -50
    assert clock.to_wall(now + 3000) == fake.wall() + 3000
    view = clock.view()
    assert view["synced"] and view["rttMs"] == 20
    assert view["offsetMs"] == round(now - fake.wall())


def test_ping_loop_fast_then_slow(monkeypatch):
    from agent import timesync

    monkeypatch.setattr(timesync, "FAST_EVERY_S", 0.01)
    monkeypatch.setattr(timesync, "FAST_FOR_S", 0.05)
    monkeypatch.setattr(timesync, "SLOW_EVERY_S", 0.2)
    clock = ClockSync()
    sent = []

    async def send():
        sent.append(time.monotonic())
        return f"p{len(sent)}"

    async def scenario():
        task = asyncio.create_task(run_pings(clock, send))
        await asyncio.sleep(0.3)
        task.cancel()

    asyncio.run(scenario())
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    assert len(sent) >= 5 and gaps[0] < 0.05 and gaps[-1] >= 0.15


# ---- the scheduler ---------------------------------------------------------------------------------


def synced(fake):
    clock = ClockSync(now=fake.now, wall=fake.wall)
    exchange(clock, fake, "p1", 10, 10, 0)
    return clock, Scheduler(clock, timers=fake)


def test_runs_at_the_server_time():
    fake = FakeTime()
    clock, sched = synced(fake)
    fired = []
    at = clock.server_now() + 300
    sched.at(at, lambda: fired.append(at))
    assert len(sched.pending()) == 1
    fake.advance(299)
    assert fired == []
    fake.advance(1)
    assert fired == [at]
    # It ran at the local time that matches the server time
    assert clock.to_local(at) == fake.ms
    assert sched.pending() == []


def test_late_arrival_runs_at_once():
    fake = FakeTime()
    clock, sched = synced(fake)
    fired = []
    sched.at(clock.server_now() - 45, lambda: fired.append(1))
    fake.advance(0)
    assert fired == [1]


def test_cancel_by_group_and_all():
    fake = FakeTime()
    clock, sched = synced(fake)
    ran = []
    now = clock.server_now()
    sched.at(now + 100, lambda: ran.append("go"), group="cue")
    sched.at(now + 100, lambda: ran.append("osc"), group="osc")
    sched.at(now + 200, lambda: ran.append("go2"), group="cue")
    assert [j.group for j in sched.cancel("cue")] == ["cue", "cue"]
    fake.advance(300)
    assert ran == ["osc"]
    sched.at(now + 400, lambda: ran.append("late one"))
    assert len(sched.cancel()) == 1
    fake.advance(500)
    assert ran == ["osc"]


def test_without_a_clock_it_runs_at_once():
    fake = FakeTime()
    sched = Scheduler(ClockSync(now=fake.now, wall=fake.wall), timers=fake)
    fired = []
    sched.at(123, lambda: fired.append(123))
    fake.advance(0)
    assert fired == [123]


def test_fire_plan():
    plan = FirePlan(at=1_000_000, delay_ms=150, latency_ms=60)
    assert plan.fire_ms == 1_000_090
    assert FirePlan(at=1_000_000, delay_ms=-200).fire_ms == 999_800
    assert "+150 ms delay" in plan.text() and "−60 ms start latency" in plan.text()
    assert server_time(1_800_000_000_123).endswith(".123")


# ---- the real timers ---------------------------------------------------------------------------------


def test_loop_timers_are_precise_and_cancel_in_both_phases():
    async def scenario():
        timers = LoopTimers()
        fired = {}
        start = time.perf_counter()
        for name, delay in (("near", 0.012), ("far", 0.08), ("zero", 0.0)):
            timers.call_later(delay, lambda name=name: fired.setdefault(name, time.perf_counter() - start))
        coarse = timers.call_later(0.08, lambda: fired.setdefault("coarse", 0))
        precise = timers.call_later(0.01, lambda: fired.setdefault("precise", 0))
        coarse.cancel()  # still waiting on the loop
        await asyncio.sleep(0.005)
        precise.cancel()  # already handed to the thread
        await asyncio.sleep(0.15)
        return fired

    fired = asyncio.run(scenario())
    assert set(fired) == {"near", "far", "zero"}
    assert fired["near"] == pytest.approx(0.012, abs=0.004)
    assert fired["far"] == pytest.approx(0.08, abs=0.004)
    assert fired["zero"] < 0.004


def test_sleep_until():
    target = time.perf_counter() + 0.02
    sleep_until(target)
    assert 0 <= time.perf_counter() - target < 0.002
