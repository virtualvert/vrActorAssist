"""The director's GO plan (agent/cues.py): armed sounds, one `at`, actors held for older builds."""

from dataclasses import dataclass, field

from agent.cues import armable, plan_go

CURRENT = ["soundpad", "soundpad.lines", "soundpad.position", "soundpad.list", "soundpad.add", "osc", "files", "schedule"]
M2 = [c for c in CURRENT if c != "schedule"]
AT = 1_800_000_000_300


@dataclass
class A:
    id: str
    name: str
    legacy: bool = False
    capabilities: list[str] = field(default_factory=lambda: list(CURRENT))
    delay_ms: int = 0
    latency_ms: int | None = 40


def by_type(plan):
    return {(s.type, tuple(s.ids)): s for s in plan.sends}


def test_two_armed_and_one_plain_share_one_at():
    nova, vega, coda = A("s_nova", "Nova"), A("s_vega", "Vega"), A("s_coda", "Coda")
    armed = {
        "s_nova": {"sound": {"key": "0123456789abcdef"}, "label": "Scene 4 - Nova", "lines": "speakers"},
        "s_vega": {"sound": {"sha256": "ab" * 32}, "label": "Sent: Scene 4 - Vega.wav", "lines": None},
    }
    plan = plan_go([nova, vega, coda], armed, AT)
    sends = by_type(plan)
    assert set(sends) == {("soundpad.play", ("s_nova",)), ("soundpad.play", ("s_vega",)), ("cue.go", ("s_coda",))}
    assert sends[("soundpad.play", ("s_nova",))].data == {"sound": {"key": "0123456789abcdef"}, "lines": "speakers", "at": AT}
    assert sends[("soundpad.play", ("s_vega",))].data == {"sound": {"sha256": "ab" * 32}, "at": AT}
    assert sends[("cue.go", ("s_coda",))].data == {"at": AT}
    assert all(s.hold_until is None for s in plan.sends) and plan.fallbacks == []


def test_plain_actors_get_one_message():
    plan = plan_go([A("s_1", "One"), A("s_2", "Two")], {}, AT)
    assert [(s.type, s.ids, s.data) for s in plan.sends] == [("cue.go", ["s_1", "s_2"], {"at": AT})]


def test_a_v03_actor_armed_by_number():
    lex = A("s_lex", "Lex", legacy=True, capabilities=["legacy"])
    assert armable(lex, {"index": 3}, None) is None
    assert "by its number" in armable(lex, {"key": "0123456789abcdef"}, None)
    assert "by its number" in armable(lex, {"index": 3}, "speakers")
    plan = plan_go([lex], {"s_lex": {"sound": {"index": 3}, "label": "Sound 3", "lines": None}}, AT)
    assert [(s.type, s.data) for s in plan.sends] == [("cue.play", {"index": 3, "at": AT})]
    # A sound it can't play (it reconnected with the v0.3 app): plain GO, and the director is told
    plan = plan_go([lex], {"s_lex": {"sound": {"key": "0123456789abcdef"}, "label": "x", "lines": None}}, AT)
    assert [(s.type, s.data) for s in plan.sends] == [("cue.go", {"at": AT})] and plan.fallbacks == ["Lex"]


def test_older_builds_are_held_by_the_director():
    old = A("s_old", "Old", capabilities=M2, delay_ms=150, latency_ms=80)
    plan = plan_go([old, A("s_new", "New")], {"s_old": {"sound": {"key": "0123456789abcdef"}, "label": "x", "lines": None}}, AT, own_rtt_ms=20)
    held = next(s for s in plan.sends if s.ids == ["s_old"])
    # No `at` (it would play at once), sent at at + its delay − the trip there (20/2 + 80/2)
    assert held.type == "soundpad.play" and "at" not in held.data
    assert held.hold_until == AT + 150 - 50
    assert next(s for s in plan.sends if s.ids == ["s_new"]).data == {"at": AT}


def test_without_at_everything_goes_now():
    old = A("s_old", "Old", capabilities=M2)
    plan = plan_go([old, A("s_new", "New")], {}, None)
    assert [(s.type, s.ids, s.data, s.hold_until) for s in plan.sends] == [("cue.go", ["s_old", "s_new"], {}, None)]
