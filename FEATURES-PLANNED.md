# Planned Features

*Design specs for upcoming features. Each feature gets its own commit.*

---

## Version History

| Version | Status | Notes |
|---------|--------|-------|
| **v0.1.0** | Released | Initial release — basic WebSocket client, Soundpad integration |
| **v0.2.0** | Released | Selective triggering, file transfer, status indicators, VR-friendly buttons |
| **v0.3.0** | Planned | "Play in 3s" countdown |

---

## v0.2.0 Scope ✅ Complete

Features released in v0.2.0:
- [x] Selective actor triggering (checkboxes)
- [x] File transfer (director → actor)
- [x] Actor status indicators (ping + hover)
- [x] Multi-director warning
- [x] Bigger buttons for VR (3x size)
- [x] Configurable Soundpad path
- [x] Fix duplicate actors on reconnect

---

## v0.3.0 Scope

Features planned for v0.3.0:
- [ ] "Play in 3s" countdown button

---

## Feature 1: Selective Actor Triggering ✅

**Status:** Implemented

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

**Removed:**
- Target dropdown (replaced by checkboxes)
- "Target GO" and "Target Stop" buttons (removed for now, may be replaced later)

### Server Changes

- Track which actors are "active" (checked) per director
- Broadcast commands only go to checked actors
- Server doesn't need to know about checkboxes — director only sends to checked actors

---

## Feature 3: Actor Status Indicators ✅

**Status:** Implemented

**Goal:** Show connection quality per actor with colored dot + latency on hover.

### Server-Side Tracking

- WebSocket already sends ping every 30s (keepalive)
- Server tracks RTT per actor: `last_ping_sent` → `pong_received`
- Store in actor metadata: `{"name": "Alice", "latency_ms": 85, "last_seen": timestamp}`

### Protocol Addition

Server broadcasts status to director periodically (every 10s or on significant change):

```
STATUS|actors=[{"name":"Alice","latency_ms":85},{"name":"Bob","latency_ms":150}]
```

### Director UI

**Approved Actors List:**
- Each actor has a colored dot indicator
- Hover shows actual latency: "85ms"

**Color thresholds:**
- 🟢 Green: < 100ms (good)
- 🟡 Yellow: 100-300ms (acceptable)
- 🔴 Red: > 300ms (poor)
- ⚪ Gray: No response in 60s (missed 2+ pings)
- (removed): WebSocket closed / disconnect detected

### Actor Client

No changes needed — WebSocket ping/pong is automatic.

### Protocol

No new message types. Director simply sends to multiple actors instead of broadcast:

**Old broadcast:**
```
CMD|*go
```

**New: Director sends individual PRIV messages to each checked actor:**
```
PRIV|Director|Alice|*go
PRIV|Director|Bob|*go
```

Or add a new multi-target message:
```
CMD|*go|targets=Alice,Bob,Charlie
```

(TBD: which approach is cleaner)

---

## Feature 2: File Transfer ✅

**Status:** Implemented

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

**During transfer:**
- Progress bar in status area
- Notification on completion: "✓ Saved: sound_effect.mp3"

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

### Constraints

- Max file size: 10 MB (enforced by director before sending)
- One file at a time per actor (queue if multiple)
- Actor must be online (no server-side buffering)

---

## TODO: Additional Features (To Be Designed)

*Danny has more ideas to add here...*

---

## Low Priority / Future Ideas

### Soundpad Integration Improvements

**Investigated 2026-03-31:**

Soundpad has a Remote Control API with:
- `DoPlaySound(index)` — play by index (current approach)
- `DoPlaySoundFromCategory(catIdx, soundIdx)` — play from category
- `AddSound(path)` — add file to list (pipe API only)
- `GetSoundlist()` — retrieve current list (pipe API only)

**Limitation:** Command line API only supports index-based playback. No `DoPlaySoundByPath()`.

**Workarounds considered:**
1. Use named pipe API directly for `AddSound()` (requires custom code)
2. Python `soundpad_control` library (adds dependency)
3. Keep current workflow — file transfer separate, manual add to Soundpad

**Decision:** Keep current index-based approach. Auto-add/play after file transfer is low priority.

---

---

## Feature 4: Multi-Director Warning ✅

**Status:** Implemented

**Goal:** Warn if another director is already connected.

### Server Changes

On director registration, check for existing directors:

```python
if role == "director":
    existing = get_directors()
    if existing:
        await websocket.send_text(format_message("MSG", sender="SERVER",
            text=f"Warning: {existing[0].name} is already connected"))
    # ... continue with auth
```

### Behavior

- Second director connects → gets warning message
- Both directors have full control (no restrictions)
- Warning is informational only

---

## Feature 5: "Play in 3s" Countdown Button

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

**Implementation:**
- `tkinter.after()` for countdown ticks
- Flag to track if countdown is active
- Stop button checks flag and cancels if needed

---

## Feature 6: Bigger Buttons for VR

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

**Window sizing:**
- May need to increase window height to accommodate larger buttons
- Test minimum sizes after changes

---

## Implementation Order

Completed in v0.2.0:
1. ~~Multi-director warning (simple)~~ ✅
2. ~~Bigger buttons for VR~~ ✅
3. ~~Selective actor triggering (checkboxes)~~ ✅
4. ~~Actor status indicators~~ ✅
5. ~~File transfer~~ ✅

Remaining:
6. "Play in 3s" countdown (v0.3.0)