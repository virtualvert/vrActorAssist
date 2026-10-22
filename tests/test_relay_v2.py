# The v2 relay on /v2/ws: handshake, session ids, approvals, routing, presence, clock sync.

import json
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from relay_helpers import FakeClock, connect_v2, make_relay

MANIFEST = {
    "latest_version": "0.4.1",
    "release_notes": "notes",
    "assets": {"actor-windows-x64": {"url": "https://example.invalid/app.exe", "sha256": "ab"}},
}


@pytest.fixture
def stack():
    with ExitStack() as s:
        yield s


def relay_client(stack, tmp_path, approved=None, **kwargs):
    app = make_relay(tmp_path, approved, **kwargs)
    return stack.enter_context(TestClient(app)), app.state.relay


def ids(roster, role=None):
    return [s["id"] for s in roster["sessions"] if role is None or s["role"] == role]


# ---- handshake ------------------------------------------------------------------------------------


def test_director_welcome(tmp_path, stack):
    clock = FakeClock(1_700_000_000_000)
    client, _ = relay_client(stack, tmp_path, clock=clock)
    d = connect_v2(client, stack, "director", "Mira", "m-dir", expect=None)
    welcome = d.until("welcome")
    data = welcome["data"]
    assert welcome["from"] == "server" and welcome["to"] == {"ids": [data["session_id"]]}
    assert data["session_id"].startswith("s_")
    assert data["name"] == "Mira" and data["role"] == "director"
    assert data["server_version"] == "0.4.0-dev" and data["version_status"] == "ok"
    assert data["server_time"] == 1_700_000_000_000
    assert data["ice_servers"] == [] and data["delay_ms"] == 0
    roster = d.roster()
    assert [s["name"] for s in roster["sessions"]] == ["Mira"]


@pytest.mark.parametrize("secret", ["wrong", ""])
def test_wrong_secret_is_denied_and_closed(tmp_path, stack, secret):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir", secret=secret, expect=None)
    assert d.recv()["data"] == {"reason": "Invalid secret"}
    with pytest.raises(WebSocketDisconnect) as closed:
        d.recv()
    assert closed.value.code == 4401


