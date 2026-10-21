# The §5.5 permission table: as data (server/permissions.py), on /v2/ws, and on v0.3 traffic.

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from relay_helpers import connect_legacy, connect_v2, make_relay
from server import permissions
from shared import MSG_TYPES
from vrcas_protocol import MODELS

D, A, ACT, C = "director", "assistant", "actor", "camera"
ALL = {D, A, ACT, C}
ROLES = (D, A, ACT, C)

# Written out from the spec (§5.5 plus the rows it leaves implicit), independently of permissions.py
SPEC = {
    "chat.msg": ALL, "chat.priv": ALL,
    **{t: {D, A} for t in ("cue.go", "cue.stop", "cue.play", "soundpad.play", "soundpad.stop", "soundpad.pause",
                           "soundpad.seek", "soundpad.jump", "soundpad.volume", "soundpad.mute",
                           "soundpad.list.request", "soundpad.calibrate")},
    **{t: {ACT} for t in ("cue.ack", "soundpad.ack", "soundpad.list", "soundpad.state")},
    **{t: {D} for t in ("approval.approve", "approval.deny", "approval.forget", "actor.settings")},
    # "file.offer + chunks"; the end of a transfer and batches belong to the sender too
    **{t: {D} for t in ("file.offer", "file.end", "file.batch.start", "file.batch.end", "file.batch.cancel")},
    **{t: {ACT, C} for t in ("file.accept", "file.deny", "file.ok", "file.err", "file.progress")},
    "file.inventory.request": {D, A}, "file.inventory": {ACT, C},
    "stage.state": {D, A}, "ready.request": {D, A}, "ready.ping": {D, A}, "ready.status": {ACT, C},
    "osc.param": {D, A}, "osc.cue.load": {D, A},
    "osc.cue.ack": {ACT}, "osc.cue.fired": {ACT}, "osc.params": {ACT},
    "cuelist.save": {D, A}, "cuelist.delete": {D, A}, "cuelist.get": {D, A, ACT}, "cuelist.list": {D, A, ACT},
    **{t: {D, A} for t in ("obs.profile.apply", "obs.profile.release", "obs.record.start", "obs.record.stop",
                           "obs.mark", "obs.slate")},
    **{t: {C} for t in ("obs.profile.status", "obs.record.state", "obs.status")},
    **{t: {D, A, C} for t in ("rtc.offer", "rtc.answer", "rtc.ice", "rtc.bye")},
    "hello": ALL, "time.ping": ALL, "time.pong": ALL,
    **{t: set() for t in ("welcome", "denied", "error", "presence.roster", "presence.latency", "approval.pending",
                          "approval.forgotten", "update.available")},
}


def test_spec_covers_the_catalogue():
    assert set(SPEC) == set(MODELS)


@pytest.mark.parametrize("msg_type", sorted(SPEC))
@pytest.mark.parametrize("role", ROLES)
def test_table_matches_spec(msg_type, role):
    assert permissions.allowed(role, msg_type) == (role in SPEC[msg_type])


def test_namespace_patterns_and_unknown_types():
    assert permissions.allowed(C, "rtc.something.new")
    assert not permissions.allowed(ACT, "rtc.offer")
    assert permissions.rule("notify.toast") is None
    assert not permissions.allowed(D, "notify.toast")


@pytest.mark.parametrize("role", ROLES)
def test_v2_relay_enforces_every_row(tmp_path, role):
    """One session per role sends every known type; exactly the disallowed ones come back
    `forbidden` (the rest may still fail validation or have nobody to go to)."""
    approved = {"m-actor": {"name": "Act"}, "m-camera": {"name": "Cam", "role": "camera"}}
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(make_relay(tmp_path, approved)))
        me = connect_v2(client, stack, role, role.capitalize(), f"m-{role}", expect="welcome")
        sent = {me.send(t, {}, to="all"): t for t in sorted(SPEC)}
        replies = me.sync()
    forbidden = {sent[e["reply_to"]] for e in replies if e["type"] == "error" and e["data"]["code"] == "forbidden"}
    assert forbidden == {t for t, roles in SPEC.items() if role not in roles}


