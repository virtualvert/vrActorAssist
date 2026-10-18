# Tests for the v0.3.x relay hotfixes: update offers, director-only messages,
# malformed-message handling, and Soundpad volume scaling.

import itertools
import json
import math
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

import server_ws
import soundpad

SECRET = "test-secret"

MANIFEST = {
    "latest_version": "0.3.3",
    "release_notes": "notes",
    "assets": {
        "actor-linux-x64": {"url": "https://example.invalid/actor", "sha256": "aa"},
        "director-linux-x64": {"url": "https://example.invalid/director", "sha256": "dd"},
    },
}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def relay(tmp_path, monkeypatch):
    """A TestClient on server_ws.app with fresh state and all files in tmp_path."""
    monkeypatch.setattr(server_ws, "APPROVED_FILE", tmp_path / "approved_actors.json")
    monkeypatch.setattr(server_ws, "LOG_FILE", tmp_path / "server.log")
    monkeypatch.setattr(server_ws, "MANIFEST_FILE", tmp_path / "update_manifest.json")
    monkeypatch.setattr(server_ws, "SERVER_SECRET", SECRET)
    monkeypatch.setattr(server_ws, "approved_actors", {
        "mid-alice": {"name": "Alice"},
        "mid-bob": {"name": "Bob"},
    })
    monkeypatch.setattr(server_ws, "pending_actors", {})
    monkeypatch.setattr(server_ws, "clients", {})
    monkeypatch.setattr(server_ws, "pending_transfers", {})

    async def no_status_loop():
        pass

    monkeypatch.setattr(server_ws, "status_broadcast_loop", no_status_loop)

    # Entering the client shares one event loop between all websockets
    with TestClient(server_ws.app) as client:
        yield client


def read_until(ws, prefix):
    """Read messages until one starts with prefix (str or tuple). Returns all of them, match last."""
    seen = []
    while True:
        msg = ws.receive_text()
        seen.append(msg)
        if msg.startswith(prefix):
            return seen


_sync_ids = itertools.count()


def sync(sender, sender_name, *receivers):
    """Broadcast a marker MSG from sender and drain each receiver up to it.

    The relay handles one connection's messages in order, so everything the
    sender sent before the marker has been routed (or rejected) by the time the
    marker arrives. Returns the messages each receiver read, marker last.
    """
    marker = f"MSG|{sender_name}|sync-{next(_sync_ids)}"
    sender.send_text(marker)
    return [read_until(ws, marker) for ws in receivers]


def connect_director(stack, client, version="", platform=""):
    ws = stack.enter_context(client.websocket_connect("/ws"))
    ws.send_text(f"REGISTER|Director|mid-director|director|{SECRET}|{version}|{platform}")
    read_until(ws, "PENDING|")
    return ws


def connect_actor(stack, client, name, machine_id, version="", platform=""):
    ws = stack.enter_context(client.websocket_connect("/ws"))
    ws.send_text(f"REGISTER|{name}|{machine_id}|actor||{version}|{platform}")
    read_until(ws, "USERS|")
    return ws


def is_denial(msg):
    return msg.startswith("MSG|SERVER|Permission denied")


# ---------------------------------------------------------------------------
# find_update: only offer strictly newer versions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("client_version", ["0.3.2", "0.2.9", "0.3", "0.3.2-dev", "v0.3.0"])
def test_find_update_offers_newer_version(client_version):
    update = server_ws.find_update(MANIFEST, "actor", "linux-x64", client_version)
    assert update == {
        "latest_version": "0.3.3",
        "download_url": "https://example.invalid/actor",
        "sha256": "aa",
        "release_notes": "notes",
    }


@pytest.mark.parametrize("client_version", ["0.3.3", "0.3.3-dev", "0.3.4", "0.4.0", "0.4.0-dev", "1.0.0"])
def test_find_update_never_offers_same_or_older(client_version):
    assert server_ws.find_update(MANIFEST, "actor", "linux-x64", client_version) == {}


def test_find_update_compares_numerically():
    manifest = dict(MANIFEST, latest_version="0.3.10")
    assert server_ws.find_update(manifest, "actor", "linux-x64", "0.3.9")["latest_version"] == "0.3.10"
    manifest = dict(MANIFEST, latest_version="0.3.9")
    assert server_ws.find_update(manifest, "actor", "linux-x64", "0.3.10") == {}


def test_find_update_tolerates_suffix_on_latest():
    manifest = dict(MANIFEST, latest_version="0.4.0-rc1")
    assert server_ws.find_update(manifest, "actor", "linux-x64", "0.3.3")["latest_version"] == "0.4.0-rc1"


