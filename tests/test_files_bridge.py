# Files between v0.3 clients on /ws and v0.4 apps on /v2/ws (spec §11.2, Phase 2 plan §4.1).

import base64
import hashlib
import os
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from relay_helpers import connect_legacy, connect_v2, make_relay
from vrcas_protocol import pack_chunk, unpack_chunk

APPROVED = {"m-ari": {"name": "Ari"}, "m-lex": {"name": "Lex"}}
TID = "0f" * 16
K64 = 65536


@pytest.fixture
def client(tmp_path, stack):
    return stack.enter_context(TestClient(make_relay(tmp_path, APPROVED)))


def relay_of(client):
    return client.app.state.relay


def v2(client, stack, role, name, machine_id, caps=("files",)):
    return connect_v2(client, stack, role, name, machine_id, capabilities=list(caps), expect="welcome")


def of_type(envs, msg_type):
    return [e for e in envs if e["type"] == msg_type]


def frames(legacy, prefix):
    return [f for f in legacy.sync() if f.startswith(prefix)]


def b64_pieces(data):
    return [base64.b64encode(data[o:o + K64]).decode() for o in range(0, len(data), K64)]


# ==== v0.3 director → v0.4 actor ====================================================================


def test_v03_director_sends_a_batch_to_a_v2_actor(client, stack, tmp_path):
    old = connect_legacy(client, stack, "director", "Old", "m-old")
    ari = v2(client, stack, "actor", "Ari", "m-ari")
    old_id = next(s for s in relay_of(client).registry if s.name == "Old").id
    data = os.urandom(K64 + 1000)
    md5 = hashlib.md5(data).hexdigest()

    old.send(f"BATCH_START|Ari|2|{len(data) + 4}")
    old.send(f"FILEREQ|Director|Ari|a.wav|{len(data)}|{md5}")
    got = ari.sync()
    start = of_type(got, "file.batch.start")[0]
    offer = of_type(got, "file.offer")[0]
    assert start["from"] == old_id and start["data"]["files"] == 2 and start["data"]["bytes"] == len(data) + 4
    assert offer["from"] == old_id
    batch_id = start["data"]["batch_id"]
    tid = offer["data"]["transfer_id"]
    assert offer["data"] == {"transfer_id": tid, "batch_id": batch_id, "name": "a.wav", "size": len(data),
                             "chunk_size": K64, "md5": md5}

    ari.send("file.accept", {"transfer_id": tid}, to={"ids": [old_id]})
    assert frames(old, "FILE") == ["FILEACK|a.wav|1|"]

    old.send("FILESTART|a.wav|2|65536")
    for i, piece in enumerate(b64_pieces(data)):
        old.send(f"FILECHUNK|a.wav|{i}|{piece}")
    old.send(f"FILEEND|a.wav|{md5}")
    chunks = [unpack_chunk(ari.next_chunk()) for _ in range(2)]
    assert [(c.transfer_id, c.index) for c in chunks] == [(tid, 0), (tid, 1)]
    assert b"".join(c.payload for c in chunks) == data
    assert of_type(ari.sync(), "file.end")[0]["data"] == {"transfer_id": tid, "md5": md5}

    # progress has no v0.3 equivalent; ok comes back as FILEOK
    ari.send("file.progress", {"transfer_id": tid, "received": 2}, to={"ids": [old_id]})
    ari.send("file.ok", {"transfer_id": tid, "saved_as": "vrcActorSync/a.wav"}, to={"ids": [old_id]})
    assert frames(old, "FILE") == ["FILEOK|a.wav|vrcActorSync/a.wav"]

    # the second file is declined, then the batch ends
    old.send(f"FILEREQ|Director|Ari|b.wav|4|{hashlib.md5(b'data').hexdigest()}")
    tid2 = of_type(ari.sync(), "file.offer")[0]["data"]["transfer_id"]
    ari.send("file.deny", {"transfer_id": tid2, "reason": "Declined"}, to={"ids": [old_id]})
    assert frames(old, "FILE") == ["FILEDENY|b.wav|Declined"]
    old.send("BATCH_END|Ari|1|1")
    assert of_type(ari.sync(), "file.batch.end")[0]["data"] == {"batch_id": batch_id, "ok": 1, "failed": 1}

    relay = relay_of(client)
    assert relay.files.by_id == {} and relay.transfers == {} and relay.bridge.files.from_legacy == {}
    log = (tmp_path / "server.log").read_text(encoding="utf-8")
    assert "File Old → Ari: a.wav (65.0 KB): ok" in log and "File Old → Ari: b.wav (0.0 KB): declined (Declined)" in log


