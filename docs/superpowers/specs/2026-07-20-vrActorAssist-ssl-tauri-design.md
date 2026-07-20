# vrActorAssist: SSL Fix + Tauri Migration Design

**Date:** 2026-07-20  
**Status:** Approved  
**Version:** 1.0

---

## 1. Problem Statement

### 1.1 SSL Certificate Verification Errors

Users connecting to the vrActorAssist server via Tailscale Funnel receive "SSL certificate verify failed" errors when using PyInstaller-built `.exe` files on Windows.

**Root cause:** The `websocket-client` library is passed `sslopt={"cert_reqs": ssl.CERT_NONE}` as a dict, which is unreliable in PyInstaller builds on Windows. Python's SSL module cannot locate system CA certificates in a frozen environment, and `certifi` is not bundled. The SSL context creation itself fails before `cert_reqs` is ever evaluated.

### 1.2 User Experience Limitations

The current tkinter-based GUI is functional but dated — hard to theme, not touch-friendly, and visually inconsistent across Windows versions. A modern replacement is desired.

---

## 2. Scope

- **SSL fix** — Immediate patch to the current Python clients and build system
- **Tauri migration** — Replace both Director and Actor Python clients with a single Tauri v2 + Svelte desktop application
- **Server stays** — The Python FastAPI/WebSocket server is NOT being replaced. It continues running on the VPS under Tailscale Funnel or Caddy reverse proxy.

---

## 3. SSL Fix (Phase 1 — Ship Immediately)

### 3.1 Changes Required

| File | Change |
|------|--------|
| `build_exe.py` | Add `certifi`, `_ssl`, `ssl` to `extra_hiddenimports` for both builds |
| `requirements.txt` | Add `certifi` to dependencies |
| `actor_client_ws.py` | Replace `sslopt={"cert_reqs": ssl.CERT_NONE}` with explicit `ssl.SSLContext` |
| `director_client_ws.py` | Same SSL context change |
| `update_manifest.json` | Update SHA256 hashes for new builds |

### 3.2 SSL Context Pattern

```python
import ssl
import certifi

ssl_context = ssl.create_default_context(cafile=certifi.where())
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

self.ws.run_forever(ping_interval=30, ping_timeout=10, ssl=ssl_context)
```

### 3.3 Verification

- Build `.exe` with updated `build_exe.py` from a clean Windows environment
- Connect to a Tailscale Funnel `wss://` endpoint
- Confirm no SSL errors
- Confirm the existing Caddy reverse proxy path still works

---

## 4. Tauri Migration (Phases 2-5)

### 4.1 Architecture

