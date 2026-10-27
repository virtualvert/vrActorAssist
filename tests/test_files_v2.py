# File transfers on /v2/ws (spec §8.4, §5.7): offers, binary chunk frames, replies, clean-up.

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from relay_helpers import connect_legacy, connect_v2, make_relay
from vrcas_protocol import pack_chunk

TID = "0f" * 16
OFFER = {"transfer_id": TID, "batch_id": "b1", "name": "Scene 4 - Diego.mp3", "size": 300_000, "sha256": "ab" * 32}


def session(stack, tmp_path, **settings):
    app = make_relay(tmp_path, {"m-a1": {"name": "Coda"}, "m-a2": {"name": "Ari"}, "m-old": {"name": "Lex"}}, **settings)
    client = stack.enter_context(TestClient(app))
    return client, app.state.relay


def errors(c):
    return [e["data"] for e in c.sync() if e["type"] == "error"]


def offered(client, stack, **offer):
    d = connect_v2(client, stack, "director", "Mira", "m-dir", expect="welcome")
    a1 = connect_v2(client, stack, "actor", "Coda", "m-a1", expect="welcome")
    d.send("file.offer", {**OFFER, **offer}, to={"ids": [a1.session_id]})
    got = a1.until("file.offer")
    assert got["from"] == d.session_id and got["data"]["name"] == OFFER["name"]
    return d, a1


def test_whole_transfer(tmp_path, stack):
    client, relay = session(stack, tmp_path)
    d, a1 = offered(client, stack, size=300_000)
    a2 = connect_v2(client, stack, "actor", "Ari", "m-a2", expect="welcome")

    # No data before the actor accepts
    d.ws.send_bytes(pack_chunk(TID, 0, b"x" * 10))
    assert [e["code"] for e in errors(d)] == ["invalid"]

    # The accept reaches the director, whatever `to` the actor used
    a1.send("file.accept", {"transfer_id": TID}, to={"ids": [a2.session_id]})
    accept = d.until("file.accept")
    assert accept["from"] == a1.session_id and accept["to"] == {"ids": [d.session_id]}

    first, second = b"\x01" * 262_144, b"\x02" * (300_000 - 262_144)
    d.ws.send_bytes(pack_chunk(TID, 0, first))
    d.ws.send_bytes(pack_chunk(TID, 1, second))
    assert a1.next_chunk() == pack_chunk(TID, 0, first)
    assert a1.next_chunk() == pack_chunk(TID, 1, second)
    a1.send("file.progress", {"transfer_id": TID, "received": 2}, to={"ids": [d.session_id]})
    assert d.until("file.progress")["data"]["received"] == 2

    d.send("file.end", {"transfer_id": TID, "sha256": "ab" * 32}, to={"ids": [a2.session_id]})
    assert a1.until("file.end")["data"]["sha256"] == "ab" * 32
    a1.send("file.ok", {"transfer_id": TID, "saved_as": "vrcActorSync/Scene 4 - Diego.mp3"}, to={"ids": [d.session_id]})
    assert d.until("file.ok")["data"]["saved_as"] == "vrcActorSync/Scene 4 - Diego.mp3"

    assert relay.files.by_id == {}
    assert not [e for e in a2.sync() if e["type"].startswith("file.")]
    log = (tmp_path / "server.log").read_text(encoding="utf-8")
    assert "File Mira → Coda: Scene 4 - Diego.mp3 (293.0 KB): ok" in log


def test_only_directors_send_files(tmp_path, stack):
    client, _ = session(stack, tmp_path)
    asst = connect_v2(client, stack, "assistant", "Ash", "m-asst", expect="welcome")
    a1 = connect_v2(client, stack, "actor", "Coda", "m-a1", expect="welcome")
    a2 = connect_v2(client, stack, "actor", "Ari", "m-a2", expect="welcome")
    a1.send("file.offer", OFFER, to={"ids": [a2.session_id]})
    asst.send("file.offer", OFFER, to={"ids": [a2.session_id]})
    a1.ws.send_bytes(pack_chunk(TID, 0, b"x"))
    assert [e["code"] for e in errors(a1)] == ["forbidden", "forbidden"]
    assert [e["code"] for e in errors(asst)] == ["forbidden"]
    assert not [e for e in a2.sync() if e["type"].startswith("file.")]