def test_v03_director_cancels_between_files(client, stack):
    old = connect_legacy(client, stack, "director", "Old", "m-old")
    ari = v2(client, stack, "actor", "Ari", "m-ari")
    old.send("BATCH_START|Ari|2|8")
    old.send(f"FILEREQ|Director|Ari|a.wav|4|{hashlib.md5(b'abcd').hexdigest()}")
    got = ari.sync()
    batch_id = of_type(got, "file.batch.start")[0]["data"]["batch_id"]
    old.send("BATCH_CANCEL|Ari|Cancelled by director")
    cancel = of_type(ari.sync(), "file.batch.cancel")[0]["data"]
    assert cancel == {"batch_id": batch_id, "reason": "Cancelled by director"}
    assert relay_of(client).files.by_id == {}


@pytest.mark.parametrize("frame, error", [
    ("FILECHUNK|a.wav|0|not*base64", "isn't valid base64"),
    ("FILECHUNK|a.wav|9|ZGF0YQ==", "doesn't fit"),
    ("FILEEND|a.wav|nope", "Bad checksum"),
])
def test_bad_frames_from_a_v03_director(client, stack, frame, error):
    old = connect_legacy(client, stack, "director", "Old", "m-old")
    ari = v2(client, stack, "actor", "Ari", "m-ari")
    old_id = next(s for s in relay_of(client).registry if s.name == "Old").id
    old.send(f"FILEREQ|Director|Ari|a.wav|4|{hashlib.md5(b'abcd').hexdigest()}")
    tid = of_type(ari.sync(), "file.offer")[0]["data"]["transfer_id"]
    ari.send("file.accept", {"transfer_id": tid}, to={"ids": [old_id]})
    old.sync()
    old.send(frame)
    assert error in of_type(ari.sync(), "file.err")[0]["data"]["error"]
    err = frames(old, "FILEERR|")
    assert len(err) == 1 and err[0].startswith("FILEERR|a.wav|") and error in err[0]
    assert relay_of(client).files.by_id == {}


@pytest.mark.parametrize("request_frame, reason", [
    (f"FILEREQ|Director|Ari|a.wav|{2 * 1024**3}|{'0' * 32}", "Files over 1 GB"),
    ("FILEREQ|Director|Ari|a.wav|4|not-md5", "Bad checksum"),
])
def test_v03_requests_a_v2_actor_cant_take(client, stack, request_frame, reason):
    old = connect_legacy(client, stack, "director", "Old", "m-old")
    v2(client, stack, "actor", "Ari", "m-ari")
    old.send(request_frame)
    deny = frames(old, "FILEDENY|")
    assert len(deny) == 1 and reason in deny[0]


def test_v2_actor_leaving_ends_the_v03_directors_file(client, stack):
    old = connect_legacy(client, stack, "director", "Old", "m-old")
    with ExitStack() as inner:
        ari = v2(client, inner, "actor", "Ari", "m-ari")
        old.send(f"FILEREQ|Director|Ari|a.wav|4|{hashlib.md5(b'abcd').hexdigest()}")
        of_type(ari.sync(), "file.offer")
    assert "FILEERR|a.wav|Ari disconnected" in old.sync()
    assert relay_of(client).files.by_id == {} and relay_of(client).bridge.files.from_legacy == {}


# ==== v0.4 director → v0.3 actor ====================================================================


def setup_b(client, stack):
    d = v2(client, stack, "director", "Mira", "m-dir", caps=())
    lex = connect_legacy(client, stack, "actor", "Lex", "m-lex")
    lex_id = next(s for s in relay_of(client).registry if s.name == "Lex").id
    return d, lex, lex_id


def offer_b(d, lex_id, data, name="a.wav", tid=TID, batch="b1", **extra):
    offer = {"transfer_id": tid, "batch_id": batch, "name": name, "size": len(data),
             "sha256": hashlib.sha256(data).hexdigest(), "md5": hashlib.md5(data).hexdigest(), **extra}
    if batch is None:
        offer.pop("batch_id")
    d.send("file.offer", offer, to={"ids": [lex_id]})


