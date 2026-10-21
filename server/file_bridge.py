"""Files between v0.3 clients on /ws and v0.4 apps on /v2/ws (spec §11.2, Phase 2 plan §4.1).

v0.3 transfers are keyed by file name and carry 64 KiB base64 chunks in text frames, checked with
MD5; v2 transfers are keyed by a transfer id and carry binary chunk frames. The bridge keeps one
`Transfer` (transfers.py) per bridged file, so permissions, clean-up and the log line are shared
with v2 ↔ v2 transfers.

v0.3 director → v0.4 actor:
    FILEREQ → file.offer (chunk_size 64 KiB, md5), FILESTART swallowed, FILECHUNK → one binary
    frame, FILEEND → file.end; BATCH_* → file.batch.*. The actor's replies come back as the
    frames a v0.3 actor sends (FILEACK with an empty save_dir, FILEDENY, FILEOK, FILEERR);
    file.progress has no v0.3 equivalent and is dropped.

v0.4 director → v0.3 actor: exactly the frames a v0.3.3 director sends, in its order:
    BATCH_START (left out for a batch of one file), FILEREQ, FILESTART, FILECHUNK × 4 per
    256 KiB chunk, FILEEND with the MD5, BATCH_END / BATCH_CANCEL. The director is paced with
    file.progress after the frames of each chunk have gone out.

v0.3 ↔ v0.3 transfers don't come here: they keep the v0.3 relay's own path (legacy_bridge).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from shared import format_message
from vrcas_protocol import Envelope, MAX_FILE_BYTES, make, pack_chunk
from vrcas_protocol.chunks import LEGACY_CHUNK_SIZE, Chunk

from .sessions import Session
from .transfers import Refused, Transfer

if TYPE_CHECKING:
    from .relay import Relay

FILES_CAPABILITY = "files"
_MD5 = re.compile(r"^[0-9a-f]{32}$")
# A v0.3 actor joins the name onto its folder unchecked, and '|' would break the pipe protocol
_UNSAFE_FOR_V03 = re.compile(r'[|/\\\x00-\x1f\x7f]')


def legacy_name_ok(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not _UNSAFE_FOR_V03.search(name) and name == name.strip()


@dataclass
class ToLegacy:
    """A v2 director's file on its way to a v0.3 actor."""

    md5_offer: str | None
    sha256_offer: str | None
    started: bool = False
    next_index: int = 0
    md5: Any = field(default_factory=hashlib.md5)
    sha256: Any = field(default_factory=hashlib.sha256)


@dataclass
class LegacyBatch:
    """A v2 director's batch to a v0.3 actor."""

    director: Session
    actor: Session
    files: int
    # A batch of one is sent without BATCH_START / BATCH_END, like a v0.3 single send (D12)
    framed: bool


