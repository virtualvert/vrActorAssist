"""Files addon (spec §8.4): directors send batches of files; actors receive them.

Protocol: file.* messages plus binary chunk frames (vrcas_protocol.chunks, spec §5.7). Every send
is a batch, even one file. Files go one at a time per actor, with at most MAX_IN_FLIGHT chunks on
the way; each written chunk is acknowledged with file.progress. Cancel works at any point: the
director stops sending and the actor deletes the partial file.

Receiving (actors):
- An offer is checked first (file name, size, free space), then accepted at once (auto-accept) or
  shown to the actor, who accepts or declines. One prompt per file; it says when the file
  replaces one already there (spec §8.4, decision D4 of the Phase 2 plan).
- Chunks go to a hidden `.part` file next to the target; at file.end the hash is checked and the
  part file renamed over the target in one step.
- Received files are recorded in received.json (path and SHA-256), for `{sha256}` sound
  references and adding to Soundpad later (§8.1.3).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from vrcas_protocol import CHUNK_SIZE, MAX_FILE_BYTES, MAX_IN_FLIGHT, Chunk, chunk_count, pack_chunk, unpack_chunk
from vrcas_protocol import validate

if TYPE_CHECKING:
    from .core import Agent

RECEIVED_LOG = "received.json"
RECEIVED_LOG_MAX = 2000
RECENT_MAX = 20
BATCHES_KEPT = 10
# Free space to leave on the disk after a received file
DISK_MARGIN = 50 * 1024 * 1024
# Sending: how long to wait for progress once data flows, and for the result after file.end
STALL_TIMEOUT_S = 60.0
RESULT_TIMEOUT_S = 120.0
MAX_NAME = 200
HASH_BLOCK = 1024 * 1024

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class FileRefused(Exception):
    """A file this machine won't take; the message goes back to the sender."""


def safe_name(name: str) -> str:
    """The name a received file is saved under. Only a plain file name passes: no folders, no `..`,
    nothing Windows can't store (`<>:"/\\|?*`, control characters, `CON`, `NUL`, ..., trailing dots
    or spaces). Refuses rather than renames, so the director sees which file didn't arrive and why."""
    if not isinstance(name, str) or not name:
        raise FileRefused("The file has no name")
    if _UNSAFE_CHARS.search(name):
        raise FileRefused(f"{name!r} has characters a file name can't have here")
    if name in (".", "..") or name != name.strip() or name.endswith("."):
        raise FileRefused(f"{name!r} isn't a usable file name")
    if name.split(".", 1)[0].upper() in _RESERVED:
        raise FileRefused(f"{name!r} is a reserved name on Windows")
    if len(name) > MAX_NAME:
        raise FileRefused(f"The file name is longer than {MAX_NAME} characters")
    return name


def default_receive_dir() -> Path:
    """Documents/vrcActorSync (decision D3). The v0.3 `receive_dir` replaces it when imported."""
    return Path.home() / "Documents" / "vrcActorSync"


def file_hashes(path: Path) -> tuple[str, str, int]:
    """(sha256, md5, size) in one pass. md5 is what v0.3 actors check (their FILEEND)."""
    sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
    with open(path, "rb") as handle:
        while block := handle.read(HASH_BLOCK):
            sha.update(block)
            md5.update(block)
            size += len(block)
    return sha.hexdigest(), md5.hexdigest(), size


