"""Scheduled actions (spec §8.2): run something at a server time; cancel by group.

    fire_at = at + delay_ms − start_latency_ms     (the last term for Soundpad starts, §8.2.3)

An action due in the past (it arrived late) runs at once; how late it ran goes back to the
director as `late_ms`. Waiting never happens inside an actor's ActionQueue job: the scheduler
holds the action and queues it when it's due, so a Stop that arrives meanwhile cancels it
(`cancel(group)`) instead of waiting behind it.

Timing: asyncio's timers on Windows follow the 15.6 ms system tick before Python 3.13 (the
laptop runs 3.12). So the bulk of a wait is `loop.call_later` and the last PRECISE_S is slept in
a worker thread: `time.sleep` uses a high-resolution timer on Windows since Python 3.11.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .timesync import ClockSync

# Later than this and the director is told (§8.2.3)
LATE_MS = 20
# The last part of each wait, slept in a thread
PRECISE_S = 0.03
# An action scheduled further ahead than this is refused (a wrong clock, not a cue)
MAX_AHEAD_MS = 60_000
# Start latency assumed until the actor has measured its own (§8.2.3, laptop: ≈50 ms, first play ≈90)
DEFAULT_START_LATENCY_MS = 60

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vrcas-timer")


class Handle(Protocol):
    def cancel(self) -> None: ...


class Timers(Protocol):
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> Handle: ...


def sleep_until(target: float, now: Callable[[], float] = time.perf_counter) -> None:
    left = target - now()
    if left > 0.002:
        time.sleep(left - 0.001)
    while now() < target:
        time.sleep(0)


class _PreciseHandle:
    def __init__(self) -> None:
        self.cancelled = False
        self.timer: asyncio.TimerHandle | asyncio.Handle | None = None

    def cancel(self) -> None:
        self.cancelled = True
        if self.timer is not None:
            self.timer.cancel()


class LoopTimers:
    """call_later with about 1 ms accuracy on every platform."""

    def __init__(self, precise_s: float = PRECISE_S, now: Callable[[], float] = time.perf_counter):
        self.precise_s = precise_s
        self.now = now

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> Handle:
        loop = asyncio.get_running_loop()
        handle = _PreciseHandle()
        target = self.now() + delay_s

        def fire() -> None:
            if not handle.cancelled:
                fn()

        def precise() -> None:
            if handle.cancelled:
                return

            def wait() -> None:
                sleep_until(target, self.now)
                try:
                    loop.call_soon_threadsafe(fire)
                except RuntimeError:  # the loop closed meanwhile
                    pass

            _pool.submit(wait)

        coarse = delay_s - self.precise_s
        if coarse > 0:
            handle.timer = loop.call_later(coarse, precise)
        elif delay_s > 0.001:
            precise()
        else:
            handle.timer = loop.call_soon(fire)
        return handle


@dataclass(frozen=True)
class Fire:
    """When a scheduled action ran, in server ms."""

    due_ms: float
    fired_ms: float

    @property
    def late_ms(self) -> int:
        return max(0, round(self.fired_ms - self.due_ms))


@dataclass
class Job:
    id: int
    group: str
    due_ms: float
    handle: Handle | None = None
    data: dict[str, Any] = field(default_factory=dict)


class Scheduler:
    """Actions at server times, for one relay connection."""

    def __init__(self, clock: ClockSync, timers: Timers | None = None):
        self.clock = clock
        self.timers: Timers = timers or LoopTimers()
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)

    def at(self, server_ms: float, fn: Callable[[Fire], None], group: str = "cue", **data: Any) -> Job:
        """Run fn(Fire) at server_ms (at once if that's past, or when there's no clock yet)."""
        job = Job(next(self._ids), group, server_ms, data=data)
        until = self.clock.until(server_ms)
        delay_s = max(0.0, until / 1000) if until is not None else 0.0

        def run() -> None:
            if self._jobs.pop(job.id, None) is None:
                return  # cancelled
            now = self.clock.server_now()
            fn(Fire(server_ms, server_ms if now is None else now))

        self._jobs[job.id] = job
        job.handle = self.timers.call_later(delay_s, run)
        return job

    def cancel(self, group: str | None = None) -> list[Job]:
        """Cancel the jobs of one group (None: all). Returns what was cancelled."""
        gone = [j for j in self._jobs.values() if group is None or j.group == group]
        for job in gone:
            self._jobs.pop(job.id, None)
            if job.handle is not None:
                job.handle.cancel()
        return gone

    def pending(self, group: str | None = None) -> list[Job]:
        return sorted((j for j in self._jobs.values() if group is None or j.group == group), key=lambda j: j.due_ms)


@dataclass(frozen=True)
class FirePlan:
    """fire_at = at + delay_ms − start_latency_ms (§8.2.3)."""

    at: int
    delay_ms: int = 0
    latency_ms: int = 0

    @property
    def fire_ms(self) -> int:
        return self.at + self.delay_ms - self.latency_ms

    def text(self) -> str:
        parts = [f"at {server_time(self.at)}"]
        if self.delay_ms:
            parts.append(f"{self.delay_ms:+d} ms delay")
        if self.latency_ms:
            parts.append(f"−{self.latency_ms} ms start latency")
        return ", ".join(parts)


def server_time(ms: float) -> str:
    """A server time as HH:MM:SS.mmm (this PC's time zone; the date is left out)."""
    whole = int(ms // 1000)
    return time.strftime("%H:%M:%S", time.localtime(whole)) + f".{int(ms) % 1000:03d}"


@dataclass(frozen=True)
class Timing:
    """A scheduled action as it ran: its plan and the server time it went out."""

    plan: FirePlan
    fired_ms: float

    @property
    def late_ms(self) -> int:
        return max(0, round(self.fired_ms - self.plan.fire_ms))

    def text(self, start: bool) -> str:
        """The agent log's evidence line (spec §19: fire times compared in server time)."""
        late = f", {self.late_ms} ms late" if self.late_ms > LATE_MS else ""
        if start:
            expected = server_time(self.fired_ms + self.plan.latency_ms)
            return f"sent {server_time(self.fired_ms)} server time{late}; sound due {expected} ({self.plan.text()})"
        return f"sent {server_time(self.fired_ms)} server time{late} ({self.plan.text()})"
