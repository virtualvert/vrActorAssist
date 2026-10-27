"""The relay's clock: server time for time.pong (spec §8.2.1) and for holding scheduled cues
for v0.3 actors (§11.3). Tests swap in a fake clock."""

from __future__ import annotations

import asyncio
import time


class Clock:
    """Server time is Unix time in milliseconds."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    async def sleep_until(self, ms: int) -> None:
        delay = (ms - self.now_ms()) / 1000
        if delay > 0:
            await asyncio.sleep(delay)

