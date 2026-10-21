"""File transfers on /v2/ws (spec §8.4, §5.7): which transfer belongs to whom, and the binary chunks.

The relay doesn't read the files. It keeps one entry per offer so that:
- chunk frames are passed on only from the session that made the offer, only to the one session
  it went to, and only after that session accepted it;
- replies (accept, progress, ok, ...) always reach the offer's sender, whatever `to` says;
- when either side goes away, the other hears about it (`file.err` from the relay).

Files to and from v0.3 clients use the same entries; file_bridge.py translates for the v0.3 side.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from vrcas_protocol import Envelope, IdsTarget, KIND_FILE_CHUNK, chunk_count, make, unpack_chunk
from vrcas_protocol.chunks import HEADER_SIZE

from . import permissions
from .sessions import Session

if TYPE_CHECKING:
    from .relay import Relay

# Types this module routes itself (the rest of file.* is routed as usual)
REPLY_TYPES = ("file.accept", "file.deny", "file.progress", "file.ok", "file.err")
TYPES = ("file.offer", "file.end", "file.batch.cancel") + REPLY_TYPES


@dataclass(eq=False)
class Transfer:
    id: str
    batch_id: str | None
    name: str
    size: int
    chunk_size: int
    sender: Session
    recipient: Session
    accepted: bool = False
    forwarded: int = 0
    started: float = field(default_factory=time.monotonic)
    # file_bridge.ToLegacy for a file on its way to a v0.3 client
    leg: Any = None

    @property
    def chunks(self) -> int:
        return chunk_count(self.size, self.chunk_size)


class Refused(Exception):
    """A file message the relay won't pass on: (code, message, ids)."""

    def __init__(self, code: str, message: str, ids: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.ids = ids


def size_text(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


class Transfers:
    def __init__(self, relay: "Relay"):
        self.relay = relay
        self.by_id: dict[str, Transfer] = {}

    @property
    def log(self):
        return self.relay.log

    def open_for(self, sender: Session) -> list[Transfer]:
        return [t for t in self.by_id.values() if t.sender is sender]

    # ---- JSON messages ---------------------------------------------------------------------------

    async def message(self, sender: Session, env: Envelope, payload) -> None:
        """A validated file.* message (TYPES). Raises Refused; the router answers with an error."""
        router = self.relay.router
        if env.type == "file.offer":
            try:
                transfer = self._offer(sender, env, payload)
            except Refused as exc:
                # Besides the error, a file.err the sender can tie to its transfer
                await self._send_err_to(sender, payload.transfer_id, str(exc))
                raise
            self.by_id[transfer.id] = transfer
            await router.route(sender, env)
            return
        if env.type == "file.batch.cancel":
            for transfer in [t for t in self.open_for(sender) if t.batch_id == payload.batch_id]:
                self.close(transfer, "cancelled")
            await router.route(sender, env)
            return

        transfer = self.by_id.get(payload.transfer_id)
        if transfer is None:
            raise Refused("invalid", "Unknown or finished transfer")
        if env.type == "file.end":
            if transfer.sender is not sender:
                raise Refused("forbidden", "That transfer isn't yours")
            env.to = IdsTarget(ids=[transfer.recipient.id])
            await router.route(sender, env)
            return

        # A reply from the receiving side: it always goes back to the offer's sender
        if transfer.recipient is not sender:
            raise Refused("forbidden", "That transfer isn't addressed to you")
        env.to = IdsTarget(ids=[transfer.sender.id])
        if env.type == "file.accept":
            transfer.accepted = True
        # Routed before the entry is closed: the bridge looks the file name up for a v0.3 director
        await router.route(sender, env)
        if env.type == "file.ok":
            self.close(transfer, "ok")
        elif env.type == "file.deny":
            self.close(transfer, f"declined ({payload.reason})" if payload.reason else "declined")
        elif env.type == "file.err":
            self.close(transfer, f"failed ({payload.error})" if payload.error else "failed")

    def _offer(self, sender: Session, env: Envelope, payload) -> Transfer:
        settings = self.relay.settings
        if not isinstance(env.to, IdsTarget) or len(set(env.to.ids)) != 1:
            raise Refused("invalid", "file.offer goes to exactly one session")
        if payload.transfer_id in self.by_id:
            raise Refused("invalid", "That transfer id is already in use")
        if len(self.open_for(sender)) >= settings.max_open_transfers:
            raise Refused("invalid", f"At most {settings.max_open_transfers} transfers at once")
        recipient_id = env.to.ids[0]
        recipient = self.relay.registry.by_id(recipient_id)
        if recipient is None or recipient is sender:
            raise Refused("unknown_target", f"Not connected: {recipient_id}", [recipient_id])
        if recipient.legacy:
            self.relay.bridge.files.check_offer(sender, recipient, payload)
        return Transfer(id=payload.transfer_id, batch_id=payload.batch_id, name=payload.name, size=payload.size,
                        chunk_size=payload.chunk_size, sender=sender, recipient=recipient)

    # ---- binary chunk frames ---------------------------------------------------------------------

    async def chunk(self, sender: Session, frame: bytes) -> None:
        """One binary frame. Raises Refused for a frame that can't be tied to a transfer; problems
        with a known transfer end it, and both sides get file.err."""
        if not permissions.allowed(sender.perm_role, "file.offer"):
            raise Refused("forbidden", f"A {sender.role} can't send file data")
        if len(frame) > HEADER_SIZE + self.relay.settings.max_chunk_bytes:
            raise Refused("invalid", "Chunk frame too large")
        try:
            chunk = unpack_chunk(frame)
        except ValueError as exc:
            raise Refused("invalid", str(exc)) from None
        if chunk.kind != KIND_FILE_CHUNK:
            raise Refused("invalid", f"Unknown binary frame kind {chunk.kind}")
        transfer = self.by_id.get(chunk.transfer_id)
        if transfer is None:
            raise Refused("invalid", "Unknown or finished transfer")
        if transfer.sender is not sender:
            raise Refused("forbidden", "That transfer isn't yours")
        if not transfer.accepted:
            raise Refused("invalid", "Wait for file.accept before sending data")
        if chunk.index >= transfer.chunks or len(chunk.payload) > transfer.chunk_size:
            await self.fail(transfer, f"Chunk {chunk.index} doesn't fit a {transfer.size}-byte file")
            return
        if transfer.recipient.legacy:
            error = await self.relay.bridge.files.chunk_to_legacy(transfer, chunk)
            if error:
                await self.fail(transfer, error)
                return
        elif not await transfer.recipient.send_bytes(frame):
            await self.fail(transfer, f"{transfer.recipient.name} disconnected")
            return
        transfer.forwarded += 1

    # ---- ending transfers --------------------------------------------------------------------------

    async def fail(self, transfer: Transfer, error: str) -> None:
        """End a transfer from the relay's side: both ends get file.err (v0.3 clients their own frames)."""
        self.close(transfer, f"failed ({error})")
        for session in (transfer.sender, transfer.recipient):
            await self._send_err(session, transfer, error)

    async def session_gone(self, session: Session) -> None:
        """A connection closed: its transfers end, and the other side hears why."""
        for transfer in list(self.by_id.values()):
            if session is transfer.sender:
                other = transfer.recipient
            elif session is transfer.recipient:
                other = transfer.sender
            else:
                continue
            self.close(transfer, f"{session.name} disconnected")
            await self._send_err(other, transfer, f"{session.name} disconnected")
        self.relay.bridge.files.forget_session(session)

    async def _send_err(self, session: Session, transfer: Transfer, error: str) -> None:
        if session.legacy:
            await self.relay.bridge.files.error_to_legacy(session, transfer, error)
            return
        await self._send_err_to(session, transfer.id, error)

    async def _send_err_to(self, session: Session, transfer_id: str, error: str) -> None:
        if session.legacy or not session.id:
            return
        env = make("file.err", {"transfer_id": transfer_id, "error": error[:500]}, to={"ids": [session.id]},
                   from_="server", ts=self.relay.clock.now_ms())
        from .router import frame

        await session.send_text(frame(env))

    def close(self, transfer: Transfer, result: str) -> None:
        if self.by_id.pop(transfer.id, None) is None:
            return
        self.log(f"File {transfer.sender.name} → {transfer.recipient.name}: {transfer.name} "
                 f"({size_text(transfer.size)}): {result}")
