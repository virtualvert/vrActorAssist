import asyncio
import sys

import pytest

from agent import folders as folders_mod
from agent.folders import FolderError, Folders, list_audio, pick_folder
from agent.web import COOKIE

from .helpers import ORIGIN, login


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "EP3"
    (root / "sfx").mkdir(parents=True)
    (root / "Scene 4 - Diego.mp3").write_bytes(b"mp3")
    (root / "Scene 4 - Mira.WAV").write_bytes(b"wav")
    (root / "sfx" / "door.flac").write_bytes(b"flac")
    (root / "notes.txt").write_text("not audio")
    (root / ".hidden.wav").write_bytes(b"x")
    (root / ".cache").mkdir()
    (root / ".cache" / "a.wav").write_bytes(b"x")
    (root / "normalized").mkdir()
    (root / "normalized" / "old.wav").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.wav").write_bytes(b"secret")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "link.wav").symlink_to(outside / "secret.wav")
    return root


def test_lists_audio_only(project):
    assert [f["path"] for f in list_audio(project)] == ["Scene 4 - Diego.mp3", "Scene 4 - Mira.WAV", "sfx/door.flac"]
    assert list_audio(project)[0]["size"] == 3


def test_open_resolves_and_reports_the_output_folder(project):
    result = Folders().open(f"  '{project}' ")
    assert result["folder"] == str(project.resolve())
    assert result["output"] == str(project.resolve() / "normalized")
    assert len(result["files"]) == 3 and result["truncated"] is False


@pytest.mark.parametrize("folder", ["", "relative/path", "/no/such/folder"])
def test_open_needs_an_existing_absolute_folder(folder):
    with pytest.raises(FolderError):
        Folders().open(folder)


def test_reads_need_an_opened_folder(project):
    with pytest.raises(FolderError, match="Open the folder first"):
        Folders().source(str(project), "sfx/door.flac")


@pytest.mark.parametrize("rel", ["../outside/secret.wav", "/etc/passwd", "link.wav", "linked/secret.wav", "notes.txt", "sfx"])
def test_reads_stay_inside_and_audio_only(project, rel):
    folders = Folders()
    folders.open(str(project))
    with pytest.raises(FolderError):
        folders.source(str(project), rel)


def test_reads_an_audio_file(project):
    folders = Folders()
    folders.open(str(project))
    assert folders.source(str(project), "sfx/door.flac").read_bytes() == b"flac"


def test_writes_go_under_normalized(project):
    folders = Folders()
    folders.open(str(project))
    target = folders.write(str(project), "sfx/door.wav", b"RIFF")
    assert target == project / "normalized" / "sfx" / "door.wav"
    assert target.read_bytes() == b"RIFF"
    assert not list((project / "normalized" / "sfx").glob("*.part"))
    folders.write(str(project), "sfx/door.wav", b"RIFF2")  # overwrites its own copy
    assert target.read_bytes() == b"RIFF2"


@pytest.mark.parametrize("rel", ["door.mp3", "../door.wav", "/tmp/door.wav", "../../outside/x.wav"])
def test_writes_refuse_other_places_and_formats(project, rel):
    folders = Folders()
    folders.open(str(project))
    with pytest.raises(FolderError):
        folders.write(str(project), rel, b"RIFF")


def test_writes_refuse_links_out_of_normalized(project, tmp_path):
    folders = Folders()
    folders.open(str(project))
    (project / "normalized" / "escape").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(FolderError):
        folders.write(str(project), "escape/x.wav", b"RIFF")
    assert not (tmp_path / "outside" / "x.wav").exists()


