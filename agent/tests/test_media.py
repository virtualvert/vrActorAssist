"""agent/media.py: lengths of audio and video files from their headers (Send files' Length column)."""

import shutil
import struct
import subprocess
import wave

import pytest

from agent.media import MEDIA_EXTENSIONS, duration_ms


def write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def ebml(eid: int, body: bytes) -> bytes:
    """An EBML element with an 8-byte size."""
    return eid.to_bytes((eid.bit_length() + 7) // 8, "big") + (0x01 << 56 | len(body)).to_bytes(8, "big") + body


def test_wav_pcm(tmp_path):
    path = tmp_path / "line.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\0\0\0\0" * 48000 * 3)
    assert duration_ms(path) == 3000


def test_wav_with_chunks_before_fmt_and_an_unknown_data_size(tmp_path):
    fmt = struct.pack("<HHIIHH", 3, 1, 44100, 44100 * 4, 4, 32)  # 32-bit float, mono
    samples = b"\0" * 44100 * 4 * 2
    data = (b"LIST" + struct.pack("<I", 5) + b"INFO!" + b"\0"  # odd size: a pad byte follows
            + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", 0xFFFFFFFF) + samples)  # streamed: size unknown
    assert duration_ms(write(tmp_path, "f.wav", b"RIFF" + struct.pack("<I", 0) + b"WAVE" + data)) == 2000


def test_flac(tmp_path):
    bits = 44100 << 44 | 1 << 41 | 15 << 36 | 44100 * 5 // 2  # 2.5 s
    info = bytes(10) + bits.to_bytes(8, "big") + bytes(16)
    assert duration_ms(write(tmp_path, "a.flac", b"fLaC" + b"\x80\x00\x00\x22" + info)) == 2500


def test_mp3_constant_bitrate_after_an_id3_tag(tmp_path):
    header = bytes([0xFF, 0xFB, 0x90, 0x44])  # MPEG-1 layer III, 128 kbps, 44.1 kHz, joint stereo
    frame = header + bytes(417 - 4)  # 144 * 128000 / 44100 = 417
    id3 = b"ID3\x03\x00\x00" + bytes([0, 0, 0, 20]) + bytes(20)
    audio = frame * 200
    path = write(tmp_path, "c.mp3", id3 + audio)
    assert duration_ms(path) == round(len(audio) * 8 / 128000 * 1000)


def test_mp3_xing_frame_count(tmp_path):
    header = bytes([0xFF, 0xFB, 0x90, 0x44])
    first = bytearray(header + bytes(417 - 4))
    first[4 + 32:4 + 32 + 12] = b"Xing" + struct.pack(">II", 1, 1000)  # 1000 frames
    path = write(tmp_path, "v.mp3", bytes(first) + (header + bytes(413)) * 3)
    assert duration_ms(path) == round(1000 * 1152 / 44100 * 1000)


def test_mp4_with_moov_after_mdat(tmp_path):
    mvhd = box(b"mvhd", bytes(4) + struct.pack(">IIII", 0, 0, 600, 600 * 7) + bytes(80))
    data = box(b"ftyp", b"isom" + bytes(4)) + box(b"mdat", bytes(5000)) + box(b"moov", mvhd)
    assert duration_ms(write(tmp_path, "v.mp4", data)) == 7000
    assert duration_ms(write(tmp_path, "a.m4a", data)) == 7000


def test_mkv(tmp_path):
    info = ebml(0x2AD7B1, (1_000_000).to_bytes(3, "big")) + ebml(0x4489, struct.pack(">d", 4321.0))
    data = ebml(0x1A45DFA3, ebml(0x4282, b"webm")) + ebml(0x18538067, ebml(0x114D9B74, bytes(12)) + ebml(0x1549A966, info))
    assert duration_ms(write(tmp_path, "v.webm", data)) == 4321


def test_avi(tmp_path):
    avih = struct.pack("<IIIIIIIIII", 40000, 0, 0, 0, 250, 0, 1, 0, 640, 480) + bytes(16)  # 25 fps, 250 frames
    data = b"RIFF" + struct.pack("<I", 0) + b"AVI " + b"LIST" + struct.pack("<I", 0) + b"hdrl" + b"avih" + struct.pack("<I", 56) + avih
    assert duration_ms(write(tmp_path, "v.avi", data)) == 10000


def test_ogg_opus_uses_the_last_page_and_pre_skip(tmp_path):
    def page(granule: int, body: bytes) -> bytes:
        return b"OggS\x00\x02" + struct.pack("<q", granule) + b"SER1" + bytes(8) + bytes([1, len(body)]) + body

    head = b"OpusHead\x01\x02" + struct.pack("<H", 312) + struct.pack("<I", 48000) + bytes(3)
    data = page(0, head) + bytes(3000) + page(48000 * 2 + 312, b"x")
    assert duration_ms(write(tmp_path, "a.opus", data)) == 2000


@pytest.mark.parametrize("name,data", [
    ("empty.wav", b""),
    ("bad.wav", b"RIFF\0\0\0\0WAVEjunk"),
    ("text.mp3", b"not an mp3 at all " * 50),
    ("short.flac", b"fLaC"),
    ("loop.mkv", b"\x1a\x45\xdf\xa3\xff"),
    ("zero.mp4", box(b"moov", box(b"mvhd", bytes(4) + struct.pack(">IIII", 0, 0, 0, 100) + bytes(80)))),
    ("notes.txt", b"hello"),
    ("script.pdf", b"%PDF-1.7"),
])
def test_unreadable_or_not_media_gives_none(tmp_path, name, data):
    assert duration_ms(write(tmp_path, name, data)) is None


def test_missing_file_gives_none(tmp_path):
    assert duration_ms(tmp_path / "gone.wav") is None


# ---- real files from ffmpeg, where it's installed ----------------------------------------------------

FFMPEG = shutil.which("ffmpeg")
REAL = [
    ("a.wav", ["-c:a", "pcm_s16le"]),
    ("a.flac", ["-c:a", "flac"]),
    ("cbr.mp3", ["-c:a", "libmp3lame", "-b:a", "128k"]),
    ("vbr.mp3", ["-c:a", "libmp3lame", "-q:a", "4"]),
    ("a.ogg", ["-c:a", "libvorbis"]),
    ("a.opus", ["-c:a", "libopus"]),
    ("a.m4a", ["-c:a", "aac"]),
    ("a.aac", ["-c:a", "aac", "-f", "adts"]),
]


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg isn't installed")
@pytest.mark.parametrize("name,args", REAL)
def test_real_audio_files(tmp_path, name, args):
    path = tmp_path / name
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3.5", *args, str(path)], check=True)
    assert duration_ms(path) == pytest.approx(3500, abs=3500 * 0.03 if name.endswith(".aac") else 60)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg isn't installed")
@pytest.mark.parametrize("name,args", [
    ("v.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"]),
    ("v.mov", ["-c:v", "libx264", "-pix_fmt", "yuv420p"]),
    ("v.mkv", ["-c:v", "libx264", "-pix_fmt", "yuv420p"]),
    ("v.webm", ["-c:v", "libvpx", "-b:v", "200k"]),
    ("v.avi", ["-c:v", "mpeg4"]),
])
def test_real_video_files(tmp_path, name, args):
    path = tmp_path / name
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=4", *args, str(path)], check=True)
    assert duration_ms(path) == pytest.approx(4000, abs=60)


def test_extensions_cover_audio_the_folder_lists():
    from agent.folders import AUDIO_EXTENSIONS

    assert AUDIO_EXTENSIONS <= MEDIA_EXTENSIONS