@pytest.mark.parametrize("to, code", [
    (lambda d, a1, a2: {"ids": [a1, a2]}, "invalid"),
    (lambda d, a1, a2: {"role": "actor"}, "invalid"),
    (lambda d, a1, a2: "all", "invalid"),
    (lambda d, a1, a2: {"ids": ["s_nobody"]}, "unknown_target"),
    (lambda d, a1, a2: {"ids": [d]}, "unknown_target"),
])
def test_offer_goes_to_exactly_one_session(tmp_path, stack, to, code):
    client, relay = session(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir", expect="welcome")
    a1 = connect_v2(client, stack, "actor", "Coda", "m-a1", expect="welcome")
    a2 = connect_v2(client, stack, "actor", "Ari", "m-a2", expect="welcome")
    d.send("file.offer", OFFER, to=to(d.session_id, a1.session_id, a2.session_id))
    assert [e["code"] for e in errors(d)] == [code]
    assert relay.files.by_id == {}


def test_offer_to_a_v03_director_is_unsupported(tmp_path, stack):
    # v0.3 actors receive through the bridge (tests/test_files_bridge.py); v0.3 directors can't
    client, relay = session(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir", expect="welcome")
    connect_legacy(client, stack, "director", "Old", "m-olddir")
    old = next(s for s in relay.registry if s.name == "Old")
    d.send("file.offer", OFFER, to={"ids": [old.id]})
    got = d.sync()
    err = [e["data"] for e in got if e["type"] == "error"]
    assert err[0]["code"] == "unsupported" and err[0]["ids"] == [old.id]
    # and a file.err the sending agent can tie to its transfer
    assert [e["data"]["transfer_id"] for e in got if e["type"] == "file.err"] == [TID]
    assert relay.files.by_id == {}


def test_bad_offers(tmp_path, stack):
    client, relay = session(stack, tmp_path, max_open_transfers=2)
    d, a1 = offered(client, stack)
    d.send("file.offer", OFFER, to={"ids": [a1.session_id]})  # same transfer id again
    d.send("file.offer", {**OFFER, "transfer_id": "1f" * 16}, to={"ids": [a1.session_id]})
    d.send("file.offer", {**OFFER, "transfer_id": "2f" * 16}, to={"ids": [a1.session_id]})  # a third one
    d.send("file.offer", {**OFFER, "transfer_id": "3f" * 16, "sha256": None}, to={"ids": [a1.session_id]})
    assert [e["code"] for e in errors(d)] == ["invalid", "invalid", "invalid"]
    assert sorted(relay.files.by_id) == [TID, "1f" * 16]


def test_replies_only_from_the_recipient(tmp_path, stack):
    client, relay = session(stack, tmp_path)
    d, a1 = offered(client, stack)
    a2 = connect_v2(client, stack, "actor", "Ari", "m-a2", expect="welcome")
    a2.send("file.accept", {"transfer_id": TID}, to={"ids": [d.session_id]})
    a2.send("file.ok", {"transfer_id": "1f" * 16}, to={"ids": [d.session_id]})
    assert [e["code"] for e in errors(a2)] == ["forbidden", "invalid"]
    assert not relay.files.by_id[TID].accepted
    # and file.end only from the sender
    a1.send("file.end", {"transfer_id": TID, "md5": "cd" * 16}, to={"ids": [a1.session_id]})
    assert [e["code"] for e in errors(a1)] == ["forbidden"]


def test_bad_chunks(tmp_path, stack):
    client, relay = session(stack, tmp_path, max_chunk_bytes=1000)
    d, a1 = offered(client, stack, size=1500, chunk_size=16_384)
    a1.send("file.accept", {"transfer_id": TID}, to={"ids": [d.session_id]})
    d.until("file.accept")
    d.ws.send_bytes(pack_chunk(TID, 0, b"x" * 1001))       # bigger than the relay allows
    d.ws.send_bytes(pack_chunk("1f" * 16, 0, b"x"))         # no such transfer
    d.ws.send_bytes(b"\x02" + bytes.fromhex(TID) + bytes(4))  # unknown kind
    d.ws.send_bytes(b"\x01short")
    assert [e["code"] for e in errors(d)] == ["invalid"] * 4
    assert TID in relay.files.by_id

    # A chunk past the end of the file ends the transfer for both sides
    d.ws.send_bytes(pack_chunk(TID, 1, b"x"))
    assert "doesn't fit" in d.until("file.err")["data"]["error"]
    err = a1.until("file.err")
    assert err["from"] == "server" and err["data"]["transfer_id"] == TID
    assert relay.files.by_id == {}


def test_batch_cancel_ends_its_transfers(tmp_path, stack):
    client, relay = session(stack, tmp_path)
    d, a1 = offered(client, stack)
    d.send("file.offer", {**OFFER, "transfer_id": "1f" * 16, "batch_id": "b2"}, to={"ids": [a1.session_id]})
    a1.until("file.offer")
    d.send("file.batch.cancel", {"batch_id": "b1", "reason": "Cancelled by the director"}, to={"ids": [a1.session_id]})
    assert a1.until("file.batch.cancel")["data"]["batch_id"] == "b1"
    assert sorted(relay.files.by_id) == ["1f" * 16]
    # Chunks and replies that were already on the way are dropped without an error
    d.ws.send_bytes(pack_chunk(TID, 0, b"x"))
    a1.send("file.progress", {"transfer_id": TID, "received": 1}, to={"ids": [d.session_id]})
    assert errors(d) == [] and errors(a1) == []
    assert not [e for e in d.sync() if e["type"] == "file.progress"]
    # ...but a transfer id that never existed is still refused
    d.ws.send_bytes(pack_chunk("9f" * 16, 0, b"x"))
    assert [e["code"] for e in errors(d)] == ["invalid"]
    assert "Scene 4 - Diego.mp3 (293.0 KB): cancelled" in (tmp_path / "server.log").read_text(encoding="utf-8")


def test_actor_leaving_ends_the_transfer(tmp_path, stack):
    client, relay = session(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir", expect="welcome")
    with ExitStack() as inner:
        a1 = connect_v2(client, inner, "actor", "Coda", "m-a1", expect="welcome")
        d.send("file.offer", OFFER, to={"ids": [a1.session_id]})
        a1.until("file.offer")
    err = d.until("file.err")
    assert err["from"] == "server" and err["data"] == {"transfer_id": TID, "error": "Coda disconnected"}
    assert relay.files.by_id == {}


def test_director_leaving_ends_the_transfer(tmp_path, stack):
    client, relay = session(stack, tmp_path)
    a1 = connect_v2(client, stack, "actor", "Coda", "m-a1", expect="welcome")
    with ExitStack() as inner:
        d = connect_v2(client, inner, "director", "Mira", "m-dir", expect="welcome")
        d.send("file.offer", OFFER, to={"ids": [a1.session_id]})
        a1.until("file.offer")
    assert a1.until("file.err")["data"] == {"transfer_id": TID, "error": "Mira disconnected"}
    assert relay.files.by_id == {}


def test_unapproved_binary_frame(tmp_path, stack):
    client, _ = session(stack, tmp_path)
    pending = connect_v2(client, stack, "actor", "New", "m-new", expect="approval.pending")
    pending.ws.send_bytes(pack_chunk(TID, 0, b"x"))
    assert pending.until("error")["data"]["code"] == "not_approved"
