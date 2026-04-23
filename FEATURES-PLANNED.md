# Planned Features

*Design specs for upcoming features. Each feature gets its own commit.*

---

## Version History

| Version | Status | Notes |
|---------|--------|-------|
| **v0.1.0** | Released | Initial release — basic WebSocket client, Soundpad integration |
| **v0.2.0** | Released | Selective triggering, file transfer, status indicators, VR-friendly buttons, Play in 3s |
| **v0.2.1** | Released | Configurable Soundpad path, duplicate actor fix |
| **v0.2.2** | Released | Forget Actor flow, cross-platform builds, code cleanup |
|| **v0.3.0** | In Progress | Multi-file transfer, character routing, batch protocol, overwrite dialog, protocol versioning, auto-updater |
|| **v0.4.0** | Planned | Director client Tauri+Svelte migration, OSC cue editor with audio player |

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

**Goal:** Director can send multiple files to actors with optional character-based routing.

**Status:** Implemented (v0.3.0-dev) — code in `director_client_ws.py`, `actor_client_ws.py`, `server_ws.py`, `shared.py`

### Implementation

**Batch Protocol (new messages):**
```
BATCH_START|target|file_count|total_bytes   — Director tells actor "N files incoming"
BATCH_END|target|success_count|fail_count   — Director signals batch complete
BATCH_CANCEL|target|reason                  — Director cancels remaining files
```

**Sequential file flow:**
- Director sends BATCH_START, then FILEREQ for first file only
- After each FILEOK/FILEERR/FILEDENY, director sends FILEREQ for next file
- After all files done, director sends BATCH_END
- Each file still uses existing FILESTART/FILECHUNK/FILEEND protocol unchanged
- Actor sees progressive "Receiving batch: 2/5 files" in log

**Not the original spec** (which had "FILEREQ with multiple filenames, actor acknowledges all at once"). The implemented approach is simpler: each file goes through the standard single-file protocol, wrapped in batch envelope messages. This means:
- No new acknowledgment patterns
- No new chunk logic
- Actor auto-accept still works per-file
- Overwrite dialog still works per-file
- Server just relays batch messages (no state tracking)

### UI Changes — Director
- Multi-select file picker (`askopenfilenames`)
- Character-to-actor mapping dialog with dropdowns per character/ungrouped file
- Session memory for character→actor mappings (auto-fills on next batch)
- Single-file fallback (no ` - ` pattern) still uses simple actor-picker dialog
- "📁 Send Files..." button replaces old "📁 Send File..."

### UI Changes — Actor
- Batch progress: "📦 Receiving batch of N files (X KB)" on BATCH_START
- Per-file progress: "Batch progress: 2/5 files"
- Batch summary on BATCH_END: "✓ Batch complete: 4/5 saved, 1 failed"
- Cancellation notice on BATCH_CANCEL
- Overwrite dialog with temp file approach (no memory bloat from holding bytes in lambda)

### Cancel Batch
- `cancel_batch()` method exists on director client but has no UI button yet
- Sends BATCH_CANCEL to actor, cleans up pending files, removes batch state

---

### Feature 2b: Character-based File Routing (Audioscript Mode)

**Goal:** Automatically route audioscript files to actors based on character name in filename.

### Filename Pattern
- Format: ` - Character.ext` (e.g., "EP3 Scene 4.2 - Diego.mp3", "Scene 4 - Alice.wav")
- Character name extracted from the segment after the **last** ` - ` (space-dash-space)
- Works with any file extension (mp3, wav, ogg, etc.)
- Files **without** ` - ` in the name are listed individually (not grouped)

### Pattern Matching Logic
```python
# Extract character name from filename
if ' - ' in filename:
    character = filename.rsplit(' - ', 1)[-1].rsplit('.', 1)[0].strip()
else:
    # No character pattern — list individually
    character = None
```

### Examples
| Filename | Extracted Character | Behavior |
|----------|---------------------|----------|
| `Scene 4 - Diego.mp3` | `Diego` | Group by character |
| `EP3 - Scene 4.2 - Diego.wav` | `Diego` | Group by character (last ` - ` wins) |
| `intro_music.mp3` | None | List individually, assign manually |
| `sound-effect-final.ogg` | None | List individually (no ` - ` pattern) |

### Grouping Behavior
- Files matching the pattern are **grouped by character**
- Mapping dialog shows character name, not individual files
- Multiple files for same character appear as one row with file count
- Files without the ` - ` pattern are listed individually with full filename

