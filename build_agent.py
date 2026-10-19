#!/usr/bin/env python3
"""Build the v0.4 vrcActorSync agent (python -m agent) into a standalone program.

    python build_agent.py              # one file:   dist/vrcActorSync(.exe)
    python build_agent.py --onedir     # one folder: dist/vrcActorSync/
    python build_agent.py --skip-web   # reuse the existing web/dist instead of rebuilding it

Builds the web UI with Bun first (bun --cwd=web run build), then runs PyInstaller on
agent_entry.py with web/dist bundled as data (the agent finds it under sys._MEIPASS).
Run it with the Python that has the agent requirements and PyInstaller:

    pip install -r agent/requirements.txt pyinstaller

Windows: pywebview window (needs the WebView2 Runtime on the target), no console.
Linux: browser UI, console program. glibc isn't bundled; the build prints the oldest glibc the
binary accepts (set by libpython and libraries copied from the build machine, e.g. libgcc_s).

The output is never named vrActorClient* / vrDirectorClient*: the v0.3 updater swaps files
with those names. build_exe.py (v0.3 clients) is separate and deletes dist/ when it runs.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
WEB_DIST = WEB / "dist"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "agent"
NAME = "vrcActorSync"
IS_WINDOWS = sys.platform == "win32"
ELF_MAGIC = b"\x7fELF"
GLIBC_VERSION = re.compile(rb"GLIBC_(\d+)\.(\d+)")

# Imported lazily or by name at runtime, so PyInstaller's import scan can miss them.
# uvicorn picks its loop/protocol modules by string; websockets uses lazy re-exports.
COLLECT = ["uvicorn", "websockets"]
HIDDEN = ["pythonosc.udp_client", "certifi"]
# pywebview chooses its backend at runtime; WebView2 goes through pythonnet (clr).
HIDDEN_WINDOWS = ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]
# Linux runs in the browser. Keep a venv with system packages (for --window during development)
# from dragging GTK and pywebview into the binary.
EXCLUDE_LINUX = ["webview", "gi", "tkinter"]

# (import name, pip name) the agent can't run without.
REQUIRED = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("websockets", "websockets"),
    ("pythonosc", "python-osc"),
    ("certifi", "certifi"),
]
REQUIRED_WINDOWS = [("webview", "pywebview")]


def fail(message: str) -> None:
    print(f"\n✗ {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def check_python_deps() -> None:
    if importlib.util.find_spec("PyInstaller") is None:
        fail(f"PyInstaller isn't installed for {sys.executable}.\n  Run: {sys.executable} -m pip install pyinstaller")
    needed = REQUIRED + (REQUIRED_WINDOWS if IS_WINDOWS else [])
    missing = [pip for module, pip in needed if importlib.util.find_spec(module) is None]
    if missing:
        # PyInstaller would only warn and produce a program that crashes on start.
        fail(f"Missing agent dependencies: {', '.join(missing)}\n  Run: {sys.executable} -m pip install -r agent/requirements.txt")


def build_web(skip: bool) -> None:
    built = (WEB_DIST / "index.html").exists()
    if skip:
        if not built:
            fail("--skip-web was given but web/dist/index.html doesn't exist. Run: bun --cwd=web run build")
        print("Using the existing web/dist (--skip-web)")
        return
    bun = shutil.which("bun")
    if bun is None:
        if not built:
            fail("Bun isn't on PATH and web/dist isn't built. Install Bun (https://bun.sh) or build web/dist elsewhere.")
        print("! Bun isn't on PATH; bundling the existing web/dist, which may be out of date")
        return
    if not (WEB / "node_modules").exists():
        run([bun, "--cwd=web", "install", "--frozen-lockfile"], "bun install")
    run([bun, "--cwd=web", "run", "build"], "web UI build")
    if not (WEB_DIST / "index.html").exists():
        fail("The web build finished but web/dist/index.html is missing")


def run(cmd: list[str], what: str) -> None:
    print(f"\n→ {what}: {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        fail(f"{what} failed (exit code {result.returncode})")


def pyinstaller_command(onedir: bool) -> list[str]:
    cmd = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "agent_entry.py"),
        "--name", NAME,
        "--onedir" if onedir else "--onefile",
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        "--paths", str(ROOT),  # top-level shared.py and soundpad.py
        "--add-data", f"{WEB_DIST}{os.pathsep}web",
    ]
    for package in COLLECT:
        cmd += ["--collect-submodules", package]
    for module in HIDDEN + (HIDDEN_WINDOWS if IS_WINDOWS else []):
        cmd += ["--hidden-import", module]
    if IS_WINDOWS:
        cmd.append("--windowed")
    else:
        for module in EXCLUDE_LINUX:
            cmd += ["--exclude-module", module]
    return cmd


def required_glibc(output: Path, onedir: bool) -> tuple[str, str] | None:
    """(version, file) of the newest GLIBC_x.y symbol version any bundled ELF file needs."""
    def elf_blobs():
        if onedir:
            for path in output.parent.rglob("*"):
                if path.is_file():
                    with path.open("rb") as handle:
                        if handle.read(4) == ELF_MAGIC:
                            yield str(path.relative_to(output.parent)), path.read_bytes()
            return
        from PyInstaller.archive.readers import CArchiveReader

        yield output.name, output.read_bytes()
        archive = CArchiveReader(str(output))
        for name, entry in archive.toc.items():
            if entry[-1] != "z":  # skip the PYZ of Python modules
                data = archive.extract(name)
                if data and data[:4] == ELF_MAGIC:
                    yield name, data

    newest: tuple[tuple[int, int], str] | None = None
    try:
        for name, data in elf_blobs():
            for match in GLIBC_VERSION.finditer(data):
                version = (int(match[1]), int(match[2]))
                if newest is None or version > newest[0]:
                    newest = (version, name)
    except Exception as exc:  # PyInstaller's archive reader is internal API
        print(f"! Couldn't check the glibc requirement: {exc}")
        return None
    return (f"{newest[0][0]}.{newest[0][1]}", newest[1]) if newest else None


def clean_output() -> None:
    """Only this build's output; v0.3 exes in dist/ stay. Remove both layouts so they can't clash."""
    for path in (DIST / NAME, DIST / f"{NAME}.exe"):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Build the {NAME} agent with PyInstaller")
    parser.add_argument("--onedir", action="store_true", help="one folder instead of one file (faster start)")
    parser.add_argument("--skip-web", action="store_true", help="don't rebuild web/dist; bundle what's there")
    args = parser.parse_args()

    check_python_deps()
    build_web(args.skip_web)
    clean_output()
    run(pyinstaller_command(args.onedir), "PyInstaller")

    exe = f"{NAME}.exe" if IS_WINDOWS else NAME
    output = DIST / NAME / exe if args.onedir else DIST / exe
    if not output.exists():
        fail(f"PyInstaller finished but {output} is missing")
    size_mb = output.stat().st_size / 1_000_000
    print("\n" + "=" * 60)
    print(f"✓ {output.relative_to(ROOT)}  ({size_mb:.1f} MB{', plus its folder' if args.onedir else ''})")
    print("  Data dir: per-user app folder; --portable (or a portable.flag file next to it)")
    print("  keeps config in vrcActorSync-data/ beside the program.")
    if IS_WINDOWS:
        print("  Needs the Microsoft WebView2 Runtime for the window; falls back to the browser.")
    else:
        glibc = required_glibc(output, args.onedir)
        if glibc:
            print(f"  Needs glibc {glibc[0]} or newer on the target (newest requirement: {glibc[1]}).")
        print("  Opens the UI in the default browser; quit with Ctrl+C in its terminal.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
