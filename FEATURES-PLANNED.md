# Planned Features

*Design specs for upcoming features. Each feature gets its own commit.*

---

## Version History

| Version | Status | Notes |
|---------|--------|-------|
| **v0.1.0** | Released | Initial release — basic WebSocket client, Soundpad integration |
| **v0.2.0** | Released | Selective triggering, file transfer, status indicators, VR-friendly buttons, Play in 3s |
| **v0.3.0** | Planned | Multiple directors, multi-file transfer, ping compensation |

---

## v0.3.0 Features (Planned)

### Feature 1: Multiple Director Support

**Goal:** Allow multiple directors with different names and permission levels.

### Server Changes
- Track director connections with names and roles
- Role types: "main" (full control), "assistant" (limited commands)
- Broadcast director list to all clients

### Director UI
- Director name field in config
- Show other directors in actor list area
- Warning when another director is connected (already implemented)

### Permissions
- Main director: full control (approve/deny actors, send commands, files)
- Assistant director: limited (send commands, chat - no approve/deny, no files)

---

### Feature 2: Send Multiple Files

**Goal:** Director can send multiple files to actor at once.

### UI Changes — Director
- Multi-select in file picker
- Queue transfers with overall progress
- Cancel all button

### UI Changes — Actor
- Receive multiple files sequentially
- Overall progress indicator
- Per-file completion checkmarks

### Protocol
Same FILESTART/FILECHUNK/FILEEND protocol, but:
- Director sends FILEREQ with multiple filenames
- Actor acknowledges all at once
- Sequential transfer of each file

---

### Feature 3: Ping Compensation / Delay

**Goal:** Director can set delay per actor to compensate for network latency.

### Server Changes
- Store delay per actor in config
- Apply delay before sending command to that actor
- Delay is in milliseconds

### Director UI
- Right-click actor → "Set delay"
- Input dialog: "Delay for ActorName (ms):"
- Show delay value next to actor name (optional)

### Actor Client
- No changes needed - delay is server-side
- Actor receives command after configured delay

---

## Future Ideas

Lower priority features that will be designed when moved to a release:

- **OpenVR/OpenXR overlay** — In-VR overlay for director and actor
- **TTS messages** — Text-to-speech to actors (plays through mic)
- **Web dashboard** — Browser-based server admin
- **Auto-add + play in Soundpad** — Add transferred file and trigger playback
- **Volume control** — Remote Soundpad volume adjustment
- **Soundboard overlay** — OBS browser source showing triggered sounds
- **Voice chat integration** — Discord/Slack bridge for audio cues
- **Mobile app** — Director control from phone/tablet
- **Cloud sync** — Share approved actors list across servers
- **Scene presets** — Save/load actor configurations per scene

---

## Completed Features (v0.1.0 - v0.2.0)

*Design specs retained for reference.*

### Selective Actor Triggering ✅

**Goal:** Director can choose which actors receive broadcast commands via checkboxes.

### UI Changes — Director Client

**Approved Actors List:**
- Each actor has a checkbox (styled as speaker icon: 🔊/🔇)
- 🔊 checked = receives broadcast commands (`*go`, `*stop`, `*play:N`, `*ready?`)
- 🔇 unchecked = ignored for broadcasts

**Selection vs. Checkbox:**
- Single-click = selects actor (for targeted actions like Send File)
- Checkbox = toggle whether they receive broadcasts
- These are independent — an actor can be unchecked but still selected

**Buttons under actor list:**
- `[All]` — check all actors
- `[None]` — uncheck all actors
- `[Invert]` — flip all checkboxes
- `[Send File...]` — only enabled when one actor is selected

---

### File Transfer ✅

**Goal:** Director can send files to a selected actor. Actor can accept/decline or auto-accept.

### UI Changes — Director Client

**Send File button:**
- Under actor list
- Only enabled when exactly one actor is selected
- Opens file picker (single file for now, multi-file later)

**During transfer:**
- Progress dialog with file name, percent complete, cancel button
- Log in chat area: "Sending sound_effect.mp3 to Alice..."

### UI Changes — Actor Client

