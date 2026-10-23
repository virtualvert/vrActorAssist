"""How long an audio or video file plays, read from its headers (Send files' Length column).

Stdlib only, and only a few small reads per file: the page gets numbers, never file contents
(folders.py keeps reads of whole files to audio for Normalize folder). Anything unrecognised,
damaged or implausible gives None.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import BinaryIO, Callable

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
SCAN_BYTES = 64 * 1024
MAX_SECONDS = 7 * 24 * 3600


def duration_ms(path: Path) -> int | None:
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        return None
    try:
        with path.open("rb") as f:
            seconds = reader(f, os.fstat(f.fileno()).st_size)
    except (OSError, ValueError, struct.error, IndexError, ZeroDivisionError, OverflowError):
        return None
    if seconds is None or not 0 < seconds < MAX_SECONDS:  # NaN fails too
        return None
    return round(seconds * 1000)


def _skip_id3v2(f: BinaryIO) -> int:
    """Seek past an ID3v2 tag at the start; returns where the audio starts."""
    head = f.read(10)
    start = 0
    if len(head) == 10 and head[:3] == b"ID3":
        start = 10 + ((head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F))
        if head[5] & 0x10:
            start += 10  # footer
    f.seek(start)
    return start


# ---- WAV (RIFF and RF64) -------------------------------------------------------------------------


def _wav(f: BinaryIO, size: int) -> float | None:
    head = f.read(12)
    if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
        return None
    byte_rate = data_size = big_data = None
    while byte_rate is None or data_size is None:
        chunk = f.read(8)
        if len(chunk) < 8:
            break
        kind, n = chunk[:4], struct.unpack("<I", chunk[4:])[0]
        body_at = f.tell()
        if kind == b"ds64":
            big_data = struct.unpack("<QQ", f.read(16))[1]
        elif kind == b"fmt ":
            byte_rate = struct.unpack_from("<I", f.read(12), 8)[0]
        elif kind == b"data":
            data_size = big_data if n == 0xFFFFFFFF and big_data else n
            data_size = min(data_size, size - body_at)
        f.seek(body_at + n + (n & 1))
    if not byte_rate or not data_size:
        return None
    return data_size / byte_rate


# ---- FLAC ----------------------------------------------------------------------------------------


def _streaminfo(info: bytes) -> float | None:
    """Sample rate (20 bits) and total samples (36 bits) at bytes 10–17 of STREAMINFO."""
    bits = int.from_bytes(info[10:18], "big")
    rate, total = bits >> 44, bits & ((1 << 36) - 1)
    return total / rate if rate and total else None


def _flac(f: BinaryIO, size: int) -> float | None:
    _skip_id3v2(f)
    if f.read(4) != b"fLaC":
        return None
    block = f.read(4)
    if len(block) < 4 or block[0] & 0x7F != 0:  # STREAMINFO is always the first block
        return None
    return _streaminfo(f.read(34))


# ---- MP3 -----------------------------------------------------------------------------------------

_MP3_KBPS = {
    (True, 1): (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 3): (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 1): (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 3): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
# Version bits: 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _mp3_frame(buf: bytes, i: int) -> tuple[int, int, int, int, bool] | None:
    """(bitrate, sample rate, samples per frame, frame length, MPEG-1) of a frame header at i."""
    if i + 4 > len(buf) or buf[i] != 0xFF or buf[i + 1] & 0xE0 != 0xE0:
        return None
    h = int.from_bytes(buf[i:i + 4], "big")
    version, layer_bits, kbps_index, rate_index = (h >> 19) & 3, (h >> 17) & 3, (h >> 12) & 15, (h >> 10) & 3
    if version == 1 or layer_bits == 0 or kbps_index in (0, 15) or rate_index == 3:
        return None
    layer, mpeg1, padding = 4 - layer_bits, version == 3, (h >> 9) & 1
    bitrate = _MP3_KBPS[(mpeg1, layer)][kbps_index - 1] * 1000
    rate = _MP3_RATES[version][rate_index]
    if layer == 1:
        return bitrate, rate, 384, (12 * bitrate // rate + padding) * 4, mpeg1
    samples = 1152 if layer == 2 or mpeg1 else 576
    return bitrate, rate, samples, samples // 8 * bitrate // rate + padding, mpeg1


def _mp3(f: BinaryIO, size: int) -> float | None:
    start = _skip_id3v2(f)
    buf = f.read(SCAN_BYTES)
    for i in range(len(buf) - 4):
        frame = _mp3_frame(buf, i)
        if frame is None:
            continue
        bitrate, rate, samples, length, mpeg1 = frame
        if i + length + 4 <= len(buf) and _mp3_frame(buf, i + length) is None:
            continue  # a stray sync pattern, not a frame
        mono = (buf[i + 3] >> 6) & 3 == 3
        xing = i + 4 + ((17 if mono else 32) if mpeg1 else (9 if mono else 17))
        if buf[xing:xing + 4] in (b"Xing", b"Info") and int.from_bytes(buf[xing + 4:xing + 8], "big") & 1:
            return int.from_bytes(buf[xing + 8:xing + 12], "big") * samples / rate
        if buf[i + 36:i + 40] == b"VBRI":
            return int.from_bytes(buf[i + 50:i + 54], "big") * samples / rate
        end = size
        f.seek(max(0, size - 128))
        if f.read(3) == b"TAG":
            end -= 128
        return (end - start - i) * 8 / bitrate  # constant bitrate
    return None


# ---- AAC (ADTS) ----------------------------------------------------------------------------------

_AAC_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)


def _aac(f: BinaryIO, size: int) -> float | None:
    """Raw AAC has no length field: the average frame of the first 64 KiB, over the whole file."""
    start = _skip_id3v2(f)
    buf = f.read(SCAN_BYTES)
    i = frames = used = 0
    rate = None
    while i + 7 <= len(buf):
        if buf[i] != 0xFF or buf[i + 1] & 0xF6 != 0xF0:
            if frames:
                break
            i += 1
            continue
        rate_index = (buf[i + 2] >> 2) & 15
        length = (buf[i + 3] & 3) << 11 | buf[i + 4] << 3 | buf[i + 5] >> 5
        if rate_index >= len(_AAC_RATES) or length < 7:
            return None
        rate = _AAC_RATES[rate_index]
        frames += (buf[i + 6] & 3) + 1
        used += length
        i += length
    if not frames or not rate:
        return None
    return (size - start) / (used / frames) * 1024 / rate


# ---- Ogg (Vorbis, Opus, FLAC) --------------------------------------------------------------------


def _ogg(f: BinaryIO, size: int) -> float | None:
    page = f.read(4096)
    if page[:4] != b"OggS":
        return None
    body = page[27 + page[26]:]
    skip = 0
    if body[:7] == b"\x01vorbis":
        rate = struct.unpack_from("<I", body, 12)[0]
    elif body[:8] == b"OpusHead":
        rate, skip = 48000, struct.unpack_from("<H", body, 10)[0]
    elif body[:5] == b"\x7fFLAC":
        rate = int.from_bytes(body[27:35], "big") >> 44  # STREAMINFO starts at 17; its rate at byte 10
    else:
        return None
    if not rate:
        return None
    serial = page[14:18]
    f.seek(max(0, size - SCAN_BYTES))
    tail = f.read()
    at = tail.rfind(b"OggS")
    while at >= 0:
        if at + 18 <= len(tail) and tail[at + 14:at + 18] == serial:
            granule = struct.unpack_from("<q", tail, at + 6)[0]
            if granule >= 0:
                return max(0, granule - skip) / rate
        at = tail.rfind(b"OggS", 0, at)
    return None


# ---- MP4, M4A, MOV -------------------------------------------------------------------------------


def _atoms(f: BinaryIO, start: int, end: int):
    """(type, body start, end) of each box between start and end."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(16)
        if len(head) < 8:
            return
        n, kind = struct.unpack(">I4s", head[:8])
        header = 8
        if n == 1:
            n, header = struct.unpack(">Q", head[8:16])[0], 16
        elif n == 0:
            n = end - pos
        if n < header:
            return
        yield kind, pos + header, pos + n
        pos += n


