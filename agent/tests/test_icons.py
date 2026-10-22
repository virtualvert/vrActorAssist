import re
import struct
import sys
from pathlib import Path

import build_agent
from agent import shell

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"


def ico_frames(path: Path) -> list[tuple[int, bytes]]:
    """(size, first bytes of the image data) per frame of a .ico file."""
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind) == (0, 1)
    frames = []
    for i in range(count):
        width, height, _, _, _, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        assert width == height and bpp == 32 and offset + size <= len(data)
        frames.append((width or 256, data[offset:offset + 8]))
    return frames


def test_the_ico_has_every_size_windows_asks_for():
    frames = ico_frames(ASSETS / "vrcActorSync.ico")
    assert [size for size, _ in frames] == [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # BMP frames (a 40-byte BITMAPINFOHEADER): every Windows and .NET icon reader takes them.
    assert all(struct.unpack_from("<I", head)[0] == 40 for _, head in frames)
    assert (ASSETS / "vrcActorSync.png").read_bytes().startswith(b"\x89PNG")


def test_favicon_and_logo_match_the_small_icon():
    small = (ASSETS / "icon-small.svg").read_text()
    assert (ROOT / "web" / "public" / "favicon.svg").read_text() == small, "run scripts/gen_icons.py"
    logo = (ROOT / "web" / "src" / "lib" / "components" / "Logo.svelte").read_text()
    shapes = re.findall(r'<path d="([^"]+)"', small)
    assert len(shapes) == 4  # head + three bark lines
    for d in shapes:
        assert f'd="{d}"' in logo, "Logo.svelte drifted from assets/icon-small.svg"


def test_window_icon_is_the_ico_on_windows_and_the_png_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    assert shell.icon_path() == str(ASSETS / "vrcActorSync.ico")
    monkeypatch.setattr(sys, "platform", "linux")
    assert shell.icon_path() == str(ASSETS / "vrcActorSync.png")

    # A build finds it in the bundle; a missing file means pywebview's default, not a crash.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert shell.icon_path() is None
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "vrcActorSync.png").write_bytes(b"png")
    assert shell.icon_path() == str(tmp_path / "assets" / "vrcActorSync.png")


def test_windows_build_embeds_and_bundles_the_icon(monkeypatch):
    monkeypatch.setattr(build_agent, "IS_WINDOWS", True)
    cmd = build_agent.pyinstaller_command(onedir=False)
    assert cmd[cmd.index("--icon") + 1] == str(build_agent.ICON)
    assert f"{build_agent.ICON}{build_agent.os.pathsep}assets" in cmd
    monkeypatch.setattr(build_agent, "IS_WINDOWS", False)
    assert "--icon" not in build_agent.pyinstaller_command(onedir=False)