Example dialog:
```
┌─────────────────────────────────────────┐
│  Map Characters to Actors              │
│                                         │
│  Diego      → [Coda        ▼] (2 files) │
│  Quincey    → [Infinity    ▼] (1 file)  │
│                                         │
│  random_sound.mp3  → [Coda   ▼]         │
│  intro_music.wav   → [unassigned ▼]     │
│                                         │
│  [ ] Remember for this session          │
│                                         │
│    [Send All]       [Cancel]           │
└─────────────────────────────────────────┘
```

### Workflow
1. Director selects multiple files
2. System parses character names using ` - ` pattern
3. Files with matching pattern grouped by character
4. Files without pattern listed individually with full filename
5. Mapping dialog shows grouped characters + individual files
6. Known mappings auto-filled from session memory
7. Director reviews/confirms, clicks Send All
8. Files dispatched to respective actors

### Unmapped Characters
If a character has no actor assigned:
```
"No actor is assigned to 'Diego'. Skip this file?"
[Yes]  [No]
```
- **Yes:** Skip file, continue with remaining
- **No:** Return to mapping dialog

### Non-matching Filenames
Files that don't have the ` - ` pattern:
- Show full filename in mapping dialog
- Assign manually to any actor
- Treated same as character-based files after assignment

### Session Memory
- Character→Actor mappings persist for the session
- New batch auto-fills known mappings
- Option to clear/reset mappings
- Saved per-director (stored locally, not on server)

### Implementation Notes
- Pattern matching: strict ` - ` (space-dash-space) required
- Works with any file extension (not just .mp3)
- Session memory stored in director config
- No server changes needed — just client-side routing logic

### Overwrite Handling
When a file with the same name already exists:

| Auto-Accept | Behavior |
|-------------|----------|
| **ON** | Silent overwrite. Both parties see yellow warning log: `"⚠ Saved (replaced existing): filename.mp3"` |
| **OFF** | Prompt actor with overwrite warning before accepting |

**Prompt dialog (auto-accept OFF):**
```
┌─────────────────────────────────────────────┐
│  File Already Exists                       │
│                                            │
│  This will overwrite:                      │
│    sound_effect.mp3                        │
│                                            │
│  [ ] Auto-accept future files              │
│                                            │
│    [Accept (Overwrite)]    [Decline]       │
└─────────────────────────────────────────────┘
```

**Note:** If actor declines, director receives FILEDENY and the transfer aborts for that file. Remaining files in batch continue.

---

### Feature 3: Ping Compensation / Delay

**Goal:** Director can set delay per actor to compensate for network latency.

### Approach
- Manual adjustment by director — no automatic calculation
- Director sets delay, tests quickly with Go command, refines as needed
- Practical for live production where actors may have different network conditions

### Server Changes
- Store delay per actor in config
- Apply delay before sending command to that actor
- Delay is in milliseconds

### Director UI
- Right-click actor → "Set delay"
- Input dialog: "Delay for ActorName (ms):"
- Show delay value next to actor name (optional): `Alice (85ms) [+50ms]`

### Actor Client
- No changes needed - delay is server-side
- Actor receives command after configured delay

---

### Feature 4: Protocol Versioning

**Goal:** Clients know their protocol version and receive warnings when outdated.

**Status:** Implemented (v0.3.0-dev) — code in `shared.py`, `server_ws.py`, both clients

### Protocol Addition

Client sends version during registration:
```
REGISTER|name|machine_id|role|secret|version
```

Version is optional for backward compatibility. If omitted, server assumes legacy client.

Server responds after registration:
```
VERSION|status|server_version|message
```

| Status | Meaning |
|--------|---------|
| `ok` | Versions match, no action needed |
| `warning` | Minor/patch mismatch, some features may not work |
| `unsupported` | Major version mismatch, connection rejected |

### Version Format
- Semantic versioning: `MAJOR.MINOR.PATCH` (e.g., `0.2.0`)
- Stored in `shared.py` as `PROTOCOL_VERSION`
- Clients include version in REGISTER message

### Client Behavior
- On `warning`: display message in log, allow connection
- On `unsupported`: show error dialog, disconnect
- Old clients (no version field): server accepts with warning logged server-side

### Server Behavior
- Compare client version to server version
- Different major version → `unsupported`
- Different minor/patch → `warning`
- Log version mismatches for debugging

---

