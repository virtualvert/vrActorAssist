"""File chunks as binary frames on /v2/ws (spec §5.7).

    | 1 byte kind | 16 bytes transfer UUID | 4 bytes chunk index (big-endian) | payload |

The transfer UUID is the `transfer_id` of the `file.offer` (32 hex characters in JSON). Chunk n
holds bytes n × chunk_size … (n + 1) × chunk_size of the file; only the last one may be shorter.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

KIND_FILE_CHUNK = 0x01
HEADER = struct.Struct(">B16sI")
HEADER_SIZE = HEADER.size  # 21

CHUNK_SIZE = 256 * 1024
MIN_CHUNK_SIZE = 16 * 1024
# v0.3 clients send and receive 64 KiB chunks, base64 in text frames
LEGACY_CHUNK_SIZE = 64 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
# Chunks a sender may have on the way before a file.progress acknowledges them
MAX_IN_FLIGHT = 8


@dataclass(frozen=True)
class Chunk:
    kind: int
    transfer_id: str
    index: int
    payload: bytes


def chunk_count(size: int, chunk_size: int = CHUNK_SIZE) -> int:
    """Chunks needed for `size` bytes; an empty file still has none."""
    return (size + chunk_size - 1) // chunk_size


def pack_chunk(transfer_id: str, index: int, payload: bytes, kind: int = KIND_FILE_CHUNK) -> bytes:
    return HEADER.pack(kind, bytes.fromhex(transfer_id), index) + payload


def unpack_chunk(frame: bytes) -> Chunk:
    """Raises ValueError for a frame that's too short to carry the header."""
    if len(frame) < HEADER_SIZE:
        raise ValueError(f"A chunk frame needs at least {HEADER_SIZE} bytes, got {len(frame)}")
    kind, raw_id, index = HEADER.unpack_from(frame)
    return Chunk(kind, raw_id.hex(), index, bytes(frame[HEADER_SIZE:]))
