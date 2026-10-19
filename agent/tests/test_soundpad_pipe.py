"""Soundpad pipe client and the actor runtime on top of it, against an in-memory Soundpad.

The fake answers like Soundpad 4.0.35 did in tools/soundpad_probe.py runs: PLAYING right after a
play command, position 0 for ~180 ms and then in ~140 ms steps, stale numbers after a stop,
DoAddSound listing the sound a moment after its R-200.
"""

import asyncio
import re
import time

import pytest

import soundpad
from agent import actor_runtime
from agent.actor_runtime import ActorRuntime, parse_cue
from agent.config import Config
from agent.soundpad_pipe import (
    NotSent,
    SoundpadError,
    SoundpadPipe,
    SoundpadTimeout,
    SoundpadUnavailable,
    answer_complete,
    parse_categories,
    parse_duration,
    parse_soundlist,
)

AUDIO_START_S = 0.060   # audio begins this long after the play command
FIRST_UPDATE_S = 0.180  # the position stays 0 until then
STEP_S = 0.140          # then it moves in steps this far apart


class FakeSoundpad:
    def __init__(self, sounds=("intro", "scene 4 - diego", "outro"), trial=False):
        self.sounds = list(sounds)
        self.trial = trial
        self.running = True
        self.status = "STOPPED"
        self.started_at = 0.0
        self.stale_position = 3127
        self.duration = 3096
        self.volume = 32
        self.commands: list[str] = []
        self.sent_times: list[float] = []
        self.connects = 0
        self.hang: set[str] = set()
        self.seeking_polls = 0
        self.pending_add: str | None = None
        self.transports: list["FakeTransport"] = []

    def connect(self):
        if not self.running:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        self.connects += 1
        transport = FakeTransport(self)
        self.transports.append(transport)
        return transport

    def position(self) -> int:
        if self.status not in ("PLAYING", "PAUSED", "SEEKING"):
            return self.stale_position
        elapsed = time.perf_counter() - self.started_at
        if elapsed < FIRST_UPDATE_S:
            return 0
        update = FIRST_UPDATE_S + int((elapsed - FIRST_UPDATE_S) / STEP_S) * STEP_S
        return round((update - AUDIO_START_S) * 1000)

    def _play(self):
        self.status = "PLAYING"
        self.started_at = time.perf_counter()
        return "R-200"

    def answer(self, command: str) -> str:
        if self.pending_add and not command.startswith("DoAddSound"):
            # Soundpad lists an added sound shortly after answering R-200
            self.sounds.append(self.pending_add)
            self.pending_add = None
        if command == "IsAlive()":
            return "R-200"
        if command == "GetVersion()":
            return "4.0.35"
        if command == "GetRemoteControlVersion()":
            return "1.1.2"
        if command == "IsTrial()":
            return "1" if self.trial else "0"
        if command == "DoPlaySelectedSound()":
            return self._play()
        if match := re.fullmatch(r"DoPlaySound\((\d+)(?:, (true|false), (true|false))?\)", command):
            return self._play() if 1 <= int(match.group(1)) <= len(self.sounds) else "R-404"
        if command == "DoStopSound()":
            self.status = "STOPPED"
            return "R-200"
        if command == "GetPlayStatus()":
            if self.seeking_polls:
                self.seeking_polls -= 1
                return "SEEKING"
            return self.status
        if command == "GetPlaybackPositionInMs()":
            return str(self.position())
        if command == "GetPlaybackDurationInMs()":
            return str(self.duration)
        if command == "GetVolume()":
            return str(self.volume)
        if match := re.fullmatch(r"SetVolume\((\d+)\)", command):
            self.volume = int(match.group(1))
            return "R-200"
        if command == "GetSoundFileCount()":
            return str(len(self.sounds))
        if match := re.fullmatch(r"GetSoundlist\((?:(\d+)(?:, (\d+))?)?\)", command):
            first = int(match.group(1) or 1)
            last = int(match.group(2) or len(self.sounds))
            rows = "".join(
                f'  <Sound index="{i}" url="C:\\Sounds\\{title}.mp3" artist="" title="{title}" duration="0:47" '
                f'addedOn="2026-10-19" lastPlayedOn="" playCount="0" tag="{title}"/>\n'
                for i, title in enumerate(self.sounds, start=1)
                if first <= i <= last
            )
            return f'<?xml version="1.0" encoding="UTF-8"?>\n<Soundlist>\n{rows}</Soundlist>'
        if command == "GetCategories(false, false)":
            return ('<?xml version="1.0" encoding="UTF-8"?>\n<Categories>\n'
                    '  <Category index="1" type="1" name="All sounds" hidden="true"/>\n'
                    '  <Category index="2" name="My Sounds"/>\n</Categories>')
        if match := re.fullmatch(r'DoAddSound\("(.+)"\)', command):
            self.pending_add = match.group(1).rsplit("\\", 1)[-1].rsplit(".", 1)[0]
            return "R-200"
        return "R-400"


