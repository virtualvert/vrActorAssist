# vrActorAssist Roadmap

*Last updated: 2026-04-02*

---

## 🚀 Features (Planned)

### Priority 1: v0.3.0

- [ ] **Multiple director support** — Allow multiple directors with different names and permissions:
  - Main director (full control)
  - Assistant director (limited commands)
  - Each director has their own identity/name
  
- [ ] **Send multiple files** — Director can send multiple files to actor at once:
  - Multi-select in file picker
  - Queue transfers with progress
  - Actor receives to configured directory
  - Character-based routing for audioscript files (` - Character.mp3` pattern)
  - Overwrite warning when file exists (auto-accept toggle determines behavior)

- [ ] **Ping compensation / delay** — Add millisecond delay per actor:
  - Director can set delay per actor (e.g., Actor A: +50ms, Actor B: +100ms)
  - Manual adjustment, tested quickly with Go command
  - Stored in actor config, applied server-side
  - Helps compensate for network latency differences

- [ ] **Protocol versioning** — Version handshake during client registration:
  - Client sends version in REGISTER message
  - Server responds with VERSION|status|server_version|message
  - Outdated clients see warning in log
  - Major version mismatch rejects connection
  - Minor/patch mismatch allows connection with warning

### Priority 2: Director Improvements

- [ ] **Actor display names** — Director can rename actors locally:
  - Right-click actor → "Set Display Name"
  - Shows character name instead of actor name on director's client
  - Display name is temporary (cleared when director disconnects)
  - Original actor name preserved and still shows on hover/tooltip
  - No server state needed — stored only in director client memory
  - Useful for mapping actors to character names during production

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