def test_assistant_needs_the_secret_too(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    a = connect_v2(client, stack, "assistant", "Ash", "m-a", secret="nope", expect=None)
    assert a.recv()["type"] == "denied"
    ok = connect_v2(client, stack, "assistant", "Ash", "m-a2")
    assert ok.session_id


def test_hello_must_come_first(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    ws = stack.enter_context(client.websocket_connect("/v2/ws"))
    ws.send_text(json.dumps({"v": 2, "id": "x1", "type": "chat.msg", "to": "all", "data": {"text": "hi"}}))
    err = json.loads(ws.receive_text())
    assert err["type"] == "error" and err["reply_to"] == "x1" and err["data"]["code"] == "invalid"
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    assert closed.value.code == 4400


@pytest.mark.parametrize("frame", ["not json", '{"v": 2}', '{"v":2,"id":"h","type":"hello","data":{"role":"boss"}}'])
def test_bad_hello_closes(tmp_path, stack, frame):
    client, _ = relay_client(stack, tmp_path)
    ws = stack.enter_context(client.websocket_connect("/v2/ws"))
    ws.send_text(frame)
    assert json.loads(ws.receive_text())["data"]["code"] == "invalid"
    with pytest.raises(WebSocketDisconnect):
        ws.receive_text()


def test_hello_timeout(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, hello_timeout_s=0.05)
    ws = stack.enter_context(client.websocket_connect("/v2/ws"))
    assert json.loads(ws.receive_text())["data"] == {"reason": "No hello received"}
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    assert closed.value.code == 4408


@pytest.mark.parametrize("version, status", [
    ("0.4.0-dev", "ok"), ("0.4.2", "ok"), ("0.3.3", "warning"), ("0.5.0", "warning"), ("1.0.0", "unsupported"),
    ("dev", "warning"),
])
def test_version_status(tmp_path, stack, version, status):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir", version=version, expect=None)
    assert d.until("welcome")["data"]["version_status"] == status


def test_update_offer(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, {"m-a": {"name": "Coda"}}, manifest=MANIFEST)
    a = connect_v2(client, stack, "actor", "Coda", "m-a", version="0.4.0", expect="welcome")
    offer = a.until("update.available")
    assert offer["data"]["latest_version"] == "0.4.1" and offer["data"]["download_url"].endswith("app.exe")
    newer = connect_v2(client, stack, "actor", "Coda", "m-a", version="0.4.1", expect="welcome")
    assert all(e["type"] != "update.available" for e in newer.sync())


# ---- approvals --------------------------------------------------------------------------------------


def test_approve_flow_and_persistence(tmp_path, stack):
    client, relay = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    a = connect_v2(client, stack, "actor", "Coda", "m-a", capabilities=["soundpad", "osc"])
    assert a.recv()["type"] == "approval.pending"
    roster = d.until(lambda e: e["type"] == "presence.roster" and e["data"]["pending"])["data"]
    assert roster["pending"] == [{"machine_id": "m-a", "name": "Coda", "role": "actor", "legacy": False}]

    # Pending clients may sync clocks but nothing else
    a.send("chat.msg", {"text": "hello?"}, to="all")
    assert a.recv()["data"]["code"] == "not_approved"
    ping = a.send("time.ping", {"t0": 1})
    assert a.recv()["reply_to"] == ping

    d.send("approval.approve", {"machine_id": "m-a"})
    welcome = a.until("welcome")["data"]
    roster = d.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 2)["data"]
    assert roster["pending"] == []
    actor_entry = next(s for s in roster["sessions"] if s["role"] == "actor")
    assert actor_entry["id"] == welcome["session_id"]
    assert actor_entry["capabilities"] == ["soundpad", "osc"] and actor_entry["legacy"] is False
    assert json.loads((tmp_path / "approved_actors.json").read_text())["m-a"]["name"] == "Coda"
    # The actor's roster has no pending list
    assert a.roster()["pending"] == []


def test_known_machine_reconnects_with_same_session_id(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, {"m-a": {"name": "Coda (approved)"}})
    first = connect_v2(client, stack, "actor", "Coda", "m-a", expect="welcome")
    first_id = first.seen[-1]["data"]["session_id"]
    second = connect_v2(client, stack, "actor", "Coda", "m-a", expect="welcome")
    welcome = next(e for e in second.seen if e["type"] == "welcome")["data"]
    assert welcome["session_id"] == first_id
    assert welcome["name"] == "Coda (approved)"  # the approved name wins, as on v0.3
    # The older connection is told and closed
    assert first.until("denied")["data"]["reason"] == "Reconnected from another location"
    with pytest.raises(WebSocketDisconnect):
        first.recv()


def test_two_directors_on_one_machine_get_different_ids(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    one = connect_v2(client, stack, "director", "Mira", "m-same")
    two = connect_v2(client, stack, "director", "Bo", "m-same")
    assert one.session_id != two.session_id
    roster = one.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 2)["data"]
    assert sorted(ids(roster)) == sorted([one.session_id, two.session_id])


def test_deny(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    c = connect_v2(client, stack, "camera", "Cam", "m-c", expect="approval.pending")
    d.until(lambda e: e["type"] == "presence.roster" and e["data"]["pending"])
    d.send("approval.deny", {"machine_id": "m-c"})
    assert c.until("denied")["data"]["reason"] == "Denied by director"
    with pytest.raises(WebSocketDisconnect):
        c.recv()
    assert d.until("presence.roster")["data"]["pending"] == []


def test_log_names_the_role(tmp_path, stack):
    # server.log said "Actor approved by director: Cam" for a camera (manual checklist, step 19)
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    c = connect_v2(client, stack, "camera", "Cam", "m-c", expect="approval.pending")
    a = connect_v2(client, stack, "actor", "Coda", "m-a", expect="approval.pending")
    d.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["pending"]) == 2)
    d.send("approval.approve", {"machine_id": "m-c"})
    c.until("welcome")
    d.send("approval.deny", {"machine_id": "m-a"})
    a.until("denied")
    log = (tmp_path / "server.log").read_text()
    assert "Camera approved by director: Cam" in log
    assert "Actor denied by director: Coda" in log


