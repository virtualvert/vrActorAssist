# Mixed sessions (spec §11.3): v0.3 clients on /ws and v2 clients on /v2/ws in one session.

import json
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from relay_helpers import connect_legacy, connect_v2, make_relay
from server.legacy_bridge import osc_value_from_text, parse_cue

APPROVED = {
    "m-coda": {"name": "Coda"},      # v0.3 actor
    "m-ari": {"name": "Ari"},        # v2 actor
    "m-cam": {"name": "Cam", "role": "camera"},
}


@pytest.fixture
def stack():
    with ExitStack() as s:
        yield s


@pytest.fixture
def client(tmp_path, stack):
    return stack.enter_context(TestClient(make_relay(tmp_path, APPROVED)))


def v2_actor(client, stack, name="Ari", machine_id="m-ari"):
    a = connect_v2(client, stack, "actor", name, machine_id, expect="welcome")
    a.session_id = a.seen[-1]["data"]["session_id"]
    return a


def roster_of(c):
    return c.until("presence.roster")["data"]


def session_named(roster, name):
    return next(s for s in roster["sessions"] if s["name"] == name)


def v2_got(c, msg_type):
    return [e for e in c.sync() if e["type"] == msg_type]


# ---- v0.3 clients see v2 actors, never cameras --------------------------------------------------------


