"""Who may send what (spec §5.5), as data. Applied to /v2/ws and to v0.3 traffic on /ws.

Columns are the role of the sender. A pattern ending in `.*` covers a whole namespace; an exact
type wins over a pattern. Types missing here are rejected (`unknown_type` on v2): a new addon
needs its rows added, nothing else.
"""

from __future__ import annotations

DIRECTOR = "director"
ASSISTANT = "assistant"
ACTOR = "actor"
CAMERA = "camera"
EVERYONE = frozenset({DIRECTOR, ASSISTANT, ACTOR, CAMERA})
DIRECTION = frozenset({DIRECTOR, ASSISTANT})
NOBODY: frozenset[str] = frozenset()

# (message types, roles that may send them). Rows in §5.5 order, then the ones §5.5 leaves out.
ROWS: list[tuple[tuple[str, ...], frozenset[str]]] = [
    (("chat.msg", "chat.priv"), EVERYONE),
    (("cue.go", "cue.stop", "cue.play",
      "soundpad.play", "soundpad.stop", "soundpad.pause", "soundpad.seek", "soundpad.jump",
      "soundpad.volume", "soundpad.mute", "soundpad.list.request", "soundpad.calibrate"), DIRECTION),
    (("cue.ack", "soundpad.ack", "soundpad.list", "soundpad.state"), frozenset({ACTOR})),
    (("approval.approve", "approval.deny", "approval.forget", "actor.settings"), frozenset({DIRECTOR})),
    # "file.offer + chunks": the sending side of a transfer, including its end and batches
    (("file.offer", "file.end", "file.batch.start", "file.batch.end", "file.batch.cancel"), frozenset({DIRECTOR})),
    (("file.accept", "file.deny", "file.ok", "file.err", "file.progress"), frozenset({ACTOR, CAMERA})),
    (("file.inventory.request",), DIRECTION),
    (("file.inventory",), frozenset({ACTOR, CAMERA})),
    (("stage.state", "ready.request", "ready.ping"), DIRECTION),
    (("ready.status",), frozenset({ACTOR, CAMERA})),
    (("osc.param", "osc.cue.load"), DIRECTION),
    (("osc.cue.ack", "osc.cue.fired", "osc.params"), frozenset({ACTOR})),
    (("cuelist.save", "cuelist.delete"), DIRECTION),
    (("cuelist.get", "cuelist.list"), frozenset({DIRECTOR, ASSISTANT, ACTOR})),
    (("obs.profile.apply", "obs.profile.release", "obs.record.start", "obs.record.stop", "obs.mark", "obs.slate"),
     DIRECTION),
    (("obs.profile.status", "obs.record.state", "obs.status"), frozenset({CAMERA})),
    (("rtc.*",), frozenset({DIRECTOR, ASSISTANT, CAMERA})),
    # Not in §5.5: the handshake and clock sync, addressed to the relay itself
    (("hello", "time.ping", "time.pong"), EVERYONE),
    # Only the relay sends these
    (("welcome", "denied", "error", "presence.roster", "presence.latency", "approval.pending",
      "approval.forgotten", "update.available"), NOBODY),
]

TABLE: dict[str, frozenset[str]] = {}
for _types, _roles in ROWS:
    for _type in _types:
        assert _type not in TABLE, f"{_type} is listed twice"
        TABLE[_type] = _roles


def rule(msg_type: str) -> frozenset[str] | None:
    """The roles allowed to send msg_type, or None if the type isn't known at all."""
    if msg_type in TABLE:
        return TABLE[msg_type]
    parts = msg_type.split(".")
    for i in range(len(parts) - 1, 0, -1):
        roles = TABLE.get(".".join(parts[:i]) + ".*")
        if roles is not None:
            return roles
    return None


def allowed(role: str, msg_type: str) -> bool:
    roles = rule(msg_type)
    return roles is not None and role in roles


# ---- v0.3 pipe protocol ------------------------------------------------------------------------

# What each v0.3 message means in v2 terms (spec §11.2), for the permission check. REGISTER,
# PONG and REFRESH are part of the connection itself and aren't checked.
LEGACY_TYPES = {
    "MSG": "chat.msg",
    "CMD": "cue.go",
    "ACK": "cue.ack",
    "OSC_CUE": "osc.param",
    "FILEREQ": "file.offer",
    "FILESTART": "file.offer",
    "FILECHUNK": "file.offer",
    "FILEEND": "file.end",
    "BATCH_START": "file.batch.start",
    "BATCH_END": "file.batch.end",
    "BATCH_CANCEL": "file.batch.cancel",
    "FILEACK": "file.accept",
    "FILEDENY": "file.deny",
    "FILEOK": "file.ok",
    "FILEERR": "file.err",
    "APPROVE": "approval.approve",
    "DENY": "approval.deny",
    "FORGET_NAME": "approval.forget",
}

# The v0.3 relay answered these from a non-director with "Permission denied: only the director
# can send X"; v0.3 clients keep getting exactly that. Anything else rejected on /ws is dropped
# silently, as the v0.3 relay did for APPROVE / DENY / FORGET_NAME.
LEGACY_NOTICE_TYPES = {
    "CMD", "OSC_CUE", "PRIV",
    "FILEREQ", "FILESTART", "FILECHUNK", "FILEEND",
    "BATCH_START", "BATCH_END", "BATCH_CANCEL",
}


def is_cue_text(text: str) -> bool:
    """A v0.3 actor runs any private message starting with '*' as a command."""
    return text.lstrip().startswith("*")


def legacy_type(msg_type: str, msg_data: dict) -> str | None:
    """The v2 type a v0.3 message is checked as, or None for connection housekeeping."""
    if msg_type == "PRIV":
        return "cue.go" if is_cue_text(msg_data.get("text", "")) else "chat.priv"
    return LEGACY_TYPES.get(msg_type)


def legacy_role(registered_role: str) -> str:
    """v0.3 clients register as 'director' (checked against the secret) or 'actor'. Anything
    else gets an actor's rights, except 'camera' (sent by the v0.4 preview in compatibility mode)."""
    return registered_role if registered_role in (DIRECTOR, CAMERA) else ACTOR