def test_forget(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, {"m-a": {"name": "Coda"}})
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    a = connect_v2(client, stack, "actor", "Coda", "m-a", expect="welcome")
    d.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 2)
    d.send("approval.forget", {"id": a.seen[0]["data"]["session_id"]})
    assert a.until("approval.forgotten")
    with pytest.raises(WebSocketDisconnect) as closed:
        a.recv()
    assert closed.value.code == 4403
    roster = d.until(lambda e: e["type"] == "presence.roster" and e["data"]["pending"])["data"]
    assert roster["pending"][0]["machine_id"] == "m-a" and ids(roster, "actor") == []
    assert "m-a" not in json.loads((tmp_path / "approved_actors.json").read_text())
    # Reconnecting waits for approval again
    again = connect_v2(client, stack, "actor", "Coda", "m-a")
    assert again.recv()["type"] == "approval.pending"


def test_forget_unknown(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.send("approval.forget", {"id": "s_nobody"})
    assert d.until("error")["data"]["code"] == "unknown_target"


def offline(roster):
    return sorted((m["machine_id"], m["name"], m["role"]) for m in roster["offline"])


def test_roster_lists_offline_approved(tmp_path, stack):
    approved = {"m-a": {"name": "Coda", "approved_at": "2026-10-21T11:00:00"}, "m-c": {"name": "Cam", "role": "camera"}}
    client, _ = relay_client(stack, tmp_path, approved)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    roster = d.roster()
    assert offline(roster) == [("m-a", "Coda", "actor"), ("m-c", "Cam", "camera")]
    assert {m["machine_id"]: m.get("approved_at") for m in roster["offline"]} == {"m-a": "2026-10-21T11:00:00", "m-c": None}
    a = connect_v2(client, stack, "actor", "Coda", "m-a", expect="welcome")
    roster = d.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 2)["data"]
    assert offline(roster) == [("m-c", "Cam", "camera")]
    # Only directors and assistants get the list
    assert a.roster()["offline"] == []
    a.ws.close()
    roster = d.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 1)["data"]
    assert offline(roster) == [("m-a", "Coda", "actor"), ("m-c", "Cam", "camera")]


def test_forget_offline_machine(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, {"m-a": {"name": "Coda"}, "m-c": {"name": "Cam", "role": "camera"}})
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.roster()
    d.send("approval.forget", {"machine_id": "m-c"})
    roster = d.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["offline"]) == 1)["data"]
    assert offline(roster) == [("m-a", "Coda", "actor")]
    # Nobody is connected from m-c, so it doesn't wait in pending either
    assert roster["pending"] == []
    assert "m-c" not in json.loads((tmp_path / "approved_actors.json").read_text())
    assert "Camera forgotten by name: Cam" in (tmp_path / "server.log").read_text()
    # Coming back means asking again
    again = connect_v2(client, stack, "camera", "Cam", "m-c")
    assert again.recv()["type"] == "approval.pending"
    assert [p["machine_id"] for p in d.until(lambda e: e["type"] == "presence.roster" and e["data"]["pending"])["data"]["pending"]] == ["m-c"]


