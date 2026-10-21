"""vrcActorSync protocol v2: the envelope and message models shared by the relay and the agent
(spec §5). web/src/protocol/types.ts is generated from them by scripts/gen_ts_types.py."""

from .chunks import (
    CHUNK_SIZE,
    KIND_FILE_CHUNK,
    MAX_FILE_BYTES,
    MAX_IN_FLIGHT,
    Chunk,
    chunk_count,
    pack_chunk,
    unpack_chunk,
)
from .envelope import (
    PROTOCOL_VERSION,
    ROLES,
    Envelope,
    IdsTarget,
    Role,
    RoleTarget,
    Target,
    ValidationError,
    make,
    new_id,
    now_ms,
    parse,
)
from .messages import MODELS, validate

__all__ = [
    "CHUNK_SIZE", "KIND_FILE_CHUNK", "MAX_FILE_BYTES", "MAX_IN_FLIGHT", "Chunk", "chunk_count", "pack_chunk",
    "unpack_chunk",
    "MODELS", "PROTOCOL_VERSION", "ROLES", "Envelope", "IdsTarget", "Role", "RoleTarget", "Target",
    "ValidationError", "make", "new_id", "now_ms", "parse", "validate",
]
