"""Clock sync with the relay (spec §8.2.1): server time from time.ping / time.pong.

The agent sends `time.ping {t0}` every second for the first 5 s after connecting, then every
10 s. The relay answers `time.pong {t0, t1, t2}`; at receipt (t3)

    offset = ((t1 − t0) + (t2 − t3)) / 2        rtt = (t3 − t0) − (t2 − t1)

The last 8 samples are kept and the offset of the one with the lowest round trip is used.

Local times are `time.perf_counter()`, not the wall clock: it doesn't jump when Windows sets its
clock, and Python 3.12's wall and monotonic clocks on Windows tick in 15.6 ms steps (3.13 fixed
both). So `offset` turns a perf_counter reading into server ms; the wire `t0` is still Unix ms
(the relay only echoes it), and the matching perf reading is kept per ping id.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable

SAMPLES = 8
FAST_EVERY_S = 1.0
FAST_FOR_S = 5.0
SLOW_EVERY_S = 10.0
# A ping without an answer this long is forgotten
PING_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Sample:
    offset_ms: float
    rtt_ms: float


def sample(t0: float, t1: float, t2: float, t3: float) -> Sample:
    """One NTP-style sample. t0 / t3: our send and receive times; t1 / t2: the relay's receive and
    send times (all ms). The offset is exact when both directions take equally long; otherwise it
    is off by half the difference."""
    return Sample(offset_ms=((t1 - t0) + (t2 - t3)) / 2, rtt_ms=max(0.0, (t3 - t0) - (t2 - t1)))


def perf_ms() -> float:
    return time.perf_counter() * 1000


def wall_ms() -> float:
    return time.time() * 1000


class ClockSync:
    """Server time for this connection. `now` returns local ms (perf_counter by default)."""

    def __init__(self, now: Callable[[], float] = perf_ms, wall: Callable[[], float] = wall_ms):
        self._now = now
        self._wall = wall
        self.samples: deque[Sample] = deque(maxlen=SAMPLES)
        # From welcome.server_time, until the first pong: off by the one-way trip
        self.rough_offset_ms: float | None = None
        self._pings: dict[str, float] = {}

    def reset(self) -> None:
        self.samples.clear()
        self.rough_offset_ms = None
        self._pings.clear()

    # ---- samples ------------------------------------------------------------

    def seed(self, server_time_ms: int) -> None:
        """welcome.server_time: a first guess (the relay's clock, one trip ago)."""
        self.rough_offset_ms = server_time_ms - self._now()

    def sent(self, ping_id: str) -> None:
        """A time.ping just went out under this message id."""
        now = self._now()
        self._pings = {k: v for k, v in self._pings.items() if now - v < PING_TIMEOUT_S * 1000}
        self._pings[ping_id] = now

    def received(self, ping_id: str | None, t1: int, t2: int) -> Sample | None:
        """A time.pong answering one of our pings (`reply_to`). Others are ignored."""
        t0 = self._pings.pop(ping_id, None) if ping_id else None
        if t0 is None:
            return None
        s = sample(t0, t1, t2, self._now())
        self.samples.append(s)
        return s

    @property
    def best(self) -> Sample | None:
        return min(self.samples, key=lambda s: s.rtt_ms) if self.samples else None

    @property
    def synced(self) -> bool:
        return bool(self.samples)

    @property
    def offset_ms(self) -> float | None:
        best = self.best
        return best.offset_ms if best else self.rough_offset_ms

    @property
    def rtt_ms(self) -> float | None:
        best = self.best
        return best.rtt_ms if best else None

    # ---- conversions ----------------------------------------------------------

    def server_now(self) -> float | None:
        """Server time in ms now, or None before welcome."""
        offset = self.offset_ms
        return None if offset is None else self._now() + offset

    def to_local(self, server_ms: float) -> float | None:
        """A server time as a local (perf) time in ms."""
        offset = self.offset_ms
        return None if offset is None else server_ms - offset

    def until(self, server_ms: float) -> float | None:
        """ms from now until a server time (negative: it's past)."""
        now = self.server_now()
        return None if now is None else server_ms - now

    def to_wall(self, server_ms: float) -> float | None:
        """A server time on this PC's wall clock (ms since epoch), for the UI's countdown."""
        until = self.until(server_ms)
        return None if until is None else self._wall() + until

    def wall_offset_ms(self) -> float | None:
        """Server time minus this PC's wall clock: how far this PC's clock is behind the relay's."""
        now = self.server_now()
        return None if now is None else now - self._wall()

    def view(self) -> dict:
        """For the UI (AppState.clock)."""
        offset, rtt = self.wall_offset_ms(), self.rtt_ms
        return {
            "synced": self.synced,
            "offsetMs": None if offset is None else round(offset),
            "rttMs": None if rtt is None else round(rtt),
        }


async def run_pings(clock: ClockSync, send: Callable[[], Awaitable[str]]) -> None:
    """Ping the relay for as long as the connection lasts (cancel the task to stop). `send` sends
    one time.ping and returns its message id."""
    started = time.monotonic()
    while True:
        try:
            clock.sent(await send())
        except RuntimeError:
            return  # disconnected
        fast = time.monotonic() - started < FAST_FOR_S
        await asyncio.sleep(FAST_EVERY_S if fast else SLOW_EVERY_S)