### Feature 5: Actor Display Names

**Goal:** Allow directors to rename actors locally for easier identification during production.

### Director Client Changes
- Right-click actor → "Set Display Name" option
- Display name overlay shown instead of actor name in list
- Tooltip on hover shows: "Original: <actor_name>"
- Display name stored in director client memory only (not persisted)
- Cleared when director disconnects

### Use Case
- Director assigns character names to actors: "Diego", "Alice", "Bob"
- Easier to identify who to send commands to
- No confusion about which actor is playing which character

### Implementation
- `display_names: Dict[str, str]` mapping machine_id → display_name
- Applied to actor list rendering only
- Original name preserved in all protocol messages
- Server unaware of display names (purely client-side)

### UI Mockup
```
┌─────────────────────────────────────┐
│  Approved Actors                     │
│                                      │
│  🟢 Diego (hover: "Original: Coda")  │
│  🟢 Alice (hover: "Original: Infinity")│
│  🔇 Bob (hover: "Original: Quincey") │
│                                      │
│     [All] [None] [Invert]            │
│     [Send File...] [Forget Actor...] │
└─────────────────────────────────────┘
```

### Context Menu
- Right-click actor row
- "Set Display Name..." → Enter name dialog
- "Clear Display Name" → Revert to original

---

### Feature 6: Version Display & Auto-Updater

**Goal:** Official versioning system and automatic client updates.

**Status:** Implemented (v0.3.0-dev) — auto-updater, version display, protocol versioning

### Implementation

**Version:**
- Semver: `APP_VERSION = "0.3.0"` in `shared.py`
- Window titles: "Director Client v0.3.0", "Actor Client v0.3.0"
- Startup log shows version

**Protocol versioning (Feature 4):**
- REGISTER now includes version + platform: `REGISTER|name|machine_id|role|secret|version|platform`
- Server sends VERSION response after APPROVED
- Version mismatch: `ok`, `warning` (minor diff), `unsupported` (major diff)

**Auto-update flow:**
1. Server operator edits `update_manifest.json` with latest version, download URLs, SHA256
2. Client connects → REGISTER with version + platform
3. Server checks: if client version < manifest latest AND matching asset has a download URL
4. Server sends `UPDATE|latest_version|download_url|sha256|release_notes`
5. Client shows dialog: "Update available: v0.3.1. Download?"
6. User clicks Update → client downloads to temp file in background thread
7. SHA256 verification — if mismatch, aborts with error
8. Client writes updater script (`.bat` on Windows, `.sh` on Linux)
9. Launches updater, calls `self.quit()`
10. Updater waits for process exit, swaps files, relaunches
11. On next startup, client cleans up `.tmp` and `_updater.*` files

**Update manifest (`update_manifest.json`):**
```json
{
  "latest_version": "0.3.1",
  "minimum_version": "0.2.2",
  "release_notes": "Batch transfer + versioning fixes",
  "assets": {
    "actor-windows-x64": {"url": "https://...", "sha256": "abc123"},
    "actor-linux-x64": {"url": "https://...", "sha256": "def456"},
    "director-windows-x64": {"url": "https://...", "sha256": "789"},
    "director-linux-x64": {"url": "https://...", "sha256": "012"}
  }
}
```

**Key design decisions:**
- Manifest lives next to server — operator controls download URLs at any time
- Empty URLs = no update sent (operator controls rollout)
- URLs can point anywhere: GitHub Releases, private server, Tailscale file share
- No GitHub API dependency — server reads local file, not rate-limited endpoints
- SHA256 verification built into download flow
- Linux packaging: AppImage format (.AppImage.tmp → .AppImage swap)
- Backward compatible: old clients without version/platform still connect fine
- Client can verify download hash against server
- Provides extra security layer beyond GitHub
- Server endpoint: `VERSION_HASH|v0.3.0|sha256_hash`
- If server unreachable, proceed with GitHub-only verification

### Version Mismatch Warning
When client connects to server:
- Server checks client version vs. server expected version
- On mismatch: show notification to client
- Message: "Warning: Client v0.2.0 may have compatibility issues with server v0.3.0. Some features may not work."
- Connection still allowed (notification only)
- Silent releases (HOTFIX increment) do NOT trigger server warning

### Client Independence
- Director and Actor clients update independently
- No forced sync between client types
- Server tracks both and can log mismatch warnings