class FakeTransport:
    def __init__(self, soundpad: FakeSoundpad):
        self.soundpad = soundpad
        self.closed = False

    def request(self, command: str, timeout: float) -> str:
        sp = self.soundpad
        if self.closed or not sp.running:
            raise NotSent("pipe closed")
        sp.commands.append(command)
        sp.sent_times.append(time.perf_counter())
        if command in sp.hang:
            raise TimeoutError(f"no answer to {command}")
        return sp.answer(command)

    def close(self) -> None:
        self.closed = True


def make_pipe(fake: FakeSoundpad, **kwargs) -> SoundpadPipe:
    pipe = SoundpadPipe(fake.connect, **kwargs)
    pipe.start()
    return pipe


def actor_config() -> Config:
    cfg = Config()
    cfg.role = "actor"
    return cfg


# ---- parsing -----------------------------------------------------------------


def test_answer_complete():
    assert answer_complete(b"R-200")
    assert answer_complete(b"4.0.35")
    assert not answer_complete(b"")
    assert not answer_complete(b'<?xml version="1.0"?>\n<Soundl')
    assert not answer_complete(b'<?xml version="1.0"?>\n<Soundlist>\n  <Sound index="1"/>\n')
    assert answer_complete(b'<?xml version="1.0"?>\n<Soundlist>\n  <Sound index="1"/>\n</Soundlist>\r\n')
    assert answer_complete(b'<?xml version="1.0"?>\n<Soundlist/>')


def test_parse_soundlist_uses_the_probed_attributes():
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<Soundlist>\n'
           '  <Sound index="5" url="C:\\Music\\Thunder.wav" artist="" title="Thunder" duration="0:50" '
           'addedOn="2026-10-19" lastPlayedOn="" playCount="0" tag="Thunder"/>\n'
           '  <Sound index="6" url="C:\\EP3\\Scene 2 - Line 1.mp3" artist="A" title="Scene 2 - Line 1" duration="1:02:03" '
           'addedOn="2026-10-19" lastPlayedOn="2026-10-19" playCount="6" tag="x"/>\n</Soundlist>')
    first, second = parse_soundlist(xml)
    assert (first.index, first.url, first.title, first.duration_s, first.play_count) == (5, "C:\\Music\\Thunder.wav", "Thunder", 50, 0)
    assert (second.index, second.duration_s, second.play_count, second.artist) == (6, 3723, 6, "A")
    assert parse_duration("") is None


def test_parse_categories():
    xml = ('<Categories><Category index="1" type="1" name="All sounds" hidden="true"/>'
           '<Category index="2" name="My Sounds"/></Categories>')
    all_sounds, mine = parse_categories(xml)
    assert all_sounds.hidden and all_sounds.name == "All sounds"
    assert not mine.hidden and mine.index == 2


def test_parse_cue():
    assert parse_cue("*go") == ("go", None)
    assert parse_cue("STOP") == ("stop", None)
    assert parse_cue("*play:12") == ("play", 12)
    assert parse_cue("*play:0") is None
    assert parse_cue("*play:x") is None
    assert parse_cue("*volume") is None


# ---- client --------------------------------------------------------------------


def test_handshake_and_requests_are_spaced():
    fake = FakeSoundpad()
    pipe = make_pipe(fake)
    try:
        for _ in range(10):
            assert pipe.call("IsAlive()").text == "R-200"
        assert pipe.connected
        assert pipe.info.version == "4.0.35" and pipe.info.rc_version == "1.1.2"
        assert pipe.info.trial is False and pipe.info.rc_supported
        assert fake.commands[:4] == ["IsAlive()", "GetVersion()", "GetRemoteControlVersion()", "IsTrial()"]
        gaps = [b - a for a, b in zip(fake.sent_times, fake.sent_times[1:])]
        assert min(gaps) >= 0.0019
    finally:
        pipe.close()


