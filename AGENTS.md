# AGENTS.md — vrcActorSync

Guide for AI coding agents (and humans) working in this repo. Keep it accurate when you change how things work.

## What this project is

**vrcActorSync** (formerly *vrActorAssist*) keeps a VRChat film production in sync. A **director** calls cues from one place; **actors** get those cues on their own PCs, where Soundpad plays their lines/sound effects and VRChat avatar parameters fire over OSC; **camera operators** (OBS) roll on cue. Everyone connects through a small **relay server** on a VPS (Caddy or Tailscale Funnel in front).

Two generations live side by side right now:

| | v0.3.x (released) | v0.4 (in development, branch `feat/web-ui`) |
|---|---|---|
| Clients | `director_client_ws.py`, `actor_client_ws.py` (tkinter, PyInstaller exes) | One app for every role: Python **agent** (`agent/`) + **web UI** (`web/`), shown in a pywebview window or any browser |
| Relay | `server_ws.py` (FastAPI, pipe-delimited protocol on `/ws`); frozen copy in `tests/legacy_relay/` | `server/` (started by `server_ws.py`): protocol v2 on `/v2/ws`, and `/ws` for v0.3 clients through a bridge |
| Protocol | `shared.py` (`format_message` / `parse_message`) | `protocol/vrcas_protocol` (pydantic; TS types generated). The agent speaks v2 (`agent/relay_v2.py`) and falls back to v0.3 (`agent/relay_legacy.py`); UI ↔ agent contract in `web/src/lib/protocol.ts` |

The v0.4 design lives in `docs/superpowers/specs/2026-10-17-vrcActorSync-web-ui-agent-design.md` (architecture, protocol v2, Soundpad named-pipe API, OSC timeline editor, OBS addon, packaging, backward compatibility). Read the relevant section before larger changes.

## Repo map