### Platform Support
- **Windows x64:** Primary target, full auto-update
- **Linux x64:** Executable replacement or package manager
- No planned support for x86 or ARM64

### Rate Limiting
- Check for updates once at startup only
- Manual check button has 5-minute cooldown
- Avoids GitHub API rate limits (60/hr unauthenticated)

### GitHub Release Assets
Each release includes:
- `vrActorClient-v0.3.0.exe`
- `vrDirectorClient-v0.3.0.exe`
- `vrActorClient-v0.3.0` (Linux)
- `vrDirectorClient-v0.3.0` (Linux)
- `checksums.sha256`

---

## v0.4.0 Features (Planned) — Tauri Director Migration + OSC Cue Editor
### Feature: OSC Cue List

**Goal:** Director can schedule VRChat OSC parameter changes at specific times after hitting Play, synced to Soundpad audio. Enables timed avatar expressions, gestures, and indicators that need to land on a beat.

**Why a cue list instead of a single toggle:**

A single "fire this parameter at X ms" covers the common case, but the first time you need two things to happen — like mouth open at 2s, close at 5s — you're stuck. A cue list supports that and costs almost nothing extra. The single-toggle case is just a 1-item cue list.

### Director UI — OSC Cue Editor

```
┌─────────────────────────────────────────────────────────────┐
│  OSC CUES                                                    │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  🎵 sound_effect.mp3                                  │  │
│  │  ▶ 0:02.340 ████████░░░░░░░░░░░░░░░ 0:05.120  ▌▌ │  │
│  │                                                       │  │
│  │  [▶ Play] [⏹ Stop] [Load Sound...]                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  Global Delay Offset: [+0 ms]  (ping compensation)          │
│                                                              │
│  #  Delay    Parameter            Value      Actors          │
│  1  2000ms   RecIcon             true       ☑Coda           │
│  2  2000ms   /MouthOpen          true       ☑Coda           │
│  3  2300ms   /EyeClose           true       ☑Coda           │
│  4  5000ms   /MouthOpen          false      ☑Coda           │
│                                                              │
│  [+ Add Cue]  [Add at Playhead ▼]  [Test]  [Save Preset]  │
└─────────────────────────────────────────────────────────────┘
```

