"""The v2 envelope (spec §5.1) and its targets (§5.2)."""

from __future__ import annotations

import os
import time
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 2
Role = Literal["director", "assistant", "actor", "camera"]
ROLES: tuple[str, ...] = ("director", "assistant", "actor", "camera")

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(ms: int | None = None) -> str:
    """A ULID: 48-bit millisecond time + 80 random bits, Crockford base32 (26 characters)."""
    value = ((now_ms() if ms is None else ms) & ((1 << 48) - 1)) << 80 | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


class RoleTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class IdsTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=256)


# "server": handled by the relay. "all": every approved session except the sender.
Target = Union[Literal["server", "all"], RoleTarget, IdsTarget]


class Envelope(BaseModel):
    """`from` is set by the relay; whatever a client puts there is replaced (no spoofing)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    v: Literal[2] = PROTOCOL_VERSION
    id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
    from_: str | None = Field(default=None, alias="from", max_length=64)
    to: Target = "server"
    ts: int | None = None
    reply_to: str | None = Field(default=None, max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        """The JSON object as sent: `from` spelled out, `to` as a plain value."""
        return self.model_dump(mode="json", by_alias=True)


def make(type_: str, data: dict[str, Any] | BaseModel | None = None, *, to: Any = "server", from_: str | None = None,
         reply_to: str | None = None, ts: int | None = None) -> Envelope:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json", exclude_none=True)
    return Envelope(id=new_id(), type=type_, from_=from_, to=to, ts=now_ms() if ts is None else ts,
                    reply_to=reply_to, data=data or {})


def parse(raw: str | bytes | dict) -> Envelope:
    """Raises ValueError (pydantic's ValidationError is one) for anything that isn't a v2 envelope."""
    if isinstance(raw, dict):
        return Envelope.model_validate(raw)
    return Envelope.model_validate_json(raw)

