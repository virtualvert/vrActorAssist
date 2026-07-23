# vrActorAssist: SSL Fix + Tauri Migration Design

**Date:** 2026-07-20 (amended 2026-07-23)  
**Status:** Approved  
**Version:** 1.1

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-07-20 | Initial approved design (SSL fix + Tauri migration) |
| 1.1 | 2026-07-23 | SSL fix marked shipped (v0.3.3). Added: packaging & distribution matrix (§4.11), auto-update architecture via GitHub Releases (§4.12), deployment & domain change to `vra.dannygreyproductions.com` (§4.13), branch & release strategy (§4.14). Dropped macOS from v0.4.0 targets. Python clients frozen at v0.3.3. v0.4.0 scope locked to feature parity only. |

---

## 1. Problem Statement

### 1.1 SSL Certificate Verification Errors

Users connecting to the vrActorAssist server via Tailscale Funnel receive "SSL certificate verify failed" errors when using PyInstaller-built `.exe` files on Windows.

**Root cause:** The `websocket-client` library is passed `sslopt={"cert_reqs": ssl.CERT_NONE}` as a dict, which is unreliable in PyInstaller builds on Windows. Python's SSL module cannot locate system CA certificates in a frozen environment, and `certifi` is not bundled. The SSL context creation itself fails before `cert_reqs` is ever evaluated.

### 1.2 User Experience Limitations

The current tkinter-based GUI is functional but dated — hard to theme, not touch-friendly, and visually inconsistent across Windows versions. A modern replacement is desired.

---

## 2. Scope

- **SSL fix** — ✅ SHIPPED in v0.3.3. Kept below for historical record (§3).
- **Tauri migration** — Replace both Director and Actor Python clients with a single Tauri v2 + Svelte desktop application. **v0.4.0 scope is feature parity only** — no new features beyond what the Python clients do today (plus the Tauri updater). New features (OSC cue editor, Linux PipeWire actor, session recording, etc.) remain on the roadmap for v0.5+.
- **Server stays** — The Python FastAPI/WebSocket server is NOT being replaced. It continues running on the VPS behind a Caddy reverse proxy at `vra.dannygreyproductions.com` (primary) or Tailscale Funnel (alternative). See §4.13.
- **Python clients frozen** — v0.3.3 is the final Python client release. No further Python client builds; they keep working against the server until the Tauri client ships.
- **Packaging** — Windows NSIS installer (auto-updating) + Windows portable exe (update notifications only) + Linux AppImage (portable *and* auto-updating). No macOS builds in v0.4.0. See §4.11.
- **Releases** — GitHub Releases + GitHub Actions CI as the update/distribution channel. Unsigned Windows builds (SmartScreen "Run anyway" accepted for the known user group). See §4.12/§4.14.

---

## 3. SSL Fix (Phase 1 — ✅ Shipped as v0.3.3)

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

### 4.10 Cross-Platform Matrix (v0.4.0)

| Feature | Windows | Linux |
|---------|---------|-------|
| Director mode | ✅ | ✅ |
| Actor mode | ✅ | Partial (no Soundpad) |
| Soundpad | ✅ | N/A |
| VRChat OSC | ✅ | ✅ (generic OSC) |

macOS is out of scope for v0.4.0 (no known macOS users; Apple signing/notarization deferred). It may return in a later release.

### 4.11 Packaging & Distribution

One codebase, three artifacts per release:

| Artifact | Platform | Install | Auto-update |
|----------|----------|---------|-------------|
| `vrActorAssist_<ver>_x64-setup.exe` (NSIS) | Windows | Installed | ✅ Full self-update via `tauri-plugin-updater` |
| `vrActorAssist_<ver>_portable.exe` | Windows | Portable (single exe) | 🔔 Notify-only: detects new version, links to the GitHub release; user replaces the file manually |
| `vrActorAssist_<ver>_amd64.AppImage` | Linux | Portable (single file) | ✅ Full self-update via `tauri-plugin-updater` (AppImage is supported) |

**Portable detection (Windows):** at startup the Rust backend checks for an `uninstall.exe` sibling next to the running executable. Present → installed build (auto-update enabled). Absent → portable build (notify-only). On Linux, the `APPIMAGE` env var indicates an updatable AppImage; without it, fall back to notify-only.

**Portable config location:** portable builds store `config.json` next to the executable; installed builds use the OS config dir (`%APPDATA%/com.dannygrey.vractorassist` / `~/.config/com.dannygrey.vractorassist`).

