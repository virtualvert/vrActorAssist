# AGENTS.md — vrcActorSync

Guide for AI coding agents (and humans) working in this repo. Keep it accurate when you change how things work.

## What this project is

**vrcActorSync** (formerly *vrActorAssist*) keeps a VRChat film production in sync. A **director** calls cues from one place; **actors** get those cues on their own PCs, where Soundpad plays their lines/sound effects and VRChat avatar parameters fire over OSC; **camera operators** (OBS) roll on cue. Everyone connects through a small **relay server** on a VPS (Caddy or Tailscale Funnel in front).

Two generations live side by side right now:

| | v0.3.x (released) | v0.4 (in development, branch `feat/web-ui`) |
|---|---|---|
| Clients | `director_client_ws.py`, `actor_client_ws.py` (tkinter, PyInstaller exes) | One app for every role: Python **agent** (`agent/`) + **web UI** (`web/`), shown in a pywebview window or any browser |
| Relay | `server_ws.py` (FastAPI, pipe-delimited protocol on `/ws`) | Same server for now; v2 JSON protocol on `/v2/ws` is designed, not built |
| Protocol | `shared.py` (`format_message` / `parse_message`) | Agent talks v0.3 protocol to the relay (`agent/relay_legacy.py`); UI ↔ agent contract in `web/src/lib/protocol.ts` |

The v0.4 design lives in `docs/superpowers/specs/2026-10-17-vrcActorSync-web-ui-agent-design.md` (architecture, protocol v2, Soundpad named-pipe API, OSC timeline editor, OBS addon, packaging, backward compatibility). Read the relevant section before larger changes.

## Repo map

```
server_ws.py            v0.3 relay (FastAPI + WebSocket /ws). Run: python server_ws.py --port 5555 --secret ...
shared.py               v0.3 pipe protocol, APP_VERSION, machine id, config helpers
soundpad.py             Soundpad via `Soundpad.exe -rc <command>` (Windows; simulates elsewhere)
actor_client_ws.py      v0.3 tkinter actor client (Soundpad, OSC, file receive, self-updater)
director_client_ws.py   v0.3 tkinter director client (cues, approvals, file batches, OSC toggle)
build_exe.py            PyInstaller builds for the v0.3 clients
update_manifest.json    Relay-side update manifest read by server_ws.py
start-server*.sh        VPS start/stop scripts (Caddy / Tailscale Funnel)

agent/                  v0.4 desktop agent (python -m agent)
  __main__.py           CLI, port pick, uvicorn server, window vs browser
  core.py               Agent: config + relay + actor runtime; snapshot() = UI state; _call_* = UI requests
  relay_legacy.py       Connection to a v0.3 relay: REGISTER, roster from USERS/STATUS/PENDING, cues via PRIV
  actor_runtime.py      Soundpad (soundpad.py) and VRChat OSC (python-osc)
  web.py                Local UI server: Host/Origin guard, one-time token → session cookie, /ui/ws
  hub.py                Fan-out of state/log/traffic events to every open UI
  shell.py              pywebview window (Windows + WebView2) or default browser
  config.py             JSON config, data dir (installed / portable / VRCAS_DATA_DIR), v0.3 config import
  tests/                pytest (includes an end-to-end run against the real server_ws.py)

web/                    v0.4 UI: Svelte 5 + Vite + TypeScript, built and tested with Bun
  src/lib/protocol.ts   UI ↔ agent contract (AppState, events, calls). Mirror of agent/core.py snapshot()
  src/lib/transport/    AgentTransport (/ui/ws), DemoTransport (simulated session), chooser
  src/lib/demo/         DemoSession: in-page simulation used by `bun run dev` and `?demo`
  src/lib/graph/        Animated node graph (d3-force) + pure layout math (layout.ts)
  src/lib/views/        DirectorView, ActorView, CameraView, CastPanel, CueDeck
  src/lib/components/   Shell pieces: TopBar, Settings, Onboarding, LogDrawer, Button, ...
  src/app.css           Design tokens: dark/light themes, --ui-scale, VR mode, motion

tools/soundpad_probe.py Windows-only probe for Soundpad's named-pipe API (spec Appendix B)
docs/superpowers/       Design specs and plans (dated; older ones are historical records)
legacy/, archive/       TCP-era and prototype code. Reference only; don't modify
```

## Running things