@pytest.mark.parametrize("client_version", ["", "dev", "unknown"])
def test_find_update_skips_unparseable_client_version(client_version):
    assert server_ws.find_update(MANIFEST, "actor", "linux-x64", client_version) == {}


def test_find_update_needs_manifest_and_asset_url():
    assert server_ws.find_update({}, "actor", "linux-x64", "0.1.0") == {}
    assert server_ws.find_update(MANIFEST, "actor", "windows-x64", "0.1.0") == {}


@pytest.mark.parametrize("version, expect_update", [
    ("0.3.2", True),
    ("0.3.3", False),
    ("0.4.0", False),
    ("0.4.0-dev", False),
])
@pytest.mark.parametrize("role", ["actor", "director"])
def test_registration_sends_update_only_to_older_clients(relay, role, version, expect_update):
    server_ws.MANIFEST_FILE.write_text(json.dumps(MANIFEST))
    with ExitStack() as stack:
        ws = stack.enter_context(relay.websocket_connect("/ws"))
        if role == "director":
            ws.send_text(f"REGISTER|Director|mid-director|director|{SECRET}|{version}|linux-x64")
            msgs = read_until(ws, "PENDING|")
        else:
            ws.send_text(f"REGISTER|Alice|mid-alice|actor||{version}|linux-x64")
            msgs = read_until(ws, "USERS|")
    assert any(m.startswith("UPDATE|0.3.3|") for m in msgs) == expect_update


# ---------------------------------------------------------------------------
# Role checks: cues and file pushes are director-only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "CMD|go",
    "CMD|*play:3",
    "OSC_CUE|Bob|Wave|true",
    "PRIV|Alice|Bob|*go",
    "PRIV|Alice|Bob|  *stop",
    "FILEREQ|Alice|Bob|evil.exe|10|abc",
    "FILESTART|clip.wav|1|1024",
    "FILECHUNK|clip.wav|0|ZGF0YQ==",
    "FILEEND|clip.wav|abc",
    "BATCH_START|Bob|1|10",
    "BATCH_END|Bob|1|0",
    "BATCH_CANCEL|Bob|nope",
])
def test_actor_cannot_send_director_only_messages(relay, message):
    with ExitStack() as stack:
        director = connect_director(stack, relay)
        alice = connect_actor(stack, relay, "Alice", "mid-alice")
        bob = connect_actor(stack, relay, "Bob", "mid-bob")

        # A live transfer to Bob, so FILESTART/FILECHUNK/FILEEND have a route to hijack
        director.send_text("FILEREQ|Director|Bob|clip.wav|4|abc")
        (bob_msgs,) = sync(director, "Director", bob)
        assert "FILEREQ|Director|Bob|clip.wav|4|abc" in bob_msgs

        alice.send_text(message)
        alice_msgs, bob_msgs, director_msgs = sync(alice, "Alice", alice, bob, director)

    msg_type = message.split("|")[0]
    # Sender gets a notice and stays connected (it received its own marker)
    assert [m for m in alice_msgs if is_denial(m)] == [
        f"MSG|SERVER|Permission denied: only the director can send {msg_type}"
    ]
    assert not any(m.startswith(msg_type + "|") for m in bob_msgs + director_msgs)
    assert set(server_ws.pending_transfers) == {"clip.wav"}


def test_director_can_still_send_cues_and_files(relay):
    with ExitStack() as stack:
        director = connect_director(stack, relay)
        alice = connect_actor(stack, relay, "Alice", "mid-alice")
        bob = connect_actor(stack, relay, "Bob", "mid-bob")

        director.send_text("CMD|go")
        director.send_text("OSC_CUE|Bob|Wave|true")
        director.send_text("PRIV|Director|Bob|*play:3")
        director.send_text("BATCH_START|Bob|1|4")
        director_msgs, alice_msgs, bob_msgs = sync(director, "Director", director, alice, bob)

    assert not any(is_denial(m) for m in director_msgs)
    assert "CMD|go" in alice_msgs
    for expected in ("CMD|go", "OSC_CUE|Bob|Wave|true", "PRIV|Director|Bob|*play:3", "BATCH_START|Bob|1|4"):
        assert expected in bob_msgs