```
server_ws.py            Relay entry point. Run: python server_ws.py --port 5555 --secret ... [--host] [--data-dir] [--no-legacy]
server/                 The relay (FastAPI): /v2/ws (protocol v2), /ws (v0.3 clients), / and /health (spec §6)
  app.py                create_app(settings, clock): endpoints, status loop
  relay.py              Shared state and operations: approve / deny / forget, replacing old connections, ping + status loop
  router.py             /v2/ws: hello / welcome, permission check, routing by `to`, presence.roster / .latency, time.pong
  legacy_bridge.py      /ws: the v0.3 handler (byte for byte), translation to and from v2, scheduling emulation
  permissions.py        Spec §5.5 table as data, and which v2 type each v0.3 message counts as
  sessions.py           Session, Registry (connection order, session ids), Approvals (approved_actors.json)
  settings.py           Settings (secret, data dir, intervals) and the server.log writer
  timesync.py, updates.py  Server clock (fake-able); version checks and the update manifest
protocol/vrcas_protocol/  Protocol v2: envelope + one pydantic model per message type (MODELS)
scripts/gen_ts_types.py Generates web/src/protocol/types.ts from vrcas_protocol (--check exits 1 if stale)
shared.py               v0.3 pipe protocol, APP_VERSION, machine id, config helpers
soundpad.py             Soundpad via `Soundpad.exe -rc <command>` (Windows; simulates elsewhere)
actor_client_ws.py      v0.3 tkinter actor client (Soundpad, OSC, file receive, self-updater)
director_client_ws.py   v0.3 tkinter director client (cues, approvals, file batches, OSC toggle)
build_exe.py            PyInstaller builds for the v0.3 clients
build_agent.py          PyInstaller build for the v0.4 agent (dist/vrcActorSync[.exe]); entry: agent_entry.py
update_manifest.json    Relay-side update manifest (read from the relay's data dir)
start-server*.sh        VPS start/stop scripts (Caddy / Tailscale Funnel)

agent/                  v0.4 desktop agent (python -m agent)
  __main__.py           CLI, port pick, uvicorn server, window vs browser
  core.py               Agent: config + relay + actor runtime; snapshot() = UI state; _call_* = UI requests
  relay.py              The relay connection: reconnect loop, Play-in-3s countdown; tries /v2/ws, else /ws
  relay_v2.py           Protocol v2 client: hello, roster with session ids, approvals, cue.* / osc.param + cue.ack
  relay_legacy.py       Compatibility mode (v0.3 relay): REGISTER, roster from USERS/STATUS/PENDING, cues via PRIV
  actor_runtime.py      Cues → Soundpad (pipe, else soundpad.py -rc), live playback status, VRChat OSC
  soundpad_pipe.py      Soundpad named-pipe client: one worker thread, typed helpers, fake-able transport
  web.py                Local UI server: Host/Origin guard, one-time token → session cookie, /ui/ws
  hub.py                Fan-out of state/log/traffic events to every open UI
  shell.py              pywebview window (Windows + WebView2) or default browser
  config.py             JSON config, data dir (installed / portable / VRCAS_DATA_DIR), v0.3 config import
  tests/                pytest (end to end against the new relay with scripted v0.3 clients, and against v0.3.3)

web/                    v0.4 UI: Svelte 5 + Vite + TypeScript, built and tested with Bun
  src/lib/protocol.ts   UI ↔ agent contract (AppState, events, calls). Mirror of agent/core.py snapshot()
  src/protocol/types.ts Relay protocol v2 types, generated (don't edit; the UI doesn't import them yet)
  src/lib/transport/    AgentTransport (/ui/ws), DemoTransport (simulated session), chooser
  src/lib/demo/         DemoSession: in-page simulation used by `bun run dev` and `?demo`
  src/lib/graph/        Animated node graph (d3-force) + pure layout math (layout.ts)
  src/lib/views/        DirectorView, ActorView, CameraView, CastPanel, CueDeck
  src/lib/components/   Shell pieces: TopBar, Settings, Onboarding, LogDrawer, Button, ...
  src/app.css           Design tokens: dark/light themes, --ui-scale, VR mode, motion

tools/soundpad_probe.py Windows-only probe for Soundpad's named-pipe API (spec Appendix B);
                        results go to tools/probe-results/ (git-ignored: sound titles and paths)
tools/vrchat_window_probe.py  Windows-only VRChat window ↔ recording-size probe (spec §8.5.8, Appendix C);
                        window-manager calls only (EAC), read-only unless --resize / --restore
tests/                  Relay tests: protocol, permissions, v2 relay, bridge, scheduling, v0.3 hotfixes
  legacy_relay/         Frozen v0.3.3 server_ws.py: source of the golden transcript, fallback target for agent tests
  golden/               Recorded v0.3 session that /ws must reproduce byte for byte
  legacy_client.py      Scripted v0.3 client + the golden session (--record re-records from the frozen relay)
  relay_helpers.py      In-process relay, v2 and v0.3 test clients, fake clock
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

# full stack locally (--data-dir keeps approved_actors.json / server.log out of the checkout)
.venv/bin/python server_ws.py --port 5599 --secret local-test-secret --data-dir /tmp/vrcas-relay
bun --cwd=web run build          # the agent serves web/dist
.venv/bin/python -m agent --role director --name Mira --server 127.0.0.1:5599
VRCAS_MACHINE_ID=test-actor .venv/bin/python -m agent --role actor --name Coda --server 127.0.0.1:5599 --port 47810 --data-dir /tmp/vrcas-actor
```

After changing `protocol/vrcas_protocol`, regenerate the TypeScript types: `.venv/bin/python scripts/gen_ts_types.py`.

The relay matches connections by machine id, and every client on one PC shares it (derived from the host name), so give each extra agent on a PC its own `VRCAS_MACHINE_ID` (as above). Otherwise it replaces the connection in the same role and inherits that machine's approval. v0.3.3 clients take a `ws://` address with the path (`ws://host:5599/ws`); the director doesn't add `/ws` itself.

