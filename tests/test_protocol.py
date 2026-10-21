# vrcas_protocol: envelope, message models, generated TypeScript (spec §5).

import json
import sys
import time
from pathlib import Path

import pytest

import server  # noqa: F401  (puts protocol/ on sys.path)
from server import permissions
from vrcas_protocol import CHUNK_SIZE, KIND_FILE_CHUNK, MODELS, chunk_count, make, new_id, pack_chunk, parse, unpack_chunk, validate
from vrcas_protocol.messages import Payload

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_ts_types  # noqa: E402

# A valid payload for every type that has a model
SAMPLES = {
    "hello": {"role": "actor", "name": "Coda", "machine_id": "m-1", "version": "0.4.0", "platform": "windows-x64",
              "capabilities": ["soundpad", "osc"]},
    "welcome": {"session_id": "s_1", "name": "Coda", "role": "actor", "server_version": "0.4.0",
                "version_status": "ok", "server_time": 1, "delay_ms": 120,
                "ice_servers": [{"urls": ["stun:stun.example:3478"]}]},
    "denied": {"reason": "Invalid secret"},
    "error": {"code": "forbidden", "message": "no", "type": "cue.go"},
    "presence.roster": {"sessions": [{"id": "s_1", "name": "Coda", "role": "actor", "legacy": True, "latency_ms": 40}],
                        "pending": [{"machine_id": "m-2", "name": "Nova", "role": "camera"}]},
    "presence.latency": {"sessions": [{"id": "s_1", "latency_ms": None, "timed_out": True}]},
    "approval.pending": {},
    "approval.approve": {"machine_id": "m-2"},
    "approval.deny": {"machine_id": "m-2"},
    "approval.forget": {"id": "s_1"},
    "approval.forgotten": {},
    "actor.settings": {"id": "s_1", "delay_ms": -150, "display_name": "Coda B"},
    "chat.msg": {"text": "Places"},
    "chat.priv": {"text": "*not a cue*"},
    "time.ping": {"t0": 5},
    "time.pong": {"t0": 5, "t1": 7, "t2": 8},
    "update.available": {"latest_version": "0.4.1", "download_url": "https://example.invalid/x"},
    "cue.go": {"at": 1000},
    "cue.stop": {},
    "cue.play": {"index": 3},
    "cue.ack": {"command": "*go", "ok": True, "late_ms": 4},
    "soundpad.play": {"sound": {"path": "C:\\Sounds\\a.mp3"}, "lines": "speakers", "volume": 80, "at": 5},
    "soundpad.stop": {"at": 9},
    "soundpad.ack": {"status": "played", "late_ms": 0, "command": "soundpad.play"},
    "soundpad.pause": {"paused": True, "at": 5},
    "soundpad.seek": {"ms": 5000},
    "soundpad.jump": {"ms": -2000},
    "soundpad.volume": {"value": 80},
    "soundpad.mute": {"muted": False},
    "soundpad.list.request": {},
    "soundpad.list": {"total": 2, "first": 1, "last": True,
                      "sounds": [{"index": 1, "key": "0123456789abcdef", "title": "Scene 4 - Diego", "duration_ms": 47000}],
                      "categories": [{"index": 2, "name": "EP3"}]},
    "soundpad.state": {"available": True, "status": "PLAYING", "position_ms": 1400, "duration_ms": 47000,
                       "title": "Scene 4 - Diego", "index": 1, "key": "0123456789abcdef", "lines": "both", "volume": 80,
                       "muted": False},
    "osc.param": {"parameter": "RecIcon", "value": True},
    "file.batch.start": {"batch_id": "b1", "files": 2, "bytes": 300_000},
    "file.offer": {"transfer_id": "0f" * 16, "batch_id": "b1", "name": "Scene 4 - Diego.mp3", "size": 300_000,
                   "sha256": "ab" * 32, "md5": "cd" * 16, "character": "Diego"},
    "file.accept": {"transfer_id": "0f" * 16},
    "file.deny": {"transfer_id": "0f" * 16, "reason": "Declined"},
    "file.progress": {"transfer_id": "0f" * 16, "received": 1},
    "file.end": {"transfer_id": "0f" * 16, "sha256": "ab" * 32},
    "file.ok": {"transfer_id": "0f" * 16, "saved_as": "vrcActorSync/Scene 4 - Diego.mp3"},
    "file.err": {"transfer_id": "0f" * 16, "error": "Checksum mismatch"},
    "file.batch.end": {"batch_id": "b1", "ok": 1, "failed": 1},
    "file.batch.cancel": {"batch_id": "b1", "reason": "Cancelled by the director"},
}

INVALID = {
    "hello": {"role": "boss", "name": "x", "machine_id": "m"},
    "cue.play": {"index": 0},
    "chat.msg": {"text": ""},
    "approval.forget": {},
    "actor.settings": {"id": "s_1", "delay_ms": 999_999},
    "osc.param": {"parameter": "", "value": 1},
    "time.ping": {},
    "soundpad.volume": {"value": 101},
    "soundpad.play": {"sound": {"key": "NOT-A-KEY"}},
    "soundpad.state": {"available": True, "status": "LOOPING"},
    "soundpad.seek": {"ms": -1},
    "file.offer": {"transfer_id": "0f" * 16, "name": "a.wav", "size": 10},  # no hash
    "file.end": {"transfer_id": "0F" * 16, "md5": "cd" * 16},  # upper-case id
    "file.accept": {"transfer_id": "short"},
    "file.progress": {"transfer_id": "0f" * 16, "received": -1},
}