def test_requests_from_many_threads_run_one_at_a_time():
    fake = FakeSoundpad()
    pipe = make_pipe(fake, min_gap=0)
    try:
        async def burst():
            return await asyncio.gather(*(pipe.acall("GetVolume()") for _ in range(20)))

        replies = asyncio.run(burst())
        assert {r.text for r in replies} == {"32"}
        assert fake.commands.count("GetVolume()") == 20
    finally:
        pipe.close()


def test_timeout_drops_the_pipe_and_reconnects_once_right_away():
    fake = FakeSoundpad()
    pipe = make_pipe(fake)
    try:
        pipe.call("IsAlive()")
        fake.hang.add("GetVolume()")
        with pytest.raises(SoundpadTimeout):
            pipe.call("GetVolume()")
        assert not pipe.connected and fake.transports[0].closed
        assert "isn't responding" in pipe.last_error
        fake.hang.clear()
        assert pipe.call("GetVolume()").text == "32"
        assert fake.connects == 2
    finally:
        pipe.close()


def test_backoff_while_soundpad_is_closed():
    fake = FakeSoundpad()
    fake.running = False
    pipe = make_pipe(fake, backoff_start=0.2, backoff_max=1.0)
    try:
        with pytest.raises(SoundpadUnavailable, match="isn't running"):
            pipe.call("IsAlive()")
        # Inside the backoff window nothing is tried
        with pytest.raises(SoundpadUnavailable):
            pipe.call("IsAlive()")
        fake.running = True
        assert fake.connects == 0
        time.sleep(0.25)
        assert pipe.call("IsAlive()").text == "R-200"
        assert fake.connects == 1
    finally:
        pipe.close()


def test_stale_handle_after_a_soundpad_restart_reconnects_and_resends():
    fake = FakeSoundpad()
    pipe = make_pipe(fake)
    try:
        pipe.call("IsAlive()")
        fake.transports[0].closed = True  # Soundpad restarted; our handle is dead
        assert pipe.call("GetVolume()").text == "32"
        assert fake.connects == 2
    finally:
        pipe.close()


def test_typed_helpers():
    fake = FakeSoundpad()
    pipe = make_pipe(fake, min_gap=0)

    async def scenario():
        stopped = await pipe.playback()
        assert (stopped.status, stopped.position_ms, stopped.duration_ms) == ("STOPPED", 0, 0)  # not the stale 3127
        with pytest.raises(SoundpadError, match="R-404"):
            await pipe.play(9)
        await pipe.play(2, render=True, capture=False)
        assert fake.commands[-1] == "DoPlaySound(2, true, false)"
        await pipe.play(2)
        assert fake.commands[-1] == "DoPlaySound(2)"
        assert [s.title for s in await pipe.sounds(2, 3)] == ["scene 4 - diego", "outro"]
        assert [c.name for c in await pipe.categories()] == ["All sounds", "My Sounds"]
        fake.seeking_polls = 3
        await pipe.stop()
        assert fake.commands[-5:] == ["GetPlayStatus()"] * 4 + ["DoStopSound()"]
        await pipe.set_volume(40)
        assert await pipe.volume() == 40
        with pytest.raises(ValueError):
            await pipe.set_volume(0.5)
        assert await pipe.add_sound("C:\\EP3\\EP3 Scene 4 - Diego.mp3") == 4
        assert fake.sounds[-1] == "EP3 Scene 4 - Diego"

    try:
        asyncio.run(scenario())
    finally:
        pipe.close()


def test_trial_refuses_to_add():
    fake = FakeSoundpad(trial=True)
    pipe = make_pipe(fake)

    async def scenario():
        await pipe.acall("IsAlive()")
        with pytest.raises(SoundpadError, match="trial"):
            await pipe.add_sound("C:\\x.mp3")

    try:
        asyncio.run(scenario())
    finally:
        pipe.close()


# ---- actor runtime -------------------------------------------------------------


@pytest.fixture
def windows_cli(monkeypatch):
    """Pretend to be on Windows with Soundpad.exe found, and record -rc calls."""
    calls = []
    monkeypatch.setattr(soundpad, "is_windows", lambda: True)
    monkeypatch.setattr(soundpad, "get_soundpad_path", lambda: r"C:\Program Files\Soundpad\Soundpad.exe")
    monkeypatch.setattr(soundpad, "execute_command", lambda command, args="": calls.append(command) or (True, None))
    return calls