@pytest.mark.parametrize("final_reply", [
    "FILEOK|clip.wav|C:/cues/clip.wav",
    "FILEERR|clip.wav|Checksum mismatch",
])
def test_actor_file_replies_still_reach_director(relay, final_reply):
    with ExitStack() as stack:
        director = connect_director(stack, relay)
        bob = connect_actor(stack, relay, "Bob", "mid-bob")

        director.send_text("FILEREQ|Director|Bob|clip.wav|4|abc")
        (bob_msgs,) = sync(director, "Director", bob)
        assert "FILEREQ|Director|Bob|clip.wav|4|abc" in bob_msgs

        bob.send_text("FILEACK|clip.wav|1|C:/cues")
        bob_msgs, director_msgs = sync(bob, "Bob", bob, director)
        assert not any(is_denial(m) for m in bob_msgs)
        assert "FILEACK|clip.wav|1|C:/cues" in director_msgs

        pushes = ["FILESTART|clip.wav|1|1024", "FILECHUNK|clip.wav|0|ZGF0YQ==", "FILEEND|clip.wav|abc"]
        for push in pushes:
            director.send_text(push)
        (bob_msgs,) = sync(director, "Director", bob)
        assert [m for m in bob_msgs if m in pushes] == pushes

        bob.send_text(final_reply)
        bob_msgs, director_msgs = sync(bob, "Bob", bob, director)
        assert not any(is_denial(m) for m in bob_msgs)
        assert final_reply in director_msgs

    assert server_ws.pending_transfers == {}


def test_actor_can_deny_file(relay):
    with ExitStack() as stack:
        director = connect_director(stack, relay)
        bob = connect_actor(stack, relay, "Bob", "mid-bob")

        director.send_text("FILEREQ|Director|Bob|clip.wav|4|abc")
        sync(director, "Director", bob)

        bob.send_text("FILEDENY|clip.wav|Declined")
        bob_msgs, director_msgs = sync(bob, "Bob", bob, director)

    assert not any(is_denial(m) for m in bob_msgs)
    assert "FILEDENY|clip.wav|Declined" in director_msgs
    assert server_ws.pending_transfers == {}


def test_actor_chat_ack_and_plain_priv_allowed(relay):
    with ExitStack() as stack:
        director = connect_director(stack, relay)
        alice = connect_actor(stack, relay, "Alice", "mid-alice")
        bob = connect_actor(stack, relay, "Bob", "mid-bob")

        bob.send_text("ACK|Bob|go|OK")
        bob.send_text("MSG|Bob|line?")
        bob.send_text("PRIV|Bob|Director|need a minute")
        bob.send_text("PRIV|Bob|Alice|hi *wave*")  # '*' not at the start is plain chat
        bob_msgs, director_msgs, alice_msgs = sync(bob, "Bob", bob, director, alice)

    assert not any(is_denial(m) for m in bob_msgs)
    assert "MSG|Bob|line?" in director_msgs
    assert "MSG|Bob|line?" in alice_msgs
    assert "PRIV|Bob|Director|need a minute" in director_msgs
    assert "PRIV|Bob|Alice|hi *wave*" in alice_msgs


def test_malformed_message_does_not_disconnect(relay):
    with ExitStack() as stack:
        director = connect_director(stack, relay)
        alice = connect_actor(stack, relay, "Alice", "mid-alice")

        # A non-numeric chunk number used to raise in parse_message and drop the socket
        alice.send_text("FILECHUNK|clip.wav|notanumber|x")
        alice.send_text("MSG|Alice|still here")
        # Watch from the director: a dropped actor shows up as "Alice left" instead
        director_msgs = read_until(director, ("MSG|Alice|still here", "MSG|SERVER|Alice left"))

    assert director_msgs[-1] == "MSG|Alice|still here"


# ---------------------------------------------------------------------------
# Soundpad: SetVolume takes an integer 0-100
# ---------------------------------------------------------------------------

@pytest.fixture
def soundpad_calls(monkeypatch):
    calls = []

    def fake_run(command):
        calls.append(command)
        return (True, None)

    monkeypatch.setattr(soundpad, "run_soundpad_command", fake_run)
    return calls


@pytest.mark.parametrize("volume, expected", [
    (0.0, "SetVolume(0)"),
    (0.5, "SetVolume(50)"),
    (0.333, "SetVolume(33)"),
    (1.0, "SetVolume(100)"),
])
def test_set_volume_sends_percentage(soundpad_calls, volume, expected):
    assert soundpad.set_volume(volume) == (True, None)
    assert soundpad_calls == [expected]


def test_volume_command_scales_to_percentage(soundpad_calls):
    assert soundpad.execute_command("volume", "0.75") == (True, None)
    assert soundpad_calls == ["SetVolume(75)"]


@pytest.mark.parametrize("volume", [-0.1, 1.5, math.nan, math.inf])
def test_set_volume_rejects_out_of_range(soundpad_calls, volume):
    ok, _ = soundpad.set_volume(volume)
    assert not ok
    assert soundpad_calls == []