class FileBridge:
    def __init__(self, relay: "Relay"):
        self.relay = relay
        # v0.3 director → v2 actor: (director, file name) → transfer
        self.from_legacy: dict[tuple[Session, str], Transfer] = {}
        # (v0.3 director, v2 actor) → the batch id the bridge made up for its BATCH_START
        self.legacy_batches: dict[tuple[Session, Session], str] = {}
        # v2 director → v0.3 actor: (actor, file name) → transfer, and the batches
        self.to_legacy: dict[tuple[Session, str], Transfer] = {}
        self.batches_to_legacy: dict[str, LegacyBatch] = {}

    @property
    def log(self):
        return self.relay.log

    @staticmethod
    def can_receive(session: Session) -> bool:
        return FILES_CAPABILITY in session.capabilities

    # ==== v0.3 director → v2 actor ==================================================================

    async def legacy_request(self, director: Session, actor: Session, msg_data: dict) -> None:
        """FILEREQ from a v0.3 director to a v2 actor."""
        filename = msg_data.get("filename", "")
        size = msg_data.get("size", 0)
        checksum = str(msg_data.get("checksum", "")).lower()
        if not self.can_receive(actor):
            await director.send_text(format_message("FILEDENY", filename=filename,
                reason=f"{actor.name} uses an older vrcActorSync 0.4 preview; update it to receive files"))
            return
        if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            await director.send_text(format_message("FILEDENY", filename=filename,
                reason=f"Files over {MAX_FILE_BYTES // 2**30} GB can't be sent to vrcActorSync 0.4"))
            return
        if not _MD5.match(checksum):
            await director.send_text(format_message("FILEDENY", filename=filename, reason="Bad checksum in the request"))
            return
        old = self.from_legacy.pop((director, filename), None)
        if old is not None:
            self.relay.files.close(old, "replaced by a new request")
        transfer = Transfer(id=uuid.uuid4().hex, batch_id=self.legacy_batches.get((director, actor)), name=filename,
                            size=size, chunk_size=LEGACY_CHUNK_SIZE, sender=director, recipient=actor)
        self.relay.files.by_id[transfer.id] = transfer
        self.from_legacy[(director, filename)] = transfer
        offer: dict[str, Any] = {"transfer_id": transfer.id, "name": filename, "size": size,
                                 "chunk_size": LEGACY_CHUNK_SIZE, "md5": checksum}
        if transfer.batch_id:
            offer["batch_id"] = transfer.batch_id
        await self._to_v2(director, actor, "file.offer", offer)

    async def legacy_data(self, director: Session, msg_type: str, msg_data: dict) -> bool:
        """FILESTART / FILECHUNK / FILEEND from a v0.3 director. False when the file isn't bridged."""
        filename = msg_data.get("filename", "")
        transfer = self.from_legacy.get((director, filename))
        if transfer is None:
            return False
        if msg_type == "FILESTART":
            return True  # the offer already said how big the file is
        if msg_type == "FILECHUNK":
            try:
                payload = base64.b64decode(msg_data.get("data", ""), validate=True)
            except (binascii.Error, ValueError):
                await self._end_from_legacy(transfer, f"Chunk {msg_data.get('chunk_num')} isn't valid base64")
                return True
            try:
                await self.relay.files.chunk(director, pack_chunk(transfer.id, int(msg_data.get("chunk_num", 0)), payload))
            except Refused as exc:
                await self._end_from_legacy(transfer, str(exc))
            return True
        # FILEEND
        checksum = str(msg_data.get("checksum", "")).lower()
        if not _MD5.match(checksum):
            await self._end_from_legacy(transfer, "Bad checksum at the end of the file")
            return True
        await self._to_v2(director, transfer.recipient, "file.end", {"transfer_id": transfer.id, "md5": checksum})
        return True

    async def _end_from_legacy(self, transfer: Transfer, error: str) -> None:
        """A bridged file from a v0.3 director went wrong: both sides hear about it."""
        await self.relay.files.fail(transfer, error)

    async def legacy_batch(self, director: Session, actor: Session, msg_type: str, msg_data: dict) -> None:
        """BATCH_START / BATCH_END / BATCH_CANCEL from a v0.3 director to a v2 actor."""
        if not self.can_receive(actor):
            return  # as before: dropped (its FILEREQs are declined with a reason)
        key = (director, actor)
        if msg_type == "BATCH_START":
            batch_id = "b_" + uuid.uuid4().hex[:12]
            self.legacy_batches[key] = batch_id
            await self._to_v2(director, actor, "file.batch.start", {
                "batch_id": batch_id, "files": max(0, msg_data.get("file_count", 0)), "bytes": max(0, msg_data.get("total_bytes", 0))})
            return
        batch_id = self.legacy_batches.pop(key, None)
        if batch_id is None:
            return
        if msg_type == "BATCH_END":
            await self._to_v2(director, actor, "file.batch.end", {
                "batch_id": batch_id, "ok": max(0, msg_data.get("success_count", 0)), "failed": max(0, msg_data.get("fail_count", 0))})
            return
        for (d, name), transfer in list(self.from_legacy.items()):
            if d is director and transfer.batch_id == batch_id:
                self.from_legacy.pop((d, name), None)
                self.relay.files.close(transfer, "cancelled")
        await self._to_v2(director, actor, "file.batch.cancel", {"batch_id": batch_id, "reason": msg_data.get("reason", "")})

    def legacy_reply(self, env: Envelope, recipient: Session) -> str | None:
        """A v2 actor's reply, as the frame a v0.3 director expects (None: nothing to show)."""
        transfer = self.relay.files.by_id.get(str(env.data.get("transfer_id", "")))
        if transfer is None or transfer.sender is not recipient:
            return None
        name = transfer.name
        if env.type in ("file.ok", "file.deny", "file.err"):
            self.from_legacy.pop((recipient, name), None)
        if env.type == "file.accept":
            return format_message("FILEACK", filename=name, accept="1", save_dir="")
        if env.type == "file.deny":
            return format_message("FILEDENY", filename=name, reason=clean(env.data.get("reason") or "Declined"))
        if env.type == "file.ok":
            return format_message("FILEOK", filename=name, saved_path=clean(env.data.get("saved_as", "")))
        if env.type == "file.err":
            return format_message("FILEERR", filename=name, error=clean(env.data.get("error") or "Transfer failed"))
        return None  # file.progress: v0.3 directors have no use for it

    # ==== v2 director → v0.3 actor ==================================================================

    def check_offer(self, director: Session, actor: Session, offer) -> None:
        """Before a v2 director's offer to a v0.3 actor is registered. Raises Refused."""
        if actor.perm_role != "actor":
            raise Refused("unsupported", f"{actor.name} uses a v0.3 client that can't receive files", [actor.id])
        if not legacy_name_ok(offer.name):
            raise Refused("invalid", f"{actor.name} uses a v0.3 client, which can't take the file name {offer.name!r}")
        if offer.chunk_size % LEGACY_CHUNK_SIZE:
            raise Refused("invalid", "For v0.3 clients the chunk size must be a multiple of 64 KiB")
        if (actor, offer.name) in self.to_legacy:
            raise Refused("invalid", f"{actor.name} is already receiving a file named {offer.name}; try again when it's done")

    async def deliver(self, env: Envelope, sender: Session, recipient: Session) -> bool:
        """A v2 file.* message for a v0.3 client. Returns False when the client can't carry it."""
        if env.type in ("file.accept", "file.deny", "file.progress", "file.ok", "file.err"):
            text = self.legacy_reply(env, recipient)
            if text:
                await recipient.send_text(text)
            return True
        if recipient.perm_role != "actor":
            return False
        data = env.data
        if env.type == "file.batch.start":
            files = int(data.get("files", 0))
            batch = LegacyBatch(director=sender, actor=recipient, files=files, framed=files != 1)
            self.batches_to_legacy[str(data.get("batch_id"))] = batch
            if batch.framed:
                await recipient.send_text(format_message("BATCH_START", target=recipient.name, file_count=files,
                                                         total_bytes=int(data.get("bytes", 0))))
            return True
        if env.type == "file.offer":
            transfer = self.relay.files.by_id.get(str(data.get("transfer_id", "")))
            if transfer is None:
                return True
            transfer.leg = ToLegacy(md5_offer=data.get("md5"), sha256_offer=data.get("sha256"))
            self.to_legacy[(recipient, transfer.name)] = transfer
            await recipient.send_text(format_message("FILEREQ", sender=clean(sender.name), target=recipient.name,
                                                     filename=transfer.name, size=transfer.size,
                                                     checksum=data.get("md5") or ""))
            return True
        if env.type == "file.end":
            transfer = self.relay.files.by_id.get(str(data.get("transfer_id", "")))
            if transfer is not None and isinstance(transfer.leg, ToLegacy):
                await self._end_to_legacy(transfer, data.get("sha256"))
            return True
        if env.type in ("file.batch.end", "file.batch.cancel"):
            batch = self.batches_to_legacy.pop(str(data.get("batch_id")), None)
            if env.type == "file.batch.end":
                if batch is None or batch.framed:
                    await recipient.send_text(format_message("BATCH_END", target=recipient.name,
                                                             success_count=int(data.get("ok", 0)),
                                                             fail_count=int(data.get("failed", 0))))
                return True
            # Cancel: transfers.py has already ended the batch's transfers, so no more chunks pass
            for (actor, name), transfer in list(self.to_legacy.items()):
                if actor is recipient and transfer.batch_id == data.get("batch_id"):
                    self.to_legacy.pop((actor, name), None)
            await recipient.send_text(format_message("BATCH_CANCEL", target=recipient.name,
                                                     reason=clean(data.get("reason") or "Cancelled by the director")))
            return True
        return True

    async def chunk_to_legacy(self, transfer: Transfer, chunk: Chunk) -> str | None:
        """One binary chunk for a v0.3 actor, as FILECHUNK frames. Returns an error to end the transfer."""
        leg = transfer.leg
        actor = transfer.recipient
        if not isinstance(leg, ToLegacy):
            return "Not a transfer to a v0.3 client"
        if chunk.index != leg.next_index:
            return f"Chunk {chunk.index} arrived out of order (v0.3 clients need them in order)"
        if not leg.started:
            await self._start(transfer)
        per_chunk = transfer.chunk_size // LEGACY_CHUNK_SIZE
        for k, offset in enumerate(range(0, len(chunk.payload), LEGACY_CHUNK_SIZE)):
            piece = chunk.payload[offset:offset + LEGACY_CHUNK_SIZE]
            text = format_message("FILECHUNK", filename=transfer.name, chunk_num=chunk.index * per_chunk + k,
                                  data=base64.b64encode(piece).decode("ascii"))
            if not await actor.send_text(text):
                return f"{actor.name} disconnected"
        leg.md5.update(chunk.payload)
        leg.sha256.update(chunk.payload)
        leg.next_index += 1
        # Pace the director: these frames have gone out (v0.3 actors don't acknowledge chunks)
        await self._to_v2(actor, transfer.sender, "file.progress", {"transfer_id": transfer.id, "received": leg.next_index})
        return None

    async def _start(self, transfer: Transfer) -> None:
        transfer.leg.started = True
        chunks = (transfer.size + LEGACY_CHUNK_SIZE - 1) // LEGACY_CHUNK_SIZE
        await transfer.recipient.send_text(format_message("FILESTART", filename=transfer.name, total_chunks=chunks,
                                                          chunk_size=LEGACY_CHUNK_SIZE))

    async def _end_to_legacy(self, transfer: Transfer, sha256: str | None) -> None:
        leg: ToLegacy = transfer.leg
        if leg.next_index != transfer.chunks:
            await self.relay.files.fail(transfer, f"Only {leg.next_index} of {transfer.chunks} chunks arrived")
            return
        if sha256 and leg.sha256.hexdigest() != sha256:
            await self.relay.files.fail(transfer, "Checksum mismatch on the way through the relay")
            return
        if not leg.started:  # an empty file: the v0.3 actor only saves files it saw start
            await self._start(transfer)
        md5 = leg.md5_offer or leg.md5.hexdigest()
        await transfer.recipient.send_text(format_message("FILEEND", filename=transfer.name, checksum=md5))

    async def legacy_actor_reply(self, actor: Session, msg_type: str, msg_data: dict) -> bool:
        """FILEACK / FILEDENY / FILEOK / FILEERR from a v0.3 actor. False when the file isn't bridged."""
        filename = msg_data.get("filename", "")
        transfer = self.to_legacy.get((actor, filename))
        if transfer is None:
            return False
        files = self.relay.files
        if msg_type == "FILEACK" and msg_data.get("accept"):
            transfer.accepted = True
            await self._to_v2(actor, transfer.sender, "file.accept", {"transfer_id": transfer.id})
            return True
        self.to_legacy.pop((actor, filename), None)
        if msg_type in ("FILEACK", "FILEDENY"):
            reason = "Declined" if msg_type == "FILEACK" else msg_data.get("reason", "") or "Declined"
            await self._to_v2(actor, transfer.sender, "file.deny", {"transfer_id": transfer.id, "reason": reason[:500]})
            files.close(transfer, f"declined ({reason})")
        elif msg_type == "FILEOK":
            await self._to_v2(actor, transfer.sender, "file.ok", {"transfer_id": transfer.id,
                                                                  "saved_as": msg_data.get("saved_path", "")[:512]})
            files.close(transfer, "ok")
        else:
            error = msg_data.get("error", "") or "failed"
            await self._to_v2(actor, transfer.sender, "file.err", {"transfer_id": transfer.id, "error": error[:500]})
            files.close(transfer, f"failed ({error})")
        return True

    # ==== both directions ===========================================================================

    async def error_to_legacy(self, session: Session, transfer: Transfer, error: str) -> None:
        """The relay ended a bridged transfer; tell the v0.3 side in its own terms."""
        if session is transfer.sender:  # a v0.3 director
            self.from_legacy.pop((session, transfer.name), None)
            await session.send_text(format_message("FILEERR", filename=transfer.name, error=clean(error)))
        else:  # a v0.3 actor: there's no "abort this file"; a cancelled batch is the closest
            self.to_legacy.pop((session, transfer.name), None)
            await session.send_text(format_message("BATCH_CANCEL", target=session.name, reason=clean(error)))

    def forget_session(self, session: Session) -> None:
        for key in [k for k in self.from_legacy if session in (k[0], self.from_legacy[k].recipient)]:
            self.from_legacy.pop(key, None)
        for key in [k for k in self.legacy_batches if session in k]:
            self.legacy_batches.pop(key, None)
        for key in [k for k in self.to_legacy if session in (k[0], self.to_legacy[k].sender)]:
            self.to_legacy.pop(key, None)
        for batch_id in [b for b, v in self.batches_to_legacy.items() if session in (v.director, v.actor)]:
            self.batches_to_legacy.pop(batch_id, None)

    async def _to_v2(self, sender: Session, recipient: Session, msg_type: str, data: dict) -> None:
        if recipient.legacy:
            return
        from .router import frame

        env = make(msg_type, data, to={"ids": [recipient.id]}, from_=sender.id or None, ts=self.relay.clock.now_ms())
        await recipient.send_text(frame(env))


def clean(text: Any) -> str:
    return str(text).replace("|", "/").replace("\n", " ")