def test_forget_offline_machine_unknown(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.send("approval.forget", {"machine_id": "m-nobody"})
    assert d.until("error")["data"]["code"] == "unknown_target"


# ---- routing --------------------------------------------------------------------------------------------


def cast(client, stack):
    """Director, assistant, two actors and a camera, all connected and approved."""
    approved = {"m-a1": {"name": "Coda"}, "m-a2": {"name": "Ari"}, "m-c": {"name": "Cam", "role": "camera"}}
    client.app.state.relay.approvals.entries.update(approved)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    asst = connect_v2(client, stack, "assistant", "Ash", "m-asst")
    a1 = connect_v2(client, stack, "actor", "Coda", "m-a1", expect="welcome")
    a2 = connect_v2(client, stack, "actor", "Ari", "m-a2", expect="welcome")
    cam = connect_v2(client, stack, "camera", "Cam", "m-c", expect="welcome")
    for c in (a1, a2, cam):
        c.session_id = next(e for e in c.seen if e["type"] == "welcome")["data"]["session_id"]
    everyone = (d, asst, a1, a2, cam)
    for c in everyone:
        c.until(lambda e: e["type"] == "presence.roster" and len(e["data"]["sessions"]) == 5)
    return everyone


def received(c, msg_type):
    return [e for e in c.sync() if e["type"] == msg_type]


def test_roster_lists_everyone_including_cameras(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)
    roster = d.seen[-1]["data"]
    assert {s["name"]: s["role"] for s in roster["sessions"]} == {
        "Mira": "director", "Ash": "assistant", "Coda": "actor", "Ari": "actor", "Cam": "camera"}


def test_routing_by_ids_role_and_all(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)

    msg = d.send("cue.go", {}, to={"ids": [a1.session_id]})
    got = received(a1, "cue.go")
    assert len(got) == 1 and got[0]["id"] == msg and got[0]["from"] == d.session_id
    assert received(a2, "cue.go") == []

    d.send("cue.stop", {}, to={"role": "actor"})
    assert len(received(a1, "cue.stop")) == 1 and len(received(a2, "cue.stop")) == 1
    assert received(cam, "cue.stop") == [] and received(asst, "cue.stop") == []

    a1.send("chat.msg", {"text": "line?"}, to="all")
    for other in (d, asst, a2, cam):
        assert [e["data"]["text"] for e in received(other, "chat.msg")] == ["line?"]
    assert received(a1, "chat.msg") == []  # no echo

    d.send("obs.record.start", {"take": 3}, to={"role": "camera"})
    assert received(cam, "obs.record.start")[0]["data"] == {"take": 3}  # routed without reading data
    cam.send("obs.record.state", {"recording": True}, to={"ids": [d.session_id, asst.session_id]})
    assert len(received(d, "obs.record.state")) == 1 and len(received(asst, "obs.record.state")) == 1

    a1.send("cue.ack", {"command": "*go", "ok": True}, to={"ids": [d.session_id]})
    assert received(d, "cue.ack")[0]["from"] == a1.session_id


def test_from_cannot_be_spoofed(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)
    a2.send("chat.priv", {"text": "it's me, the director"}, to={"ids": [a1.session_id]}, **{"from": d.session_id})
    assert received(a1, "chat.priv")[0]["from"] == a2.session_id


def test_unknown_ids_and_names_never_route(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)
    msg = d.send("cue.go", {}, to={"ids": ["Coda", a2.session_id]})
    err = d.until("error")
    assert err["reply_to"] == msg and err["data"]["code"] == "unknown_target" and err["data"]["ids"] == ["Coda"]
    assert received(a1, "cue.go") == [] and len(received(a2, "cue.go")) == 1


def test_actor_cannot_cue_another_actor(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)
    a1.send("cue.go", {}, to={"ids": [a2.session_id]})
    assert a1.until("error")["data"]["code"] == "forbidden"
    assert received(a2, "cue.go") == []


@pytest.mark.parametrize("msg_type, data, code", [
    ("cue.play", {"index": 0}, "invalid"),
    ("osc.param", {"parameter": "Wave"}, "invalid"),
    ("chat.msg", {"text": "x"}, None),
    ("cuelist.list", {}, "unsupported"),
])
def test_validation_and_unbuilt_types(tmp_path, stack, msg_type, data, code):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.send(msg_type, data, to="all")
    errors = [e for e in d.sync() if e["type"] == "error"]
    assert [e["data"]["code"] for e in errors] == ([code] if code else [])


def test_target_required_for_routed_types(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.send("chat.msg", {"text": "x"})  # to defaults to "server"
    assert d.until("error")["data"]["code"] == "invalid"


def test_binary_frame_without_a_transfer(tmp_path, stack):
    # Binary frames carry file chunks (tests/test_files_v2.py); one that matches no offer is refused
    client, _ = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.ws.send_bytes(b"\x01" + bytes(20))
    assert d.until("error")["data"]["code"] == "invalid"


def test_oversized_frame(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, max_frame_bytes=1000)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.send("chat.msg", {"text": "x" * 2000}, to="all")
    assert d.until("error")["data"]["code"] == "invalid"


# ---- per-actor settings ---------------------------------------------------------------------------------


def test_actor_settings_stored_and_announced(tmp_path, stack):
    client, relay = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)
    d.send("actor.settings", {"id": a1.session_id, "delay_ms": 150, "display_name": "Coda|B"})
    roster = d.until(lambda e: e["type"] == "presence.roster" and any(s.get("delay_ms") == 150 for s in e["data"]["sessions"]))
    entry = next(s for s in roster["data"]["sessions"] if s["id"] == a1.session_id)
    assert entry["name"] == "Coda/B" and entry["delay_ms"] == 150
    stored = json.loads((tmp_path / "approved_actors.json").read_text())["m-a1"]
    assert stored["delay_ms"] == 150 and stored["name"] == "Coda/B"
    # Delivered in welcome on the next connection
    again = connect_v2(client, stack, "actor", "Coda", "m-a1", expect="welcome")
    welcome = next(e for e in again.seen if e["type"] == "welcome")["data"]
    assert welcome["delay_ms"] == 150 and welcome["name"] == "Coda/B"


def test_only_directors_change_settings(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path)
    d, asst, a1, a2, cam = cast(client, stack)
    asst.send("actor.settings", {"id": a1.session_id, "delay_ms": 10})
    assert asst.until("error")["data"]["code"] == "forbidden"
    d.send("actor.settings", {"id": d.session_id, "delay_ms": 10})
    assert d.until("error")["data"]["code"] == "unknown_target"


# ---- clock sync and latency ------------------------------------------------------------------------------


def test_time_pong(tmp_path, stack):
    clock = FakeClock(5_000_000)
    client, _ = relay_client(stack, tmp_path, clock=clock)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    ping = d.send("time.ping", {"t0": 4_999_900})
    pong = d.until("time.pong")
    assert pong["reply_to"] == ping and pong["from"] == "server"
    assert pong["data"] == {"t0": 4_999_900, "t1": 5_000_000, "t2": 5_000_000}


def test_relay_measures_v2_latency(tmp_path, stack):
    clock = FakeClock(10_000)
    client, relay = relay_client(stack, tmp_path, clock=clock)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    client.portal.call(relay.router.ping_sessions)
    ping = d.until("time.ping")
    assert ping["from"] == "server" and ping["data"] == {"t0": 10_000}
    clock.now = 10_080  # the client held it for 10 ms of its own time
    d.send("time.pong", {"t0": 10_000, "t1": 77, "t2": 87}, reply_to=ping["id"])
    d.sync()
    session = next(iter(relay.registry))
    assert session.latency_ms == 70
    client.portal.call(relay.router.send_latency)
    latency = d.until("presence.latency")["data"]["sessions"]
    assert latency == [{"id": d.session_id, "latency_ms": 70, "timed_out": False}]


def test_stray_pong_is_ignored(tmp_path, stack):
    client, relay = relay_client(stack, tmp_path)
    d = connect_v2(client, stack, "director", "Mira", "m-dir")
    d.send("time.pong", {"t0": 0, "t1": 0, "t2": 0}, reply_to="made-up")
    assert [e for e in d.sync() if e["type"] == "error"] == []
    assert next(iter(relay.registry)).latency_ms == 0


def test_health(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, {"m-a": {"name": "A"}})
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/").json() == {"status": "ok", "clients": 0, "approved": 1}


def test_legacy_endpoint_can_be_turned_off(tmp_path, stack):
    client, _ = relay_client(stack, tmp_path, legacy_enabled=False)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
    connect_v2(client, stack, "director", "Mira", "m-dir")
