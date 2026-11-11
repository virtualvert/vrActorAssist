import sys
from pathlib import Path

import pytest

from agent import shadermotion
from agent.shadermotion import FRAME_BYTES, POW, ROWS, WIDTH, command, decode_frame, find_ffmpeg, pack, unpack

HALF = (POW - 1) // 2


def encode(t: int) -> tuple[list[int], list[int]]:
    """An exact slot value t (0..728) → its two squares' RGB bytes (inverse of the Gray-code decoder)."""
    digits = [t // 3 ** k % 3 for k in range(5, -1, -1)]
    shown, prefix = [], 0
    for d in digits:
        shown.append(2 - d if prefix & 1 else d)
        prefix = prefix * 3 + d
    to_rgb = lambda g, r, b: [round(r * 127.5), round(g * 127.5), round(b * 127.5)]
    return to_rgb(*shown[:3]), to_rgb(*shown[3:])


def frame(values: list[int], dense: bool = False) -> bytes:
    """A captured 24×90 frame: a pixel per dense square, so a normal square is 2×2 pixels."""
    buf = bytearray(FRAME_BYTES)
    for s, t in enumerate(values):
        # the dense grid: 3 slot columns, 90 rows, the face block (135+) below the humanoid block
        x, y, size = (2 * (s // ROWS % 3), s % ROWS + s // 135 * ROWS, 1) if dense else (4 * (s // ROWS), 2 * (s % ROWS), 2)
        for square, (r, g, b) in enumerate(encode(t)):
            for dx in range(size):
                for dy in range(size):
                    i = ((y + dy) * WIDTH + x + square * size + dx) * 4
                    buf[i:i + 4] = bytes([b, g, r, 255])
    return bytes(buf)


def test_decode_frame_reads_layer_0_of_the_normal_grid():
    values = [(s * 37) % POW for s in range(270)]
    got = decode_frame(frame(values))
    # digit 1 is 127.5 / 255, which 8 bits round; a step is 1/364, so 0.001 still pins every digit
    assert got == pytest.approx([(t - HALF) / HALF for t in values], abs=1e-3)


def test_decode_frame_reads_the_dense_grid_by_its_marker():
    values = [(s * 53) % POW for s in range(270)]
    values[133:135] = [HALF + HALF // 2, HALF - HALF // 2]  # 0.5, -0.5
    got = decode_frame(frame(values, dense=True))
    assert got == pytest.approx([(t - HALF) / HALF for t in values], abs=1e-3)


def test_command_live_capture_scales_on_the_gpu():
    argv = command("ffmpeg", "hwnd=123")
    grab = argv[argv.index("-i") + 1]
    assert grab.startswith("gfxcapture=hwnd=123:") and "width=160:height=90" in grab and "scale_mode=point" in grab
    assert argv[argv.index("-vf") + 1] == "crop=24:90:0:0,setpts=N"  # setpts: no repeated timestamps


def test_command_recording_loops_at_its_own_speed(tmp_path):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"")
    argv = command("ffmpeg", str(video))
    assert argv[argv.index("-i") - 3:argv.index("-i")] == ["-re", "-stream_loop", "-1"]
    assert "format=gbrp,avgblur" in argv[argv.index("-vf") + 1]  # blur in RGB, not the video's YUV


def test_find_ffmpeg_sees_an_install_made_while_the_app_runs(tmp_path, monkeypatch):
    exe = tmp_path / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    exe.write_bytes(b"")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", "")  # the PATH the app started with doesn't have it
    monkeypatch.setattr(shadermotion, "_saved_path", lambda: str(tmp_path))
    assert Path(find_ffmpeg()).samefile(exe)


def test_find_ffmpeg_prefers_the_build_bundled_in_a_built_app(tmp_path, monkeypatch):
    bundled = tmp_path / "ffmpeg" / "ffmpeg.exe"
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert find_ffmpeg() == str(bundled)  # even with a full ffmpeg on PATH or in C:\ffmpeg\bin


def test_frames_on_the_relay_round_trip_as_int16():
    slots = [s / 135 - 1 for s in range(270)]
    text = pack(slots)
    assert len(text) == 720  # what the shadermotion.frame model expects
    assert unpack(text) == pytest.approx(slots, abs=1e-4)
    assert unpack(pack([1.2, -3.0] + [0.0] * 268))[:2] == [1.0, -1.0]  # decoder overshoot is clamped
    with pytest.raises(ValueError):
        unpack("not base64!")
