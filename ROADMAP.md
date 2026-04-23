# vrActorAssist Roadmap

*Last updated: 2026-04-23*

---

## 🚀 Features (Planned)

### Priority 1: v0.3.0 — Released ✅

- [ ] **Multiple director support** — *(deferred to v0.3.1, see Priority 1.5)*
  
- [x] **Send multiple files** — Director can send multiple files to actor at once ✅:
  - Multi-select in file picker ✅
  - Queue transfers with progress ✅ (sequential, BATCH_START/BATCH_END protocol)
  - Actor receives to configured directory ✅
  - Character-based routing for audioscript files (` - Character.mp3` pattern) ✅
  - Overwrite warning when file exists (auto-accept toggle determines behavior) ✅
  - Cancel batch button ✅

- [ ] **Ping compensation / delay** — *(deferred to v0.3.1, see Priority 1.5)*
  - Helps compensate for network latency differences

- [x] **Protocol versioning** — Version handshake during client registration ✅
  - Client sends version in REGISTER message
  - Server responds with VERSION|status|server_version|message
  - Outdated clients see warning in log
  - Major version mismatch rejects connection
  - Minor/patch mismatch allows connection with warning

- [x] **Version display & auto-updater** — Official versioning and automatic updates ✅:
  - 4-part version number: `vMAJOR.MINOR.PATCH.HOTFIX` (e.g., v0.3.0.1) — *using semver MAJOR.MINOR.PATCH instead*
  - Version shown in window title, startup log ✅
  - About dialog with version info ✅
  - Auto-check for updates from server at connect ✅
  - Server-side manifest: `update_manifest.json` with download URLs ✅
  - Client downloads, verifies SHA256, self-replaces via updater script ✅
  - Update manifest can point at any URL (GitHub, private server, Tailscale) ✅
  - Platform-aware: `windows-x64`, `linux-x64` (AppImage) ✅
  - Director and Actor clients update independently ✅

### Priority 1.5: v0.3.1 — Last tkinter Polish

- [ ] **Multiple director support** *(deferred from v0.3.0)* — Allow multiple directors with different names and permissions:
  - Main director (full control)
  - Assistant director (limited commands)
  - Each director has their own identity/name

- [ ] **Ping compensation / delay** *(deferred from v0.3.0)* — Add millisecond delay per actor:
  - Director can set delay per actor (e.g., Actor A: +50ms, Actor B: +100ms)
  - Manual adjustment, tested quickly with Go command
  - Stored in actor config, applied server-side
  - Helps compensate for network latency differences

- [ ] **Actor display names** — *(deferred to v0.4.0 — will be built in Tauri/Svelte instead of tkinter)*
  - Right-click actor → "Set Display Name"
  - Shows character name instead of actor name on director's client
  - Display name is temporary (cleared when director disconnects)
  - Original actor name preserved and still shows on hover/tooltip
  - No server state needed — stored only in director client memory
  - Useful for mapping actors to character names during production

### Priority 2.5: v0.4.0 — Tauri Director Migration + OSC Cue Editor

- [ ] **Director client → Tauri+Svelte** — Migrated from tkinter to Tauri 2.0 + Svelte 5:
  - All existing director features ported (actor panel, checkboxes, chat, file transfer, etc.)
  - Same protocol — talks to the same Python server
  - Single ~8MB binary instead of PyInstaller bundle

- [ ] **OSC cue list** — Timed VRChat parameter triggers synced to Play command:
  - Director creates list of "at X ms after Play, set parameter to value" cues
  - Supports bool values (true/false) and float values (0.0-1.0) for blend shapes
  - Actor client runs local timers — no network jitter on OSC sends
  - Same checkbox targeting as `*go` — only checked actors receive cues
  - Shorthand parameter names (`RecIcon` → `/avatar/parameters/RecIcon`)
  - Audio player with seek bar (ms precision) — load the sound, scrub to place cues visually
  - Cue markers on seek bar — vertical lines with row numbers, click row to jump to position
  - "Add at Playhead" button — inserts cue at current audio position
  - Global delay offset for ping compensation — one field, applied to all cues at send time
  - Cue presets saveable per scene (offset is per-session, not saved)
  - Test button fires OSC without playing Soundpad sound
  - Graceful fallback if VRChat OSC is disabled (log + skip)
  - `*stop` cancels all pending cue timers

