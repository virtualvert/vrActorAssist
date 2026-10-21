"""Message payloads (`data`) for protocol v2, one model per type (spec §5.4, §5.6, §8.2.1).

The relay validates the core types it handles or translates. Addon types it only routes have no
model here yet (MODELS maps them to None); their addon defines the payload when it's built.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .chunks import CHUNK_SIZE, MAX_FILE_BYTES, MIN_CHUNK_SIZE, chunk_count
from .envelope import Role


class Payload(BaseModel):
    # Unknown fields are ignored, so an older relay or agent accepts a newer peer's messages.
    model_config = ConfigDict(extra="ignore")


class Scheduled(Payload):
    """Action messages may carry `at`, a time in server-clock ms (§5.3). Without it: act on receipt."""

    at: int | None = None


# ---- handshake (§5.6) -----------------------------------------------------------------------


class Hello(Payload):
    role: Role
    name: str = Field(min_length=1, max_length=40)
    machine_id: str = Field(min_length=1, max_length=128)
    version: str = Field(default="", max_length=32)
    platform: str = Field(default="", max_length=32)
    capabilities: list[str] = Field(default_factory=list, max_length=64)
    # Directors and assistants only
    secret: str | None = Field(default=None, max_length=256)


class IceServer(Payload):
    urls: list[str]
    username: str | None = None
    credential: str | None = None


class Welcome(Payload):
    session_id: str
    # The name the relay shows for you (a director may have renamed an actor)
    name: str
    role: Role
    server_version: str
    version_status: Literal["ok", "warning", "unsupported"]
    version_message: str = ""
    server_time: int
    delay_ms: int = 0
    ice_servers: list[IceServer] = Field(default_factory=list)


class Denied(Payload):
    reason: str


ErrorCode = Literal["forbidden", "invalid", "not_approved", "unknown_type", "unknown_target", "unsupported"]


class ProtocolError(Payload):
    """The envelope's `reply_to` names the message this is about."""

    code: ErrorCode
    message: str = ""
    # The rejected message's type, and for unknown_target / unsupported the session ids concerned
    type: str | None = None
    ids: list[str] | None = None


# ---- presence --------------------------------------------------------------------------------


class RosterSession(Payload):
    id: str
    name: str
    role: Role
    # A v0.3 client on /ws: it can only do what the pipe protocol carries (§11.3)
    legacy: bool = False
    version: str = ""
    platform: str = ""
    capabilities: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    timed_out: bool = False
    delay_ms: int = 0


class PendingRequest(Payload):
    machine_id: str
    name: str
    role: Role
    legacy: bool = False


class PresenceRoster(Payload):
    """Everyone approved and connected, including the recipient. `pending` is filled for
    directors and assistants only."""

    sessions: list[RosterSession]
    pending: list[PendingRequest] = Field(default_factory=list)


class LatencyEntry(Payload):
    id: str
    latency_ms: int | None = None
    timed_out: bool = False


class PresenceLatency(Payload):
    sessions: list[LatencyEntry]


# ---- approvals and per-actor settings --------------------------------------------------------


class ApprovalPending(Payload):
    """To a client that has to wait for a director."""


class ApprovalApprove(Payload):
    machine_id: str = Field(min_length=1, max_length=128)


class ApprovalDeny(Payload):
    machine_id: str = Field(min_length=1, max_length=128)


class ApprovalForget(Payload):
    """By session id (connected) or machine id (also works while they're offline)."""

    id: str | None = None
    machine_id: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "ApprovalForget":
        if not self.id and not self.machine_id:
            raise ValueError("id or machine_id is required")
        return self


class ApprovalForgotten(Payload):
    """To a client a director just removed. The relay closes the connection after it."""


class ActorSettings(Payload):
    id: str
    delay_ms: int | None = Field(default=None, ge=-10_000, le=10_000)
    display_name: str | None = Field(default=None, min_length=1, max_length=40)


# ---- chat, time, updates ---------------------------------------------------------------------


class ChatMsg(Payload):
    text: str = Field(min_length=1, max_length=2000)


class ChatPriv(Payload):
    text: str = Field(min_length=1, max_length=2000)


class TimePing(Payload):
    t0: int


class TimePong(Payload):
    """t0: sender's send time; t1: receiver's receive time; t2: receiver's send time (ms)."""

    t0: int
    t1: int
    t2: int


class UpdateAvailable(Payload):
    latest_version: str
    download_url: str
    sha256: str = ""
    release_notes: str = ""


# ---- cues (legacy-compatible semantics) --------------------------------------------------------


class CueGo(Scheduled):
    """Play the actor's selected sound (v0.3 `*go`)."""


class CueStop(Scheduled):
    pass


class CuePlay(Scheduled):
    """Play by All-sounds index (v0.3 `*play:N`)."""

    index: int = Field(ge=1)


class CueAck(Payload):
    command: str
    ok: bool
    error: str | None = None
    late_ms: int | None = None


# ---- addon messages the relay translates for v0.3 clients --------------------------------------


class SoundRef(Payload):
    """One of: path, sha256, index, category + position, selected (§8.1.3)."""

    path: str | None = None
    sha256: str | None = None
    index: int | None = Field(default=None, ge=1)
    category: str | None = None
    position: int | None = Field(default=None, ge=1)
    selected: bool | None = None


class SoundpadPlay(Scheduled):
    sound: SoundRef
    lines: Literal["both", "speakers", "mic"] | None = None
    volume: int | None = Field(default=None, ge=0, le=100)
    start_ms: int | None = Field(default=None, ge=0)
    cuelist_id: str | None = None


class SoundpadStop(Scheduled):
    pass


class SoundpadAck(Payload):
    status: str
    late_ms: int | None = None
    error: str | None = None