def test_v2_unknown_type_is_rejected(tmp_path):
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(make_relay(tmp_path)))
        d = connect_v2(client, stack, D, "Mira", "m-d")
        msg = d.send("notify.toast", {}, to="all")
        err = d.until("error")
    assert err["reply_to"] == msg and err["data"]["code"] == "unknown_type"


# ---- v0.3 traffic ------------------------------------------------------------------------------

# Every v0.3 message type and what it is in v2 terms (spec §11.2). Client-sent types are checked
# against the table as `legacy_type`; the rest only ever come from the relay.
LEGACY_V2 = {
    "MSG": "chat.msg",
    "PRIV": "chat.priv",  # cue.* when the text starts with '*'
    "CMD": "cue.go",
    "ACK": "cue.ack",
    "OSC_CUE": "osc.param",
    "FILEREQ": "file.offer", "FILESTART": "file.offer", "FILECHUNK": "file.offer", "FILEEND": "file.end",
    "BATCH_START": "file.batch.start", "BATCH_END": "file.batch.end", "BATCH_CANCEL": "file.batch.cancel",
    "FILEACK": "file.accept", "FILEDENY": "file.deny", "FILEOK": "file.ok", "FILEERR": "file.err",
    # relay → client, derived from v2 state
    "USERS": None, "STATUS": None, "PENDING": None, "APPROVED": None, "DENIED": None, "VERSION": None,
    "UPDATE": None, "FILE": None, "FORGET": None,
    # the handshake
    "REGISTER": None,
}


def test_every_legacy_type_has_a_v2_meaning():
    assert set(LEGACY_V2) == set(MSG_TYPES)
    for legacy, v2 in LEGACY_V2.items():
        assert permissions.legacy_type(legacy, {"text": "hi"}) == v2, legacy


def test_legacy_cue_text_counts_as_a_cue():
    assert permissions.legacy_type("PRIV", {"text": "  *go"}) == "cue.go"
    assert permissions.legacy_type("PRIV", {"text": "hi *wave*"}) == "chat.priv"
    for legacy, v2 in {"APPROVE": "approval.approve", "DENY": "approval.deny", "FORGET_NAME": "approval.forget"}.items():
        assert permissions.legacy_type(legacy, {}) == v2
    for housekeeping in ("PONG", "REFRESH", "REGISTER"):
        assert permissions.legacy_type(housekeeping, {}) is None


def test_legacy_roles():
    assert permissions.legacy_role("director") == D
    assert permissions.legacy_role("camera") == C
    assert permissions.legacy_role("actor") == ACT
    assert permissions.legacy_role("assistant") == ACT  # no secret on /ws, so no director rights


@pytest.mark.parametrize("message, notice", [
    ("ACK|Mira|go|OK", False),            # actor-only: dropped, as the v0.3 relay did
    ("FILEACK|clip.wav|1|C:/", False),    # actor-only now; the v0.3 relay forwarded it
    ("CMD|go", None),                      # allowed
])
def test_legacy_director_rows(tmp_path, message, notice):
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(make_relay(tmp_path, {"m-a": {"name": "Act"}})))
        director = connect_legacy(client, stack, "director", "Mira", "m-d")
        actor = connect_legacy(client, stack, "actor", "Act", "m-a")
        director.send(message)
        got = director.sync()
        actor_got = actor.sync()
    assert not any(m.startswith("MSG|SERVER|Permission denied") for m in got)
    reached = any(m.startswith(message.split("|")[0] + "|") for m in actor_got)
    assert reached == (notice is None)


def test_legacy_camera_cannot_cue(tmp_path):
    """The v0.4 preview registers cameras as 'camera' over /ws; they get no cue rights."""
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(make_relay(tmp_path, {"m-c": {"name": "Cam", "role": "camera"}})))
        cam = connect_legacy(client, stack, "camera", "Cam", "m-c", expect="APPROVED")
        cam.send("CMD|go")
        got = cam.sync()
    assert "MSG|SERVER|Permission denied: only the director can send CMD" in got
