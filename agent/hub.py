"""Fan-out from the agent to every open UI (window and browser tabs)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Callable

log = logging.getLogger("vrcas")

MAX_LOGS = 300
STATE_COALESCE_S = 0.05


class Hub:
    def __init__(self, snapshot: Callable[[], dict]):
        self._snapshot = snapshot
        self._clients: set[Any] = set()
        self._logs: deque[dict] = deque(maxlen=MAX_LOGS)
        self._next_log = 1
        self._state_pending = False

    # ---- clients ----------------------------------------------------------

    async def add(self, ws: Any) -> None:
        self._clients.add(ws)
        await self._send(ws, {"type": "logs", "entries": list(self._logs)})
        await self._send(ws, {"type": "state", "state": self._snapshot()})

    def remove(self, ws: Any) -> None:
        self._clients.discard(ws)

    # ---- events -----------------------------------------------------------

    def log(self, level: str, text: str, sender: str | None = None) -> None:
        entry = {"id": self._next_log, "ts": int(time.time() * 1000), "level": level, "text": text}
        if sender:
            entry["from"] = sender
        self._next_log += 1
        self._logs.append(entry)
        log.info("[%s] %s%s", level, f"{sender}: " if sender else "", text)
        self._broadcast({"type": "log", "entry": entry})

    def toast(self, level: str, text: str) -> None:
        self._broadcast({"type": "toast", "level": level, "text": text})

    def traffic(self, sender: str, to: list[str], kind: str) -> None:
        if to:
            self._broadcast({"type": "traffic", "traffic": {"from": sender, "to": to, "kind": kind}})

    def state_changed(self) -> None:
        """Coalesce bursts of changes (a roster update touches many fields) into one push."""
        if self._state_pending:
            return
        self._state_pending = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._state_pending = False
            return
        loop.call_later(STATE_COALESCE_S, self._flush_state)

    def _flush_state(self) -> None:
        self._state_pending = False
        self._broadcast({"type": "state", "state": self._snapshot()})

    # ---- plumbing ---------------------------------------------------------

    def _broadcast(self, event: dict) -> None:
        if not self._clients:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for ws in list(self._clients):
            loop.create_task(self._send(ws, event))

    async def _send(self, ws: Any, event: dict) -> None:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:  # a closed tab; the socket handler removes it
            self._clients.discard(ws)
