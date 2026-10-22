#!/usr/bin/env python3
"""Make the app icon files from assets/icon.svg and assets/icon-small.svg.

    python scripts/gen_icons.py

Writes:
  assets/vrcActorSync.ico     Windows: the exe icon (build_agent.py --icon) and the window / taskbar icon
  assets/vrcActorSync.png     256 px, for the Linux --window (GTK) and anything else that wants a PNG
  web/public/favicon.svg      a copy of icon-small.svg (browser tab, and the logo the web UI links to)

Sizes up to 48 px come from icon-small.svg (bolder bark lines that survive 16 px), bigger ones from
icon.svg. The .ico frames are BMP, which every Windows icon reader handles. Needs rsvg-convert
(librsvg) and Pillow; the generated files are checked in, so builds don't need either.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
LARGE = ASSETS / "icon.svg"
SMALL = ASSETS / "icon-small.svg"
ICO = ASSETS / "vrcActorSync.ico"
PNG = ASSETS / "vrcActorSync.png"
FAVICON = ROOT / "web" / "public" / "favicon.svg"

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SMALL_MAX = 48


def render(svg: Path, size: int):
    from PIL import Image

    png = subprocess.run(
        ["rsvg-convert", "--width", str(size), "--height", str(size), str(svg)],
        check=True,
        capture_output=True,
    ).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> int:
    if shutil.which("rsvg-convert") is None:
        print("rsvg-convert isn't on PATH (package librsvg / librsvg2-bin)", file=sys.stderr)
        return 1
    try:
        import PIL  # noqa: F401
    except ImportError:
        print(f"Pillow isn't installed. Run: {sys.executable} -m pip install pillow", file=sys.stderr)
        return 1

    frames = [render(SMALL if size <= SMALL_MAX else LARGE, size) for size in ICO_SIZES]
    largest = frames[-1]
    largest.save(
        ICO,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=frames[:-1],
        bitmap_format="bmp",
    )
    largest.save(PNG, format="PNG", optimize=True)
    shutil.copyfile(SMALL, FAVICON)
    for path in (ICO, PNG, FAVICON):
        print(f"✓ {path.relative_to(ROOT)}  ({path.stat().st_size / 1000:.1f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
