# vrcActorSync

*Formerly vrActorAssist.* Keeps a VRChat film production in sync. A **director** calls cues from one place; **actors** get them on their own PCs, where Soundpad plays their lines and sound effects and VRChat avatar parameters fire over OSC; **camera operators** join the same session. Everyone connects through a small **relay server**.

| | Status |
|---|---|
| **v0.4** — one desktop app for every role (Python agent + web UI) | Preview: [`vrcActorSync.exe`](https://github.com/virtualvert/vrActorAssist/releases) (Windows), branch `feat/web-ui` |
| **v0.3** — separate tkinter director and actor clients | Stable, in use. The v0.4 relay keeps them working ([details](#v03-clients)) |

## How it works

```
                ┌──────────────────────────────┐
                │  Relay (VPS)  server_ws.py   │
                │  /v2/ws  v0.4 apps           │
                │  /ws     v0.3 clients        │
                └──────────────┬───────────────┘
        ┌──────────────┬───────┴──────┬──────────────┐
        ▼              ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
   │Director │    │ Actor 1 │    │ Actor 2 │    │ Camera  │
   │ any OS  │    │ Windows │    │ Windows │    │         │
   │         │    │Soundpad │    │Soundpad │    │         │
   │         │    │VRChat   │    │VRChat   │    │         │
   └─────────┘    └─────────┘    └─────────┘    └─────────┘
```

The relay checks the director's secret, holds new actors until a director approves them, routes cues and files, and keeps every PC's clock in sync so cues fire together.

## Quick start (v0.4 preview)

1. Download `vrcActorSync.exe` from [Releases](https://github.com/virtualvert/vrActorAssist/releases) (pre-release).
   - The exe isn't signed yet. Windows SmartScreen may say "Windows protected your PC": choose **More info → Run anyway**.
   - It opens in its own window using the Microsoft WebView2 Runtime (part of Windows 11).
2. On first launch pick your role, your name and the relay address the server owner gave you:
   - `relay.example.com` means a secure `wss://` relay (Caddy or Tailscale Funnel).
   - `192.168.1.100:5555` means a relay on its own port (`ws://`).
3. **Directors** enter the director's secret. **Actors and cameras** wait until a director approves them.

Actors also need [Soundpad](https://leppsoft.com/soundpad/) running, and OSC enabled in VRChat for avatar parameters.

## What v0.4 does

**Director**
- Cast list and network graph: who's connected, their latency, and approve / deny / forget.
- **GO**, **Play in 3s** (countdown on every PC) and **Stop**. GO fires at the same moment on every actor's PC, 300 ms after you press it (Settings → Director; 0 = at once). Each actor can have their own delay.
- Each actor's Soundpad, from the cast:
  - browse their sound list and play a sound, or arm one for the next GO;
  - choose the output (speakers, mic or both), volume, mute, pause and seek;
  - watch playback;
  - calibrate the actor's start latency.
- **Send files:** push audio to actors. Files are routed by the character name in the file name, and you can see each file's length.
- **Normalize folder:** loudness-normalize a folder of audio (default −16 LUFS, −1 dBTP ceiling) to 16-bit 48 kHz WAV in a `normalized/` subfolder.

**Actor**
- Cues drive Soundpad through its named pipe, and VRChat avatar parameters through OSC.
- Received files are saved and added to Soundpad. This needs the full version of Soundpad, and you can turn it off.
- The app measures your Soundpad start latency and compensates for it.

**Everyone:** dark and light themes, UI scale, VR mode (large controls), reduced motion.

**Not built yet:**
- OBS control for cameras;
- the OSC timeline editor;
- P2P streaming;
- tray icon, installer and auto-updater (closing the window quits);
- MP3 output in Normalize folder.

The design for these is in the [design spec](docs/superpowers/specs/2026-10-17-vrcActorSync-web-ui-agent-design.md). Current limits are in [AGENTS.md → Known gaps](AGENTS.md#known-gaps-v04-preview).

### Mixing v0.3 and v0.4

- The relay serves v0.3 clients on `/ws` unchanged and translates between them and v0.4 apps: cues, Play #N, and files in both directions.
- A v0.4 app connected to an old v0.3 relay runs in compatibility mode: cast, approvals, Go / Play in 3s / Stop, and Soundpad and OSC cues. It has no file transfer there.
- v0.3 directors don't see cameras, so a v0.4 director has to approve them.

## Running a relay

Needs Python 3.10+.

```bash
python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python server_ws.py --port 5555 --secret your-secret --data-dir /srv/vrcas
```

| Flag | |
|---|---|
| `--host` | Address to bind (default `0.0.0.0`; use `127.0.0.1` behind a proxy) |
| `--data-dir` | Where `approved_actors.json`, `server.log` and `update_manifest.json` live |
| `--no-legacy` | Refuse v0.3 clients on `/ws` |

Endpoints: `/v2/ws` (v0.4), `/ws` (v0.3), and `/health`.

| Setup | v0.4 app address | v0.3 client URL |
|---|---|---|
| Local network | `192.168.1.100:5555` | `ws://192.168.1.100:5555/ws` |
| Tailscale Funnel | `<machine>.<tailnet>.ts.net` | `wss://<machine>.<tailnet>.ts.net/ws` |
| Public domain (Caddy) | `relay.example.com` | `wss://relay.example.com/ws` |

For a public domain, Caddy provides HTTPS automatically:

```
relay.example.com {
    reverse_proxy localhost:5555
}
```

## Development

Prerequisites: Python 3.10+ and [Bun](https://bun.sh), which this project uses instead of Node for everything in `web/`.

```bash
# one-time
python -m venv .venv && .venv/bin/pip install -r agent/requirements-dev.txt
bun --cwd=web install

# UI alone with a simulated session (no relay or agent): http://localhost:5173/?demo=director (or actor, camera)
bun --cwd=web run dev

# full stack locally
.venv/bin/python server_ws.py --port 5599 --secret local-test-secret --data-dir /tmp/vrcas-relay
bun --cwd=web run build
.venv/bin/python -m agent --role director --name Mira --server 127.0.0.1:5599

# tests and checks
.venv/bin/python -m pytest agent/tests tests -q
bun --cwd=web test && bun --cwd=web run check
```

Useful agent flags:
- `--headless`: use the browser instead of a window.
- `--window`: open a desktop window on Linux. It needs `python-gobject` and `webkit2gtk-4.1`, and a venv created with `--system-site-packages` plus `pip install pywebview`.
- `--no-open`: print the UI link instead of opening it.
- `--data-dir` and `--portable`: choose where config and logs live.

To run a second agent on the same PC, give it its own `VRCAS_MACHINE_ID` and `--port`. **[AGENTS.md](AGENTS.md)** is the full contributor guide: repo map, rules that keep v0.3 working, and known gaps.

### Builds

```bash
.venv/bin/pip install pyinstaller
.venv/bin/python build_agent.py           # v0.4 → dist/vrcActorSync(.exe), one file
.venv/bin/python build_agent.py --onedir  # one folder instead
```

Build on the OS you're targeting, because PyInstaller doesn't cross-compile.
- **Windows** builds are windowed apps (WebView2).
- **Linux** builds are console programs that open your browser. They aren't published as releases.

## v0.3 clients

The tkinter clients (`director_client_ws.py`, `actor_client_ws.py`) are the current stable release. Their builds are `vrDirectorClient(.exe)` and `vrActorClient.exe`. They take the relay URL with its path, for example `wss://relay.example.com/ws`.
- The director sends `*go` (play the selected sound) and `*stop`.
- **Play in 3s** sends `*go` after a local countdown.

```bash
pip install -r requirements.txt
python director_client_ws.py        # or actor_client_ws.py
python build_exe.py all             # → dist/vrActorClient.exe, dist/vrDirectorClient(.exe); deletes dist/ first
```

| Version | Notes |
|---|---|
| v0.1.0 | Initial release: basic WebSocket client, Soundpad integration |
| v0.2.0 | Selective actor triggering, file transfer, status indicators, VR-friendly buttons |
| v0.2.1 | Configurable Soundpad path, duplicate actor fix |
| v0.2.2 | Forget Actor flow, cross-platform builds, code cleanup |
| v0.3.0 | Multi-file batch transfer, character routing, protocol versioning, auto-updater, cancel batch, overwrite dialog |
| v0.3.3 | SSL cert fix for Windows PyInstaller builds (explicit SSLContext + certifi) |
| v0.4.0-preview.1, .2 | Desktop app preview (Windows) |

## Project structure

```
server_ws.py, server/     Relay: /v2/ws (protocol v2), /ws (v0.3 bridge), /health
protocol/vrcas_protocol/  Protocol v2 message models (TypeScript types generated into web/)
agent/                    v0.4 desktop agent (python -m agent): relay link, Soundpad, OSC, files, local UI server
web/                      v0.4 UI: Svelte 5 + Vite + TypeScript, built with Bun
build_agent.py            v0.4 PyInstaller build
director_client_ws.py, actor_client_ws.py, shared.py, soundpad.py, build_exe.py   v0.3 clients
tests/, agent/tests/      Relay and agent tests (incl. a byte-for-byte v0.3 transcript)
tools/                    Windows-only probes (Soundpad pipe API, VRChat window size)
docs/superpowers/         Design specs and plans
docs/ROADMAP.md, docs/FEATURES-PLANNED.md   Earlier roadmap and feature plans (history)
legacy/, archive/         TCP-era code and prototypes (reference only)
```
