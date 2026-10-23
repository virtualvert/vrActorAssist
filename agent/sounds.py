"""An actor's Soundpad sound list, as directors see it (spec §8.1.3, Phase 2 decision D6).

Directors pick sounds by `key`: a hash of the sound's path on the actor's PC. The path itself
never leaves the actor's machine; the actor's agent maps a key back to the current All-sounds
index, and checks before playing that the index still holds that file (index drift guard).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .soundpad_pipe import Sound

LIST_PAGE = 500
# soundpad.list limits (vrcas_protocol SoundEntry, CategoryEntry, SoundpadList): the relay checks
# every message and drops a page that breaks one, so the director would never get the list
TEXT_MAX = 300
CATEGORIES_MAX = 500
# The relay also drops text frames over 256 KiB (server settings.max_frame_bytes); 500 long
# non-Latin titles can pass that, so a page ends at this many bytes of entries too
PAGE_BYTES = 160 * 1024


def normal_path(path: str) -> str:
    """Windows paths compare case-insensitively and with either slash."""
    return path.strip().replace("/", "\\").casefold()


def sound_key(path: str) -> str:
    return hashlib.sha1(normal_path(path).encode("utf-8")).hexdigest()[:16]


def entry(sound: Sound) -> dict:
    """A sound as soundpad.list carries it: no path."""
    return {
        "index": sound.index,
        "key": sound_key(sound.url),
        "title": sound.title[:TEXT_MAX],
        "duration_ms": sound.duration_s * 1000 if sound.duration_s is not None else None,
    }


def _json_bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 1


def pages(sounds: list[Sound], categories: list[dict], size: int = LIST_PAGE, max_bytes: int = PAGE_BYTES) -> list[dict]:
    """soundpad.list payloads: pages of at most `size` sounds and about `max_bytes` of entries, so
    every page gets past the relay; the first page carries the categories."""
    categories = [{"index": c["index"], "name": c["name"][:TEXT_MAX]} for c in categories[:CATEGORIES_MAX]]
    chunks: list[list[dict]] = [[]]
    used = _json_bytes(categories)
    for sound in sounds:
        item = entry(sound)
        cost = _json_bytes(item)
        if chunks[-1] and (len(chunks[-1]) >= size or used + cost > max_bytes):
            chunks.append([])
            used = 0
        chunks[-1].append(item)
        used += cost
    return [{
        "total": len(sounds),
        "first": chunk[0]["index"] if chunk else 1,
        "sounds": chunk,
        "categories": categories if n == 0 else [],
        "last": n == len(chunks) - 1,
    } for n, chunk in enumerate(chunks)]


@dataclass
class SoundCache:
    """The last full list read from Soundpad, with lookups by key and by path."""

    sounds: list[Sound] = field(default_factory=list)
    count: int = -1
    _by_key: dict[str, Sound] = field(default_factory=dict)
    _by_path: dict[str, Sound] = field(default_factory=dict)

    def load(self, sounds: list[Sound]) -> None:
        self.sounds = sounds
        self.count = len(sounds)
        self._by_key = {sound_key(s.url): s for s in sounds}
        self._by_path = {normal_path(s.url): s for s in sounds}

    def by_key(self, key: str) -> Sound | None:
        return self._by_key.get(key)

    def by_path(self, path: str) -> Sound | None:
        return self._by_path.get(normal_path(path))

    def by_index(self, index: int) -> Sound | None:
        return next((s for s in self.sounds if s.index == index), None)
