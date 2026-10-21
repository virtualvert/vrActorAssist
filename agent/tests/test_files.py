"""Files addon (agent/files.py): receiving, sending, and both through a real v2 relay."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import files as files_mod
from agent.config import Config, ConfigStore
from agent.files import (
    MAX_IN_FLIGHT,
    FileRefused,
    Receiver,
    Sender,
    load_received,
    parse_character_name,
    safe_name,
)
from vrcas_protocol import pack_chunk, unpack_chunk

from .test_relay_legacy import SECRET, make_agent, wait_for
from .test_relay_v2 import relay  # noqa: F401  (fixture)

CHUNK = 16 * 1024


# ---- names ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Scene 4 - Diego.mp3", "日本語.wav", "a.b.c.flac", "x" * 200, "CONSOLE.wav", "con-list.txt"])
def test_safe_names_pass(name):
    assert safe_name(name) == name


@pytest.mark.parametrize("name", [
    "", ".", "..", "../x.wav", "a/b.wav", "a\\b.wav", "C:\\x.wav", "C:x.wav", "x.wav.", "x.wav ", " x.wav",
    "CON", "con.wav", "NUL.mp3", "COM1.wav", "lpt9.txt", "a|b.wav", "a?.wav", "tab\there.wav", "x" * 201,
])
def test_unsafe_names_are_refused(name):
    with pytest.raises(FileRefused):
        safe_name(name)


@pytest.mark.parametrize("filename, character", [
    ("Scene 4 - Diego.mp3", "Diego"),
    ("EP3 - Scene 4.2 - Diego.wav", "Diego"),
    ("intro.wav", None),
    ("Scene 4 - .mp3", None),
    ("Scene 4 - Mira Jones.flac", "Mira Jones"),
])
def test_parse_character_name(filename, character):
    assert parse_character_name(filename) == character


# ---- receiving (no relay: the sent messages are recorded) -------------------------------------------


class Recorder:
    def __init__(self):
        self.sent = []
        self.frames = []

    async def send(self, msg_type, data, to):
        self.sent.append((msg_type, data, to))

    async def send_frame(self, frame):
        self.frames.append(frame)

    def types(self):
        return [t for t, _, _ in self.sent]

    def last(self, msg_type):
        return next(d for t, d, _ in reversed(self.sent) if t == msg_type)


def fake_agent(tmp_path, role="actor", auto_accept=False):
    cfg = Config()
    cfg.role = role
    cfg.files.receive_dir = str(tmp_path / "inbox")
    cfg.files.auto_accept = auto_accept
    store = SimpleNamespace(folder=tmp_path / "data", save=lambda: None, config=cfg)
    logs = []
    agent = SimpleNamespace(
        config=cfg, store=store, changed=lambda: None, files=Recorder(),
        hub=SimpleNamespace(log=lambda level, text, sender=None: logs.append((level, text)), toast=lambda *a: None),
    )
    agent.logs = logs
    return agent


def offer_env(content: bytes, tid="0f" * 16, name="Scene 4 - Diego.mp3", **extra):
    data = {"transfer_id": tid, "name": name, "size": len(content), "chunk_size": CHUNK,
            "sha256": hashlib.sha256(content).hexdigest(), **extra}
    return {"type": "file.offer", "from": "s_dir", "data": data}


def frames(content: bytes, tid="0f" * 16):
    return [pack_chunk(tid, i, content[o:o + CHUNK]) for i, o in enumerate(range(0, len(content), CHUNK))]


async def deliver(rx, content, tid="0f" * 16, sha256=None):
    for frame in frames(content, tid):
        await rx.on_chunk(frame)
    end = {"transfer_id": tid}
    end["sha256"] = sha256 or hashlib.sha256(content).hexdigest()
    await rx.on_message({"type": "file.end", "from": "s_dir", "data": end}, "Mira")


def test_receive_with_prompt(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path)
        rx = Receiver(agent)
        content = os.urandom(CHUNK * 2 + 100)
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "Scene 4 - Diego.mp3").write_bytes(b"old")
        await rx.on_message(offer_env(content, character="Diego"), "Mira")
        view = rx.view()["incoming"][0]
        assert view["state"] == "asking" and view["replaces"] and view["character"] == "Diego" and view["from"] == "Mira"
        assert agent.files.types() == []

        # Chunks before the answer are dropped
        await rx.on_chunk(frames(content)[0])
        assert not list((tmp_path / "inbox").glob(".*.part"))

        await rx.answer("0f" * 16, accept=True)
        assert agent.files.types() == ["file.accept"]
        await deliver(rx, content)
        assert (tmp_path / "inbox" / "Scene 4 - Diego.mp3").read_bytes() == content
        assert agent.files.types() == ["file.accept"] + ["file.progress"] * 3 + ["file.ok"]
        assert agent.files.last("file.progress")["received"] == 3
        assert agent.files.last("file.ok")["saved_as"] == "inbox/Scene 4 - Diego.mp3"
        assert not list((tmp_path / "inbox").glob(".*"))
        assert rx.view()["incoming"] == [] and rx.view()["recent"][0]["ok"]
        record = load_received(tmp_path / "data" / "received.json")
        assert record[0]["sha256"] == hashlib.sha256(content).hexdigest()
        assert record[0]["path"] == str(tmp_path / "inbox" / "Scene 4 - Diego.mp3")
        # every reply goes back to the director's session
        assert {json.dumps(to) for _, _, to in agent.files.sent} == {json.dumps({"ids": ["s_dir"]})}

    asyncio.run(scenario())


def test_decline_and_auto_accept(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path)
        rx = Receiver(agent)
        await rx.on_message(offer_env(b"abc"), "Mira")
        await rx.answer("0f" * 16, accept=False)
        assert agent.files.last("file.deny")["reason"] == "Declined"
        assert rx.view()["incoming"] == []

        # "Accept files automatically from now on" answers this one and turns auto-accept on
        await rx.on_message(offer_env(b"abc", tid="1f" * 16), "Mira")
        await rx.answer("1f" * 16, accept=True, always=True)
        assert agent.config.files.auto_accept
        await rx.on_message(offer_env(b"xyz", tid="2f" * 16, name="b.wav"), "Mira")
        assert agent.files.types()[-1] == "file.accept"
        await deliver(rx, b"xyz", tid="2f" * 16)
        assert (tmp_path / "inbox" / "b.wav").read_bytes() == b"xyz"

    asyncio.run(scenario())


def test_accept_the_rest_of_the_batch(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path)
        rx = Receiver(agent)
        await rx.on_message({"type": "file.batch.start", "from": "s_dir", "data": {"batch_id": "b1", "files": 3, "bytes": 9}}, "Mira")
        await rx.on_message(offer_env(b"one", tid="1f" * 16, name="1.wav", batch_id="b1"), "Mira")
        view = rx.view()["incoming"][0]
        assert (view["index"], view["count"]) == (1, 3)
        await rx.answer("1f" * 16, accept=True, rest=True)
        await rx.on_message(offer_env(b"two", tid="2f" * 16, name="2.wav", batch_id="b1"), "Mira")
        assert agent.files.types() == ["file.accept", "file.accept"]
        assert not agent.config.files.auto_accept
        # another batch asks again
        await rx.on_message(offer_env(b"three", tid="3f" * 16, name="3.wav", batch_id="b2"), "Mira")
        assert agent.files.types() == ["file.accept", "file.accept"]

    asyncio.run(scenario())


@pytest.mark.parametrize("offer, reason", [
    ({"name": "../evil.wav"}, "characters"),
    ({"name": "NUL.wav"}, "reserved"),
    ({"size": 10**12}, "Bad offer"),
    ({"sha256": None}, "Bad offer"),
])
def test_bad_offers_are_declined(tmp_path, offer, reason):
    async def scenario():
        agent = fake_agent(tmp_path)
        rx = Receiver(agent)
        env = offer_env(b"abc")
        env["data"].update(offer)
        await rx.on_message(env, "Mira")
        assert agent.files.types() == ["file.deny"]
        assert reason in agent.files.last("file.deny")["reason"]
        assert rx.view()["incoming"] == []

    asyncio.run(scenario())


def test_not_enough_disk_space(tmp_path, monkeypatch):
    async def scenario():
        agent = fake_agent(tmp_path)
        rx = Receiver(agent)
        monkeypatch.setattr(files_mod.shutil, "disk_usage", lambda p: SimpleNamespace(free=10))
        await rx.on_message(offer_env(b"abc"), "Mira")
        assert "disk space" in agent.files.last("file.deny")["reason"]

    asyncio.run(scenario())


def test_bad_data_leaves_nothing_behind(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path, auto_accept=True)
        rx = Receiver(agent)
        content = os.urandom(CHUNK + 10)
        inbox = tmp_path / "inbox"

        # wrong hash at the end
        await rx.on_message(offer_env(content, tid="1f" * 16), "Mira")
        await deliver(rx, content, tid="1f" * 16, sha256="00" * 32)
        assert agent.files.last("file.err")["error"] == "Checksum mismatch"

        # a chunk of the wrong size
        await rx.on_message(offer_env(content, tid="2f" * 16), "Mira")
        await rx.on_chunk(pack_chunk("2f" * 16, 1, b"short"))
        assert "doesn't fit" in agent.files.last("file.err")["error"]

        # file.end before every chunk arrived
        await rx.on_message(offer_env(content, tid="3f" * 16), "Mira")
        await rx.on_chunk(frames(content, "3f" * 16)[0])
        await rx.on_message({"type": "file.end", "from": "s_dir", "data": {"transfer_id": "3f" * 16, "sha256": "ab" * 32}}, "Mira")
        assert "1 of 2 chunks" in agent.files.last("file.err")["error"]

        assert list(inbox.iterdir()) == []
        assert rx.incoming == {}

    asyncio.run(scenario())


def test_duplicate_chunks_and_md5_only(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path, auto_accept=True)
        rx = Receiver(agent)
        content = os.urandom(CHUNK + 10)
        env = offer_env(content, sha256=None, md5=hashlib.md5(content).hexdigest())
        await rx.on_message(env, "Mira")
        first = frames(content)[0]
        await rx.on_chunk(first)
        await rx.on_chunk(first)
        assert agent.files.last("file.progress")["received"] == 1
        await rx.on_chunk(frames(content)[1])
        await rx.on_message({"type": "file.end", "from": "s_dir", "data": {"transfer_id": "0f" * 16, "md5": hashlib.md5(content).hexdigest()}}, "Mira")
        assert agent.files.types()[-1] == "file.ok"
        assert (tmp_path / "inbox" / "Scene 4 - Diego.mp3").read_bytes() == content

    asyncio.run(scenario())


def test_cancel_and_relay_loss_delete_partial_files(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path, auto_accept=True)
        rx = Receiver(agent)
        content = os.urandom(CHUNK * 3)
        inbox = tmp_path / "inbox"
        await rx.on_message({"type": "file.batch.start", "from": "s_dir", "data": {"batch_id": "b1", "files": 2, "bytes": 1}}, "Mira")
        await rx.on_message(offer_env(content, batch_id="b1"), "Mira")
        await rx.on_chunk(frames(content)[0])
        assert len(list(inbox.glob(".*.part"))) == 1
        await rx.on_message({"type": "file.batch.cancel", "from": "s_dir", "data": {"batch_id": "b1", "reason": "x"}}, "Mira")
        assert list(inbox.iterdir()) == [] and rx.incoming == {}
        assert rx.view()["recent"][0]["detail"] == "cancelled by the director"

        # chunks after the cancel are ignored
        await rx.on_chunk(frames(content)[1])
        assert list(inbox.iterdir()) == []

        # the relay goes away mid-file
        await rx.on_message(offer_env(content, tid="1f" * 16), "Mira")
        await rx.on_chunk(frames(content, "1f" * 16)[0])
        rx.reset("Lost the relay connection")
        assert list(inbox.iterdir()) == [] and rx.incoming == {}

        # the relay reports that the director left
        await rx.on_message(offer_env(content, tid="2f" * 16), "Mira")
        await rx.on_message({"type": "file.err", "from": "server", "data": {"transfer_id": "2f" * 16, "error": "Mira disconnected"}}, "Mira")
        assert list(inbox.iterdir()) == [] and rx.incoming == {}

    asyncio.run(scenario())


# ---- sending (no relay) --------------------------------------------------------------------------


def make_file(tmp_path, name, size):
    path = tmp_path / "src" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


def test_sender_window_and_result(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path, role="director")
        tx = Sender(agent)
        path = make_file(tmp_path, "Scene 4 - Diego.mp3", 12 * 256 * 1024 + 5)
        batch = tx.start("s_coda", "Coda", [path])
        await settle()
        sent = agent.files
        assert sent.types() == ["file.batch.start", "file.offer"]
        offer = sent.last("file.offer")
        assert offer["character"] == "Diego" and offer["size"] == path.stat().st_size
        assert offer["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert offer["md5"] == hashlib.md5(path.read_bytes()).hexdigest()
        tid = offer["transfer_id"]
        assert batch.view()["current"]["waiting"]

        tx.on_message({"type": "file.accept", "data": {"transfer_id": tid}})
        await settle()
        assert len(sent.frames) == MAX_IN_FLIGHT  # waits for progress
        tx.on_message({"type": "file.progress", "data": {"transfer_id": tid, "received": 4}})
        await settle()
        assert len(sent.frames) == 12
        tx.on_message({"type": "file.progress", "data": {"transfer_id": tid, "received": 13}})
        await settle()
        assert len(sent.frames) == 13 and sent.types()[-1] == "file.end"
        assert b"".join(unpack_chunk(f).payload for f in sent.frames) == path.read_bytes()
        assert [unpack_chunk(f).index for f in sent.frames] == list(range(13))

        tx.on_message({"type": "file.ok", "data": {"transfer_id": tid, "saved_as": "x"}})
        await settle()
        assert sent.types()[-1] == "file.batch.end" and sent.last("file.batch.end") == {"batch_id": batch.id, "ok": 1, "failed": 0}
        view = batch.view()
        assert view["state"] == "done" and view["ok"] == 1 and view["sentBytes"] == view["bytes"]
        assert {json.dumps(to) for _, _, to in sent.sent} == {json.dumps({"ids": ["s_coda"]})}

    asyncio.run(scenario())


def test_sender_decline_err_and_cancel(tmp_path):
    async def scenario():
        agent = fake_agent(tmp_path, role="director")
        tx = Sender(agent)
        paths = [make_file(tmp_path, f"{i}.wav", 300_000) for i in range(3)]
        batch = tx.start("s_coda", "Coda", paths)
        await settle()
        tx.on_message({"type": "file.deny", "data": {"transfer_id": agent.files.last("file.offer")["transfer_id"], "reason": "Declined"}})
        await settle()
        second = agent.files.last("file.offer")
        assert second["name"] == "1.wav"
        tx.on_message({"type": "file.accept", "data": {"transfer_id": second["transfer_id"]}})
        await settle()
        tx.on_message({"type": "file.err", "data": {"transfer_id": second["transfer_id"], "error": "Writing failed"}})
        await settle()
        assert agent.files.last("file.offer")["name"] == "2.wav"
        await tx.cancel(batch.id)
        assert agent.files.types()[-1] == "file.batch.cancel"
        view = batch.view()
        assert view["state"] == "cancelled" and view["ok"] == 0 and view["failed"] == 3
        assert [r["state"] for r in view["results"]] == ["declined", "failed", "cancelled"]

    asyncio.run(scenario())


def test_sender_stall(tmp_path, monkeypatch):
    monkeypatch.setattr(files_mod, "STALL_TIMEOUT_S", 0.1)

    async def scenario():
        agent = fake_agent(tmp_path, role="director")
        tx = Sender(agent)
        batch = tx.start("s_coda", "Coda", [make_file(tmp_path, "big.wav", 20 * 256 * 1024)])
        await settle()
        tx.on_message({"type": "file.accept", "data": {"transfer_id": agent.files.last("file.offer")["transfer_id"]}})
        await asyncio.sleep(0.4)
        assert batch.state == "failed" and "stopped answering" in batch.detail
        assert "file.batch.cancel" in agent.files.types()

    asyncio.run(scenario())


# ---- through the relay -------------------------------------------------------------------------


def test_files_end_to_end(relay, tmp_path, monkeypatch):  # noqa: F811
    running, state = relay
    url = f"127.0.0.1:{running.port}"
    src = tmp_path / "project"
    (src / "normalized").mkdir(parents=True)
    names = ["Scene 4 - Diego.mp3", "Scene 5 - Diego.wav", "normalized/Scene 6 - Rin.wav"]
    contents = {n: os.urandom(size) for n, size in zip(names, (700_000, 10, 300_000))}
    for n, data in contents.items():
        (src / n).write_bytes(data)

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        coda = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", url)
        rin = make_agent(tmp_path, monkeypatch, "Rin", "actor", "m-rin", url)
        for actor in (coda, rin):
            actor.config.files.receive_dir = str(tmp_path / f"inbox-{actor.config.name}")
        rin.config.files.auto_accept = True
        (tmp_path / "inbox-Coda").mkdir()
        (tmp_path / "inbox-Coda" / "Scene 5 - Diego.wav").write_bytes(b"old take")
        try:
            await director.start()
            await wait_for(lambda: director.relay.status == "connected")
            for actor in (coda, rin):
                await actor.start()
            await wait_for(lambda: len(director.snapshot()["pending"]) == 2)
            for p in list(director.snapshot()["pending"]):
                await director.handle_call("approve", {"id": p["id"]})
            await wait_for(lambda: coda.relay.status == "connected" and rin.relay.status == "connected")
            await wait_for(lambda: len([p for p in director.snapshot()["peers"] if "files" in p["caps"]]) == 2)
            ids = {p["name"]: p["id"] for p in director.snapshot()["peers"]}

            listing = director.folders.open(str(src), "all")
            assert [f["path"] for f in listing["files"]] == sorted(names, key=str.casefold)
            await director.handle_call("sendFiles", {"folder": str(src), "items": [
                {"path": names[0], "actorId": ids["Coda"]},
                {"path": names[1], "actorId": ids["Coda"]},
                {"path": names[2], "actorId": ids["Rin"]},
            ]})

            # Rin auto-accepts; Coda is asked once per file, the second one "replaces"
            await wait_for(lambda: (tmp_path / "inbox-Rin" / "Scene 6 - Rin.wav").exists())
            await wait_for(lambda: len(coda.snapshot()["actor"]["files"]["incoming"]) == 1)
            first = coda.snapshot()["actor"]["files"]["incoming"][0]
            assert first["name"] == names[0] and first["from"] == "Mira" and first["character"] == "Diego"
            assert (first["index"], first["count"]) == (1, 2) and not first["replaces"]
            await coda.handle_call("answerFile", {"transferId": first["transferId"], "accept": True})
            await wait_for(lambda: any(i["name"] == names[1] for i in coda.snapshot()["actor"]["files"]["incoming"]))
            second = coda.snapshot()["actor"]["files"]["incoming"][0]
            assert second["replaces"]
            await coda.handle_call("answerFile", {"transferId": second["transferId"], "accept": True})

            await wait_for(lambda: all(b["state"] == "done" for b in director.snapshot()["director"]["files"]["batches"]))
            for name, folder in ((names[0], "inbox-Coda"), (names[1], "inbox-Coda"), (names[2], "inbox-Rin")):
                assert (tmp_path / folder / Path(name).name).read_bytes() == contents[name]
            batches = {b["actorName"]: b for b in director.snapshot()["director"]["files"]["batches"]}
            assert (batches["Coda"]["ok"], batches["Rin"]["ok"]) == (2, 1)
            assert state.files.by_id == {}
            log = (tmp_path / "relay" / "server.log").read_text(encoding="utf-8")
            assert "File Mira → Coda: Scene 4 - Diego.mp3 (683.6 KB): ok" in log

            # Cancel mid-file: Coda writes slowly, the director cancels after the first progress
            slow = files_mod._write_at

            def slow_write(handle, offset, payload):
                import time
                time.sleep(0.05)
                slow(handle, offset, payload)

            monkeypatch.setattr(files_mod, "_write_at", slow_write)
            coda.config.files.auto_accept = True
            big = src / "Scene 7 - Diego.wav"
            big.write_bytes(os.urandom(40 * 256 * 1024))
            director.folders.open(str(src), "all")
            await director.handle_call("sendFiles", {"folder": str(src), "items": [{"path": big.name, "actorId": ids["Coda"]}]})
            await wait_for(lambda: any(b["state"] == "sending" and b["sentBytes"] > 0
                                       for b in director.snapshot()["director"]["files"]["batches"]), timeout=10)
            running_batch = next(b for b in director.snapshot()["director"]["files"]["batches"] if b["state"] == "sending")
            await director.handle_call("cancelBatch", {"id": running_batch["id"]})
            await wait_for(lambda: coda.files.receiver.incoming == {} and state.files.by_id == {}, timeout=10)
            await asyncio.sleep(0.3)
            assert not (tmp_path / "inbox-Coda" / big.name).exists()
            assert not list((tmp_path / "inbox-Coda").glob(".*.part"))

            # Files outside the opened folder, hidden ones and duplicate names are refused
            with pytest.raises(Exception, match="inside the folder"):
                await director.handle_call("sendFiles", {"folder": str(src), "items": [{"path": "../x", "actorId": ids["Coda"]}]})
            (src / ".hidden.wav").write_bytes(b"x")
            with pytest.raises(Exception, match="hidden"):
                await director.handle_call("sendFiles", {"folder": str(src), "items": [{"path": ".hidden.wav", "actorId": ids["Coda"]}]})
            with pytest.raises(Exception, match="two files named"):
                await director.handle_call("sendFiles", {"folder": str(src), "items": [
                    {"path": names[2], "actorId": ids["Coda"]}, {"path": names[2], "actorId": ids["Coda"]}]})
        finally:
            for agent in (rin, coda, director):
                await agent.shutdown()

    asyncio.run(scenario())


def test_v03_import_of_file_settings(tmp_path):
    (tmp_path / "actor_config.json").write_text(json.dumps({"actor_name": "Coda", "receive_dir": "C:/cues", "auto_accept_files": True}))
    store = ConfigStore(tmp_path / "data", legacy_folder=tmp_path)
    assert store.config.files.receive_dir == "C:/cues" and store.config.files.auto_accept
    again = ConfigStore(tmp_path / "data")
    assert again.config.files.receive_dir == "C:/cues"
