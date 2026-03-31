# vrActorAssist Roadmap

*Last updated: 2026-03-31*

---

## 🐛 Bugs / UX Issues

- [ ] **Config dialog too small** — Edit config dialog should show Connect/Save button without expanding window (set minimum size or auto-size)

---

## 🚀 Features (Planned)

### Priority 1: Director Control Improvements

- [ ] **Selective actor triggering** — Toggle to select which actors receive commands:
  - Checkboxes per actor in a list
  - "Select All" / "Select None" buttons
  - Commands only go to checked actors
  
- [ ] **Ping compensation / delay** — Add millisecond delay per actor:
  - Director can set delay per actor (e.g., Actor A: +50ms, Actor B: +100ms)
  - Helps compensate for network latency differences
  - Stored in actor config, applied server-side

- [ ] **Actor status indicators** — Show connection quality:
  - Green/yellow/red indicator per actor
  - Based on ping time or message ACK latency

### Priority 2: File Transfer (Lost in WebSocket Migration)

- [ ] **Send files to actors** — Director can send files (audio files, config, etc.):
  - Progress bar for transfer
  - Files saved to configurable directory on actor machine
  - Support for small files (< 10MB typical)

### Priority 3: Soundpad Integration

- [ ] **Sound list sync** — Director can request actor's Soundpad sound list:
  - Shows numbered list of sounds
  - Director knows what `*play:N` will trigger
  
- [ ] **Sound preview** — Director can preview sound before triggering (local playback)

- [ ] **Hotkey mapping** — Custom hotkeys for common commands:
  - F1-F12 for frequently used sounds
  - Configurable per actor or global

### Priority 4: Actor Improvements

- [ ] **Minimize to tray** — Actor client can minimize to system tray:
  - Right-click menu for quick status
  - Notifications for commands received
  
- [ ] **Auto-start with Soundpad** — Option to launch Soundpad automatically
  
- [ ] **Volume control** — Director can adjust actor's Soundpad volume remotely

### Priority 5: Server Improvements

- [ ] **Web dashboard** — Simple web UI for server admin:
  - View connected actors
  - Kick/ban actors
  - View logs
  - Restart server
  
- [ ] **Multiple director support** — Allow multiple directors with different permissions:
  - Main director (full control)
  - Assistant director (limited commands)
  
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
- [x] Soundpad CLI integration
- [x] Basic command system (`*go`, `*stop`, `*play:N`)
- [x] Private messaging to specific actors