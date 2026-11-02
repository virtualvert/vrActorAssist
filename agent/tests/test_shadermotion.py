import pytest

from agent.shadermotion import FRAME_BYTES, POW, ROWS, SQUARES, command, decode_frame

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


def frame(values: list[int]) -> bytes:
    buf = bytearray(FRAME_BYTES)
    for s, t in enumerate(values):
        col, row = divmod(s, ROWS)
        for square, (r, g, b) in enumerate(encode(t)):
            i = (row * SQUARES + 2 * col + square) * 4
            buf[i:i + 4] = bytes([b, g, r, 255])
    return bytes(buf)


def test_decode_frame_reads_layer_0_in_slot_order():
    values = [(s * 37) % POW for s in range(270)]
    got = decode_frame(frame(values))
    assert len(got) == 270
    # digit 1 is 127.5 / 255, which 8 bits round; a step is 1/364, so 0.001 still pins every digit
    assert got == pytest.approx([(t - HALF) / HALF for t in values], abs=1e-3)


def test_command_live_capture_scales_on_the_gpu():
    argv = command("ffmpeg", "hwnd=123")
    grab = argv[argv.index("-i") + 1]
    assert grab.startswith("gfxcapture=hwnd=123:") and "width=80:height=45" in grab and "scale_mode=point" in grab
    assert argv[argv.index("-vf") + 1] == "crop=12:45:0:0"


def test_command_recording_loops_at_its_own_speed(tmp_path):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"")
    argv = command("ffmpeg", str(video))
    assert argv[argv.index("-i") - 3:argv.index("-i")] == ["-re", "-stream_loop", "-1"]
    assert "avgblur" in argv[argv.index("-vf") + 1]