def test_writes_refuse_a_linked_output_folder(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (root / "normalized").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    folders = Folders()
    folders.open(str(root))
    with pytest.raises(FolderError, match="is a link"):
        folders.write(str(root), "a.wav", b"RIFF")


# --- picker -------------------------------------------------------------------------------


class FakeWindow:
    def __init__(self, result):
        self.result = result
        self.kinds = []

    def create_file_dialog(self, kind):
        self.kinds.append(kind)
        return self.result


def test_picker_uses_the_app_window(monkeypatch):
    window = FakeWindow(("/home/me/EP3",))
    monkeypatch.setattr(folders_mod, "_pywebview_window", lambda: window)
    monkeypatch.setattr(folders_mod, "_folder_dialog_kind", lambda: "folder")
    assert asyncio.run(pick_folder()) == "/home/me/EP3"
    assert window.kinds == ["folder"]
    window.result = None
    assert asyncio.run(pick_folder()) is None


def test_linux_picker_prefers_kdialog_on_kde(monkeypatch):
    monkeypatch.setattr(folders_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert folders_mod._linux_picker()[0] == "kdialog"
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert folders_mod._linux_picker()[0] == "zenity"
    monkeypatch.setattr(folders_mod.shutil, "which", lambda name: "/usr/bin/kdialog" if name == "kdialog" else None)
    assert folders_mod._linux_picker()[0] == "kdialog"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux dialog fallback")
@pytest.mark.parametrize(("code", "out", "expected"), [(0, "/home/me/EP3\n", "/home/me/EP3"), (1, "", None)])
def test_linux_picker_result_and_cancel(monkeypatch, tmp_path, code, out, expected):
    script = tmp_path / "picker"
    script.write_text(f"#!/bin/sh\nprintf '{out}'\nexit {code}\n")
    script.chmod(0o755)
    monkeypatch.setattr(folders_mod, "_pywebview_window", lambda: None)
    monkeypatch.setattr(folders_mod, "_linux_picker", lambda: [str(script)])
    assert asyncio.run(pick_folder()) == expected


def test_no_picker_asks_for_a_typed_path(monkeypatch):
    monkeypatch.setattr(folders_mod, "_pywebview_window", lambda: None)
    monkeypatch.setattr(folders_mod, "_linux_picker", lambda: None)
    with pytest.raises(FolderError, match="Type or paste"):
        asyncio.run(pick_folder())


# --- HTTP endpoints -----------------------------------------------------------------------


@pytest.fixture
def client(env):
    client, security, _ = env
    login(client, security)
    return client


def test_endpoints_need_origin_and_session(client, project):
    assert client.post("/api/folders/open", json={"folder": str(project)}).status_code == 403
    client.cookies.delete(COOKIE)
    res = client.post("/api/folders/open", json={"folder": str(project)}, headers={"Origin": ORIGIN})
    assert res.status_code == 401


def test_open_read_write_round_trip(client, project):
    headers = {"Origin": ORIGIN}
    listing = client.post("/api/folders/open", json={"folder": str(project)}, headers=headers).json()
    assert [f["path"] for f in listing["files"]][-1] == "sfx/door.flac"

    read = client.post("/api/folders/read", json={"folder": listing["folder"], "path": "sfx/door.flac"}, headers=headers)
    assert read.status_code == 200 and read.content == b"flac"

    bad = client.post("/api/folders/read", json={"folder": listing["folder"], "path": "../outside/secret.wav"}, headers=headers)
    assert bad.status_code == 400 and "outside" in bad.json()["error"]

    written = client.post(
        "/api/folders/write",
        params={"folder": listing["folder"], "path": "sfx/door.wav"},
        content=b"RIFFdata",
        headers=headers,
    )
    assert written.status_code == 200
    assert (project / "normalized" / "sfx" / "door.wav").read_bytes() == b"RIFFdata"


def test_unknown_folder_is_refused(client, project):
    res = client.post("/api/folders/read", json={"folder": str(project), "path": "sfx/door.flac"}, headers={"Origin": ORIGIN})
    assert res.status_code == 400 and res.json()["error"] == "Open the folder first"


def test_durations_endpoint_returns_only_numbers_for_media_in_an_opened_folder(client, project):
    import wave

    with wave.open(str(project / "Scene 4 - Mira.WAV"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 12000)  # 1.5 s
    (project / "clip.mp4").write_bytes(b"not really a video")
    headers = {"Origin": ORIGIN}
    paths = ["Scene 4 - Mira.WAV", "clip.mp4", "notes.txt", "link.wav", "../outside/secret.wav", "gone.wav"]

    refused = client.post("/api/folders/durations", json={"folder": str(project), "paths": paths}, headers=headers)
    assert refused.status_code == 400 and refused.json()["error"] == "Open the folder first"
    assert client.post("/api/folders/durations", json={"folder": str(project), "paths": paths}).status_code == 403

    listing = client.post("/api/folders/open", json={"folder": str(project), "kind": "all"}, headers=headers).json()
    res = client.post("/api/folders/durations", json={"folder": listing["folder"], "paths": paths}, headers=headers)
    assert res.status_code == 200
    assert res.json()["durations"] == {
        "Scene 4 - Mira.WAV": 1500, "clip.mp4": None, "notes.txt": None,
        "link.wav": None, "../outside/secret.wav": None, "gone.wav": None,
    }
    bad = client.post("/api/folders/durations", json={"folder": listing["folder"], "paths": "x"}, headers=headers)
    assert bad.status_code == 400