**Config additions:**
- `receive_dir` — directory for incoming files (prompt on first run if unset)
- `auto_accept_files` — bool, skip confirmation dialog

**File Request Dialog:**
```
┌─────────────────────────────────────┐
│  Incoming File                      │
│                                     │
│  Director wants to send:            │
│    sound_effect.mp3 (2.3 MB)        │
│                                     │
│  Save to: ~/Documents/vrActorFiles  │
│                                     │
│  [ ] Auto-accept future files       │
│                                     │
│    [Accept]       [Decline]          │
└─────────────────────────────────────┘
```

### Protocol

Base64-encoded chunks over WebSocket:

```
# Director → Server → Actor
FILEREQ|sender|filename|size_bytes|checksum_md5

# Actor → Server → Director
FILEACK|filename|accept|save_dir
FILEDENY|filename|reason

# Transfer (chunked, base64)
FILESTART|filename|total_chunks|chunk_size
FILECHUNK|filename|chunk_num|base64_data
FILEEND|filename|checksum_md5

# Confirmation
FILEOK|filename|saved_path
FILEERR|filename|error_message
```

**Chunk size:** 64KB (good balance of progress updates and overhead)

---

### Actor Status Indicators ✅

**Goal:** Show connection quality per actor with colored dot + latency on hover.

### Server-Side Tracking

- WebSocket sends ping every 30s (keepalive)
- Server tracks RTT per actor: `last_ping_sent` → `pong_received`
- Store in actor metadata: `{"name": "Alice", "latency_ms": 85, "last_seen": timestamp}`

### Protocol Addition

Server broadcasts status to director periodically (every 10s or on significant change):

```
STATUS|actors=[{"name":"Alice","latency_ms":85},{"name":"Bob","latency_ms":150}]
```

### Director UI

**Color thresholds:**
- 🟢 Green: < 100ms (good)
- 🟡 Yellow: 100-300ms (acceptable)
- 🔴 Red: > 300ms (poor)
- ⚪ Gray: No response in 60s (missed 2+ pings)

---

### Multi-Director Warning ✅

**Goal:** Warn if another director is already connected.

### Server Changes

On director registration, check for existing directors:

```python
if role == "director":
    existing = get_directors()
    if existing:
        await websocket.send_text(format_message("MSG", sender="SERVER",
            text=f"Warning: {existing[0].name} is already connected"))
```

### Behavior

- Second director connects → gets warning message
- Both directors have full control (no restrictions)
- Warning is informational only

---

### "Play in 3s" Countdown Button ✅

**Goal:** New button that sends Go command after 3-second countdown.

### UI — Director Client

**New button alongside Go:**
```
[▶ Go]  [⏱ Play in 3s]  [■ Stop]
```

**Countdown behavior:**
- Click → button shows `[3...]` → `[2...]` → `[1...]` → sends `*go`
- Button disabled during countdown
- Stop button cancels countdown (resets button)
- Actor receives nothing until countdown completes

---

### Bigger Buttons for VR ✅

**Goal:** Buttons 3x current size for easier VR clicking via desktop overlay.

### UI Changes

**Button sizing:**
- Height: `height=3` (lines)
- Width: `width=20` (characters)
- Font: `font=('Arial', 14, 'bold')`
- Padding: `pady=10` between buttons

**Affected buttons:**
- Go / Play in 3s / Stop
- Approve / Deny
- All action buttons in both clients

---

### Configurable Soundpad Path ✅

**Goal:** Allow actors to set custom Soundpad.exe location.

### Implementation

Priority order:
1. Config file setting (via GUI)
2. `SOUNDPAD_PATH` environment variable
3. Auto-detection search (Program Files, Steam, etc.)

### UI — Actor Client

Config dialog has "Soundpad Path (optional)" field with Browse button.

---

### Duplicate Actor Fix ✅

**Goal:** Prevent actors from appearing twice when reconnecting.

### Problem

When an actor reconnects quickly, the old connection hadn't fully cleaned up, causing duplicates in the director's actor list.

### Solution

On actor registration, check for existing connection with same `machine_id` and role "actor", then disconnect the old connection before approving the new one.