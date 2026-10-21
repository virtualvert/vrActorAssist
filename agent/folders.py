"""Folder access for Normalize folder (spec §8.4.2) and Send files (§8.4): pick, list, read, write.

The page measures and converts the audio itself; the agent only moves bytes, within limits:
- it reads only files inside folders the person opened in this run of the app: audio files for
  Normalize folder, any non-hidden file (up to 1 GiB) for sending;
- it writes only `.wav` files under `<folder>/normalized/`, atomically;
- symlinks and `..` can't lead outside those folders.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac"}
OUTPUT_DIR = "normalized"
MAX_FILES = 5000
MAX_READ_BYTES = 300 * 1024 * 1024
MAX_WRITE_BYTES = 1024 * 1024 * 1024
MAX_SEND_BYTES = 1024 * 1024 * 1024
PICKER_TITLE = "Choose a folder of audio files"


class FolderError(Exception):
    """A problem the person can fix; the message is shown in the UI."""


class Folders:
    def __init__(self) -> None:
        self._opened: set[Path] = set()

    def open(self, folder: str, kind: str = "audio") -> dict:
        """kind "audio": audio files outside normalized/ (Normalize folder). "all": every
        non-hidden file, normalized/ included (Send files)."""
        root = resolve_root(folder)
        files = list_all(root) if kind == "all" else list_audio(root)
        self._opened.add(root)
        return {
            "folder": str(root),
            "output": str(root / OUTPUT_DIR),
            "files": files[:MAX_FILES],
            "truncated": len(files) > MAX_FILES,
        }

    def source(self, folder: str, rel: str) -> Path:
        root = self._root(folder)
        path = inside(root, rel)
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise FolderError(f"{rel} isn't an audio file")
        if not path.is_file():
            raise FolderError(f"{rel} no longer exists")
        if path.stat().st_size > MAX_READ_BYTES:
            raise FolderError(f"{rel} is larger than {MAX_READ_BYTES // 2**20} MB")
        return path

    def send_source(self, folder: str, rel: str) -> Path:
        """A file to send: any type, inside an opened folder, not hidden, at most 1 GiB."""
        root = self._root(folder)
        path = inside(root, rel)
        if any(part.startswith(".") for part in PurePosixPath(rel.replace("\\", "/")).parts):
            raise FolderError(f"{rel} is hidden")
        if path.is_symlink() or not path.is_file():
            raise FolderError(f"{rel} isn't a file in the folder")
        if path.stat().st_size > MAX_SEND_BYTES:
            raise FolderError(f"{rel} is larger than {MAX_SEND_BYTES // 2**30} GB")
        return path

    def write(self, folder: str, rel: str, data: bytes) -> Path:
        root = self._root(folder)
        if not rel.lower().endswith(".wav"):
            raise FolderError("Copies must be .wav files")
        if len(data) > MAX_WRITE_BYTES:
            raise FolderError("That copy is too large")
        out_root = root / OUTPUT_DIR
        if out_root.is_symlink():
            raise FolderError(f"{out_root} is a link; remove it or pick another folder")
        out_root.mkdir(exist_ok=True)
        target = inside(out_root, rel, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Check again now that the folders exist, in case something swapped one for a link.
        if not target.parent.resolve().is_relative_to(out_root.resolve()):
            raise FolderError(f"{rel} leads outside the folder")
        fd, temp = tempfile.mkstemp(prefix=".vrcas-", suffix=".part", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp, target)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        return target

    def _root(self, folder: str) -> Path:
        root = resolve_root(folder)
        if root not in self._opened:
            raise FolderError("Open the folder first")
        return root


def resolve_root(folder: str) -> Path:
    text = folder.strip().strip('"').strip("'")
    if not text:
        raise FolderError("Choose a folder first")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise FolderError("Use the full path of the folder")
    try:
        root = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise FolderError(f"{text} doesn't exist") from None
    if not root.is_dir():
        raise FolderError(f"{text} isn't a folder")
    return root


def inside(root: Path, rel: str, must_exist: bool = True) -> Path:
    """`root / rel`, refusing absolute paths, `..` and links that lead outside root."""
    clean = rel.replace("\\", "/")
    parts = PurePosixPath(clean).parts
    # A colon would name a drive or an NTFS stream on Windows; elsewhere it's a normal character.
    if clean.startswith("/") or any(p == ".." or (os.name == "nt" and ":" in p) for p in parts):
        raise FolderError(f"Not a path inside the folder: {rel}")
    path = root.joinpath(*parts)
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError):
        raise FolderError(f"{rel} doesn't exist") from None
    if not resolved.is_relative_to(root.resolve()):
        raise FolderError(f"{rel} leads outside the folder")
    return path


def list_audio(root: Path) -> list[dict]:
    """Audio files under root (relative, forward slashes), skipping hidden files, links and our output."""
    found: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and not (here == root and d.casefold() == OUTPUT_DIR)
            and not (here / d).is_symlink()
        ]
        for name in filenames:
            path = here / name
            if name.startswith(".") or path.suffix.lower() not in AUDIO_EXTENSIONS or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append({"path": path.relative_to(root).as_posix(), "size": size})
            if len(found) > MAX_FILES:
                break
    found.sort(key=lambda f: f["path"].casefold())
    return found


def list_all(root: Path) -> list[dict]:
    """Every regular file under root, skipping hidden files and folders and links."""
    found: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and not (here / d).is_symlink()]
        for name in filenames:
            path = here / name
            if name.startswith(".") or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append({"path": path.relative_to(root).as_posix(), "size": size})
            if len(found) > MAX_FILES:
                break
    found.sort(key=lambda f: f["path"].casefold())
    return found


async def pick_folder() -> str | None:
    """Ask for a folder with a native dialog. None when the person cancels."""
    window = _pywebview_window()
    if window is not None:
        result = await asyncio.to_thread(window.create_file_dialog, _folder_dialog_kind())
        return str(result[0]) if result else None
    if sys.platform.startswith("linux"):
        argv = _linux_picker()
        if argv:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            out, _ = await proc.communicate()
            if proc.returncode == 0:
                return out.decode("utf-8", "replace").strip() or None
            if proc.returncode == 1:  # both kdialog and zenity use 1 for Cancel
                return None
            raise FolderError(f"The folder dialog failed ({argv[0]} exited with {proc.returncode})")
    raise FolderError("No folder dialog is available here. Type or paste the folder path instead.")


def _pywebview_window():
    try:
        import webview
    except ImportError:
        return None
    windows = getattr(webview, "windows", None) or []
    return windows[0] if windows else None


def _folder_dialog_kind():
    import webview

    kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
    return kind if kind is not None else webview.FOLDER_DIALOG


def _linux_picker() -> list[str] | None:
    """kdialog first on KDE, zenity first elsewhere; whichever is installed."""
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    candidates = {
        "kdialog": ["kdialog", "--title", PICKER_TITLE, "--getexistingdirectory", str(Path.home())],
        "zenity": ["zenity", "--file-selection", "--directory", f"--title={PICKER_TITLE}"],
    }
    for name in (["kdialog", "zenity"] if kde else ["zenity", "kdialog"]):
        if shutil.which(name):
            return candidates[name]
    return None