def size_text(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def parse_character_name(filename: str) -> str | None:
    """`Scene 4 - Diego.mp3` → `Diego`; the last " - " wins; None without the pattern.
    Same rule as the v0.3 director (director_client_ws.py) and web/src/lib/files/character.ts."""
    if " - " not in filename:
        return None
    character = filename.rsplit(" - ", 1)[-1].rsplit(".", 1)[0].strip()
    return character or None


# ---- receiving ---------------------------------------------------------------------------------


@dataclass(eq=False)
class Incoming:
    transfer_id: str
    batch_id: str | None
    name: str
    size: int
    chunk_size: int
    sha256: str | None
    md5: str | None
    character: str | None
    sender_id: str
    sender_name: str
    folder: Path
    replaces: bool
    index: int | None = None
    count: int | None = None
    state: str = "asking"  # asking → receiving
    received: set[int] = field(default_factory=set)
    handle: Any = None
    asked_at: float = field(default_factory=time.time)

    @property
    def target(self) -> Path:
        return self.folder / self.name

    @property
    def part(self) -> Path:
        return self.folder / f".{self.name}.{self.transfer_id[:8]}.part"

    @property
    def chunks(self) -> int:
        return chunk_count(self.size, self.chunk_size)

    def received_bytes(self) -> int:
        if not self.received:
            return 0
        full = len(self.received) * self.chunk_size
        last = self.chunks - 1
        if last in self.received:
            full -= self.chunk_size - (self.size - last * self.chunk_size)
        return full

    def view(self) -> dict:
        return {
            "transferId": self.transfer_id,
            "batchId": self.batch_id,
            "name": self.name,
            "size": self.size,
            "from": self.sender_name,
            "character": self.character,
            "replaces": self.replaces,
            "index": self.index,
            "count": self.count,
            "state": self.state,
            "receivedBytes": self.received_bytes(),
        }


@dataclass
class IncomingBatch:
    sender_id: str
    files: int
    seen: int = 0
    # The actor pressed "Accept the rest of this batch"
    accept_rest: bool = False


class Receiver:
    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.incoming: dict[str, Incoming] = {}
        self.batches: dict[str, IncomingBatch] = {}
        self.recent: deque[dict] = deque(maxlen=RECENT_MAX)

    @property
    def log(self):
        return self.agent.hub.log

    def folder(self) -> Path:
        configured = self.agent.config.files.receive_dir
        return Path(configured).expanduser() if configured else default_receive_dir()

    def view(self) -> dict:
        cfg = self.agent.config.files
        return {
            "receiveDir": str(self.folder()),
            "autoAccept": cfg.auto_accept,
            "incoming": [i.view() for i in self.incoming.values()],
            "recent": list(self.recent),
        }

    # ---- relay messages -----------------------------------------------------------------------------

    async def on_message(self, env: dict, sender_name: str) -> None:
        msg_type = env.get("type")
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        sender = env.get("from") or ""
        try:
            payload = validate(msg_type, data)
        except ValueError as exc:
            if msg_type == "file.offer" and isinstance(data.get("transfer_id"), str):
                await self._send("file.deny", {"transfer_id": data["transfer_id"], "reason": f"Bad offer: {exc}"[:400]}, sender)
            return
        if msg_type == "file.batch.start":
            self.batches[payload.batch_id] = IncomingBatch(sender_id=sender, files=payload.files)
            self.log("info", f"{sender_name} is sending {payload.files} file{'s' if payload.files != 1 else ''} "
                             f"({size_text(payload.bytes)})")
        elif msg_type == "file.offer":
            await self._offer(payload, sender, sender_name)
        elif msg_type == "file.end":
            item = self.incoming.get(payload.transfer_id)
            if item and item.sender_id == sender:
                await self._finish(item, payload.sha256, payload.md5)
        elif msg_type == "file.batch.end":
            self.batches.pop(payload.batch_id, None)
            self.log("info", f"{sender_name}'s batch is done: {payload.ok} received"
                             + (f", {payload.failed} not" if payload.failed else ""))
        elif msg_type == "file.batch.cancel":
            self.batches.pop(payload.batch_id, None)
            dropped = [i for i in self.incoming.values() if i.batch_id == payload.batch_id and i.sender_id == sender]
            for item in dropped:
                self._discard(item)
                self._remember(item, False, "cancelled by the director")
            self.log("warning", f"{sender_name} cancelled the batch" + (f": {payload.reason}" if payload.reason else ""))
        elif msg_type == "file.err":
            item = self.incoming.get(payload.transfer_id)
            if item:
                self._discard(item)
                self._remember(item, False, payload.error or "failed")
                self.log("warning", f"{item.name} didn't arrive: {payload.error or 'the transfer failed'}")
        self.agent.changed()

    async def _offer(self, offer, sender: str, sender_name: str) -> None:
        batch = self.batches.get(offer.batch_id) if offer.batch_id else None
        index = None
        if batch is not None and batch.sender_id == sender:
            batch.seen += 1
            index = batch.seen
        try:
            if self.agent.config.role not in ("actor", "camera"):
                raise FileRefused("This computer isn't set up to receive files")
            name = safe_name(offer.name)
            folder = self.folder()
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise FileRefused(f"Can't use the receive folder: {exc.strerror or exc}") from None
            target = folder / name
            if target.is_dir():
                raise FileRefused(f"{name} is a folder on the actor's computer")
            if shutil.disk_usage(folder).free < offer.size + DISK_MARGIN:
                raise FileRefused("Not enough free disk space")
            if offer.transfer_id in self.incoming:
                raise FileRefused("That transfer is already open")
        except FileRefused as exc:
            await self._send("file.deny", {"transfer_id": offer.transfer_id, "reason": str(exc)}, sender)
            self.log("warning", f"Declined {offer.name} from {sender_name}: {exc}")
            return
        item = Incoming(
            transfer_id=offer.transfer_id, batch_id=offer.batch_id, name=name, size=offer.size,
            chunk_size=offer.chunk_size, sha256=offer.sha256, md5=offer.md5, character=offer.character,
            sender_id=sender, sender_name=sender_name, folder=folder, replaces=target.exists(),
            index=index, count=batch.files if batch else None,
        )
        self.incoming[item.transfer_id] = item
        if self.agent.config.files.auto_accept or (batch is not None and batch.accept_rest):
            await self._accept(item)
        else:
            self.agent.hub.toast("info", f"{sender_name} wants to send {name}")
            self.log("info", f"{sender_name} wants to send {name} ({size_text(item.size)})"
                             + (" — it replaces your copy" if item.replaces else ""))

    # ---- the actor's answer ----------------------------------------------------------------------

    async def answer(self, transfer_id: str, accept: bool, rest: bool = False, always: bool = False) -> None:
        item = self.incoming.get(transfer_id)
        if item is None or item.state != "asking":
            return
        if always:
            self.agent.config.files.auto_accept = True
            self.agent.store.save()
        if not accept:
            self.incoming.pop(transfer_id, None)
            await self._send("file.deny", {"transfer_id": transfer_id, "reason": "Declined"}, item.sender_id)
            self._remember(item, False, "declined")
            self.log("info", f"Declined {item.name}")
            return
        if rest and item.batch_id in self.batches:
            self.batches[item.batch_id].accept_rest = True
        await self._accept(item)
        # Accepting with "the rest" or "always" also answers the other open prompts from that director
        for other in list(self.incoming.values()):
            if other.state == "asking" and other.sender_id == item.sender_id and (
                always or (rest and other.batch_id == item.batch_id)
            ):
                await self._accept(other)

    async def _accept(self, item: Incoming) -> None:
        try:
            item.handle = await asyncio.to_thread(open, item.part, "wb")
        except OSError as exc:
            self.incoming.pop(item.transfer_id, None)
            await self._send("file.deny", {"transfer_id": item.transfer_id, "reason": f"Can't write the file: {exc.strerror or exc}"}, item.sender_id)
            self._remember(item, False, "couldn't be written")
            return
        item.state = "receiving"
        await self._send("file.accept", {"transfer_id": item.transfer_id}, item.sender_id)
        self.log("info", f"Receiving {item.name} ({size_text(item.size)}) from {item.sender_name}")

    # ---- data ------------------------------------------------------------------------------------

    async def on_chunk(self, frame: bytes) -> None:
        try:
            chunk = unpack_chunk(frame)
        except ValueError:
            return
        item = self.incoming.get(chunk.transfer_id)
        if item is None or item.state != "receiving":
            return  # declined, cancelled, or never offered: nothing is written
        if not self._fits(item, chunk):
            await self._fail(item, f"Chunk {chunk.index} doesn't fit the file")
            return
        if chunk.index not in item.received:
            try:
                await asyncio.to_thread(_write_at, item.handle, chunk.index * item.chunk_size, chunk.payload)
            except OSError as exc:
                await self._fail(item, f"Writing failed: {exc.strerror or exc}")
                return
            item.received.add(chunk.index)
        await self._send("file.progress", {"transfer_id": item.transfer_id, "received": len(item.received)}, item.sender_id)
        self.agent.changed()

    @staticmethod
    def _fits(item: Incoming, chunk: Chunk) -> bool:
        if chunk.index >= item.chunks:
            return False
        last = chunk.index == item.chunks - 1
        expected = item.size - chunk.index * item.chunk_size if last else item.chunk_size
        return len(chunk.payload) == expected

    async def _finish(self, item: Incoming, sha256: str | None, md5: str | None) -> None:
        if item.state != "receiving":
            return
        if len(item.received) != item.chunks:
            await self._fail(item, f"Only {len(item.received)} of {item.chunks} chunks arrived")
            return
        expected_sha = sha256 or item.sha256
        expected_md5 = md5 or item.md5
        try:
            await asyncio.to_thread(item.handle.close)
            item.handle = None
            actual_sha, actual_md5, size = await asyncio.to_thread(file_hashes, item.part)
        except OSError as exc:
            await self._fail(item, f"Reading the file back failed: {exc.strerror or exc}")
            return
        if size != item.size:
            await self._fail(item, f"Size mismatch ({size} of {item.size} bytes)")
            return
        if (expected_sha and actual_sha != expected_sha) or (not expected_sha and expected_md5 != actual_md5):
            await self._fail(item, "Checksum mismatch")
            return
        try:
            await asyncio.to_thread(os.replace, item.part, item.target)
        except OSError as exc:
            await self._fail(item, f"Saving failed: {exc.strerror or exc}")
            return
        self.incoming.pop(item.transfer_id, None)
        saved_as = f"{item.folder.name}/{item.name}"
        await self._send("file.ok", {"transfer_id": item.transfer_id, "saved_as": saved_as}, item.sender_id)
        self._remember(item, True, "replaced your copy" if item.replaces else "")
        self._record(item, actual_sha)
        self.log("success", f"Received {item.name} ({size_text(item.size)}, sha256 {actual_sha[:12]}…) from "
                            f"{item.sender_name} → {item.target}")

    async def _fail(self, item: Incoming, error: str) -> None:
        self._discard(item)
        await self._send("file.err", {"transfer_id": item.transfer_id, "error": error}, item.sender_id)
        self._remember(item, False, error)
        self.log("error", f"{item.name} from {item.sender_name}: {error}")

    def _discard(self, item: Incoming) -> None:
        """Forget a transfer and delete its partial file."""
        self.incoming.pop(item.transfer_id, None)
        if item.handle is not None:
            try:
                item.handle.close()
            except OSError:
                pass
            item.handle = None
        try:
            item.part.unlink(missing_ok=True)
        except OSError:
            pass

    def reset(self, reason: str) -> None:
        """The relay connection is gone: every open transfer is void."""
        for item in list(self.incoming.values()):
            self._discard(item)
            self._remember(item, False, reason)
            self.log("warning", f"{item.name} from {item.sender_name} not saved: {reason}")
        self.batches.clear()

    # ---- records ---------------------------------------------------------------------------------

    def _remember(self, item: Incoming, ok: bool, detail: str) -> None:
        self.recent.appendleft({"name": item.name, "ok": ok, "at": int(time.time() * 1000), "from": item.sender_name,
                                "detail": detail})

    def _record(self, item: Incoming, sha256: str) -> None:
        path = self.agent.store.folder / RECEIVED_LOG
        entries = load_received(path)
        entries = [e for e in entries if e.get("path") != str(item.target)]
        entries.append({"sha256": sha256, "path": str(item.target), "name": item.name, "from": item.sender_name,
                        "at": int(time.time() * 1000)})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries[-RECEIVED_LOG_MAX:], indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            self.log("warning", f"Couldn't update {RECEIVED_LOG}: {exc}")

    async def _send(self, msg_type: str, data: dict, to: str) -> None:
        try:
            await self.agent.files.send(msg_type, data, {"ids": [to]})
        except RuntimeError:
            pass  # the relay connection is gone; reset() cleans up


def _write_at(handle, offset: int, payload: bytes) -> None:
    handle.seek(offset)
    handle.write(payload)


def load_received(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


# ---- sending -----------------------------------------------------------------------------------


@dataclass(eq=False)
class Outgoing:
    path: Path
    name: str
    character: str | None
    size: int = 0
    transfer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sha256: str = ""
    md5: str = ""
    state: str = "queued"  # queued → offered → sending → ok | declined | failed | cancelled
    acked: int = 0
    sent: int = 0
    detail: str = ""
    decision: asyncio.Future | None = None
    # The id of the file.offer message, which a relay error names in reply_to
    offer_id: str | None = None
    result: asyncio.Future | None = None
    progress: asyncio.Event = field(default_factory=asyncio.Event)
    chunk_size: int = CHUNK_SIZE

    @property
    def chunks(self) -> int:
        return chunk_count(self.size, self.chunk_size)


@dataclass(eq=False)
class Batch:
    id: str
    actor_id: str
    actor_name: str
    files: list[Outgoing]
    state: str = "waiting"  # waiting → sending → done | cancelled | failed
    detail: str = ""
    task: asyncio.Task | None = None

    @property
    def ok(self) -> int:
        return sum(f.state == "ok" for f in self.files)

    @property
    def failed(self) -> int:
        return sum(f.state in ("declined", "failed", "cancelled") for f in self.files)

    def view(self) -> dict:
        current = next((f for f in self.files if f.state in ("offered", "sending")), None)
        total = sum(f.size for f in self.files)
        sent = sum(f.size if f.state == "ok" else min(f.size, f.acked * f.chunk_size) for f in self.files)
        return {
            "id": self.id,
            "actorId": self.actor_id,
            "actorName": self.actor_name,
            "files": len(self.files),
            "done": self.ok + self.failed,
            "ok": self.ok,
            "failed": self.failed,
            "bytes": total,
            "sentBytes": sent,
            "current": None if current is None else {
                "name": current.name,
                "size": current.size,
                "sent": min(current.size, current.acked * current.chunk_size),
                "waiting": current.state == "offered",
            },
            "state": self.state,
            "detail": self.detail,
            "results": [{"name": f.name, "state": f.state, "detail": f.detail} for f in self.files],
        }


class Sender:
    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.batches: dict[str, Batch] = {}
        self._by_transfer: dict[str, Outgoing] = {}

    @property
    def log(self):
        return self.agent.hub.log

    def view(self) -> dict:
        return {"batches": [b.view() for b in self.batches.values()]}

    def start(self, actor_id: str, actor_name: str, paths: list[Path]) -> Batch:
        """One batch to one actor; runs in the background. Paths are already checked (folders.py)."""
        files = [Outgoing(path=p, name=p.name, character=parse_character_name(p.name)) for p in paths]
        batch = Batch(id="b_" + uuid.uuid4().hex[:12], actor_id=actor_id, actor_name=actor_name, files=files)
        self.batches[batch.id] = batch
        self._trim()
        batch.task = asyncio.get_running_loop().create_task(self._run(batch))
        return batch

    def _trim(self) -> None:
        finished = [b for b in self.batches.values() if b.state in ("done", "cancelled", "failed")]
        for batch in finished[: max(0, len(self.batches) - BATCHES_KEPT)]:
            self.batches.pop(batch.id, None)

    async def cancel(self, batch_id: str) -> None:
        targets = list(self.batches.values()) if batch_id == "all" else [self.batches[batch_id]] if batch_id in self.batches else []
        for batch in targets:
            if batch.task is not None and not batch.task.done():
                batch.task.cancel()
                try:
                    await batch.task
                except (asyncio.CancelledError, Exception):
                    pass

    def reset(self, reason: str) -> None:
        for batch in self.batches.values():
            if batch.task is not None and not batch.task.done():
                batch.detail = reason
                batch.task.cancel()

    # ---- replies from the actor -----------------------------------------------------------------

    def on_message(self, env: dict) -> None:
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        item = self._by_transfer.get(str(data.get("transfer_id", "")))
        if item is None:
            return
        msg_type = env.get("type")
        if msg_type == "file.accept" and item.decision and not item.decision.done():
            item.decision.set_result(("accept", ""))
        elif msg_type == "file.deny":
            self._settle(item, ("deny", str(data.get("reason") or "Declined")))
        elif msg_type == "file.progress":
            received = data.get("received")
            if isinstance(received, int) and received > item.acked:
                item.acked = received
                item.progress.set()
                self.agent.changed()
        elif msg_type == "file.ok":
            self._settle(item, ("ok", str(data.get("saved_as") or "")))
        elif msg_type == "file.err":
            self._settle(item, ("err", str(data.get("error") or "failed")))

    def on_error(self, reply_to: Any, message: str) -> bool:
        """A relay `error` about one of our offers: that file fails. True when it was ours."""
        item = next((i for i in self._by_transfer.values() if reply_to and i.offer_id == reply_to), None)
        if item is None:
            return False
        self._settle(item, ("err", message or "The relay refused the file"))
        return True

    @staticmethod
    def _settle(item: Outgoing, outcome: tuple[str, str]) -> None:
        for future in (item.decision, item.result):
            if future is not None and not future.done():
                future.set_result(outcome)
        item.progress.set()

    # ---- the batch ------------------------------------------------------------------------------

    async def _run(self, batch: Batch) -> None:
        files = self.agent.files
        to = {"ids": [batch.actor_id]}
        current: Outgoing | None = None
        try:
            for item in batch.files:
                item.sha256, item.md5, item.size = await asyncio.to_thread(file_hashes, item.path)
            await files.send("file.batch.start", {"batch_id": batch.id, "files": len(batch.files),
                                                  "bytes": sum(f.size for f in batch.files)}, to)
            batch.state = "sending"
            self.agent.changed()
            for item in batch.files:
                current = item
                await self._send_file(batch, item, to)
                self.agent.changed()
            current = None
            await files.send("file.batch.end", {"batch_id": batch.id, "ok": batch.ok, "failed": batch.failed}, to)
            batch.state = "done"
            level = "success" if not batch.failed else "warning"
            problems = [f"{f.name}: {f.detail or f.state}" for f in batch.files if f.state != "ok"]
            self.log(level, f"Files to {batch.actor_name}: {batch.ok} sent" + (f", {batch.failed} not" if batch.failed else "")
                     + (f" ({'; '.join(problems[:3])}{'; …' if len(problems) > 3 else ''})" if problems else ""))
        except asyncio.CancelledError:
            batch.state = "cancelled"
            for item in batch.files:
                if item.state in ("queued", "offered", "sending"):
                    item.state = "cancelled"
            try:
                await files.send("file.batch.cancel", {"batch_id": batch.id, "reason": batch.detail or "Cancelled by the director"}, to)
            except RuntimeError:
                pass
            self.log("warning", f"Files to {batch.actor_name} cancelled" + (f" ({current.name})" if current else ""))
        except (OSError, RuntimeError) as exc:
            batch.state = "failed"
            batch.detail = str(exc)
            for item in batch.files:
                if item.state in ("queued", "offered", "sending"):
                    item.state = "failed"
            self.log("error", f"Files to {batch.actor_name} stopped: {exc}")
        finally:
            for item in batch.files:
                self._by_transfer.pop(item.transfer_id, None)
            self.agent.changed()

    async def _send_file(self, batch: Batch, item: Outgoing, to: dict) -> None:
        files = self.agent.files
        loop = asyncio.get_running_loop()
        item.decision, item.result = loop.create_future(), loop.create_future()
        self._by_transfer[item.transfer_id] = item
        offer = {"transfer_id": item.transfer_id, "batch_id": batch.id, "name": item.name, "size": item.size,
                 "chunk_size": item.chunk_size, "sha256": item.sha256, "md5": item.md5}
        if item.character:
            offer["character"] = item.character
        item.state = "offered"
        item.offer_id = await files.send("file.offer", offer, to)
        self.agent.changed()
        verdict, detail = await item.decision  # no time limit: the actor may be away; Cancel ends it
        if verdict != "accept":
            self._finish(item, verdict, detail)
            return
        item.state = "sending"
        self.agent.changed()
        handle = await asyncio.to_thread(open, item.path, "rb")
        try:
            for index in range(item.chunks):
                while index - item.acked >= MAX_IN_FLIGHT and not item.result.done():
                    item.progress.clear()
                    try:
                        await asyncio.wait_for(item.progress.wait(), STALL_TIMEOUT_S)
                    except asyncio.TimeoutError:
                        raise _Stalled() from None
                if item.result.done():
                    break
                payload = await asyncio.to_thread(handle.read, item.chunk_size)
                await files.send_frame(pack_chunk(item.transfer_id, index, payload))
                item.sent = index + 1
        except _Stalled:
            self._finish(item, "err", f"{batch.actor_name} stopped answering")
            await files.send("file.batch.cancel", {"batch_id": batch.id, "reason": "Stalled"}, to)
            raise RuntimeError(f"{batch.actor_name} stopped answering") from None
        finally:
            await asyncio.to_thread(handle.close)
        if not item.result.done():
            await files.send("file.end", {"transfer_id": item.transfer_id, "sha256": item.sha256}, to)
        try:
            verdict, detail = await asyncio.wait_for(item.result, RESULT_TIMEOUT_S)
        except asyncio.TimeoutError:
            verdict, detail = "err", "No answer after the last chunk"
        self._finish(item, verdict, detail)

    def _finish(self, item: Outgoing, verdict: str, detail: str) -> None:
        item.state = {"ok": "ok", "deny": "declined"}.get(verdict, "failed")
        item.detail = detail
        self._by_transfer.pop(item.transfer_id, None)
        if item.state == "ok":
            item.acked = item.chunks


class _Stalled(Exception):
    pass


# ---- the addon -----------------------------------------------------------------------------------


class Files:
    """Owns both sides; the relay connection hands it file.* messages and binary frames."""

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self.receiver = Receiver(agent)
        self.sender = Sender(agent)

    def _relay(self):
        impl = self.agent.relay.impl
        if impl.legacy or impl.status != "connected":
            raise RuntimeError("Files need a connection to a v2 relay")
        return impl

    async def send(self, msg_type: str, data: dict, to: Any) -> str:
        return await self._relay().send(msg_type, data, to)

    async def send_frame(self, frame: bytes) -> None:
        await self._relay().send_frame(frame)

    async def on_message(self, env: dict, sender_name: str) -> None:
        msg_type = env.get("type")
        if msg_type in ("file.accept", "file.deny", "file.progress", "file.ok") or (
            msg_type == "file.err" and self._is_outgoing(env)
        ):
            self.sender.on_message(env)
            return
        await self.receiver.on_message(env, sender_name)

    def _is_outgoing(self, env: dict) -> bool:
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        return str(data.get("transfer_id", "")) in self.sender._by_transfer

    async def on_chunk(self, frame: bytes) -> None:
        await self.receiver.on_chunk(frame)

    def reset(self, reason: str) -> None:
        self.receiver.reset(reason)
        self.sender.reset(reason)

    def sizes_ok(self, paths: list[Path]) -> None:
        for path in paths:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise FileRefused(f"{path.name} is larger than {MAX_FILE_BYTES // 2**30} GB")
