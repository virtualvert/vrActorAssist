"""What a director's GO sends on a v2 relay (spec §8.2.2, Phase 2 M3).

One server time `at` for everyone, so all actors start together:
- an actor with an armed sound gets `soundpad.play {sound, lines}` (v0.4 apps with the sound
  list) or `cue.play {index}` (v0.3 apps and older builds can only be armed by number);
- every other actor gets `cue.go` (Soundpad's selected sound);
- actors that announce `schedule`, and v0.3 actors (the relay holds those, §11.3), get `at`;
- older v0.4 builds without `schedule` would play an `at` cue at once, so the director's agent
  holds their message and sends it without `at` when it's due: at + their delay − the trip there.

Pure functions; agent/relay_v2.py sends what plan_go() returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class Actor(Protocol):
    id: str
    name: str
    legacy: bool
    capabilities: list[str]
    delay_ms: int
    latency_ms: int | None


@dataclass
class Send:
    type: str
    data: dict[str, Any]
    ids: list[str]
    names: list[str]
    # Director-held (an older build): send at this server time, without `at`
    hold_until: float | None = None


@dataclass
class Plan:
    sends: list[Send] = field(default_factory=list)
    # Actors whose armed sound their app can't play: they get GO instead
    fallbacks: list[str] = field(default_factory=list)


def reach(actor: Actor) -> str:
    """full: the whole Soundpad addon; legacy: the v0.3 app; old: a v0.4 build before M2."""
    if actor.legacy:
        return "legacy"
    return "full" if "soundpad.list" in actor.capabilities else "old"


def schedules(actor: Actor) -> bool:
    """Whether an `at` cue to this actor starts on time (v0.3: the relay holds it)."""
    return actor.legacy or "schedule" in actor.capabilities


def armable(actor: Actor, sound: dict, lines: str | None) -> str | None:
    """Why this sound can't be armed on this actor, or None."""
    if reach(actor) == "full":
        return None
    if set(sound) != {"index"} or lines not in (None, "both"):
        app = "the v0.3 app" if actor.legacy else "an older vrcActorSync build"
        return f"{actor.name} uses {app}: arm a sound by its number"
    return None


def action(actor: Actor, armed: dict | None) -> tuple[str, dict[str, Any], bool]:
    """(type, data, fell back) for one actor."""
    if armed:
        sound, lines = armed.get("sound") or {}, armed.get("lines")
        if reach(actor) == "full":
            data: dict[str, Any] = {"sound": sound}
            if lines:
                data["lines"] = lines
            return "soundpad.play", data, False
        if armable(actor, sound, lines) is None:
            return "cue.play", {"index": sound["index"]}, False
        return "cue.go", {}, True
    return "cue.go", {}, False


def plan_go(actors: list[Actor], armed: dict[str, dict], at: int | None, own_rtt_ms: float | None = None) -> Plan:
    """The messages for one GO. `at` None: everything at once (no lead, or no clock yet)."""
    plan = Plan()
    merged: dict[tuple, Send] = {}
    for actor in actors:
        msg_type, data, fell_back = action(actor, armed.get(actor.id))
        if fell_back:
            plan.fallbacks.append(actor.name)
        hold = None
        if at is not None:
            if schedules(actor):
                data = {**data, "at": at}
            else:
                trip = ((own_rtt_ms or 0) + (actor.latency_ms or 0)) / 2
                hold = at + actor.delay_ms - trip
        key = (msg_type, repr(sorted(data.items())), hold)
        if key in merged:
            merged[key].ids.append(actor.id)
            merged[key].names.append(actor.name)
        else:
            merged[key] = Send(msg_type, data, [actor.id], [actor.name], hold)
    plan.sends = list(merged.values())
    return plan


def describe(armed: dict | None) -> str:
    """How the log names an actor's part of a GO."""
    if not armed:
        return "GO"
    lines = armed.get("lines")
    return f"{armed.get('label') or 'armed sound'}" + (f" ({lines})" if lines else "")