def test_cues_go_through_the_pipe(windows_cli):
    fake = FakeSoundpad()
    logs = []
    runtime = ActorRuntime(actor_config(), log=lambda level, text: logs.append((level, text)),
                           pipe_factory=lambda: SoundpadPipe(fake.connect))

    async def scenario():
        await runtime.refresh()
        await asyncio.sleep(0.05)
        state = runtime.soundpad_state()
        assert state["state"] == "ready"
        assert state["info"] == {"version": "4.0.35", "rcVersion": "1.1.2", "trial": False}
        assert runtime.live_status == "STOPPED"

        assert await runtime.run_cue("*go") == (True, None)
        assert "DoPlaySelectedSound()" in fake.commands
        await asyncio.sleep(0.6)  # the start measurement needs a few position steps
        assert runtime.live_status == "PLAYING"
        assert runtime.soundpad_state()["playback"]["positionMs"] > 0

        assert await runtime.run_cue("*play:2") == (True, None)
        assert fake.commands.count("DoPlaySound(2)") == 1
        await asyncio.sleep(0.6)
        assert runtime.soundpad_state()["playback"]["title"] == "scene 4 - diego"

        ok, error = await runtime.run_cue("*play:9")
        assert not ok and "R-404" in error

        assert await runtime.run_cue("*stop") == (True, None)
        assert runtime.live_status == "STOPPED"
        assert runtime.soundpad_state()["playback"] == {"status": "STOPPED", "positionMs": 0, "durationMs": 0, "title": None}
        await runtime.close()

    asyncio.run(scenario())
    assert windows_cli == []  # never fell back to -rc
    assert any("Soundpad 4.0.35 connected" in text for _, text in logs)


def test_start_latency_is_read_off_position_steps(windows_cli, monkeypatch):
    monkeypatch.setattr(actor_runtime, "POLL_IDLE_S", 5.0)  # keep the poller out of the way
    fake = FakeSoundpad()
    logs = []
    runtime = ActorRuntime(actor_config(), log=lambda level, text: logs.append(text),
                           pipe_factory=lambda: SoundpadPipe(fake.connect))

    async def scenario():
        await runtime.refresh()
        await runtime.run_cue("*go")
        await runtime._measure_task
        await runtime.close()

    asyncio.run(scenario())
    # Audio starts 60 ms after the command; polling adds a few ms. Loose bounds for slow CI.
    assert 55 <= runtime.start_latency_ms <= 120, runtime.start_latency_ms
    assert any(text.startswith("Soundpad start: PLAYING after") for text in logs)


def test_falls_back_to_the_command_line_only_when_nothing_was_sent(windows_cli):
    fake = FakeSoundpad()
    fake.running = False
    runtime = ActorRuntime(actor_config(), pipe_factory=lambda: SoundpadPipe(fake.connect))

    async def scenario():
        await runtime.refresh()
        await asyncio.sleep(0.05)
        state = runtime.soundpad_state()
        assert state["state"] == "fallback" and "-rc" in state["detail"]
        assert await runtime.run_cue("*go") == (True, None)
        assert windows_cli == ["*go"]

        # Connected, but Soundpad hangs: the command may have run, so no second try via -rc
        fake.running = True
        await asyncio.sleep(0.6)  # past the backoff
        fake.hang.add("DoStopSound()")
        ok, error = await runtime.run_cue("*stop")
        assert not ok and "isn't responding" in error
        assert windows_cli == ["*go"]
        await runtime.close()

    asyncio.run(scenario())


def test_pipe_is_only_opened_for_actors_with_soundpad_on(windows_cli):
    fake = FakeSoundpad()
    cfg = actor_config()
    cfg.role = "director"
    runtime = ActorRuntime(cfg, pipe_factory=lambda: SoundpadPipe(fake.connect))

    async def scenario():
        await runtime.refresh()
        assert runtime._pipe is None
        cfg.role = "actor"
        await runtime.refresh()
        assert runtime._pipe is not None
        cfg.soundpad.enabled = False
        await runtime.refresh()
        assert runtime._pipe is None
        assert runtime.soundpad_state()["state"] == "disabled"

    asyncio.run(scenario())