def test_v2_director_sends_a_batch_to_a_v03_actor(client, stack, tmp_path):
    d, lex, lex_id = setup_b(client, stack)
    data = os.urandom(256 * 1024 + 37_856)
    md5 = hashlib.md5(data).hexdigest()
    d.send("file.batch.start", {"batch_id": "b1", "files": 2, "bytes": len(data) + 10}, to={"ids": [lex_id]})
    offer_b(d, lex_id, data)
    assert lex.sync()[-3:-1] == [f"BATCH_START|Lex|2|{len(data) + 10}", f"FILEREQ|Mira|Lex|a.wav|{len(data)}|{md5}"]

    lex.send("FILEACK|a.wav|1|C:/cues")
    accept = of_type(d.sync(), "file.accept")[0]
    assert accept["from"] == lex_id and accept["data"] == {"transfer_id": TID}

    d.ws.send_bytes(pack_chunk(TID, 0, data[:256 * 1024]))
    d.ws.send_bytes(pack_chunk(TID, 1, data[256 * 1024:]))
    progress = [e["data"]["received"] for e in of_type(d.sync(), "file.progress")]
    assert progress == [1, 2]
    d.send("file.end", {"transfer_id": TID, "sha256": hashlib.sha256(data).hexdigest()}, to={"ids": [lex_id]})
    got = [f for f in lex.sync() if f.startswith("FILE")]
    assert got[0] == "FILESTART|a.wav|5|65536"
    chunks = got[1:6]
    assert [c.split("|")[2] for c in chunks] == ["0", "1", "2", "3", "4"]
    assert b"".join(base64.b64decode(c.split("|")[3]) for c in chunks) == data
    assert [len(base64.b64decode(c.split("|")[3])) for c in chunks] == [K64] * 4 + [37_856]
    assert got[6:] == [f"FILEEND|a.wav|{md5}"]

    lex.send("FILEOK|a.wav|C:/cues/a.wav")
    assert of_type(d.sync(), "file.ok")[0]["data"] == {"transfer_id": TID, "saved_as": "C:/cues/a.wav"}

    # The second file: the actor declines the overwrite after the data arrived (v0.3 behaviour)
    small = b"take two"
    offer_b(d, lex_id, small, name="b.wav", tid="1f" * 16)
    lex.send("FILEACK|b.wav|1|C:/cues")
    d.ws.send_bytes(pack_chunk("1f" * 16, 0, small))
    d.send("file.end", {"transfer_id": "1f" * 16, "sha256": hashlib.sha256(small).hexdigest()}, to={"ids": [lex_id]})
    assert frames(lex, "FILEEND|") == [f"FILEEND|b.wav|{hashlib.md5(small).hexdigest()}"]
    lex.send("FILEDENY|b.wav|Declined overwrite")
    assert of_type(d.sync(), "file.deny")[0]["data"] == {"transfer_id": "1f" * 16, "reason": "Declined overwrite"}

    d.send("file.batch.end", {"batch_id": "b1", "ok": 1, "failed": 1}, to={"ids": [lex_id]})
    assert frames(lex, "BATCH_") == ["BATCH_END|Lex|1|1"]
    relay = relay_of(client)
    assert relay.files.by_id == {} and relay.bridge.files.to_legacy == {} and relay.bridge.files.batches_to_legacy == {}
    log = (tmp_path / "server.log").read_text(encoding="utf-8")
    assert "File Mira → Lex: a.wav" in log and ": ok" in log


def test_a_one_file_batch_looks_like_a_v03_single_send(client, stack):
    d, lex, lex_id = setup_b(client, stack)
    data = b"line"
    d.send("file.batch.start", {"batch_id": "b1", "files": 1, "bytes": 4}, to={"ids": [lex_id]})
    offer_b(d, lex_id, data)
    lex.send("FILEACK|a.wav|1|C:/cues")
    d.ws.send_bytes(pack_chunk(TID, 0, data))
    d.send("file.end", {"transfer_id": TID, "sha256": hashlib.sha256(data).hexdigest()}, to={"ids": [lex_id]})
    lex.send("FILEOK|a.wav|C:/cues/a.wav")
    d.send("file.batch.end", {"batch_id": "b1", "ok": 1, "failed": 0}, to={"ids": [lex_id]})
    got = lex.sync()
    assert not [f for f in got if f.startswith("BATCH_")]
    assert [f.split("|")[0] for f in got if f.startswith("FILE")] == ["FILEREQ", "FILESTART", "FILECHUNK", "FILEEND"]


def test_v2_director_cancels_mid_file(client, stack):
    d, lex, lex_id = setup_b(client, stack)
    data = os.urandom(3 * 256 * 1024)
    d.send("file.batch.start", {"batch_id": "b1", "files": 2, "bytes": len(data)}, to={"ids": [lex_id]})
    offer_b(d, lex_id, data)
    lex.send("FILEACK|a.wav|1|C:/cues")
    d.ws.send_bytes(pack_chunk(TID, 0, data[:256 * 1024]))
    d.send("file.batch.cancel", {"batch_id": "b1", "reason": "Cancelled by the director"}, to={"ids": [lex_id]})
    d.ws.send_bytes(pack_chunk(TID, 1, data[256 * 1024:512 * 1024]))  # already on the way: dropped quietly
    assert of_type(d.sync(), "error") == []
    got = lex.sync()
    assert [f.split("|")[0] for f in got if f.startswith(("FILE", "BATCH_"))] == \
        ["BATCH_START", "FILEREQ", "FILESTART", "FILECHUNK", "FILECHUNK", "FILECHUNK", "FILECHUNK", "BATCH_CANCEL"]
    assert "BATCH_CANCEL|Lex|Cancelled by the director" in got
    assert relay_of(client).files.by_id == {} and relay_of(client).bridge.files.to_legacy == {}