### Priority 3: Actor Improvements

- [ ] **Auto-start with Soundpad** — Option to launch Soundpad automatically

### Priority 3: Server Improvements

- [ ] **Session recording** — Log all commands and messages for review:
  - Export as JSON or CSV
  - Replay session for debugging

---

## 🔧 Technical Debt

- [ ] **Unit tests** — Add pytest tests for protocol parsing
- [ ] **Error handling** — Better error messages and recovery
- [ ] **Logging levels** — Configurable log verbosity
- [ ] **Config validation** — Validate URLs, names, etc. before connecting
- [x] **Cancel Batch UI button** — Added "✖ Cancel Batch" button, enabled when batch is active
- [x] **Duplicate filename collision** — Fixed: `pending_files` now uses composite key `batch_id:filename` for batch files, with `_find_pending_by_filename()` lookup helper
- [ ] **Pipe character in filenames** — `|` in a filename breaks the pipe-delimited protocol. Unlikely in practice but should be documented or escaped
- [ ] **Actor file dialog on WS thread** — `filedialog.askdirectory()` called from WebSocket thread can crash tkinter on some platforms. Move to `root.after()` pattern

---

## 💡 Ideas (Future)

- [ ] **OpenVR/OpenXR overlay** — In-VR overlay for both clients without desktop view
- [ ] **TTS messages** — Send text-to-speech to actors (plays through mic)
- [ ] **Web dashboard** — Web UI for server admin (view, kick, logs)
- [ ] **Auto-add + play in Soundpad** — Automatically add transferred file and play it
- [ ] **Volume control** — Director can adjust actor's Soundpad volume remotely
- [ ] **Soundboard overlay** — OBS browser source showing triggered sounds
- [ ] **Voice chat integration** — Discord/Slack bridge for audio cues
- [ ] **Mobile app** — Director control from phone/tablet
- [ ] **Cloud sync** — Share approved actors list across servers
- [ ] **Scene presets** — Save/load actor configurations per scene

---

## Completed ✅

- [x] WebSocket migration (from raw TCP)
- [x] Director approval system
- [x] Auto-reconnect with keepalive
- [x] Windows .exe build for actors
- [x] Linux executable build (cross-platform support)
- [x] Director client executable build
- [x] Soundpad CLI integration
- [x] Basic command system (`*go`, `*stop`, `*play:N`)
- [x] Private messaging to specific actors
- [x] UI improvements (timestamps, error logging, window sizing)
- [x] Multi-director warning — shows warning if another director is already connected
- [x] Bigger buttons for VR — larger buttons for easier desktop overlay clicking
- [x] Selective actor triggering — checkboxes to select which actors receive commands
- [x] Actor status indicators — latency-based green/yellow/red connection quality dots
- [x] File transfer — director can send files to actors
- [x] Configurable Soundpad path — actors can set custom Soundpad.exe location via config or env var
- [x] Duplicate actor fix — old connection now properly disconnected on reconnect
- [x] "Play in 3s" countdown — button with 3-second delay before sending Go
- [x] Config dialog sizing — fixed to show Connect/Save button properly
- [x] Forget Actor flow — director can remove actor, actor must re-request approval
- [x] Cross-platform builds — Linux executables, director client builds
- [x] Code cleanup — removed unused functions and handlers
- [x] v0.1.0 release — initial actor client
- [x] v0.2.0 release — selective triggering, file transfer, status indicators
- [x] v0.2.1 release — configurable Soundpad path, duplicate actor fix
- [x] v0.2.2 release — forget actor, cross-platform builds, cleanup