class OscParam(Scheduled):
    """`parameter` is a VRChat avatar parameter name, or a full address starting with '/'."""

    parameter: str = Field(min_length=1, max_length=256)
    value: Union[bool, int, float, str]


# ---- files addon (spec §8.4, §5.7) ------------------------------------------------------------
# The bytes travel as binary frames (chunks.py). Every reply goes to the session that sent the offer.

# The 16-byte UUID of the binary chunk frames, as 32 hex characters
TransferId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Md5 = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


def _one_hash(payload: "Payload") -> None:
    if not getattr(payload, "sha256", None) and not getattr(payload, "md5", None):
        raise ValueError("sha256 or md5 is required")


class FileBatchStart(Payload):
    """Every send from the new app is a batch, even one file. Files are offered one at a time."""

    batch_id: str = Field(min_length=1, max_length=64)
    files: int = Field(ge=0)
    bytes: int = Field(ge=0)


class FileOffer(Payload):
    """To exactly one session. `chunk_size` is set per offer: the relay's bridge passes a v0.3
    director's 64 KiB chunks through as they are. `md5` is for v0.3 actors (their FILEEND)."""

    transfer_id: TransferId
    batch_id: str | None = Field(default=None, min_length=1, max_length=64)
    # A file name only (no folders); the receiver checks it again before writing
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0, le=MAX_FILE_BYTES)
    chunk_size: int = Field(default=CHUNK_SIZE, ge=MIN_CHUNK_SIZE, le=CHUNK_SIZE)
    sha256: Sha256 | None = None
    md5: Md5 | None = None
    # From the file name (" - Diego.mp3"), shown to the actor
    character: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _hashes(self) -> "FileOffer":
        _one_hash(self)
        return self

    @property
    def chunks(self) -> int:
        return chunk_count(self.size, self.chunk_size)


class FileAccept(Payload):
    transfer_id: TransferId


class FileDeny(Payload):
    transfer_id: TransferId
    reason: str = Field(default="", max_length=500)


class FileProgress(Payload):
    """Chunks written so far. The sender keeps at most MAX_IN_FLIGHT chunks unacknowledged."""

    transfer_id: TransferId
    received: int = Field(ge=0)


class FileEnd(Payload):
    transfer_id: TransferId
    sha256: Sha256 | None = None
    md5: Md5 | None = None

    @model_validator(mode="after")
    def _hashes(self) -> "FileEnd":
        _one_hash(self)
        return self


class FileOk(Payload):
    transfer_id: TransferId
    # Where it went, as the receiver chooses to show it (a folder name and the file, not a full path)
    saved_as: str = Field(default="", max_length=512)


class FileErr(Payload):
    """From the receiver, or from the relay when the other side disconnected."""

    transfer_id: TransferId
    error: str = Field(default="", max_length=500)


class FileBatchEnd(Payload):
    batch_id: str = Field(min_length=1, max_length=64)
    ok: int = Field(ge=0)
    failed: int = Field(ge=0)


class FileBatchCancel(Payload):
    """Ends the batch at once, mid-file too: the receiver deletes the partial file."""

    batch_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=500)


# ---- catalogue ---------------------------------------------------------------------------------

MODELS: dict[str, type[Payload] | None] = {
    # core
    "hello": Hello,
    "welcome": Welcome,
    "denied": Denied,
    "error": ProtocolError,
    "presence.roster": PresenceRoster,
    "presence.latency": PresenceLatency,
    "approval.pending": ApprovalPending,
    "approval.approve": ApprovalApprove,
    "approval.deny": ApprovalDeny,
    "approval.forget": ApprovalForget,
    "approval.forgotten": ApprovalForgotten,
    "actor.settings": ActorSettings,
    "chat.msg": ChatMsg,
    "chat.priv": ChatPriv,
    "time.ping": TimePing,
    "time.pong": TimePong,
    "update.available": UpdateAvailable,
    "cue.go": CueGo,
    "cue.stop": CueStop,
    "cue.play": CuePlay,
    "cue.ack": CueAck,
    "stage.state": None,
    "ready.request": None,
    "ready.status": None,
    "ready.ping": None,
    # soundpad addon
    "soundpad.play": SoundpadPlay,
    "soundpad.stop": SoundpadStop,
    "soundpad.ack": SoundpadAck,
    **{f"soundpad.{t}": None for t in ("pause", "seek", "jump", "volume", "mute", "list.request", "list", "state", "calibrate")},
    # files addon (chunks are binary frames, chunks.py)
    "file.batch.start": FileBatchStart,
    "file.offer": FileOffer,
    "file.accept": FileAccept,
    "file.deny": FileDeny,
    "file.progress": FileProgress,
    "file.end": FileEnd,
    "file.ok": FileOk,
    "file.err": FileErr,
    "file.batch.end": FileBatchEnd,
    "file.batch.cancel": FileBatchCancel,
    **{f"file.{t}": None for t in ("inventory.request", "inventory")},
    # osc addon
    "osc.param": OscParam,
    **{f"osc.{t}": None for t in ("cue.load", "cue.ack", "cue.fired", "params")},
    # cue list storage on the relay (not built yet)
    **{f"cuelist.{t}": None for t in ("save", "get", "list", "delete")},
    # obs addon
    **{f"obs.{t}": None for t in ("profile.apply", "profile.status", "profile.release", "record.start", "record.stop",
                                   "record.state", "mark", "slate", "status")},
    # stream addon
    **{f"rtc.{t}": None for t in ("offer", "answer", "ice", "bye")},
}


def validate(type_: str, data: dict) -> Payload | None:
    """The typed payload, or None for a type without a model. Raises ValueError if invalid."""
    model = MODELS.get(type_)
    return model.model_validate(data) if model is not None else None
