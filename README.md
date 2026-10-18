# vrcActorSync

*Formerly vrActorAssist.* A director/actor communication system for VRChat filmmaking. Director sends commands, actors receive and execute Soundpad sounds.

> **v0.4 preview (branch `feat/web-ui`):** one desktop app for directors, actors and camera operators — a Python agent with a web UI (pywebview window or any browser), an animated network graph, dark/light themes and VR-sized controls. It works with today's v0.3 relay. See [Desktop app (v0.4 preview)](#desktop-app-v04-preview) and [AGENTS.md](AGENTS.md).

## Quick Start

### For Directors

Download **vrDirectorClient.exe** (Windows) or **vrDirectorClient** (Linux) from [Releases](https://github.com/virtualvert/vrActorAssist/releases).

Run it and enter:
- **Server URL** — provided by server owner (e.g., `ws://192.168.1.100:5555/ws`)
- **Director's Secret** — password from server owner

### For Actors

Download **vrActorClient.exe** (Windows) from [Releases](https://github.com/virtualvert/vrActorAssist/releases).

Run it and enter:
- Server URL and your actor name
- Choose where to save received files
- Configure Soundpad path if not in default location
- Click Connect and wait for director approval

## Releases

See [GitHub Releases](https://github.com/virtualvert/vrActorAssist/releases) for downloadable builds.

| File | Platform | Description |
|------|----------|-------------|
| `vrDirectorClient.exe` | Windows | Standalone director client |
| `vrActorClient.exe` | Windows | Standalone actor client |
| `vrDirectorClient` | Linux | Standalone director client |

> **Note:** No Linux actor binary is distributed. `soundpad.py` is Windows-only; Linux actors can run from source if needed. See [Platform Strategy](#platform-strategy) below.

| Version | Notes |
|---------|-------|
| v0.1.0 | Initial release — basic WebSocket client, Soundpad integration |
| v0.2.0 | Selective actor triggering, file transfer, status indicators, VR-friendly buttons |
| v0.2.1 | Configurable Soundpad path, duplicate actor fix |
| v0.2.2 | Forget Actor flow, cross-platform builds, code cleanup |
| v0.3.0 | Multi-file batch transfer, character routing, protocol versioning, auto-updater, cancel batch, overwrite dialog |
| v0.3.3 | SSL cert fix for Windows PyInstaller builds — explicit SSLContext + certifi |

## Commands

Director can send:

| Command | Action |
|---------|--------|
| `*go` | Play selected sound in Soundpad |
| `*stop` | Stop playback |

**Play in 3s:** Button sends `*go` after 3-second countdown. Actors receive nothing until countdown completes.

## Deployment

| Scenario | Server URL |
|----------|------------|
| Local network | `ws://192.168.1.100:5555/ws` |
| Tailscale tailnet | `ws://100.104.39.106:5555/ws` |
| Tailscale Funnel (public) | `wss://<tailscale-dns-name>/ws` |
| Public domain (Caddy) | `wss://actor.yourdomain.com/ws` |

### Public Domain Setup (Optional)

Use Caddy for auto-HTTPS:

```bash
# Caddyfile
actor.yourdomain.com {
    reverse_proxy localhost:5555
}
```

## Architecture

```
┌─────────────────────────────────────┐
│         Server (VPS)                │
│  - WebSocket endpoint: /ws          │
│  - Director auth via shared secret   │
│  - Actor approval system            │
└─────────────────────────────────────┘
                 │
     ┌───────────┼───────────┐
     ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│Director │ │ Actor 1 │ │ Actor 2 │
│(Linux)  │ │(Windows)│ │(Windows)│
│         │ │Soundpad │ │Soundpad │
└─────────┘ └─────────┘ └─────────┘
```

## Development

### Install Dependencies

```bash
# Server
pip install fastapi uvicorn websockets

# Clients (from source)
pip install websocket-client PySide6
```

### Start the Server

```bash
python server_ws.py --port 5555 --secret your-secret-here
```

### Run from Source

```bash
# Director client
python director_client_ws.py

# Actor client
python actor_client_ws.py
```

### Build Executables

```bash
pip install pyinstaller

python build_exe.py          # Build actor client (default)
python build_exe.py actor    # Build actor client
python build_exe.py director # Build director client
python build_exe.py all      # Build both
```

Output:
- **Windows:** `dist/vrActorClient.exe` / `dist/vrDirectorClient.exe`
- **Linux:** `dist/vrDirectorClient` only (actor build skipped — see [Platform Strategy](#platform-strategy))

## Project Structure

```
vrcActorSync/
├── server_ws.py          # WebSocket server (FastAPI)
├── director_client_ws.py # Director GUI (Python/tkinter)
├── actor_client_ws.py    # Actor GUI with Soundpad (Python/tkinter)
├── shared.py             # Protocol utilities
├── soundpad.py           # Soundpad CLI integration
├── build_exe.py          # PyInstaller build script
├── requirements.txt      # Dependencies
├── FEATURES-PLANNED.md   # Planned features
├── ROADMAP.md            # Future roadmap
│
├── agent/                # v0.4 desktop agent (python -m agent)
├── web/                  # v0.4 web UI (Svelte 5 + Vite, built with Bun)
├── tools/                # soundpad_probe.py (Windows Soundpad API check)
├── AGENTS.md             # Project guide for contributors and coding agents
│
├── docs/superpowers/     # Design specs and implementation plans
│
├── legacy/               # TCP socket version (reference)
│   ├── server.py
│   ├── director_client.py
│   └── actor_client.py
│
└── archive/              # Early prototypes
    └── *03.py, *04.py
```

## Desktop app (v0.4 preview)

The new app replaces both tkinter clients. It opens straight into your role (picked on first launch, or imported from your v0.3 `actor_config.json` / `director_config.json`).

```bash
python -m venv .venv
.venv/bin/pip install -r agent/requirements.txt
bun --cwd=web install
bun --cwd=web run build
.venv/bin/python -m agent
```

- Windows shows a desktop window (needs the Microsoft WebView2 Runtime); Linux opens your browser. **Settings → Open in browser** opens the same live UI in any browser.
- Desktop window on Linux: install `python-gobject` and `webkit2gtk-4.1`, create the venv with `--system-site-packages`, `pip install pywebview`, then run `.venv/bin/python -m agent --window`.
- Try the UI without a relay: `bun --cwd=web run dev`, then open http://localhost:5173/?demo=director (or `actor`, `camera`).
- Works with the current v0.3 relay: cast list, approvals, Go / Play in 3s / Stop, chat, Soundpad and OSC cues. Not yet: file transfer, OBS control, installer/auto-update. Details in [AGENTS.md](AGENTS.md#known-gaps-v04-preview) and the [design spec](docs/superpowers/specs/2026-10-17-vrcActorSync-web-ui-agent-design.md).

## Requirements

### Server (VPS)
- Python 3.8+
- fastapi, uvicorn, websockets

### Director (Linux/Windows/macOS)
- Python 3.8+ (if running from source)
- websocket-client, tkinter
- **OR** use standalone executable (no Python needed)

### Actor (Windows)
- **Windows 10/11** for Soundpad integration
- Soundpad installed
- Python 3.8+ (if running from source)
- **OR** use standalone `vrActorClient.exe` (no Python needed)

> **Note:** Actor builds are Windows-only. Soundpad has no Linux equivalent, so Linux actor binaries are not distributed. The source code remains cross-platform for future Pipewire support. See [ROADMAP.md](ROADMAP.md).

## Future

See [ROADMAP.md](ROADMAP.md) for planned features:
- **Tauri v2 + Svelte migration** — Replacing Python/tkinter clients with a modern desktop app
- OSC cue editor with audio player
- Multiple director support
- Ping compensation/delay
- OpenVR/OpenXR overlay
- Web dashboard for server admin

---

## Platform Strategy

| Client | Windows | Linux | Notes |
|--------|---------|-------|-------|
| **Director** | ✅ Full feature | ✅ Full feature | Cross-platform, no OS-specific dependencies |
| **Actor** | ✅ Full feature | ⛔ Build not distributed | Soundpad.exe Windows-only; source still runs on Linux for chat/file receive |

We are migrating both clients from **Python/tkinter** to **Tauri v2 + Svelte** in v0.4.0 for a modern, cross-platform desktop app with a Rust backend. The Python server stays unchanged. See [ROADMAP.md](ROADMAP.md) for details.
