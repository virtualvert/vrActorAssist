# Golden transcripts (spec §11.5): v0.3 clients on /ws must see exactly what the v0.3.3 relay
# sent them. tests/golden/legacy_session.txt was recorded from tests/legacy_relay/server_ws_v033.py.

import json
import threading

from legacy_client import GOLDEN, SECRET, RelayThread, golden_session, load_v033_relay, prepare_data_dir


def test_frozen_v033_relay_reproduces_golden(tmp_path):
    """The harness itself is deterministic against the relay the golden came from."""
    module = load_v033_relay(prepare_data_dir(tmp_path))
    with RelayThread(module.app) as relay:
        transcript = golden_session(relay.url)
    assert transcript == GOLDEN.read_text(encoding="utf-8")


def test_new_relay_reproduces_golden(tmp_path):
    from server.app import create_app
    from server.settings import Settings

    app = create_app(Settings(secret=SECRET, data_dir=prepare_data_dir(tmp_path), status_interval_s=None, echo_log=False))
    with RelayThread(app) as relay:
        transcript = golden_session(relay.url)
    assert transcript == GOLDEN.read_text(encoding="utf-8")


class V2Listener:
    """A v2 client on a real socket that says hello and then records everything in a thread."""

    def __init__(self, url, role, name, machine_id, secret=None):
        from websockets.sync.client import connect

        self.ws = connect(url, open_timeout=5).__enter__()
        hello = {"role": role, "name": name, "machine_id": machine_id, "version": "0.4.0-dev"}
        if secret:
            hello["secret"] = secret
        self.ws.send(json.dumps({"v": 2, "id": f"{name}-hello", "type": "hello", "to": "server", "data": hello}))
        self.welcome = json.loads(self.ws.recv(timeout=5))
        self.received = []
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for frame in self.ws:
                self.received.append(json.loads(frame))
        except Exception:
            pass

    def close(self):
        self.ws.close()
        self.thread.join(5)


def test_golden_unchanged_with_v2_camera_and_assistant(tmp_path):
    """Cameras are hidden from v0.3 clients and assistants aren't directors: with both connected
    over v2, v0.3 clients see exactly the golden session."""
    from server.app import create_app
    from server.settings import Settings

    data_dir = prepare_data_dir(tmp_path)
    (data_dir / "approved_actors.json").write_text(json.dumps({"m-cam": {"name": "Cam", "role": "camera"}}))
    app = create_app(Settings(secret=SECRET, data_dir=data_dir, status_interval_s=None, echo_log=False))
    with RelayThread(app) as relay:
        v2_url = relay.url[: -len("/ws")] + "/v2/ws"
        cam = V2Listener(v2_url, "camera", "Cam", "m-cam")
        ash = V2Listener(v2_url, "assistant", "Ash", "m-ash", secret=SECRET)
        try:
            transcript = golden_session(relay.url)
        finally:
            cam.close()
            ash.close()
    assert cam.welcome["type"] == "welcome" and ash.welcome["type"] == "welcome"
    assert transcript == GOLDEN.read_text(encoding="utf-8")
    # The v2 side did see the session: chat from the v0.3 director, and v0.3 actors in the roster
    texts = [e["data"]["text"] for e in ash.received if e["type"] == "chat.msg"]
    assert "Places ¡Acción! 🎬 a|b" in texts
    rosters = [e["data"] for e in ash.received if e["type"] == "presence.roster"]
    assert any({"Coda", "Ari", "Oldie"} <= {s["name"] for s in r["sessions"]} for r in rosters)
    assert any(r["pending"] for r in rosters)  # assistants see join requests