def test_v2_actor_in_users_and_joined(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    v2_actor(client, stack)
    got = old_dir.collect_until("USERS|")
    assert got == ["MSG|SERVER|Ari joined", "USERS|Ari"]


def test_v2_actor_left(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    ari = v2_actor(client, stack)
    old_dir.collect_until("USERS|Ari")
    # Close by hand: leaving the TestClient context cancels the relay's handler before its cleanup
    ari.ws.close()
    assert old_dir.collect_until("MSG|SERVER|Ari left") == ["USERS|", "MSG|SERVER|Ari left"]


def test_pending_v2_actor_in_legacy_pending_and_approved_from_v03(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    nova = connect_v2(client, stack, "actor", "Nova", "m-nova")
    assert nova.recv()["type"] == "approval.pending"
    assert old_dir.until("PENDING|") == 'PENDING|[{"machine_id": "m-nova", "name": "Nova"}]'
    old_dir.send("APPROVE|m-nova")
    welcome = nova.until("welcome")
    assert welcome["data"]["name"] == "Nova"
    assert old_dir.collect_until("PENDING|") == ["MSG|SERVER|Nova joined", "USERS|Nova", "PENDING|[]"]


def test_cameras_are_hidden_from_v03(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    old_dir.collect_until("MSG|SERVER|⚠ Warning: Bo")
    connect_v2(client, stack, "camera", "Cam", "m-cam", expect="welcome")
    pending_cam = connect_v2(client, stack, "camera", "Cam2", "m-cam2")
    assert pending_cam.recv()["type"] == "approval.pending"
    # The v2 director sees both cameras
    roster = v2_dir.until(lambda e: e["type"] == "presence.roster" and e["data"]["pending"])["data"]
    assert session_named(roster, "Cam")["role"] == "camera"
    assert roster["pending"][0]["name"] == "Cam2"
    # The v0.3 director sees neither, and can't reach one by name
    old_dir.send("REFRESH")
    old_dir.send("PRIV|Mira|Cam|*go")
    got = old_dir.sync()
    assert "USERS|" in got and "PENDING|[]" in got
    assert "MSG|SERVER|Actor 'Cam' not found" in got
    assert not any("Cam" in m and m.startswith(("USERS", "PENDING", "MSG|SERVER|Cam")) for m in got)


def test_v03_status_includes_v2_actors(client, stack):
    relay = client.app.state.relay
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    v2_actor(client, stack)
    next(s for s in relay.registry if s.name == "Ari").latency_ms = 42
    client.portal.call(relay.bridge.send_actor_status)
    status = next(m for m in iter(old_dir.ws.receive_text, None) if m.startswith("STATUS|"))
    assert [(a["name"], a["latency_ms"]) for a in json.loads(status[7:])] == [("Ari", 42)]


def test_directors_are_warned_across_kinds(client, stack):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir", expect=None)
    got = old_dir.collect_until("PENDING|")
    assert "MSG|SERVER|⚠ Warning: Bo is already connected" in got
    roster = v2_dir.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 2)["data"]
    assert session_named(roster, "Mira")["legacy"] is True
    assert session_named(roster, "Mira")["capabilities"] == ["legacy"]


# ---- v0.3 director → v2 actor -------------------------------------------------------------------------


@pytest.mark.parametrize("legacy_text, v2_type, data", [
    ("*go", "cue.go", {}),
    ("*stop", "cue.stop", {}),
    ("*play:3", "cue.play", {"index": 3}),
    ("  *GO", "cue.go", {}),
])
def test_v03_priv_cue_to_v2_actor(client, stack, legacy_text, v2_type, data):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    ari = v2_actor(client, stack)
    old_dir.send(f"PRIV|Mira|Ari|{legacy_text}")
    got = v2_got(ari, v2_type)
    assert len(got) == 1 and got[0]["data"] == data and got[0]["to"] == {"ids": [ari.session_id]}
    assert got[0]["from"] == next(s.id for s in client.app.state.relay.registry if s.name == "Mira")


def test_v03_cmd_reaches_v2_and_v03_actors(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    ari = v2_actor(client, stack)
    old_dir.send("CMD|go")
    assert "CMD|go" in coda.sync()
    got = v2_got(ari, "cue.go")
    assert len(got) == 1 and got[0]["to"] == {"role": "actor"}


def test_v03_osc_chat_and_files_to_v2_actor(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    ari = v2_actor(client, stack)
    old_dir.send("OSC_CUE|Ari|RecIcon|true")
    old_dir.send("OSC_CUE|Ari|Volume|0.5")
    old_dir.send("MSG|Mira|Places")
    old_dir.send("PRIV|Mira|Ari|You're up next")
    old_dir.send("FILEREQ|Mira|Ari|line.wav|4|00")
    old_dir.send("BATCH_START|Ari|1|4")
    got = ari.sync()
    osc = [e["data"] for e in got if e["type"] == "osc.param"]
    assert osc == [{"parameter": "RecIcon", "value": True}, {"parameter": "Volume", "value": 0.5}]
    assert [e["data"]["text"] for e in got if e["type"] == "chat.msg"] == ["Places"]
    assert [e["data"]["text"] for e in got if e["type"] == "chat.priv"] == ["You're up next"]
    assert not any(e["type"].startswith("file.") for e in got)
    director_got = old_dir.sync()
    # Ari's app doesn't announce `files` (a build from before Phase 2): declined with a reason
    assert "FILEDENY|line.wav|Ari uses an older vrcActorSync 0.4 preview; update it to receive files" in director_got
    assert client.app.state.relay.transfers == {}


def test_v03_actor_cannot_cue_v2_actor(client, stack):
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    ari = v2_actor(client, stack)
    coda.send("PRIV|Coda|Ari|*go")
    assert "MSG|SERVER|Permission denied: only the director can send PRIV" in coda.sync()
    assert v2_got(ari, "cue.go") == []


def test_v03_ack_reaches_v2_directors(client, stack):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    asst = connect_v2(client, stack, "assistant", "Ash", "m-ash")
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    coda.send("ACK|Coda|*go|OK")
    coda.sync()
    for c in (v2_dir, asst):
        ack = v2_got(c, "cue.ack")
        assert [a["data"] for a in ack] == [{"command": "*go", "ok": True}]


# ---- v2 director → v0.3 actor -------------------------------------------------------------------------


def coda_id(client):
    return next(s.id for s in client.app.state.relay.registry if s.name == "Coda")


@pytest.mark.parametrize("msg_type, data, legacy", [
    ("cue.go", {}, "PRIV|Bo|Coda|*go"),
    ("cue.stop", {}, "PRIV|Bo|Coda|*stop"),
    ("cue.play", {"index": 4}, "PRIV|Bo|Coda|*play:4"),
    ("soundpad.play", {"sound": {"selected": True}}, "PRIV|Bo|Coda|*go"),
    ("soundpad.play", {"sound": {"index": 2}, "lines": "both"}, "PRIV|Bo|Coda|*play:2"),
    ("soundpad.stop", {}, "PRIV|Bo|Coda|*stop"),
    ("osc.param", {"parameter": "Wave", "value": 1}, "OSC_CUE|Coda|Wave|1"),
    ("osc.param", {"parameter": "RecIcon", "value": False}, "OSC_CUE|Coda|RecIcon|false"),
    ("chat.priv", {"text": "you're up"}, "PRIV|Bo|Coda|you're up"),
    ("chat.priv", {"text": "*go is not a cue here"}, "PRIV|Bo|Coda| *go is not a cue here"),
])
def test_v2_director_to_v03_actor(client, stack, msg_type, data, legacy):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    v2_dir.send(msg_type, data, to={"ids": [coda_id(client)]})
    assert [e for e in v2_dir.sync() if e["type"] == "error"] == []
    got = coda.sync()
    assert legacy in got


@pytest.mark.parametrize("data", [
    {"sound": {"path": "C:\\a.mp3"}},
    {"sound": {"key": "0123456789abcdef"}},
    {"sound": {"selected": True}, "lines": "speakers"},
    {"sound": {"index": 1}, "volume": 50},
])
def test_v2_actions_v03_cant_do(client, stack, data):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    msg = v2_dir.send("soundpad.play", data, to={"ids": [coda_id(client)]})
    err = v2_dir.until("error")
    assert err["reply_to"] == msg and err["data"]["code"] == "unsupported" and err["data"]["ids"] == [coda_id(client)]
    assert not any(m.startswith("PRIV") for m in coda.sync())


@pytest.mark.parametrize("msg_type, data", [
    ("soundpad.pause", {"paused": True}),
    ("soundpad.seek", {"ms": 1000}),
    ("soundpad.jump", {"ms": -500}),
    ("soundpad.volume", {"value": 40}),
    ("soundpad.mute", {"muted": True}),
    ("soundpad.list.request", {}),
])
def test_soundpad_controls_v03_cant_do(client, stack, msg_type, data):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    msg = v2_dir.send(msg_type, data, to={"ids": [coda_id(client)]})
    err = v2_dir.until("error")
    assert err["reply_to"] == msg and err["data"]["code"] == "unsupported" and err["data"]["ids"] == [coda_id(client)]
    assert not [m for m in coda.sync() if not m.startswith("MSG|")]


def test_v2_broadcasts_reach_both_kinds(client, stack):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    coda = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    ari = v2_actor(client, stack)
    v2_dir.send("cue.go", {}, to={"role": "actor"})
    v2_dir.send("chat.msg", {"text": "Rolling"}, to="all")
    v2_dir.send("obs.record.start", {}, to="all")  # nothing to show a v0.3 client
    assert [e for e in v2_dir.sync() if e["type"] == "error"] == []
    got = coda.sync()
    assert "PRIV|Bo|Coda|*go" in got and "MSG|Bo|Rolling" in got
    assert not any("obs" in m for m in got)
    assert len(v2_got(ari, "cue.go")) == 1


def test_v2_director_approves_v03_actor(client, stack):
    v2_dir = connect_v2(client, stack, "director", "Bo", "m-bo")
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    newbie = connect_legacy(client, stack, "actor", "Nova", "m-nova", expect="DENIED|Pending")
    roster = v2_dir.until(lambda e: e["type"] == "presence.roster" and e["data"]["pending"])["data"]
    assert roster["pending"] == [{"machine_id": "m-nova", "name": "Nova", "role": "actor", "legacy": True}]
    v2_dir.send("approval.approve", {"machine_id": "m-nova"})
    assert newbie.collect_until("USERS|")[:2] == ["APPROVED", "VERSION|ok|0.3.3|"]
    assert old_dir.collect_until("PENDING|[]")[-3:] == ["MSG|SERVER|Nova joined", "USERS|Nova", "PENDING|[]"]


def test_v03_director_forgets_v2_actor(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    ari = v2_actor(client, stack)
    old_dir.collect_until("USERS|Ari")
    old_dir.send("FORGET_NAME|Ari")
    assert ari.until("approval.forgotten")
    with pytest.raises(WebSocketDisconnect):
        ari.recv()
    got = old_dir.collect_until("PENDING|")
    assert got[-2:] == ["USERS|", 'PENDING|[{"machine_id": "m-ari", "name": "Ari"}]']


def test_v2_replaces_v03_connection_of_same_machine(client, stack):
    old_dir = connect_legacy(client, stack, "director", "Mira", "m-dir")
    coda_old = connect_legacy(client, stack, "actor", "Coda", "m-coda")
    old_dir.collect_until("USERS|Coda")
    coda_new = v2_actor(client, stack, "Coda", "m-coda")
    assert coda_old.until("MSG|SERVER|Reconnected")
    assert coda_new.session_id
    roster = roster_of(coda_new)
    assert [s["name"] for s in roster["sessions"] if s["role"] == "actor"] == ["Coda"]
    assert session_named(roster, "Coda")["legacy"] is False


def test_v03_replaces_v2_connection_of_same_machine(client, stack):
    ari_v2 = v2_actor(client, stack)
    connect_legacy(client, stack, "actor", "Ari", "m-ari")
    assert ari_v2.until("denied")["data"]["reason"] == "Reconnected from another location"


# ---- translation helpers --------------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("*go", ("cue.go", {})), ("go", ("cue.go", {})), ("*stop", ("cue.stop", {})),
    ("*play:12", ("cue.play", {"index": 12})), ("*play:0", None), ("*play:x", None), ("*volume:0.5", None),
])
def test_parse_cue(text, expected):
    assert parse_cue(text) == expected


@pytest.mark.parametrize("text, value", [
    ("true", True), ("False", False), ("1", 1), ("-2", -2), ("0.5", 0.5), ("hello", "hello"),
])
def test_osc_values(text, value):
    result = osc_value_from_text(text)
    assert result == value and type(result) is type(value)