def _mp4(f: BinaryIO, size: int) -> float | None:
    for kind, body, end in _atoms(f, 0, size):
        if kind != b"moov":
            continue
        for sub, sub_body, _ in _atoms(f, body, end):
            if sub != b"mvhd":
                continue
            f.seek(sub_body)
            head = f.read(32)
            if head[0] == 1:
                scale, duration = struct.unpack_from(">IQ", head, 20)
                unknown = duration == (1 << 64) - 1
            else:
                scale, duration = struct.unpack_from(">II", head, 12)
                unknown = duration == 0xFFFFFFFF
            return None if unknown or not scale else duration / scale
        return None
    return None


# ---- Matroska, WebM ------------------------------------------------------------------------------

_EBML, _SEGMENT, _INFO, _CLUSTER = 0x1A45DFA3, 0x18538067, 0x1549A966, 0x1F43B675
_TIMECODE_SCALE, _DURATION = 0x2AD7B1, 0x4489


def _vint(f: BinaryIO, marker: bool) -> tuple[int, bool]:
    """An EBML variable-size integer: (value, all value bits set, i.e. "unknown size")."""
    first = f.read(1)
    if not first:
        raise ValueError("end of file")
    length, mask = 1, 0x80
    while length <= 8 and not first[0] & mask:
        length, mask = length + 1, mask >> 1
    if length > 8:
        raise ValueError("bad EBML number")
    rest = f.read(length - 1)
    if len(rest) != length - 1:
        raise ValueError("end of file")
    value = first[0] if marker else first[0] & (mask - 1)
    for byte in rest:
        value = value << 8 | byte
    return value, not marker and value == (1 << 7 * length) - 1