```
┌─────────────────────────────────────────────────┐
│  Tauri + Svelte App (single binary)              │
│                                                   │
│  ┌──────────────── Mode Selector ──────────────┐ │
│  │  Launch screen: [Director Mode] [Actor Mode] │ │
│  │  (remembers choice via config)               │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────── Svelte Frontend ────────────────────┐ │
│  │  Shared: Chat, Connection, Settings,         │ │
│  │  Status bar, Update notifier                 │ │
│  │  Director: Actor list, Cue buttons,          │ │
│  │  File send, Character routing, Approve/Deny  │ │
│  │  Actor: File receive, Soundpad, OSC config   │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────── Rust Backend ───────────────────────┐ │
│  │  ws_client, protocol, config, connection,    │ │
│  │  file_transfer, soundpad (Windows), osc      │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 4.2 Mode Selector

- Launch screen with [Director Mode] [Actor Mode] toggle
- "Remember my choice" checkbox (saves to `config.json`)
- Mode can be changed later via Settings panel
- Single binary, conditional compilation for OS-specific features

### 4.3 Shared Components

| Component | Description |
|-----------|-------------|
| Connection Panel | Server URL input, Connect/Disconnect button, live status indicator |
| Chat Panel | Message history (scrollable), text input field, send button |
| Settings Dialog | Server URL, auto-reconnect toggle, theme (light/dark), mode switching, about info |
| Status Bar | Connection state, ping latency (ms), current mode badge |

### 4.4 Director Mode Features

| Feature | Details |
|---------|---------|
| Actor List | Table with name, status dot (green/yellow/red for latency bins), pending/approved badge |
| Cue Controls | Big Go button, Stop button, "Play in Xs" dropdown (3/5/10s), OSC cue triggers |
| File Sender | Native file picker, target actor selector, character/tag routing dropdown, progress bar |
| Approve/Deny | Accept or reject pending actor registrations |

### 4.5 Actor Mode Features

| Feature | Details |
|---------|---------|
| Status Display | Actor's own name, approval status, connected director info |
| File Receiver | Incoming file notification popup, accept/deny buttons, download progress, configurable save directory |
| Soundpad Panel | Enable/disable toggle, Soundpad.exe path config, status indicator (Windows only) |
| OSC Panel | VRChat host (default: `127.0.0.1`), port (default: `9000`), enable/disable toggle |

### 4.6 Rust Backend Modules

```
src/
├── main.rs           — Tauri entry point, mode selection, app lifecycle
├── ws_client.rs      — WebSocket connection (tungstenite), ping/pong, reconnection
├── protocol.rs       — Pipe-delimited message serialize/deserialize (matches shared.py)
├── config.rs         — JSON config read/write, defaults
├── connection.rs     — Connection state machine (disconnected/connecting/authenticated)
├── file_transfer.rs  — Chunk assembly (actor) / chunk splitting (director)
├── soundpad.rs       — Windows-only Soundpad CLI (#[cfg(target_os = "windows")])
└── osc.rs            — VRChat OSC UDP sender via rosc crate
```

### 4.7 Communication Pattern

```
Svelte Frontend                  Rust Backend               Python Server
─────────────────               ────────────               ─────────────
invoke("connect") ──────────►    ws_client.connect()
                                 │                          
                                 │──── REGISTER ──────────► Authenticate
                                 │◄─── APPROVED ───────────
emit("connected") ◄──────────    │                          
                                 │
invoke("send_msg") ──────────►   ws_client.send(MSG) ────► Broadcast
                                 │◄─── MSG ───────────────
emit("message") ◄────────────    │
```

### 4.8 Key Rust Crates

| Crate | Purpose |
|-------|---------|
| `tokio-tungstenite` | Async WebSocket client |
| `serde` + `serde_json` | Config serialization |
| `rosc` | OSC UDP messages (VRChat) |
| `tauri` (v2) | Desktop app framework |
| `tauri-plugin-updater` | Auto-update |
| `tauri-plugin-dialog` | File open/save dialogs |
| `tauri-plugin-shell` | Spawn Soundpad.exe |

### 4.9 File Transfer Protocol (unchanged)

The existing pipe-delimited file transfer protocol is preserved:
```
Director: FILEREQ → Actor: FILEACK/FILEDENY
        → FILESTART → FILECHUNK × N → FILEEND
        → Actor: FILEOK/FILEERR
```
Chunk size: 64KB. Checksum: MD5.

### 4.10 Cross-Platform Matrix

| Feature | Windows | Linux | macOS |
|---------|---------|-------|-------|
| Director mode | ✅ | ✅ | ✅ |
| Actor mode | ✅ | Partial (no Soundpad) | ❌ |
| Soundpad | ✅ | N/A | N/A |
| VRChat OSC | ✅ | ✅ (generic OSC) | N/A |

---

## 5. Migration Phases & Timeline

### Phase 1: SSL Fix (1-2 days)
- `build_exe.py` hidden imports
- SSL context refactor in both clients
- Rebuild, update manifest, ship

### Phase 2: Tauri Scaffold (1 week)
- `npm create tauri-app@latest` with Svelte template
- Rust WebSocket client with protocol parser
- Shared UI: connection panel, chat, settings
- Config persistence

### Phase 3: Director Mode (1 week)
- Actor list with latency status dots
- Cue buttons (Go, Stop, Play in Xs)
- File sender with character routing
- Approve/deny actor flow

### Phase 4: Actor Mode (1 week)
- File receiver with chunk assembly + MD5 verify
- Soundpad integration (Windows)
- VRChat OSC integration

### Phase 5: Polish & Ship (1 week)
- Tauri updater integration
- Windows code signing
- Testing on clean Windows machines
- Distribution

**Total: ~4-5 weeks**

---

## 6. Success Criteria

- [ ] SSL fix: Users on Tailscale Funnel connect without certificate errors
- [ ] SSL fix: Existing Caddy reverse proxy path still works
- [ ] Tauri: Director mode matches current Python client feature-for-feature
- [ ] Tauri: Actor mode matches current Python client feature-for-feature
- [ ] Tauri: File transfers work end-to-end between Tauri clients and Python server
- [ ] Tauri: Auto-update works via Tauri updater
- [ ] Tauri: Windows executable works on clean Windows machines (no Python required)
