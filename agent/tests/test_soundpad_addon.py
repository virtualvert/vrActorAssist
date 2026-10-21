"""The rest of the soundpad addon (spec §8.1, Phase 2 M2) against an in-memory Soundpad: sound
references, the drift guard, output lines, volume / pause / seek / mute, lists, state, auto-add."""

import asyncio
import hashlib
import re

import pytest

import soundpad
from agent import actor_runtime
from agent.actor_runtime import ActorRuntime
from agent.soundpad_pipe import SoundpadPipe, Sound
from agent.sounds import LIST_PAGE, normal_path, pages, sound_key

from .test_relay_v2 import relay  # noqa: F401  (fixture)
from .test_soundpad_pipe import FakeSoundpad, actor_config, windows_cli  # noqa: F401  (fixture)


class FullSoundpad(FakeSoundpad):
    """The fake plus the commands M2 uses, recording what each play asked for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.muted = False
        self.seeks: list[str] = []
        self.plays: list[str] = []
        self.urls: dict[str, str] = {}  # title → the path Soundpad lists (added sounds keep theirs)

    def url(self, title):
        return self.urls.get(title, f"C:\\Sounds\\{title}.mp3")

    def answer(self, command):
        if match := re.fullmatch(r'DoAddSound\("(.+)"\)', command):
            answer = super().answer(command)
            self.urls[self.pending_add] = match.group(1)  # listed under the path it was added from
            return answer
        if match := re.fullmatch(r"GetSoundlist\((?:(\d+)(?:, (\d+))?)?\)", command):
            if self.pending_add:
                self.sounds.append(self.pending_add)
                self.pending_add = None
            first, last = int(match.group(1) or 1), int(match.group(2) or len(self.sounds))
            rows = "".join(
                f'<Sound index="{i}" url="{self.url(t)}" artist="" title="{t}" duration="0:47" addedOn="" '
                f'lastPlayedOn="" playCount="0" tag=""/>'
                for i, t in enumerate(self.sounds, start=1) if first <= i <= last)
            return f"<Soundlist>{rows}</Soundlist>"
        if re.fullmatch(r"DoPlaySound\(.*\)|DoPlaySelectedSound\(\)|DoPlaySoundFromCategory\(.*\)", command):
            self.plays.append(command)
        if match := re.fullmatch(r"DoPlaySoundFromCategory\((\d+), (\d+), (true|false), (true|false)\)", command):
            return self._play() if match.group(1) == "2" else "R-404"
        if match := re.fullmatch(r"Do(Seek|Jump)Ms\((-?\d+)\)", command):
            self.seeks.append(command)
            return "R-200"
        if command == "DoTogglePause()":
            self.status = {"PLAYING": "PAUSED", "PAUSED": "PLAYING"}.get(self.status, self.status)
            return "R-200"
        if command == "IsMuted()":
            return "1" if self.muted else "0"
        if command == "DoToggleMute()":
            self.muted = not self.muted
            return "R-200"
        return super().answer(command)


async def ready(fake, cfg=None, **attrs):
    runtime = ActorRuntime(cfg or actor_config(), pipe_factory=lambda: SoundpadPipe(fake.connect))
    for name, value in attrs.items():
        setattr(runtime, name, value)
    await runtime.refresh()
    await asyncio.sleep(0.05)
    assert runtime.soundpad_state()["state"] == "ready"
    return runtime


def key_of(fake, title):
    return sound_key(fake.url(title))


# ---- keys and pages -------------------------------------------------------------------------------


def test_keys_ignore_case_and_slash_direction():
    assert sound_key("C:\\Sounds\\A.mp3") == sound_key("c:/sounds/a.MP3")
    assert normal_path(" C:/X/Y.wav ") == "c:\\x\\y.wav"
    assert re.fullmatch(r"[0-9a-f]{16}", sound_key("x"))


def test_pages():
    sounds = [Sound(i, f"C:\\s\\{i}.wav", f"t{i}", "", 47, "", "", 0, "") for i in range(1, 1201)]
    out = pages(sounds, [{"index": 2, "name": "EP3"}])
    assert [(p["first"], len(p["sounds"]), p["last"], bool(p["categories"])) for p in out] == [
        (1, LIST_PAGE, False, True), (501, LIST_PAGE, False, False), (1001, 200, True, False)]
    assert out[0]["sounds"][0] == {"index": 1, "key": sound_key("C:\\s\\1.wav"), "title": "t1", "duration_ms": 47000}
    assert "url" not in out[0]["sounds"][0]
    assert pages([], []) == [{"total": 0, "first": 1, "sounds": [], "categories": [], "last": True}]


# ---- playing ------------------------------------------------------------------------------------


def test_play_by_key_with_lines_and_the_drift_guard(windows_cli):
    fake = FullSoundpad(sounds=["intro", "scene 4 - diego", "outro"])

    async def scenario():
        runtime = await ready(fake)
        sounds, categories = await runtime.sound_list()
        assert [s.title for s in sounds] == ["intro", "scene 4 - diego", "outro"]
        assert categories == [{"index": 2, "name": "My Sounds"}]

        assert await runtime.play_sound({"key": key_of(fake, "scene 4 - diego")}, "speakers") == ("ok", None)
        assert fake.plays[-1] == "DoPlaySound(2, true, false)"
        await asyncio.sleep(0.1)  # the poller reads the new status
        state = runtime.state_for_directors()
        assert state["available"] and state["status"] == "PLAYING"
        assert (state["index"], state["key"], state["lines"], state["title"]) == (2, key_of(fake, "scene 4 - diego"), "speakers", "scene 4 - diego")

        # The actor reorders Soundpad: same count, so only the drift guard notices
        fake.sounds = ["scene 4 - diego", "intro", "outro"]
        assert await runtime.play_sound({"key": key_of(fake, "scene 4 - diego")}, "mic") == ("ok", None)
        assert fake.plays[-1] == "DoPlaySound(1, false, true)"

        status, error = await runtime.play_sound({"key": "0" * 16})
        assert status == "not_in_soundpad" and "isn't in this actor's Soundpad" in error
        await runtime.close()

    asyncio.run(scenario())


def test_default_lines_volume_and_start_position(windows_cli):
    fake = FullSoundpad()
    cfg = actor_config()
    cfg.soundpad.default_lines = "mic"

    async def scenario():
        runtime = await ready(fake, cfg)
        assert await runtime.play_sound({"index": 3}, volume=70, start_ms=5000) == ("ok", None)
        commands = fake.commands[-12:]
        assert "SetVolume(70)" in commands and fake.plays[-1] == "DoPlaySound(3, false, true)"
        assert commands.index("SetVolume(70)") < commands.index("DoPlaySound(3, false, true)")
        assert fake.seeks == ["DoSeekMs(5000)"]
        assert runtime.volume_level == 70
        await runtime.close()

    asyncio.run(scenario())


def test_selected_sound(windows_cli):
    fake = FullSoundpad()

    async def scenario():
        runtime = await ready(fake)
        assert await runtime.play_sound({"selected": True}) == ("ok", None)
        assert fake.plays[-1] == "DoPlaySelectedSound()"
        status, error = await runtime.play_sound({"selected": True}, "speakers")
        assert status == "unsupported" and "pick a sound" in error
        await runtime.close()

    asyncio.run(scenario())


def test_paths_received_files_and_auto_add(windows_cli, tmp_path):
    fake = FullSoundpad(sounds=["intro"])
    new = tmp_path / "Scene 9 - Rin.wav"
    new.write_bytes(b"RIFF")
    digest = hashlib.sha256(b"RIFF").hexdigest()

    async def scenario():
        runtime = await ready(fake, received_lookup=lambda sha: str(new) if sha == digest else None)
        # in Soundpad already (case and slashes don't matter)
        assert await runtime.play_sound({"path": "c:/sounds/INTRO.mp3"}) == ("ok", None)
        assert fake.plays[-1] == "DoPlaySound(1, true, true)"
        # a received file, added on the way (full version)
        assert await runtime.play_sound({"sha256": digest}) == ("ok", None)
        assert any(c.startswith('DoAddSound("') for c in fake.commands)
        assert fake.plays[-1] == "DoPlaySound(2, true, true)"
        # unknown hash, missing file
        assert (await runtime.play_sound({"sha256": "ab" * 32}))[0] == "not_found"
        assert (await runtime.play_sound({"path": str(tmp_path / "gone.wav")}))[0] == "not_found"
        # adding turned off
        runtime._config.soundpad.auto_add_received = False
        other = tmp_path / "other.wav"
        other.write_bytes(b"x")
        assert (await runtime.play_sound({"path": str(other)}))[0] == "not_in_soundpad"
        await runtime.close()

    asyncio.run(scenario())


def test_trial_cant_add(windows_cli, tmp_path):
    fake = FullSoundpad(trial=True)
    path = tmp_path / "x.wav"
    path.write_bytes(b"x")

    async def scenario():
        runtime = await ready(fake)
        status, error = await runtime.play_sound({"path": str(path)})
        assert status == "trial_limit" and "by hand" in error
        assert not any(c.startswith("DoAddSound") for c in fake.commands)
        await runtime.close()

    asyncio.run(scenario())


def test_category_reference(windows_cli):
    fake = FullSoundpad()

    async def scenario():
        runtime = await ready(fake)
        assert await runtime.play_sound({"category": "my sounds", "position": 1}, "speakers") == ("ok", None)
        assert fake.plays[-1] == "DoPlaySoundFromCategory(2, 1, true, false)"
        assert (await runtime.play_sound({"category": "Nope"}))[0] == "not_found"
        await runtime.close()

    asyncio.run(scenario())


def test_without_the_pipe(windows_cli):
    fake = FullSoundpad()
    fake.refuse = PermissionError(5, "Access is denied")

    async def scenario():
        runtime = await ready_or_fallback(fake)
        # what the command line can do still works
        assert await runtime.play_sound({"index": 2}) == ("ok", None)
        assert windows_cli == ["*play:2"]
        # Soundpad closed: no command line (it would start Soundpad); the director gets offline
        fake.refuse = None
        fake.running = False
        runtime._pipe.reconnect_now()
        assert await runtime.play_sound({"index": 2}) == ("soundpad_offline", "Soundpad isn't running")
        assert windows_cli == ["*play:2"]
        assert runtime.state_for_directors()["detail"].startswith("Soundpad isn't running")
        status, error = await runtime.play_sound({"key": "0" * 16})
        assert status == "soundpad_offline"
        assert (await runtime.control("volume", 50))[0] == "soundpad_offline"
        runtime._config.soundpad.enabled = False
        assert (await runtime.play_sound({"index": 1}))[0] == "skipped"
        state = runtime.state_for_directors()
        assert state == {"available": False, "detail": "Soundpad is off on this computer"}
        await runtime.close()

    async def ready_or_fallback(fake):
        runtime = ActorRuntime(actor_config(), pipe_factory=lambda: SoundpadPipe(fake.connect))
        await runtime.refresh()
        await asyncio.sleep(0.05)
        assert runtime.soundpad_state()["state"] == "fallback"
        return runtime

    asyncio.run(scenario())


# ---- transport --------------------------------------------------------------------------------------


def test_pause_seek_jump_volume_mute(windows_cli):
    fake = FullSoundpad()

    async def scenario():
        runtime = await ready(fake)
        await runtime.play_sound({"index": 1})
        assert await runtime.control("pause") == ("ok", None)
        assert await runtime.control("pause") == ("ok", None)  # already paused: no second toggle
        assert fake.commands.count("DoTogglePause()") == 1 and fake.status == "PAUSED"
        assert await runtime.control("resume") == ("ok", None)
        assert fake.status == "PLAYING"
        await runtime.control("seek", 12000)
        await runtime.control("jump", -2000)
        assert fake.seeks == ["DoSeekMs(12000)", "DoJumpMs(-2000)"]
        assert await runtime.control("volume", 40) == ("ok", None)
        assert fake.volume == 40
        assert (await runtime.control("volume", 101))[0] == "error"
        await runtime.control("mute")
        await runtime.control("mute")
        assert fake.commands.count("DoToggleMute()") == 1 and fake.muted
        await runtime.control("unmute")
        assert not fake.muted
        state = runtime.state_for_directors()
        assert (state["volume"], state["muted"]) == (40, False)
        await runtime.close()

    asyncio.run(scenario())


def test_levels_and_list_changes_are_noticed(windows_cli, monkeypatch):
    monkeypatch.setattr(actor_runtime, "LEVELS_EVERY_S", 0.05)
    monkeypatch.setattr(actor_runtime, "POLL_IDLE_S", 0.05)
    fake = FullSoundpad()
    fake.volume, fake.muted = 55, True
    changed = []

    async def scenario():
        runtime = await ready(fake, on_list_changed=lambda: changed.append(1))
        await runtime.sound_list()
        await asyncio.sleep(0.2)
        assert (runtime.volume_level, runtime.is_muted) == (55, True)
        fake.sounds.append("new line")
        await asyncio.sleep(0.3)
        assert changed
        await runtime.close()

    asyncio.run(scenario())


def test_received_files_are_added_once(windows_cli, tmp_path):
    fake = FullSoundpad(sounds=["intro"])
    path = tmp_path / "Scene 1 - Coda.wav"
    path.write_bytes(b"x")

    async def scenario():
        runtime = await ready(fake)
        runtime.on_file_received(str(path))
        await asyncio.sleep(0.2)
        runtime.on_file_received(str(path))  # an updated file: same path, already listed
        await asyncio.sleep(0.2)
        assert sum(c.startswith("DoAddSound") for c in fake.commands) == 1
        runtime._config.soundpad.auto_add_received = False
        runtime.on_file_received(str(tmp_path / "another.wav"))
        await asyncio.sleep(0.1)
        assert sum(c.startswith("DoAddSound") for c in fake.commands) == 1
        await runtime.close()

    asyncio.run(scenario())


def test_auto_launch_starts_soundpad_once(windows_cli, monkeypatch):
    started = []
    monkeypatch.setattr(actor_runtime.subprocess, "Popen", lambda args, **kw: started.append(args))
    fake = FullSoundpad()
    fake.running = False
    cfg = actor_config()
    cfg.soundpad.auto_launch = True

    async def scenario():
        runtime = ActorRuntime(cfg, pipe_factory=lambda: SoundpadPipe(fake.connect))
        await runtime.refresh()
        await asyncio.sleep(0.1)
        runtime._maybe_launch()
        await runtime.close()

    asyncio.run(scenario())
    assert started == [[r"C:\Program Files\Soundpad\Soundpad.exe"]]


def test_a_cue_never_starts_soundpad(windows_cli, monkeypatch):
    """Only "Start Soundpad when it isn't running" starts it (laptop run, M2: a GO did, via -rc)."""
    started = []
    monkeypatch.setattr(actor_runtime.subprocess, "Popen", lambda args, **kw: started.append(args))
    fake = FullSoundpad()
    fake.running = False
    cfg = actor_config()

    async def scenario():
        runtime = ActorRuntime(cfg, pipe_factory=lambda: SoundpadPipe(fake.connect))
        await runtime.refresh()
        await asyncio.sleep(0.1)
        assert await runtime.run_cue("*go") == (False, "Soundpad isn't running")
        assert started == [] and windows_cli == []
        cfg.soundpad.auto_launch = True
        assert await runtime.run_cue("*go") == (False, "Soundpad isn't running; starting it now")
        assert await runtime.run_cue("*go") == (False, "Soundpad isn't running")  # once per run
        await runtime.close()

    asyncio.run(scenario())
    assert started == [[r"C:\Program Files\Soundpad\Soundpad.exe"]] and windows_cli == []


# ---- director ↔ actor through the relay -------------------------------------------------------------


def test_director_controls_an_actors_soundpad(relay, tmp_path, monkeypatch, windows_cli):  # noqa: F811
    from .test_relay_legacy import SECRET, make_agent, wait_for

    monkeypatch.setattr(actor_runtime, "LEVELS_EVERY_S", 0.2)
    monkeypatch.setattr(actor_runtime, "POLL_IDLE_S", 0.1)
    running, _ = relay
    url = f"127.0.0.1:{running.port}"
    fake = FullSoundpad(sounds=["intro", "scene 4 - diego", "outro"])

    async def scenario():
        director = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", url, SECRET)
        coda = make_agent(tmp_path, monkeypatch, "Coda", "actor", "m-coda", url)
        coda.actor._pipe_factory = lambda: SoundpadPipe(fake.connect)
        events = []
        director.hub.event = events.append
        try:
            await director.start()
            await coda.start()
            await wait_for(lambda: director.snapshot()["pending"])
            await director.handle_call("approve", {"id": director.snapshot()["pending"][0]["id"]})

            def coda_peer():
                return next((p for p in director.snapshot()["peers"] if p["name"] == "Coda"), None)

            await wait_for(lambda: coda_peer() and coda_peer()["soundpad"] and coda_peer()["soundpad"]["available"])
            peer = coda_peer()
            assert {"soundpad.list", "soundpad.lines", "files"} <= set(peer["caps"])
            ids = [peer["id"]]

            # The list: titles and keys, never paths
            await director.handle_call("requestSounds", {"id": peer["id"]})
            await wait_for(lambda: events)
            listed = events[-1]
            assert listed["peerId"] == peer["id"] and listed["total"] == 3
            assert [s["title"] for s in listed["sounds"]] == ["intro", "scene 4 - diego", "outro"]
            assert "C:\\\\Sounds" not in str(listed) and "url" not in str(listed) and all(set(s) == {"index", "key", "title", "durationMs"} for s in listed["sounds"])

            key = listed["sounds"][1]["key"]
            await director.handle_call("play", {"ids": ids, "sound": {"key": key}, "lines": "speakers", "label": "scene 4 - diego"})
            await wait_for(lambda: coda_peer()["soundpad"]["status"] == "PLAYING" and coda_peer()["soundpad"]["key"] == key)
            state = coda_peer()["soundpad"]
            assert (state["title"], state["lines"], state["index"]) == ("scene 4 - diego", "speakers", 2)
            assert fake.plays[-1] == "DoPlaySound(2, true, false)"
            assert coda_peer()["activity"] == "playing"  # the cast row and graph show it

            await director.handle_call("transport", {"ids": ids, "action": "volume", "value": 30})
            await wait_for(lambda: coda_peer()["soundpad"]["volume"] == 30)
            await director.handle_call("transport", {"ids": ids, "action": "pause"})
            await wait_for(lambda: coda_peer()["soundpad"]["status"] == "PAUSED")
            await director.handle_call("transport", {"ids": ids, "action": "seek", "value": 1500})
            await wait_for(lambda: "DoSeekMs(1500)" in fake.seeks)

            await director.handle_call("playIndex", {"ids": ids, "index": 3})
            await wait_for(lambda: fake.plays[-1] == "DoPlaySound(3)")

            # A refusal comes back as a warning on the director
            await director.handle_call("play", {"ids": ids, "sound": {"key": "0" * 16}})
            await wait_for(lambda: any("isn't in this actor's Soundpad" in e["text"] for e in director.hub._logs))

            await director.handle_call("transport", {"ids": ids, "action": "stop"})
            await wait_for(lambda: coda_peer()["soundpad"]["status"] == "STOPPED")
            assert coda_peer()["activity"] == "idle"

            # A sound added on the actor's side reaches the director's open list
            fake.sounds.append("new line")
            await wait_for(lambda: events[-1]["total"] == 4, timeout=5)

            with pytest.raises(Exception, match="Pick an actor"):
                await director.handle_call("play", {"ids": [], "sound": {"index": 1}})
        finally:
            await coda.shutdown()
            await director.shutdown()

    asyncio.run(scenario())


def test_repeated_controls_are_dropped(tmp_path, monkeypatch):
    """A held key or stuck input repeats the same control every ~35 ms (laptop run, M2): only the
    first one goes out until it stops for REPEAT_S."""
    from agent import core

    from .test_relay_legacy import make_agent

    agent = make_agent(tmp_path, monkeypatch, "Mira", "director", "m-mira", "127.0.0.1:9", "s")
    handled = []

    async def fake(args):
        handled.append(args)

    for name in ("play", "transport", "cue", "sendChat"):
        monkeypatch.setattr(agent, f"_call_{name}", fake)

    async def scenario():
        play = {"ids": ["s_1"], "sound": {"key": "ab" * 8}}
        for _ in range(10):
            await agent.handle_call("play", play)
            await asyncio.sleep(0.03)
        assert len(handled) == 1
        await agent.handle_call("play", {**play, "lines": "mic"})  # different: goes out
        await agent.handle_call("cue", {"command": "stop"})
        await agent.handle_call("cue", {"command": "stop"})
        assert len(handled) == 3
        await asyncio.sleep(core.REPEAT_S + 0.05)
        await agent.handle_call("cue", {"command": "stop"})
        await agent.handle_call("sendChat", {"text": "hi"})
        await agent.handle_call("sendChat", {"text": "hi"})  # not a control: never dropped
        assert len(handled) == 6

    asyncio.run(scenario())