def modelled():
    return sorted(t for t, m in MODELS.items() if m is not None)


def test_every_model_has_a_sample():
    assert set(SAMPLES) == set(modelled())


@pytest.mark.parametrize("msg_type", modelled())
def test_payload_round_trip(msg_type):
    payload = validate(msg_type, SAMPLES[msg_type])
    assert isinstance(payload, Payload)
    dumped = payload.model_dump(mode="json")
    assert validate(msg_type, dumped) == payload
    env = make(msg_type, payload, to={"ids": ["s_1"]}, from_="s_2")
    again = parse(json.dumps(env.wire()))
    assert again == env
    assert validate(msg_type, again.data) == payload


@pytest.mark.parametrize("msg_type", sorted(INVALID))
def test_invalid_payloads_are_rejected(msg_type):
    with pytest.raises(ValueError):
        validate(msg_type, INVALID[msg_type])


def test_unmodelled_types_are_not_read():
    assert validate("obs.record.start", {"anything": [1, 2]}) is None


def test_unknown_fields_are_ignored():
    assert validate("cue.play", {"index": 2, "from_the_future": True}).index == 2


@pytest.mark.parametrize("to", ["server", "all", {"role": "camera"}, {"ids": ["s_1", "s_2"]}])
def test_targets(to):
    env = parse({"v": 2, "id": "a", "type": "chat.msg", "to": to, "data": {"text": "x"}})
    assert env.wire()["to"] == to


@pytest.mark.parametrize("raw", [
    {"v": 1, "id": "a", "type": "chat.msg", "to": "all"},
    {"v": 2, "id": "", "type": "chat.msg", "to": "all"},
    {"v": 2, "id": "a", "type": "Chat Msg", "to": "all"},
    {"v": 2, "id": "a", "type": "chat.msg", "to": "everyone"},
    {"v": 2, "id": "a", "type": "chat.msg", "to": {"role": "producer"}},
    {"v": 2, "id": "a", "type": "chat.msg", "to": {"ids": []}},
    {"v": 2, "id": "a", "type": "chat.msg", "to": {"name": "Coda"}},  # names never route
    {"v": 2, "id": "a", "type": "chat.msg", "data": "text"},
])
def test_bad_envelopes(raw):
    with pytest.raises(ValueError):
        parse(raw)


def test_from_is_read_but_named_from_on_the_wire():
    env = parse('{"v":2,"id":"a","type":"chat.msg","from":"s_x","to":"all","data":{"text":"x"}}')
    assert env.from_ == "s_x"
    assert env.wire()["from"] == "s_x" and "from_" not in env.wire()


def test_ulids_are_unique_and_time_ordered():
    a = new_id(1_000)
    b = new_id(2_000)
    assert len(a) == 26 and a < b
    assert len({new_id() for _ in range(1000)}) == 1000
    assert new_id()[:8] >= new_id(int(time.time() * 1000) - 60_000)[:8]


@pytest.mark.parametrize("data", [
    {"size": 2 * 1024**3},  # over 1 GiB
    {"chunk_size": 512 * 1024},
    {"chunk_size": 1024},
    {"name": ""},
])
def test_file_offer_limits(data):
    offer = {"transfer_id": "0f" * 16, "name": "a.wav", "size": 10, "md5": "cd" * 16, **data}
    with pytest.raises(ValueError):
        validate("file.offer", offer)


def test_file_offer_chunk_count():
    offer = validate("file.offer", {"transfer_id": "0f" * 16, "name": "a.wav", "size": CHUNK_SIZE * 2 + 1, "md5": "cd" * 16})
    assert offer.chunk_size == CHUNK_SIZE and offer.chunks == 3
    assert chunk_count(0) == 0 and chunk_count(1) == 1 and chunk_count(65536, 65536) == 1


def test_chunk_frames():
    frame = pack_chunk("0f" * 16, 7, b"payload")
    assert len(frame) == 21 + 7
    assert frame[0] == KIND_FILE_CHUNK and frame[1:17] == bytes.fromhex("0f" * 16) and frame[17:21] == b"\x00\x00\x00\x07"
    chunk = unpack_chunk(frame)
    assert (chunk.kind, chunk.transfer_id, chunk.index, chunk.payload) == (1, "0f" * 16, 7, b"payload")
    assert unpack_chunk(pack_chunk("0f" * 16, 0, b"")).payload == b""
    with pytest.raises(ValueError):
        unpack_chunk(b"\x01short")


def test_every_type_has_a_permission_rule():
    missing = [t for t in MODELS if permissions.rule(t) is None]
    assert missing == []


def test_permission_table_only_names_known_types():
    for msg_type in permissions.TABLE:
        if msg_type.endswith(".*"):
            assert any(t.startswith(msg_type[:-1]) for t in MODELS)
        else:
            assert msg_type in MODELS, msg_type


def test_generated_typescript_is_current():
    expected = gen_ts_types.render()
    actual = gen_ts_types.OUT.read_text(encoding="utf-8")
    assert actual == expected, "web/src/protocol/types.ts is stale: run python scripts/gen_ts_types.py"


def test_typescript_has_every_type():
    text = gen_ts_types.render()
    for msg_type in MODELS:
        assert f'  "{msg_type}": ' in text
    assert "export interface Envelope<T extends MsgType = MsgType>" in text