**Windows prerequisite:** WebView2 runtime (preinstalled on Windows 10/11; NSIS bundle downloads it if missing, portable exe requires it present).

### 4.12 Auto-Update Architecture

- **Channel:** GitHub Releases on `virtualvert/vrActorAssist`. CI publishes artifacts plus a Tauri-signed `latest.json` manifest.
- **Endpoint:** `https://github.com/virtualvert/vrActorAssist/releases/latest/download/latest.json`
- **Signing:** Tauri updater keypair (`minisign`-style) generated once; private key + password stored as GitHub Actions secrets (`TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`). This is independent of Windows code signing (which we skip for now).
- **Flow (installed/AppImage):** app checks endpoint on launch → prompts user → downloads, verifies signature, installs, relaunches.
- **Flow (portable):** app checks the same endpoint → shows a notification bar with release notes and a "Download" button opening the release page. No self-replacement.
- **Python-era updater:** `update_manifest.json` on the server stays as-is for the frozen v0.3.3 clients; it is not used by the Tauri client.

### 4.13 Deployment & Domain

- **Primary:** VPS with Caddy reverse proxy, domain **`vra.dannygreyproductions.com`** (replaces `relay.dannygreyproductions.com` — old domain retired). Caddy terminates TLS; server listens on `localhost:5555`.
- **Alternative:** Tailscale Funnel (public HTTPS through Tailscale) via `start-server-ts.sh` — unchanged mechanism.
- **Client default server URL:** `wss://vra.dannygreyproductions.com/ws`.
- **Server code:** unchanged. Only `start-server.sh` (Caddy domain) and documentation change.

### 4.14 Branch & Release Strategy

- All Tauri work happens on a new **`tauri`** branch off `main`; merged back to `main` when v0.4.0 ships.
- `main` stays the home of the frozen Python clients and server until then; server/ops fixes land on `main` and merge into `tauri` as needed.
- **Release process:** push a `v0.4.x` tag on the release branch → GitHub Actions (`tauri-action`) builds Windows (NSIS + portable) on `windows-latest` and AppImage on `ubuntu-22.04`, signs update artifacts, and publishes the GitHub Release with `latest.json`.

---

## 5. Migration Phases & Timeline

### Phase 1: SSL Fix — ✅ DONE (shipped as v0.3.3)
- `build_exe.py` hidden imports
- SSL context refactor in both clients
- Rebuild, update manifest, ship

### Phase 2: Branch + Tauri Scaffold (1 week)
- Create `tauri` branch; update deployment scripts to `vra.dannygreyproductions.com`
- `npm create tauri-app@latest` with Svelte template under `client/`
- Rust WebSocket client with protocol parser (+ unit tests against `shared.py` formats)
- Shared UI: mode selector, connection panel, chat, settings
- Config persistence (portable vs installed aware)

### Phase 3: Director Mode (1 week)
- Actor list with latency status dots and enable/disable checkboxes
- Cue buttons (Go, Stop, Play in Xs), OSC cue triggers on Go/Stop
- File sender with character routing and batch protocol
- Approve/deny/forget actor flow

### Phase 4: Actor Mode (1 week)
- File receiver with chunk assembly + MD5 verify, auto-accept toggle
- Soundpad integration (Windows)
- VRChat OSC integration

### Phase 5: Distribution & Ship (1 week)
- Tauri updater integration (installed/AppImage) + notify-only path for portable
- Updater signing keys, GitHub Actions release workflow (`tauri-action`)
- Testing on clean Windows machines (unsigned — SmartScreen "Run anyway")
- Tag `v0.4.0`, publish GitHub Release, merge `tauri` → `main`

**Total: ~4-5 weeks**

---

## 6. Success Criteria

- [x] SSL fix: Users on Tailscale Funnel connect without certificate errors (v0.3.3)
- [x] SSL fix: Existing Caddy reverse proxy path still works (v0.3.3)
- [ ] Tauri: Director mode matches current Python client feature-for-feature
- [ ] Tauri: Actor mode matches current Python client feature-for-feature
- [ ] Tauri: File transfers work end-to-end between Tauri clients and Python server
- [ ] Tauri: Installed (NSIS) and AppImage builds auto-update via Tauri updater from GitHub Releases
- [ ] Tauri: Windows portable build shows an update notification with a working download link (no self-update)
- [ ] Tauri: Windows executable works on clean Windows machines (no Python required)
- [ ] Server reachable at `wss://vra.dannygreyproductions.com/ws` behind Caddy; Tailscale Funnel path still works
- [ ] Release pipeline: pushing a version tag produces all three artifacts + signed `latest.json` automatically