def _element(f: BinaryIO) -> tuple[int, int | None, int]:
    eid = _vint(f, True)[0]
    n, unknown = _vint(f, False)
    return eid, None if unknown else n, f.tell()


def _mkv(f: BinaryIO, size: int) -> float | None:
    eid, n, body = _element(f)
    if eid != _EBML or n is None:
        return None
    f.seek(body + n)
    eid, n, body = _element(f)
    if eid != _SEGMENT:
        return None
    end = size if n is None else min(size, body + n)
    pos = body
    while pos < end:
        f.seek(pos)
        eid, n, body = _element(f)
        if eid == _INFO and n is not None:
            scale, duration = 1_000_000, None
            at = body
            while at < body + n:
                f.seek(at)
                cid, cn, cbody = _element(f)
                if cn is None:
                    return None
                value = f.read(cn)
                if cid == _TIMECODE_SCALE:
                    scale = int.from_bytes(value, "big")
                elif cid == _DURATION:
                    duration = struct.unpack(">f" if cn == 4 else ">d", value)[0]
                at = cbody + cn
            return duration * scale / 1e9 if duration is not None else None
        if eid == _CLUSTER or n is None:
            return None  # media before the Info element: nothing to read the length from
        pos = body + n
    return None


# ---- AVI -----------------------------------------------------------------------------------------


def _avi(f: BinaryIO, size: int) -> float | None:
    head = f.read(32)
    if head[:4] != b"RIFF" or head[8:12] != b"AVI " or head[12:16] != b"LIST" or head[20:24] != b"hdrl" or head[24:28] != b"avih":
        return None
    main = f.read(20)
    micro_per_frame, frames = struct.unpack_from("<I", main, 0)[0], struct.unpack_from("<I", main, 16)[0]
    return micro_per_frame * frames / 1e6 if micro_per_frame and frames else None


_READERS: dict[str, Callable[[BinaryIO, int], float | None]] = {
    ".wav": _wav,
    ".flac": _flac,
    ".mp3": _mp3,
    ".aac": _aac,
    ".ogg": _ogg,
    ".oga": _ogg,
    ".opus": _ogg,
    ".m4a": _mp4,
    ".mp4": _mp4,
    ".m4v": _mp4,
    ".mov": _mp4,
    ".mkv": _mkv,
    ".webm": _mkv,
    ".avi": _avi,
}