@pytest.mark.parametrize("name", ["a|b.wav", "../x.wav", "sub/x.wav", "back\\slash.wav", "..", " lead.wav"])
def test_names_a_v03_actor_cant_take(client, stack, name):
    d, lex, lex_id = setup_b(client, stack)
    offer_b(d, lex_id, b"x", name=name)
    got = d.sync()
    assert [e["data"]["code"] for e in of_type(got, "error")] == ["invalid"]
    assert of_type(got, "file.err")[0]["data"]["transfer_id"] == TID
    assert not [f for f in lex.sync() if f.startswith("FILE")]


def test_same_name_while_one_is_open(client, stack):
    d, lex, lex_id = setup_b(client, stack)
    offer_b(d, lex_id, b"one")
    offer_b(d, lex_id, b"two", tid="1f" * 16)
    assert [e["data"]["message"] for e in of_type(d.sync(), "error")] == [
        "Lex is already receiving a file named a.wav; try again when it's done"]


def test_out_of_order_chunk_ends_the_file(client, stack):
    d, lex, lex_id = setup_b(client, stack)
    data = os.urandom(300_000)
    d.send("file.batch.start", {"batch_id": "b1", "files": 2, "bytes": len(data)}, to={"ids": [lex_id]})
    offer_b(d, lex_id, data)
    lex.send("FILEACK|a.wav|1|C:/cues")
    d.ws.send_bytes(pack_chunk(TID, 1, data[256 * 1024:]))
    assert "out of order" in of_type(d.sync(), "file.err")[0]["data"]["error"]
    cancel = frames(lex, "BATCH_CANCEL|")
    assert len(cancel) == 1 and "out of order" in cancel[0]


def test_empty_file_to_a_v03_actor(client, stack):
    d, lex, lex_id = setup_b(client, stack)
    offer_b(d, lex_id, b"", name="empty.wav", batch=None)
    lex.send("FILEACK|empty.wav|1|C:/cues")
    d.send("file.end", {"transfer_id": TID, "sha256": hashlib.sha256(b"").hexdigest()}, to={"ids": [lex_id]})
    assert [f for f in lex.sync() if f.startswith("FILE")] == [
        f"FILEREQ|Mira|Lex|empty.wav|0|{hashlib.md5(b'').hexdigest()}",
        "FILESTART|empty.wav|0|65536",
        f"FILEEND|empty.wav|{hashlib.md5(b'').hexdigest()}",
    ]


def test_v03_actor_leaving(client, stack):
    d = v2(client, stack, "director", "Mira", "m-dir", caps=())
    with ExitStack() as inner:
        connect_legacy(client, inner, "actor", "Lex", "m-lex")
        lex_id = next(s for s in relay_of(client).registry if s.name == "Lex").id
        offer_b(d, lex_id, b"data")
        d.sync()
    err = d.until("file.err")
    assert err["from"] == "server" and err["data"] == {"transfer_id": TID, "error": "Lex disconnected"}
    assert relay_of(client).files.by_id == {} and relay_of(client).bridge.files.to_legacy == {}


def test_v2_director_leaving(client, stack):
    lex = connect_legacy(client, stack, "actor", "Lex", "m-lex")
    lex_id = next(s for s in relay_of(client).registry if s.name == "Lex").id
    with ExitStack() as inner:
        d = v2(client, inner, "director", "Mira", "m-dir", caps=())
        offer_b(d, lex_id, b"data")
        lex.until("FILEREQ|")
    assert lex.until("BATCH_CANCEL|") == "BATCH_CANCEL|Lex|Mira disconnected"
    assert relay_of(client).files.by_id == {} and relay_of(client).bridge.files.to_legacy == {}


def test_cancel_without_a_reason_uses_the_v03_wording(client, stack):
    d, lex, lex_id = setup_b(client, stack)
    d.send("file.batch.start", {"batch_id": "b1", "files": 2, "bytes": 8}, to={"ids": [lex_id]})
    offer_b(d, lex_id, b"data")
    d.send("file.batch.cancel", {"batch_id": "b1"}, to={"ids": [lex_id]})
    assert frames(lex, "BATCH_CANCEL|") == ["BATCH_CANCEL|Lex|Cancelled by director"]
