# vrcas_protocol: envelope, message models, generated TypeScript (spec §5).

import json
import sys
import time
from pathlib import Path

import pytest

import server  # noqa: F401  (puts protocol/ on sys.path)
from server import permissions
from vrcas_protocol import MODELS, Envelope, make, new_id, parse, validate
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
    "soundpad.ack": {"status": "played", "late_ms": 0},
    "osc.param": {"parameter": "RecIcon", "value": True},
}

INVALID = {
    "hello": {"role": "boss", "name": "x", "machine_id": "m"},
    "cue.play": {"index": 0},
    "chat.msg": {"text": ""},
    "approval.forget": {},
    "actor.settings": {"id": "s_1", "delay_ms": 999_999},
    "osc.param": {"parameter": "", "value": 1},
    "time.ping": {},
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
