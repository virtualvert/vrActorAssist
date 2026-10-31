"""Camera operator (spec §8.5): the obs-websocket client against a fake OBS, and the VRChat
window match / restore rules against a fake window module (the real one needs Windows and VRChat)."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve

from agent.camera import CameraError, CameraRuntime
from agent.config import Config, ConfigStore
from agent.core import Agent
from agent.obs import ObsClient, ObsError, auth_string
from agent.vrchat_window import Window

PASSWORD = "obs-pass"
SALT, CHALLENGE = "salt123", "challenge456"


def fake_obs(answers, password=PASSWORD):
    """An obs-websocket 5 server: Hello (with auth when password is set), Identify check, then answers[requestType]."""

    async def handler(ws):
        hello = {"obsWebSocketVersion": "5.6.2", "rpcVersion": 1}
        if password:
            hello["authentication"] = {"salt": SALT, "challenge": CHALLENGE}
        await ws.send(json.dumps({"op": 0, "d": hello}))
        identify = json.loads(await ws.recv())["d"]
        if password and identify.get("authentication") != auth_string(password, SALT, CHALLENGE):
            await ws.close(4009, "Authentication failed.")
            return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            req = json.loads(raw)["d"]
            data = answers.get(req["requestType"])
            status = {"result": data is not None, "code": 100 if data is not None else 204}
            await ws.send(json.dumps({"op": 7, "d": {"requestType": req["requestType"], "requestId": req["requestId"],
                                                      "requestStatus": status, "responseData": data or {}}}))

    return serve(handler, "127.0.0.1", 0)


def url_of(server):
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"


@pytest.mark.anyio
async def test_obs_client_identifies_and_requests():
    async with fake_obs({"GetVideoSettings": {"baseWidth": 1920, "baseHeight": 1080}}) as server:
        client = await ObsClient.open(url_of(server), PASSWORD)
        assert client.version == "5.6.2"
        assert (await client.request("GetVideoSettings"))["baseWidth"] == 1920
        with pytest.raises(ObsError, match="refused GetStats"):
            await client.request("GetStats")
        await client.close()


@pytest.mark.anyio
async def test_obs_client_wrong_or_missing_password():
    async with fake_obs({}) as server:
        with pytest.raises(ObsError, match="refused the password"):
            await ObsClient.open(url_of(server), "wrong")
        with pytest.raises(ObsError, match="asks for a password"):
            await ObsClient.open(url_of(server), "")


@pytest.mark.anyio
async def test_obs_client_nothing_listening():
    with pytest.raises(ObsError, match="isn't running"):
        await ObsClient.open("ws://127.0.0.1:1", "")


VRCHAT = Window(hwnd=42, cls="UnityWndClass", client=(1700, 950), rect=(100, 100, 1818, 1097),
                style=0, exstyle=0, dpi=120, mode="window")


class FakeWindows:
    SUPPORTED = True

    def __init__(self):
        self.win = VRCHAT
        self.calls = []

    def find(self):
        return self.win

    def resize(self, win, width, height):
        self.calls.append(("resize", width, height))
        self.win = replace(win, client=(width, height))
        return self.win

    def place(self, hwnd, rect):
        self.calls.append(("place", hwnd, rect))
        if self.win is None or self.win.hwnd != hwnd:
            return None
        self.win = replace(self.win, client=VRCHAT.client, rect=rect)
        return self.win


class FakeObs:
    def __init__(self):
        self.recording = False

    async def request(self, request_type, data=None):
        return {"outputActive": self.recording}

    async def close(self):
        pass


def camera_runtime(allow=True):
    config = Config(role="camera")
    config.obs.allow_window_resize = allow
    logs = []
    windows = FakeWindows()
    cam = CameraRuntime(config, changed=lambda: None, log=lambda level, text: logs.append(text), window=windows)
    cam.obs = FakeObs()
    cam.video = {"base": (1920, 1080), "output": (1920, 1080), "fps": 60.0}
    return cam, windows, logs


@pytest.mark.anyio
async def test_match_needs_consent_and_no_recording():
    cam, windows, _ = camera_runtime(allow=False)
    with pytest.raises(CameraError, match="Turn on"):
        await cam.match()
    cam._config.obs.allow_window_resize = True
    cam.obs.recording = True  # asked fresh, even though the last poll said not recording
    with pytest.raises(CameraError, match="recording"):
        await cam.match()
    assert windows.calls == []


@pytest.mark.anyio
async def test_match_then_close_puts_the_window_back():
    cam, windows, logs = camera_runtime()
    await cam.match()
    assert windows.calls == [("resize", 1920, 1080)]
    assert cam.view()["window"] == {"state": "matched", "size": [1920, 1080], "mode": "window",
                                    "allowResize": True, "canRestore": True}
    await cam.match()  # a second match keeps the first restore point
    await cam.close()
    assert windows.calls[-1] == ("place", 42, VRCHAT.rect)
    assert windows.win.client == VRCHAT.client
    assert any("put back" in text for text in logs)


@pytest.mark.anyio
async def test_restore_after_vrchat_restarted_does_nothing():
    cam, windows, logs = camera_runtime()
    await cam.match()
    windows.win = replace(VRCHAT, hwnd=43)  # a new VRChat window
    await cam.restore()
    assert cam.view()["window"]["canRestore"] is False
    assert any("restarted" in text for text in logs)
    with pytest.raises(CameraError, match="nothing to put back"):
        await cam.restore()


def test_obs_password_stays_out_of_the_ui(tmp_path):
    store = ConfigStore(tmp_path)
    store.config.role = "camera"
    store.config.obs.password = PASSWORD
    store.save()
    again = ConfigStore(tmp_path).config
    assert (again.obs.url, again.obs.password, again.obs.allow_window_resize) == ("ws://127.0.0.1:4455", PASSWORD, False)
    agent = Agent(ConfigStore(tmp_path))
    snapshot = agent.snapshot()
    assert snapshot["camera"]["obs"]["hasPassword"] is True
    assert PASSWORD not in json.dumps(snapshot)


def test_view_without_obs_or_vrchat():
    cam = CameraRuntime(Config(role="camera"), changed=lambda: None, log=lambda *a: None,
                        window=SimpleNamespace(SUPPORTED=True))
    assert cam.view()["window"]["state"] == "not_found"
    cam.window = VRCHAT
    assert cam.view()["window"]["state"] == "unknown"
    assert cam.view()["obs"]["base"] is None
