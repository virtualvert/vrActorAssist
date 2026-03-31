# Planned Features

*Design specs for upcoming features. Each feature gets its own commit.*

---

## Version History

| Version | Status | Notes |
|---------|--------|-------|
| **v0.1.0** | Released | Initial release — basic WebSocket client, Soundpad integration |
| **v0.2.0** | Planned | Selective triggering, file transfer, status indicators |

---

## v0.2.0 Scope

Features planned for v0.2.0:
- [ ] Selective actor triggering (checkboxes)
- [ ] File transfer (director → actor)
- [ ] Actor status indicators (ping + hover)

Window sizing fix (2026-03-31) will be included in v0.2.0 build.

---

## Feature 1: Selective Actor Triggering

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

**Removed:**
- Target dropdown (replaced by checkboxes)
- "Target GO" and "Target Stop" buttons (removed for now, may be replaced later)

### Server Changes

- Track which actors are "active" (checked) per director
- Broadcast commands only go to checked actors
- Server doesn't need to know about checkboxes — director only sends to checked actors

---

## Feature 3: Actor Status Indicators

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

## Feature 2: File Transfer (Director → Actor)

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

## Implementation Order

1. Selective actor triggering (checkboxes)
2. File transfer (send/receive)

Each feature = one commit.