The live relay runs from the main checkout (`venv/bin/python server_ws.py --host 127.0.0.1 --secret …` on port 5555, behind Tailscale Funnel), and it has real testers. Never stop, restart or signal it, and don't run `start-server*.sh`, unless the user asks; test relays go on ports 5600+ with their own `--data-dir`. The switch-over steps and the rollback are part B of `docs/superpowers/plans/2026-10-20-relay-v2-checklist.md`.

Useful agent flags: `--headless` (browser instead of window), `--window` (pywebview window on Linux), `--no-open` (print the one-time UI URL), `--dev` (accept the Vite dev server origin so `bun run dev` can proxy to a running agent), `--data-dir`, `--portable`.

Standalone build (no Python or Bun on the target): `.venv/bin/pip install pyinstaller`, then

```bash
.venv/bin/python build_agent.py             # bun web build + one file: dist/vrcActorSync (vrcActorSync.exe on Windows)
.venv/bin/python build_agent.py --onedir    # one folder: dist/vrcActorSync/  (--skip-web reuses web/dist)
```

Build on the OS you're targeting (PyInstaller doesn't cross-compile). Windows builds are windowed (pywebview + WebView2); Linux builds are console programs that open the browser; they have no window, and `--window` only works from a source checkout (a bundled Qt WebEngine window was tried: ~500 MB and tied to the build machine's glibc). On Linux the build prints the oldest glibc the binary accepts: with uv's standalone Python it was 2.35 (from the bundled libgcc_s), with a distro Python it can be the build machine's own glibc. Never name the output `vrActorClient*` / `vrDirectorClient*`. `build_exe.py` deletes `dist/` when it runs.

Desktop window: Windows uses pywebview + WebView2 by default. On Linux it's opt-in with `--window` and uses the system WebKit2GTK through PyGObject, so the venv must see system packages: install `python-gobject` and `webkit2gtk-4.1` (Arch/CachyOS names), create the venv with `python -m venv --system-site-packages .venv`, then `pip install pywebview`.

## Tests and checks — run before you finish

```bash
.venv/bin/python -m pytest agent/tests tests -q   # agent + relay: golden v0.3 transcript, permissions, end to end
bun --cwd=web test                            # layout, formatting, demo session
bun --cwd=web run check                       # svelte-check / TypeScript (0 errors, 0 warnings expected)
bun --cwd=web run build
```

There are no tests for the v0.3 tkinter clients; test changes there by hand. Relay changes that could reach v0.3.3 clients get the manual checklist too (part A: real v0.3.3 clients and a Windows build against a test relay).

## Rules that keep things working

- **Backward compatibility is a requirement.** v0.3 clients in the field must keep working with the relay (`/ws`, pipe protocol, `PING`/`PONG`, `REGISTER|name|machine_id|role|secret|version|platform`). Don't change existing message formats in `shared.py`; add, don't alter. `/ws` must reproduce `tests/golden/legacy_session.txt` byte for byte; don't re-record it to make a change pass (it comes from the frozen v0.3.3 relay). The v0.3 updater swaps files named `vrActorClient*` / `vrDirectorClient*`, so those build names stay.
- **The UI contract has two sides.** Changing `AppState`, events or calls in `web/src/lib/protocol.ts` means changing `agent/core.py` (`snapshot()` / `_call_*`) and `web/src/lib/demo/session.ts` in the same change.
- **Local server security** (`agent/web.py`): bind 127.0.0.1 only; check `Host` on every request and `Origin` on POST/WebSocket; data and sockets need the session cookie from a one-time `?t=` token. Never send secrets (director secret, future OBS password) to the UI — expose `hasSecret`-style booleans. Don't write one-time UI links to the log file.
- **Permissions are data.** `server/permissions.py` holds the §5.5 table; the relay checks every v2 message, and every v0.3 message as its v2 type, against it. A new message type needs a row there (and a model in `vrcas_protocol` if the relay reads it), or the relay answers `unknown_type`. A v0.3.3 relay only enforces the director boundary (director secret; cues and file pushes from directors only), so compatibility mode can't rely on it for more.
- **Protocol models are the source of truth.** Change `protocol/vrcas_protocol`, then run `scripts/gen_ts_types.py`; `tests/test_protocol.py` fails while `web/src/protocol/types.ts` is stale. Where the built relay differs from the spec is listed in spec §20.1.
- **UI sizing:** use `rem` (it tracks the UI scale) and `var(--target)` for hit targets; collapse layouts with container queries (`@container`), not media queries, so breakpoints follow the scaled UI. Colours come from tokens in `app.css` — define new ones for both themes. Respect `[data-motion="reduce"]`.
- **Svelte 5 runes:** don't name a prop or local `state` (it collides with `$state`); the codebase uses `data`.
- **Node graph:** layout math belongs in `graph/layout.ts` (pure, unit-tested). Nodes are mutable objects shared with d3; template reads go through `specOf(n, frame)` / `nodeTransform(n, frame)` so they re-render.
- **Windows-only pieces** (Soundpad, WebView2 window) can't be exercised on Linux: `soundpad.py` simulates, the agent opens the browser. Say so when reporting results instead of claiming they were tested.
- **Naming:** the project is *vrcActorSync*. Env vars use `VRCAS_`, the cookie/storage prefix is `vrcas`. GitHub URLs still point at `virtualvert/vrActorAssist` until the repository is renamed.

## Known gaps (v0.4 preview)

- The v2 relay is built and merged into `feat/web-ui` (2026-10-21), and part A of its manual checklist passes. The live relay runs from this checkout but still runs the old code (v0.3.3) until it's restarted; until then the agent uses compatibility mode there, and camera operators stay invisible. Whatever restarts it next, for any reason, starts the new relay. Not built on v2 yet: the agent-side scheduler (Play in 3s is a local countdown, then Go), files over v2 (v0.3 ↔ v0.3 transfers through `/ws` still work), cue-list storage, ICE/TURN, hosting the web app, storing `stage.*`. v0.3 directors never see cameras, so a v2 director or assistant has to approve them. Session ids last until the relay restarts. Assistants aren't a role in the UI yet.
- File transfer isn't in the new app (actors decline `FILEREQ` with a clear reason).
- Soundpad cues (Go / Stop / `*play:N`) go through the named pipe, with `-rc` as the fallback. Actors run `*play:N`, but the director UI only sends Go / Stop / countdown, so nothing in the new app sends it yet. The rest of the soundpad addon (sound references, picker, volume / pause / seek messages) and scheduling (§8.2) aren't built.
- No tray icon, installer or auto-updater yet; closing the window quits. In browser mode, Ctrl+C in the terminal quits. With no terminal (a Windows build without WebView2, or a Linux build started from a file manager), the only way to quit is ending the process.
- `build_agent.py`: the Linux one-file build is tested (CachyOS): UI, relay connection, director → actor cue, `--portable`, Ctrl+C. The Windows one-file build is tested too (Windows 11, Python 3.12, PyInstaller 6.22, pywebview 6.2 on WebView2 155): the window opens without the browser fallback, the actor drives Soundpad through the named pipe while frozen, Go / Stop / countdown and `*play:N` play against a local relay, closing the window ends the process, and `--portable` keeps its data beside the exe. An actor on the live `wss://` relay (Tailscale Funnel) gets approved and plays Go / Stop. The exe is unsigned: a copy marked as downloaded gets SmartScreen's "Windows protected your PC" block. Not tried yet: a PC without the WebView2 Runtime.
- OBS addon, OSC timeline editor and P2P streaming are designed (spec §8.3, §8.5, §8.6), not built.