**Audio Player:**
- Director loads a Soundpad sound file (or picks from the actor's sound list if remote library is implemented)
- Seek bar shows the full waveform timeline with millisecond precision
- Playhead position displayed as `M:SS.mmm` (e.g., `0:02.340`)
- Click anywhere on the seek bar to jump to that position
- Cues are marked on the seek bar as vertical lines with their row number
- Clicking a cue row scrolls the seek bar to show that cue's position
- **Add at Playhead** button inserts a new cue with the delay set to the current playhead position

**Global Delay Offset (Ping Compensation):**
- Single field (in ms) added to ALL cue delays before sending
- Director sets it once instead of editing each cue individually
- Example: offset of +80ms means a cue at 2000ms fires at 2080ms for the actor
- Offset is per-session, not saved in presets (network conditions change)
- Display shows effective times: `1  2080ms (+80)  RecIcon  true`

**Controls:**
- **Add Cue** — adds a new row with delay, parameter, value, and actor checkboxes
- **Add at Playhead** — adds a new row with delay set to current audio position
- **Test** — fires OSC cues without playing Soundpad sound (verify timing)
- **Save as Preset** — saves cue list for reuse (per scene)
- **Load Preset** — load a saved cue list
- **Remove** — delete a cue row
- Double-click a cue row to jump audio player to that position
- All delays are in milliseconds, editable

**Parameter format:**
- Shorthand: `RecIcon` → automatically expands to `/avatar/parameters/RecIcon`
- Full path: `/avatar/parameters/CustomParam` → used as-is
- Leading slash distinguishes full paths from shorthand

**Value types:**
- `true` / `false` — bool parameters (toggles, visibility)
- `0.0` to `1.0` — float parameters (blend shapes, gesture weights, sliders)

**Actor targeting:**
- Same checkbox pattern as `*go` command
- Only checked actors receive the OSC event
- Director can send different cues to different actors

### Actor Client — OSC Integration

**New dependency:** `python-osc` (for VRChat OSC)

**Behavior:**
- On receiving `*go`, actor starts local timers for all cues targeting them
- Each timer fires the OSC parameter at the specified delay
- Timers are local to the actor client — no network jitter on OSC sends
- On receiving `*stop`, cancel all pending timers and optionally reset parameters

**Config addition:**
```json
{
  "vrchat_osc_host": "127.0.0.1",
  "vrchat_osc_port": 9000,
  "osc_enabled": true
}
```

### Protocol Addition

```
# Director sends cue list to actors (before or with the go command)
OSC_CUE|delay_ms|parameter|value

# Example: cue list sent before *go
OSC_CUE|2000|RecIcon|true
OSC_CUE|2000|/avatar/parameters/MouthOpen|true
OSC_CUE|2300|/avatar/parameters/EyeClose|true
OSC_CUE|5000|/avatar/parameters/MouthOpen|false

# When director hits Play (*go), each actor starts their local timers
# OSC_CUE messages are targeted — only sent to checked actors
# *go command triggers the timers (same actor targeting as *go checkboxes)

# Actor acknowledges cue list received
OSC_CUE_ACK|count|4
```

**Flow:**
1. Director creates cue list in UI (or loads preset)
2. Director optionally adjusts Global Delay Offset for ping compensation
3. Director clicks Play (or Play in 3s)
4. Director sends OSC_CUE messages to checked actors (with global offset applied)
5. Immediately sends `*go` to same actors (or after 3s countdown)
6. Actors receive `*go` → play Soundpad sound + start OSC cue timers
7. Each timer fires at its delay + global offset → sends OSC parameter to VRChat
8. Actor sends OSC_CUE_ACK confirming cue count

**Timing accuracy:**
- Timers run on actor client (local to VRChat, no network jitter on OSC)
- OSC is UDP — near-instant delivery to localhost
- Typical jitter: <5ms, well within tolerance for synced expressions
- If Soundpad has latency, actor can adjust delays per-sound in the preset
- Global offset is applied once at send time, not saved in presets (network conditions change per session)

### Preset System

**Purpose:** Save and load cue lists so directors don't rebuild them every take.

**Storage:** Per-director, saved in director config directory as JSON files.

**Preset format:**
```json
{
  "name": "EP3 Scene 4 - Diego monologue",
  "cues": [
    {"delay_ms": 2000, "parameter": "RecIcon", "value": "true", "actors": ["Coda"]},
    {"delay_ms": 2000, "parameter": "/avatar/parameters/MouthOpen", "value": "true", "actors": ["Coda"]},
    {"delay_ms": 5000, "parameter": "/avatar/parameters/MouthOpen", "value": "false", "actors": ["Coda"]}
  ]
}
```

**UI flow:**
- "Save as Preset" prompts for name
- "Load Preset" dropdown shows saved presets
- Presets can be associated with specific sounds (auto-load when sound is selected)

### Fallback for non-OSC setups

If actor client has `osc_enabled: false` or VRChat OSC is not reachable:
- Cues are still received and stored
- Log shows: `[OSC] Cue at 2000ms: RecIcon=true (skipped — OSC disabled)`
- Director sees: actor name shows ⚠ OSC indicator
- No error popups, just silent skip with log entry

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

## v0.2.2 Features

### Forget Actor Flow ✅

**Goal:** Allow director to remove an actor, requiring them to re-approve before reconnecting.

### Director Client Changes
- Forget Actor dialog now always shows selection list (same pattern as Send File)
- Removed Deny button from pending actors — only Approve needed
- Cleaner UX with consistent dialog pattern

### Actor Client Changes
- Receives "forgotten" message from server
- Disconnects locally (clean UI state)
- Shows "Forgotten - click Connect to rejoin" status
- Actor must manually click Connect to request approval again

### Server Changes
- FORGET_NAME notifies actor and adds to pending list
- Actor must be re-approved after being forgotten
- Fix reconnect logic to update websocket in pending_actors
- Removed unused FORGET and DENY handlers

---

### Cross-Platform Builds ✅

**Goal:** Support Linux executables in addition to Windows .exe.

### Build Script Changes
- Auto-detect Windows vs Linux
- Use correct path separator for PyInstaller (`;` on Windows, `:` on Unix)
- Support building actor, director, or both
- Output correct executable name per platform:
  - Windows: `vrActorClient.exe` / `vrDirectorClient.exe`
  - Linux: `vrActorClient` / `vrDirectorClient`

---

### Code Cleanup ✅

**Goal:** Remove unused code for maintainability.

### Removed
- `deny_selected` function from director client (button was removed)
- `FORGET` message handler from server (FORGET_NAME is used)
- Unused imports and dead code

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