Prerequisites: Python 3.10+, [Bun](https://bun.sh) (used instead of Node for everything in `web/`).

```bash
# one-time
python -m venv .venv && .venv/bin/pip install -r agent/requirements-dev.txt
bun --cwd=web install

# web UI alone, simulated session (no agent or relay needed): http://localhost:5173
bun --cwd=web run dev            # add ?demo=director | actor | camera to pick a role

# full stack locally
.venv/bin/python server_ws.py --port 5599 --secret local-test-secret
bun --cwd=web run build          # the agent serves web/dist
.venv/bin/python -m agent --role director --name Mira --server 127.0.0.1:5599
VRCAS_MACHINE_ID=test-actor .venv/bin/python -m agent --role actor --name Coda --server 127.0.0.1:5599 --port 47810 --data-dir /tmp/vrcas-actor
```

Useful agent flags: `--headless` (browser instead of window), `--window` (pywebview window on Linux), `--no-open` (print the one-time UI URL), `--dev` (accept the Vite dev server origin so `bun run dev` can proxy to a running agent), `--data-dir`, `--portable`.

Desktop window: Windows uses pywebview + WebView2 by default. On Linux it's opt-in with `--window` and uses the system WebKit2GTK through PyGObject, so the venv must see system packages: install `python-gobject` and `webkit2gtk-4.1` (Arch/CachyOS names), create the venv with `python -m venv --system-site-packages .venv`, then `pip install pywebview`.

## Tests and checks — run before you finish

```bash
.venv/bin/python -m pytest agent/tests -q     # agent, incl. end-to-end against server_ws.py
bun --cwd=web test                            # layout, formatting, demo session
bun --cwd=web run check                       # svelte-check / TypeScript (0 errors, 0 warnings expected)
bun --cwd=web run build
```

There are no tests for the v0.3 tkinter clients; test changes there by hand.

## Rules that keep things working

- **Backward compatibility is a requirement.** v0.3 clients in the field must keep working with the relay (`/ws`, pipe protocol, `PING`/`PONG`, `REGISTER|name|machine_id|role|secret|version|platform`). Don't change existing message formats in `shared.py`; add, don't alter. The v0.3 updater swaps files named `vrActorClient*` / `vrDirectorClient*`, so those build names stay.
- **The UI contract has two sides.** Changing `AppState`, events or calls in `web/src/lib/protocol.ts` means changing `agent/core.py` (`snapshot()` / `_call_*`) and `web/src/lib/demo/session.ts` in the same change.
- **Local server security** (`agent/web.py`): bind 127.0.0.1 only; check `Host` on every request and `Origin` on POST/WebSocket; data and sockets need the session cookie from a one-time `?t=` token. Never send secrets (director secret, future OBS password) to the UI — expose `hasSecret`-style booleans. Don't write one-time UI links to the log file.
- **Relay roles aren't enforced by the v0.3 server** (any approved client can send `CMD`/`PRIV`). Don't rely on the server for permissions; the v2 relay design fixes this (spec §5.5, §17).
- **UI sizing:** use `rem` (it tracks the UI scale) and `var(--target)` for hit targets; collapse layouts with container queries (`@container`), not media queries, so breakpoints follow the scaled UI. Colours come from tokens in `app.css` — define new ones for both themes. Respect `[data-motion="reduce"]`.
- **Svelte 5 runes:** don't name a prop or local `state` (it collides with `$state`); the codebase uses `data`.
- **Node graph:** layout math belongs in `graph/layout.ts` (pure, unit-tested). Nodes are mutable objects shared with d3; template reads go through `specOf(n, frame)` / `nodeTransform(n, frame)` so they re-render.
- **Windows-only pieces** (Soundpad, WebView2 window) can't be exercised on Linux: `soundpad.py` simulates, the agent opens the browser. Say so when reporting results instead of claiming they were tested.
- **Naming:** the project is *vrcActorSync*. Env vars use `VRCAS_`, the cookie/storage prefix is `vrcas`. GitHub URLs still point at `virtualvert/vrActorAssist` until the repository is renamed.

## Known gaps (v0.4 preview)

- No v2 relay yet; camera operators register but stay invisible to others on a v0.3 relay.
- File transfer isn't in the new app (actors decline `FILEREQ` with a clear reason).
- Soundpad still uses `-rc`; the named-pipe client waits for the Windows probe results (spec §8.1, Appendix B).
- No tray icon, installer, auto-updater or PyInstaller build for the agent yet; closing the window quits.
- OBS addon, OSC timeline editor and P2P streaming are designed (spec §8.3, §8.5, §8.6), not built.
