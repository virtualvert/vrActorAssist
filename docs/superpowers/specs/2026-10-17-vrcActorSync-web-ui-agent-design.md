# vrcActorSync: Desktop Web UI + Local Agent Design

**Date:** 2026-10-17 (revised 2026-10-21)
**Status:** Draft — implementation started on branch `feat/web-ui` (see §20)
**Version:** 0.13
**Supersedes:** §4 (Tauri migration) of `2026-07-20-vrcActorSync-ssl-tauri-design.md`. The `origin/tauri` branch stays as a source of reusable UI and test code.

### Changes in v0.13

- Phase 2 milestone M3 built on branch `feat/phase2-timing`: timing (§8.2). Every agent syncs its clock with the relay; GO goes out for server time now + 300 ms and Play in 3s for now + 3 s, with the countdown on the director and the actors; Stop cancels what is still waiting; per-actor delay from the cast row; start-latency calibration (`soundpad.calibrate`) and compensation; directors hold cues for older builds. Added to M3: **armed sounds** (a sound per actor that GO plays instead of the selected one). Choices are in §20.2.

### Changes in v0.12

- Phase 2 milestone M2 built on branch `feat/phase2-soundpad`: the rest of the soundpad addon (§8.1). Directors pick sounds from each actor's list by `key` (not `path`), choose the output line, change volume, mute, pause, seek, and see each actor's playback; Play #N in the cue deck; received files are added to Soundpad; actor settings for the default line, auto-add, auto-start and Detect. Choices are in §20.2.

### Changes in v0.11

- Phase 2 milestone M1b built on branch `feat/phase2-files-bridge`: files between v0.3 clients and v0.4 apps through the bridge (§11.2, §11.3), in both directions. What v0.3 clients receive is listed in §20.2.

### Changes in v0.10

- Phase 2 milestone M1a built on branch `feat/phase2-files` (plan: `docs/superpowers/plans/2026-10-21-phase2-plan.md`): files between v0.4 apps over `/v2/ws` (§8.4, §5.7), with binary chunk frames, a transfer table in the relay, Send files for directors and the accept prompt for actors. Choices are in §20.2.

### Changes in v0.9

- **Normalize folder** (§8.4.2, production helpers step 1, §15.1) built on branch `feat/normalize-folder` and merged into `feat/web-ui` on 2026-10-21 (§20): loudness per BS.1770 / R128 with 4× true peak, measured in the director's page; normalized copies go to `<folder>/normalized/`.
- §8.4.2 as built:
  - Every copy is 16-bit WAV at 48 kHz (TPDF dither). MP3 output for MP3 sources isn't built; it waits on open question 12.
  - Folder picker: the desktop window's dialog; in browser mode on Linux `kdialog` or `zenity`; otherwise a typed path.
  - The agent reads only audio files inside folders opened in this run and writes only `.wav` files under `normalized/`.

### Changes in v0.8

- Phase 0 built on branch `feat/relay-v2` and merged into `feat/web-ui` on 2026-10-21 (§20): `vrcas_protocol`, the v2 relay on `/v2/ws`, the permission table, the v0.3 bridge with scheduling emulation, golden transcripts, and the agent's v2 client with automatic fallback to compatibility mode.
- Where the build differs from §5, §6 and §11, the sections carry a short note; the full list is §20.1.
- §18 question 5 is settled as proposed: assistants may cue, play sounds and roll cameras.
- Manual checklist run with real v0.3.3 clients and a Windows build: part A passes (`docs/superpowers/plans/2026-10-20-relay-v2-checklist.md`). From it, §8.4: Cancel stays usable for the whole batch.

### Changes in v0.7

- **Actor output visualizer** on the stage graph (§9.6): an actor's node shows a small live level display while their Soundpad is playing, so the director can see that sound is actually coming out on their line, and a "No sound" warning when Soundpad reports PLAYING but nothing is audible.
  - The Soundpad pipe has no audio level and reports `PLAYING` before any audio (§8.1.6), so the level is measured separately on the actor's PC (Windows Core Audio peak meter). Which meter matches the `mic` line is **unconfirmed** and gets a Windows probe (Appendix B, steps 8–9).
  - New message `soundpad.level` and capability `soundpad.level` (§5.4, §5.5, §8.1.7). Needs the v2 relay for directors; the actor's own node works anywhere (§11.3).
  - Build order step 6 (§15.1). Design only; nothing is built.

### Changes in v0.6

- Production helpers agreed on 2026-10-20, with a build order (§15.1):
  - **Loudness matching** of sent files, also as a standalone **Normalize folder** tool (§8.4.2). High priority.
  - **Project folder sync** with a `vrcactorsync.yml` manifest and per-actor up-to-date status (§8.4.1).
  - **Headset notifications** (§8.7): Standby, Rolling and setup errors in XSOverlay or OVR Toolkit. On by default.
  - **Stage state and ready check** with a director ping (§8.8).
  - **Control input** (§8.9): Go, Stop, Standby and Ready from a VRChat avatar menu over OSC, and from Stream Deck or MIDI through Bitfocus Companion.
- New core namespaces `stage.*` and `ready.*`, and `file.inventory*` (§5.4, §5.5, §11.3).
- Later ideas: scene list ("run of show"), post-production export, "your line next" (§14).

### Changes in v0.5

- Soundpad probe results from the Windows test box are folded into §8.1, §8.2.3, Appendix A and Appendix B. Open items are marked unconfirmed.
- Key findings:
  - `SetVolume` changes both lines.
  - Position moves in about 140 ms steps.
  - The status says PLAYING before any audio.
  - Audio starts about 50–90 ms after the command.
  - `DoAddSound` lists the sound asynchronously.
- §8.2.3 measures start latency from position changes, not from the first non-zero position.
- VRChat window test results (Windows rows of Appendix C) folded into §8.5.8:
  - live resize works, even beyond the monitor size;
  - the launch options are honoured and persist;
  - VRChat is per-monitor DPI aware, but resizes itself when Windows scaling changes;
  - OBS Game Capture hooks VRChat under EAC.
- The Linux rows are not tested.

### Changes in v0.4

- §8.5.8: VRChat window ↔ recording-resolution helper for camera operators (live resize where the OS allows it, generated launch options everywhere, gamescope for bigger-than-monitor rendering on Linux), with its own test plan (Appendix C).

### Changes in v0.3

- Project renamed **vrcActorSync** (was vrActorAssist). Env vars `VRCAS_*`, Python package `vrcas_protocol`.
- The new app also speaks the **v0.3 protocol** to today's relay ("compatibility mode", §5.6, §11.3), so it's usable before the v2 relay exists.
- First implementation slice built and tested (§20): web UI, desktop agent, compatibility mode.
- §17 gains #9 (the relay offers "updates" to newer clients).

### Changes in v0.2

- **Desktop window via pywebview** (§4.3). The same UI is also reachable from any browser.
- **Full Soundpad control through its named-pipe API** (§8.1, Appendix A): play a specific file, speakers-only / mic-only / both, volume, mute, pause, seek, live position and sound list.
- **Timing and delay compensation** (§8.2): server-synced scheduled starts, per-actor offsets, measured Soundpad start latency.
- **OSC timeline editor** (§8.3): waveform, one lane per actor, cues with one or more parameters, anchored to Soundpad's playback position.
- **Installed and portable builds** (§10). The installed build updates itself; the portable build only notifies.
- **Legacy `/ws` clients supported with no removal date** (§11). This includes server-side emulation of scheduling for old actors.
- **Windows test plan and a Soundpad probe script** (`tools/soundpad_probe.py`, Appendix B).
- Linux is limited to directors; Linux actor features are out of scope.

---

## 1. Summary

The tkinter clients are replaced by one **desktop app**: a small Python **agent** with a **pywebview** window. The window shows a web UI that the agent serves on `127.0.0.1`.
- The same UI opens in any browser through **Open in browser**.
- The relay server also hosts the UI, so a director can work with no install.
- Tauri and Electron are not used.

- **Actors and camera operators** run the desktop app. The agent holds the relay connection and owns local hardware: Soundpad (named-pipe API), VRChat OSC, the file system and OBS (obs-websocket).
- **Directors** use either the desktop app or `https://<relay>/` in a browser.
- **Features are addons:** `soundpad`, `osc`, `files`, `obs`, and later `stream`. A new addon needs no relay server change.
- **Protocol v2** is a typed JSON envelope with namespaced message types. Server and agent share one Python schema package, and the UI's TypeScript types are generated from it.
- **Old v0.3.x clients keep working** on `/ws` through a bridge, with no removal date.
- **Distribution:** a per-user Windows installer with auto-update, plus a single-file portable exe.

---

## 2. Goals and Non-Goals

### 2.1 Goals

| # | Goal |
|---|------|
| G1 | Feature parity with the v0.3.3 Python clients (§13) |
| G2 | No Tauri, no Electron. A pywebview desktop window by default; the same UI also works in a normal browser |
| G3 | Modular: each feature is an addon. New addons need no relay server change |
| G4 | Stable: closing the window never drops a session. The protocol is typed and shared. Faults stay inside one addon |
| G5 | Full Soundpad control: play a specific file, choose the output line, volume, mute, pause, seek, report status |
| G6 | Delay compensation: scheduled starts with per-actor offsets |
| G7 | OSC timeline editor: one or more VRChat parameters per cue, for chosen actors, at chosen points in a sound |
| G8 | Camera-operator addon: sync OBS settings, start and stop recording together, report status |
| G9 | Installed build with auto-update, and a portable build |
| G10 | Backward compatibility with v0.3.x WebSocket clients, with no removal date |
| G11 | Leave room for P2P video between camera operators and the director (designed, built later) |

### 2.2 Non-Goals

- Replacing the Python relay server
- A Linux soundboard or Linux actor features (ROADMAP Priority 3 stays deferred)
- macOS builds
- Loading third-party addons from outside the repo (the interface allows it later)
- Frame-accurate genlock across cameras

---

## 3. Why a Local Agent

| Capability | Plain web page can do it? | Needed by |
|---|---|---|
| Talk to Soundpad's named pipe `\\.\pipe\sp_remote_control` | No | Actor |
| Send UDP OSC to `127.0.0.1:9000` | No. Browsers have no UDP | Actor |
| Save to a chosen folder by path, with overwrite checks | Partly. The File System Access API is Chromium-only and asks permission each session | Actor |
| Connect to obs-websocket with a stored password | Awkward: the password would live in the page | Camera op |
| Stay connected after the window or tab closes | No | Actor, Camera op |

The agent does the local work. The UI is a view of it, and that view can be the pywebview window, a browser tab, or both at once.

---

## 4. Architecture

### 4.1 Components

```
                ┌──────────────────────────────────────┐
                │ Relay server (FastAPI, VPS)           │
                │  /v2/ws   JSON router + permissions   │
                │  /ws      legacy pipe bridge (v0.3.x) │
                │  /        web app (static build)      │
                │  /health  health check                │
                │  time.*, rtc.* signaling, ICE config  │
                │  cue lists, per-actor delays          │
                └──────────────────┬───────────────────┘
         ┌─────────────────────────┼──────────────────────────┐
         │                         │                          │
 Director: browser          Actor PC (Windows)           Camera-op PC
 or desktop app       ┌────────────────────────┐   ┌────────────────────────┐
                      │ vrcActorSync app      │   │ vrcActorSync app      │
                      │ ┌────────────────────┐ │   │  agent + addons:       │
                      │ │ pywebview window   │ │   │  obs, (stream)         │
                      │ └─────────┬──────────┘ │   └──────────┬─────────────┘
                      │   http://127.0.0.1     │       obs-websocket :4455
                      │ ┌─────────▼──────────┐ │       → local OBS Studio
                      │ │ agent + addons:    │ │
                      │ │ soundpad, osc,     │ │
                      │ │ files              │ │
                      │ └──┬──────────┬──────┘ │
                      └────┼──────────┼────────┘
                 named pipe│          │UDP OSC
                       Soundpad     VRChat
```

| Component | Language | Role |
|---|---|---|
| Relay server | Python (FastAPI, evolves from `server_ws.py`) | Auth, approval, presence, routing, permissions, clock sync, signaling, storage for cue lists and delays, serves the web app |
| Desktop app | Python: agent (FastAPI + uvicorn, asyncio) + pywebview shell | Local hardware access, holds the relay connection, serves and shows the UI |
| Web app | Svelte 5 + Vite + TypeScript (ported from `origin/tauri` `client/src`) | All UI for every role: desktop window, browser tab, hosted mode |
| `vrcas_protocol` | Python (pydantic v2) | Message schemas shared by server and agent; source of the generated TS types |

### 4.2 Runtime Modes

| Mode | Who | UI shown in | Holds relay connection |
|---|---|---|---|
| Desktop (default) | Actor, camera op, director | pywebview window → `http://127.0.0.1:<port>/` | Agent |
| Desktop + browser | Same, plus a second screen, OBS dock, etc. | Window and/or any local browser tab (Open in browser) | Agent |
| Headless | When WebView2 is missing, or `--headless` | Browser tab only | Agent |
| Hosted | Director with nothing installed (any OS, phone, tablet) | `https://<relay>/` | Browser |

### 4.3 Desktop Shell (pywebview)

**Threads:**
- pywebview requires `webview.start()` on the main thread.
- The agent (asyncio loop with uvicorn, relay client and addons) runs in a background thread that starts first.
- `create_window()` loads `http://127.0.0.1:<port>/?t=<token>` only once the agent reports that its UI server is ready.

**Renderer (Windows):**
- pywebview's Edge Chromium renderer needs the WebView2 Runtime and .NET Framework 4.6.2+.
- By default pywebview falls back to MSHTML (IE11), which can't run this app. So the agent checks for WebView2 itself, using the registry key for client `{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` under `EdgeUpdate\Clients` (HKLM and HKCU).
  - If WebView2 is present, start pywebview.
  - If it is missing, use headless mode, open the default browser, and show a one-line hint to install WebView2.
  - The page also runs a startup self-check and asks the agent to switch to the browser if it detects it isn't running on Chromium.

**Renderer (Linux, directors only):** headless mode is the default. A WebKitGTK window can be enabled in settings.

**Close behaviour:**
- The window's `closing` handler returns `False` and hides the window, so the agent keeps running in the tray.
- The tray icon (`pystray`, its own thread) offers **Open window**, **Open in browser** and **Quit**.
- A setting turns closing the window into Quit.

**Browser access:**
- **Open in browser** (tray menu and UI menu) opens the same URL with a fresh one-time token.
- Any number of windows and tabs can be open; they all receive the same events.

**Native dialogs:**
- In the window: `window.create_file_dialog(FileDialog.OPEN / FOLDER)`.
- In browser mode: the agent opens a `tkinter.filedialog` on one dedicated thread instead.

**Window state:**
- `private_mode=True` (pywebview's default); the per-launch token cookie lives in memory.
- In portable mode, `storage_path` points inside the portable folder (§10.3).

**Why pywebview over Tauri:** on Windows it uses the same WebView2 engine, but everything stays in Python: no Rust toolchain, one language with the server, and the UI also runs unchanged in a browser.

### 4.4 Transport Abstraction (Web App)

UI components never talk to a socket directly:

```ts
interface Transport {
  state: Readable<"disconnected" | "connecting" | "ready">;
  send(env: Envelope): void;                         // relay message
  on<T extends MsgType>(type: T, fn: (env: EnvelopeOf<T>) => void): () => void;
  call<R>(method: string, params?: object): Promise<R>; // agent-local call (dialogs, config)
}
```

- `AgentTransport` connects to `ws://127.0.0.1:<port>/ui/ws` (desktop and headless modes).
- `RelayTransport` connects to `wss://<relay>/v2/ws` (hosted mode). Agent-only calls are unavailable there, and the UI hides what depends on them.

### 4.5 Example Flow: Scheduled Play with OSC Cues

```
Director UI ── osc.cue.load {cuelist, cues for A} ──► Relay ──► Actor A agent ── cue ack
Director UI ── soundpad.play {sound:{path}, lines:"both", at:T, cuelist_id} ──► Relay ──► Actor A agent
                                     Actor A agent: fire_at = T + delay_A − start_latency_A   (§8.2)
                                       ├─► soundpad: DoPlaySound(i, true, true)
                                       ├─► osc: anchor to GetPlaybackPositionInMs, fire cues (§8.3)
                                       └─► soundpad.ack {late_ms} ──► Relay ──► Director UI
```

---

## 5. Protocol v2

### 5.1 Envelope

```json
{
  "v": 2,
  "id": "01JA9X3V7Q0K3M8Z5W2C4R6T1B",
  "type": "soundpad.play",
  "from": "s_8f2c",
  "to": {"ids": ["s_a11e", "s_b72d"]},
  "ts": 1760740000123,
  "reply_to": null,
  "data": {"sound": {"path": "C:\\Sounds\\EP3 Scene 4 - Diego.mp3"}, "lines": "both", "at": 1760740000423}
}
```

| Field | Type | Notes |
|---|---|---|
| `v` | int | Always `2` |
| `id` | string | ULID, unique per message |
| `type` | string | `namespace.action[.sub]` |
| `from` | string | Session ID. **The server sets this field**; a client-supplied value is ignored, which prevents spoofing |
| `to` | target | §5.2 |
| `ts` | int | Sender's server-synced time in ms |
| `reply_to` | string? | `id` of the request this answers |
| `data` | object | Payload validated by the type's schema |

### 5.2 Targeting

`to` takes one of these forms:
- `"server"`
- `"all"` (everyone approved **except the sender**; the relay doesn't echo, §20.1)
- `{"role": "camera"}`
- `{"ids": [...]}`

Session IDs come from the server and map to `machine_id`. **Display names are never used for routing.**

### 5.3 Scheduling Fields

Any action message (`soundpad.play`, `soundpad.stop`, `cue.go`, `osc.param`, `obs.record.start`) may carry `at`, a time in **server-clock** ms.
- With `at`, the receiver schedules the action (§8.2).
- Without `at`, it acts on receipt.

### 5.4 Namespaces

| Namespace | Owner | Examples |
|---|---|---|
| `hello`, `welcome`, `denied`, `error` | core | handshake, failures |
| `presence.*` | core | `roster` (includes each actor's `delay_ms`), `latency` |
| `approval.*` | core | `pending`, `approve`, `deny`, `forget`, `forgotten` |
| `actor.settings` | core | `{id, delay_ms, display_name}` stored server-side |
| `chat.*` | core | `msg`, `priv` |
| `time.*` | core | `ping`, `pong` |
| `update.*` | core | `available` |
| `cue.*` | core | `go` (play selected), `stop`, `play` (index), `ack` — legacy-compatible semantics |
| `stage.*` | core | `state` (idle / standby / rolling), stored by the server (§8.8.1) |
| `ready.*` | core | `request`, `status`, `ping` (§8.8.2) |
| `soundpad.*` | soundpad addon | `play`, `stop`, `pause`, `seek`, `jump`, `volume`, `mute`, `list.request`, `list`, `state`, `level` (§9.6), `ack`, `calibrate` |
| `file.*` | files addon | `offer`, `accept`, `deny`, `progress`, `end`, `ok`, `err`, `batch.start/end/cancel` (+ binary frames), `inventory.request`, `inventory` (§8.4.1) |
| `osc.*` | osc addon | `param`, `cue.load`, `cue.ack`, `cue.fired`, `params` (discovered avatar parameters) |
| `cuelist.*` | server storage | `save`, `get`, `list`, `delete` |
| `obs.*` | obs addon | `profile.apply/status/release`, `record.start/stop/state`, `mark`, `slate`, `status` |
| `rtc.*` | stream addon | `offer`, `answer`, `ice`, `bye` |

The server understands only core namespaces and `cuelist.*`. Everything else it routes without reading `data`, applying only the permission table.

### 5.5 Permission Table (Server-Enforced)

Columns are the role of the **sender**.

| Message type | director | assistant | actor | camera |
|---|---|---|---|---|
| `chat.msg`, `chat.priv` | ✅ | ✅ | ✅ | ✅ |
| `cue.go/stop/play`, `soundpad.play/stop/pause/seek/jump/volume/mute/list.request/calibrate` | ✅ | ✅ | ❌ | ❌ |
| `cue.ack`, `soundpad.ack/list/state/level` | ❌ | ❌ | ✅ | ❌ |
| `approval.approve/deny/forget`, `actor.settings` | ✅ | ❌ | ❌ | ❌ |
| `file.offer` + chunks | ✅ | ❌ | ❌ | ❌ |
| `file.accept/deny/ok/err/progress` | ❌ | ❌ | ✅ | ✅ |
| `file.inventory.request` | ✅ | ✅ | ❌ | ❌ |
| `file.inventory` | ❌ | ❌ | ✅ | ✅ |
| `stage.state`, `ready.request`, `ready.ping` | ✅ | ✅ | ❌ | ❌ |
| `ready.status` | ❌ | ❌ | ✅ | ✅ |
| `osc.param`, `osc.cue.load` | ✅ | ✅ | ❌ | ❌ |
| `osc.cue.ack`, `osc.cue.fired`, `osc.params` | ❌ | ❌ | ✅ | ❌ |
| `cuelist.save/delete` | ✅ | ✅ | ❌ | ❌ |
| `cuelist.get/list` | ✅ | ✅ | ✅ | ❌ |
| `obs.profile.apply/release`, `obs.record.start/stop`, `obs.mark`, `obs.slate` | ✅ | ✅ | ❌ | ❌ |
| `obs.profile.status`, `obs.record.state`, `obs.status` | ❌ | ❌ | ❌ | ✅ |
| `rtc.*` | ✅ | ✅ | ❌ | ✅ |

- The table is data in `server/permissions.py`.
- Rows the table leaves implicit (built): `file.end` and `file.batch.*` go with `file.offer`; `hello` and `time.*` are open to everyone; types only the relay sends (`welcome`, `presence.*`, …) are open to no one. A type that isn't in the table is rejected with `unknown_type`, so a new addon needs its rows added (§20.1).
- Rejected messages get `error {code: "forbidden", reply_to}`.
- The legacy bridge applies the same table (§11).

### 5.6 Handshake

```
client → hello   {role, name, machine_id, version, platform, capabilities[], secret?}
server → welcome {session_id, server_version, version_status, server_time, delay_ms, ice_servers[]}
       | approval.pending {}
       | denied {reason}
```

- `capabilities` examples: `["soundpad", "soundpad.lines", "soundpad.add", "soundpad.position", "osc"]` or `["obs.record", "obs.profile"]`. The director UI shows controls per participant based on them.
- As built (§20.1): `welcome` also carries the `name` and `role` the relay uses (an approved actor keeps its approved name). Join requests reach directors and assistants as `presence.roster.pending`, and `approval.approve` / `deny` name the `machine_id`. Errors use `error {code, message, type, ids?}` with codes `forbidden`, `invalid`, `not_approved`, `unknown_type`, `unknown_target`, `unsupported`.
- Directors and assistants authenticate with a secret, as today. Actors and cameras go through approval; `approved_actors.json` gains `role` and `delay_ms`.
- `version_status` follows `compare_versions()` (major mismatch → unsupported).
- A v0.4 app that reaches a v0.3.x server runs in **compatibility mode** (`agent/relay_legacy.py`): it registers over the pipe protocol on `/ws` and supports the cast list, approvals, Go / Play in 3s / Stop, chat, Soundpad and OSC cues. Not available there: camera operators in the roster, file transfer, scheduling, the v2 permission checks. The UI says it's on a v0.3 relay.

### 5.7 File Chunks as Binary Frames

```
| 1 byte kind | 16 bytes transfer UUID | 4 bytes chunk index (BE) | payload |
```

- Transfers are keyed by transfer UUID. Chunks are 256 KiB; integrity is SHA-256 in `file.end`.
- Flow control: at most 8 unacknowledged chunks are in flight, acknowledged with `file.progress`.
- Batches and cancel keep their v0.3.0 semantics.
- As built (§20.2): `chunk_size` is declared in each `file.offer` (256 KiB from v0.4 apps), an offer goes to exactly one session, and the relay passes chunks only from the offer's sender to its recipient after `file.accept`.

### 5.8 Schema Source of Truth

- `protocol/vrcas_protocol/` contains pydantic v2 models, one per message type, plus the envelope. Server and agent both import it.
- `scripts/gen_ts_types.py` exports JSON Schema and generates `web/src/protocol/types.ts`. CI fails if it is stale. (There's no CI yet: `tests/test_protocol.py` fails when the file is stale, and `--check` exits 1.)
- The cue list file format (`cuelist.v1`, §8.3.2) is defined in the same package.

---

## 6. Relay Server Changes

| Change | Detail |
|---|---|
| `/v2/ws` endpoint | Envelope parsing, validation of core types, routing by `to` |
| Permission enforcement | §5.5 table, applied to v2 and legacy traffic |
| Session IDs | Issued in `welcome`, mapped to `machine_id` |
| Clock sync | Answers `time.ping` with `time.pong {t0, t1, t2}` (§8.2.1) |
| Per-actor settings | `delay_ms` and `display_name` stored in `approved_actors.json`, included in `welcome` and `presence.roster` |
| Cue list storage | `cuelists/<id>.json` (`cuelist.v1`), keyed by sound SHA-256 + name. `cuelist.*` messages |
| Legacy bridge | `/ws` stays (§11), including emulated scheduling for legacy actors |
| ICE config | `welcome.ice_servers` with STUN/TURN URLs and short-lived TURN credentials (coturn shared secret) |
| Web app hosting | Static build at `/`. **The health JSON moves from `/` (`server_ws.py:665`) to `/health` only** |
| Take log (optional) | `takes/YYYY-MM-DD.jsonl` from `obs.record.state` + `cue.*` / `soundpad.*` events |
| Existing fixes | §17 |

```
server/
├── app.py             # FastAPI app: /v2/ws, /ws, /health, static web build
├── router.py          # v2 routing by target
├── permissions.py     # role × message-type table
├── legacy_bridge.py   # pipe ⇄ v2 (uses shared.py) + legacy scheduling emulation
├── sessions.py        # session registry, approvals, per-actor settings
├── storage.py         # cue lists, take log
├── timesync.py
└── updates.py         # manifest lookup (moved from server_ws.py)
```

`server_ws.py` stays as a thin entrypoint shim, so `start-server.sh` and `start-server-ts.sh` keep working unchanged.

As built (§20.1): `server/relay.py` holds the shared state and the operations both endpoints use (approve, deny, forget, status loop), and `server/settings.py` the settings and log. `storage.py` (cue lists, take log) isn't built.

---

## 7. Agent

### 7.1 Responsibilities

- Hold the relay connection: reconnect with backoff (1 s → 30 s cap, with jitter), clock sync, handshake
- Run addons and route relay messages to them through the event bus
- Serve the web app and local UI API on loopback; run the pywebview window and tray
- Provide native dialogs
- Updates: auto-install for installed builds, notify-only for portable builds (§10)

### 7.2 Process and Lifecycle

1. **Single-instance lock:** a second launch only focuses or reopens the window of the running instance.
2. **Startup order:** load config → start addons in dependency order → start the UI server → open the window (or browser in headless mode) → connect to the relay.
3. **Logs:** rotating file in the data dir. The UI log panel streams the same events.
4. **Shutdown:** addons stop in reverse order.
   - **The OBS addon never stops a recording because the app exits or loses the relay.**
   - The soundpad addon never stops a playing sound on exit.

### 7.3 Event Bus

- In-process async pub/sub. Topics are the protocol `type` strings; local-only topics use the `local.` prefix.
- Each handler runs as its own task with a timeout. An exception is logged, the addon is marked `degraded` and shown in the UI, and **nothing else stops**.

### 7.4 Addon Interface

```python
class Addon(ABC):
    id: ClassVar[str]                       # "soundpad"
    platforms: ClassVar[set[str]] = {"win32", "linux"}
    requires: ClassVar[list[str]] = []      # other addon ids
    handles: ClassVar[list[str]] = []       # relay types, globs allowed: ["soundpad.*", "cue.*"]
    config_model: ClassVar[type[BaseModel]] # pydantic → settings form drawn by the UI

    async def start(self, ctx: AddonContext) -> None: ...
    async def stop(self) -> None: ...
    async def on_message(self, env: Envelope) -> None: ...
    def capabilities(self) -> list[str]: return []
    def ui_calls(self) -> dict[str, Callable]: return {}   # local calls exposed to the UI

@dataclass
class AddonContext:
    bus: EventBus
    relay: RelayClient          # send(), session_id, server_time(), delay_ms
    scheduler: Scheduler        # call_at_server_time(), cancel(group) — §8.2
    config: BaseModel
    save_config: Callable[[BaseModel], Awaitable[None]]
    log: Logger
    data_dir: Path
```

- **States:** `disabled → starting → running ⇄ degraded → stopped`. An addon whose platform doesn't match is listed as unavailable.
- **Registration:** first-party addons are listed in `agent/addons/__init__.py`. Python entry points (`vrcas.addons`) can be added later.

### 7.5 Config

| Build | Config and data location |
|---|---|
| Installed | `%APPDATA%\vrcActorSync\` (Linux: `~/.config/vrcActorSync/`) |
| Portable | `<exe folder>\vrcActorSync-data\` (§10.3) |

- **Migration:** on first run, import an existing v0.3.x `config.json` from next to the exe (`shared.py:84` behaviour). This covers old clients that auto-update into the portable build (§11.4).
- **Structure:** `{ "core": {...}, "addons": { "<id>": {...} } }`. Each addon section is validated by its `config_model`; invalid values fall back to defaults with a warning.
- **Machine ID:** keep the current `uuid5(NAMESPACE_DNS, hostname)` so existing approvals stay valid.

### 7.6 Local UI API

| Endpoint | Purpose |
|---|---|
| `GET /` and static assets | Web app build |
| `GET /api/state` | Snapshot: connection, roster, addon states, config (secrets redacted) |
| `WS /ui/ws` | Relay envelopes both ways, plus `{"call": "<addon>.<method>", "args": {...}}` RPC |
| `GET /overlay/*` | OBS browser-source pages (§9.4) |

### 7.7 Local Security

1. Bind to `127.0.0.1` only by default.
2. Reject requests whose `Host` isn't `127.0.0.1:<port>` / `localhost:<port>` (blocks DNS rebinding).
3. Reject WebSocket upgrades with a foreign `Origin`.
4. One-time token per open: the window or browser loads `/?t=<token>` and exchanges it for an `HttpOnly; SameSite=Strict` cookie. Every API and WS call needs the cookie.
5. No CORS headers.
6. Secrets (director secret, OBS password) never reach the UI. It only sees `"set": true/false`.

**LAN mode** (phone or tablet) is a later, opt-in mode with a pairing code. Tailscale is the recommended path.

---

## 8. Addons

### 8.1 `soundpad` (Windows)

Based on Leppsoft's reference client `SoundpadRemoteControl.java` (RC interface 1.1.2). Full command list: Appendix A. Assumptions were checked by `tools/soundpad_probe.py` on the Windows test box on 2026-10-19 (Soundpad 4.0.35, RC 1.1.2, full version; Appendix B). Results are marked **Confirmed**; anything the probe didn't reach is marked **unconfirmed**.

#### 8.1.1 Transport: Named Pipe

- **Pipe:** `\\.\pipe\sp_remote_control`, local machine only.
  - Requests are UTF-8 command text such as `DoPlaySound(5, true, false)`.
  - Action commands answer with HTTP-style codes (`R-200`, `R-404`, …).
  - Getters answer with the raw value or XML.
- **Why the pipe replaces the CLI:**
  - `Soundpad.exe -rc` starts a new process per command and returns nothing.
  - The pipe returns position, status, volume and the sound list, which the status display, sound picker and cue anchoring all need.
  - **Confirmed:** a pipe round trip takes 0.10 ms (median of 50 `IsAlive()`, p95 0.17 ms). `Soundpad.exe -rc` takes 179 ms (median of 5), and 837 ms for the first call.
- **Client:**
  - One worker thread owns the pipe handle and runs one request at a time, at least 2 ms apart. The reference client warns that back-to-back requests can break the pipe.
  - Timeouts: 2 s, or 10 s for list calls. On a timeout or a broken pipe, the client reconnects with backoff and marks the addon `degraded`; the UI shows "Soundpad not responding".
  - Read method, as in the reference client: block for the first byte, then read the rest of what is available (`PeekNamedPipe`). The probe uses the same method. **Confirmed** for answers up to about 1 KB (a 6-sound list). Large sound lists are **unconfirmed**.
  - The agent's client (`agent/soundpad_pipe.py`) differs in two ways:
    - It waits for the first byte by polling `PeekNamedPipe` every 0.2 ms instead of blocking, so a hung Soundpad can't wedge the worker thread and the timeout is a plain deadline.
    - It reads XML answers until the root element closes, rather than relying on a short pause.
  - **Confirmed:** Soundpad accepts more than one pipe client at a time, so the agent keeping the pipe open doesn't lock out the probe or other tools (for example Stream Deck plugins).
- **Startup probe:** `IsAlive()`, `GetVersion()`, `GetRemoteControlVersion()`, `IsTrial()` → feature flags. The test box answered `R-200`, `4.0.35`, `1.1.2`, `0`.
  - `add_sound` is off in the trial version: `DoAddSound` isn't allowed there.
  - Warn if the RC version is below 1.1.2, since some commands would be missing.
- **Auto-launch (optional):** if the pipe is missing and `auto_launch` is on, start Soundpad.exe (path from config, else auto-detected by `soundpad.py`'s `find_soundpad_exe`) and wait up to 15 s for the pipe. This covers ROADMAP Priority 4, "Auto-start with Soundpad".
- **CLI fallback:** if the pipe can't be opened but Soundpad.exe was found, only play-selected, play-by-index and stop work, through `-rc` as today. The addon reports `capabilities: ["soundpad"]` only.
  - As built (§20.2): not while Soundpad isn't running (no pipe at all). `-rc` would start Soundpad then, and v0.3's 5 s timeout killed it again; such a cue fails at once instead, and only `auto_launch` starts Soundpad.

#### 8.1.2 Commands

| Message | Data | Soundpad calls |
|---|---|---|
| `soundpad.play` | `sound` (§8.1.3), `lines`, `volume?`, `start_ms?`, `at?`, `cuelist_id?` | resolve sound → [`SetVolume(v)`] → `DoPlaySound(i, render, capture)` → [`DoSeekMs(start_ms)`] |
| `soundpad.stop` | `at?` | `DoStopSound()`; cancels this actor's scheduled actions and cue timers |
| `soundpad.pause` | `paused: bool` | `GetPlayStatus()`, then `DoTogglePause()` only if needed, so the command is idempotent |
| `soundpad.seek` | `ms` | `DoSeekMs(ms)` (absolute) |
| `soundpad.jump` | `ms` (±) | `DoJumpMs(ms)` (relative) |
| `soundpad.volume` | `value` 0–100 | `SetVolume(value)` |
| `soundpad.mute` | `muted: bool` | `IsMuted()`, then `DoToggleMute()` only if needed |
| `soundpad.list.request` | — | `GetSoundlist()`, `GetCategories(false, false)` → `soundpad.list` |
| `soundpad.calibrate` | `sound?` | Speakers-only test play to measure start latency (§8.2.3) |
| `cue.go` / `cue.stop` | legacy semantics | `DoPlaySelectedSound()` / `DoStopSound()` |
| `cue.play` | `index` (legacy `*play:N`) | `DoPlaySound(N)` |

- `soundpad.ack {status, late_ms, error?}` answers every action.
  - As built (§20.2): `status` is `"ok"` or an error code, and the ack names the message it answers (`command`). `late_ms` comes with scheduling (Phase 2 M3).
- Error codes: `not_found`, `not_in_soundpad`, `trial_limit`, `soundpad_offline`, `timeout`.
- `start_ms` seeks right after starting playback.
  - **Confirmed:** a seek shows `SEEKING` for 20–50 ms, during which the position reads 0 or the old value, then the exact target (`DoSeekMs(5000)` → 5000). A seek and a pause/resume in the middle of a sound sounded clean to the actor and to a listener in VRChat.
  - Whether seeking right after `DoPlaySound` makes an audible blip is **unconfirmed**; until it's checked, the UI marks `start_ms` as "approximate".
  - Don't stop during `SEEKING`. Once, a `DoStopSound()` sent mid-seek made the next `DoPlaySound` of that sound start at the seek target instead of 0. `soundpad.stop` waits for the seek to finish (up to 250 ms) first.

#### 8.1.3 Sound References ("Play a Specific File")

```json
{"path": "C:\\Users\\coda\\vrActorFiles\\EP3 Scene 4 - Diego.mp3"}
{"sha256": "9f2c…"}                    // a file received through the files addon
{"index": 12}                          // All-sounds index (changes if the actor reorders sounds)
{"category": "Scene 4", "position": 2}
{"selected": true}                     // what the actor has selected (legacy Go)
```

How the actor's agent resolves a reference:
1. `sha256` → local path, from the files addon's receive log.
2. `path` → index, through a cached sound list.
   - Match the `url` attribute, normalised and case-insensitive.
   - **Confirmed** format: `<Soundlist>` of `<Sound>` elements with `index`, `url` (the full Windows path), `title` (file name without extension), `artist`, `duration` (`m:ss`, whole seconds only), `addedOn`, `lastPlayedOn`, `playCount`, `tag`. `GetSoundlist(from, to)` returns just that range.
   - Refresh the cache when `GetSoundFileCount()` changes, or on a miss.
3. Not in Soundpad:
   - With `auto_add` on and the full version: `DoAddSound("<path>")`, refresh, then use the new index.
   - **Confirmed:** `DoAddSound` answers `R-200` at once but the sound is listed a little later, so the agent waits for `GetSoundFileCount()` to change (up to 5 s). The new sound was appended at the end of All sounds. A path with spaces works inside the quotes.
   - In the trial: error `trial_limit` with the hint "add it to Soundpad by hand".
4. **Index drift guard:** before playing by index, `GetSoundlist(i,i)` must still show the same `url`. Otherwise refresh and resolve again.
5. `category` → `GetCategories` → category index → `DoPlaySoundFromCategory(cat, pos, render, capture)`.

**Director sound picker:**
- Each actor's Soundpad list (from `soundpad.list`) is searchable.
- Picking a sound sends a `path` reference, which stays correct even if the actor reorders sounds.
  - As built (§20.2, decision D6): the list carries an opaque `key` per sound instead of its path (paths contain Windows user names), and picking sends `{key}`. The drift guard applies the same way.
- Files sent through the files addon appear as "Sent files" and use `sha256` references, with auto-add.

#### 8.1.4 Output Lines

| `lines` | Soundpad args | Use |
|---|---|---|
| `both` (default) | `render=true, capture=true` | Normal performance |
| `speakers` | `render=true, capture=false` | Rehearsal and checks: only the actor hears it. Also used for calibration |
| `mic` | `render=false, capture=true` | Audience hears it, actor doesn't |

The default is set per actor in config. The director can override it on each play.

**Confirmed by listen test** with `DoPlaySound(i, render, capture)`: `speakers` was heard only by the actor, `both` by the actor and a listener in VRChat, `mic` only by the VRChat listener.

#### 8.1.5 Volume and Mute

- `SetVolume` / `GetVolume` use **0–100** (**confirmed**). `SetVolume(0.5)` answers `R-200` and sets the volume to 0, so the agent only sends whole numbers.
- **Confirmed by listen test: `SetVolume` changes both lines**, although the reference client calls it "volume of the speakers". Playing on the mic line only at 5 and then at 100, the VRChat listener heard the second clip much louder. (40 vs 100 on `both` was too close to call.)
  - So there's one control, labelled "Volume", and it changes what the audience hears as well as the actor's speakers. Soundpad has no separate mic-line volume.
- `IsMuted()` / `DoToggleMute()` mute the speakers. Whether mute also silences the mic line is **unconfirmed**.
- v0.3's `soundpad.py` sent 0.0–1.0 to `SetVolume`, which mutes in practice; fixed on main in 0.3.3 (§17 #8).

#### 8.1.6 Status Reporting

- **While playing:** poll `GetPlayStatus()` and `GetPlaybackPositionInMs()` every 250 ms. Send `soundpad.state {status, position_ms, duration_ms, sound, lines, volume, muted}` to directors at most twice a second. Otherwise send on change, plus a heartbeat every 10 s.
- **Confirmed position behaviour** (a 50 s WAV; other formats **unconfirmed**):
  - The status reads `PLAYING` 5–6 ms after `DoPlaySound`, before any audio. The position stays 0 until about 180–215 ms after the command.
  - After that the position advances in steps about 140 ms apart, so the UI interpolates between reads.
  - It reads 0 or the old value while `SEEKING`.
  - After a stop, `GetPlaybackPositionInMs()` and `GetPlaybackDurationInMs()` keep the last sound's values (once 3127 ms of a 3096 ms sound), so `STOPPED` means "no position".
- **List changes:** poll `GetSoundFileCount()` every 5 s; push `soundpad.list` when the count changes.
- **Director UI:** a mini transport per actor with status, title, progress bar and volume.
- **No audio level on the pipe:** the Remote Control API has no playback level (`GetRecordingPeak()` belongs to Soundpad's recorder, Appendix A). `PLAYING` plus an advancing position means the file is progressing, not that sound reaches anyone. The actor's agent therefore measures the output level itself and reports it as `soundpad.level` (§9.6).

#### 8.1.7 Config and Capabilities

- **Config:** `enabled`, `path`, `auto_launch`, `default_lines`, `auto_add_received`, `auto_compensate_latency`, `level_meter` (on by default, §9.6.5), `silent_after_ms` (§9.6.1).
- **Capabilities:**
  - `soundpad` (play/stop)
  - `soundpad.lines`, `soundpad.position`, `soundpad.list` (pipe available)
  - `soundpad.add` (full version)
  - `soundpad.level` (a working output meter was found, §9.6.3)
- As built (§20.2, decision D7): capabilities are fixed per build; whether Soundpad answers right now comes in `soundpad.state.available`.

### 8.2 Timing and Delay Compensation

Shared by `soundpad`, `osc` and `obs` through `ctx.scheduler`.

#### 8.2.1 Clock Sync (NTP-style)

- The agent sends `time.ping {t0}`; the server replies `time.pong {t0, t1, t2}`; the agent receives it at `t3`.
- `offset = ((t1 − t0) + (t2 − t3)) / 2`
- `rtt = (t3 − t0) − (t2 − t1)`
- Sample every 10 s (every 1 s for the first 5 s after connecting). Keep 8 samples and use the offset of the sample with the lowest RTT.
- The scheduler converts server time to the local monotonic clock and uses `loop.call_at`.
  - As built (§20.2): the local clock is `time.perf_counter()`, and the last 30 ms of each wait is slept in a worker thread, because asyncio's timers and Python 3.12's wall and monotonic clocks on Windows move in 15.6 ms steps.

#### 8.2.2 Scheduled Starts

- The director UI sends one message to all targeted actors with `at = server_now + lead`. The default lead is 300 ms (configurable).
  - The UI warns when any actor's one-way latency (RTT/2) approaches the lead.
- **Play in 3s** becomes `at = now + 3000`. Every agent shows the countdown locally, and **Stop** cancels it everywhere.
- As built (§20.2): directors hold the cue for v0.4 builds without the `schedule` capability (they would play an `at` cue at once) and send it without `at` when it's due. A director can **arm** a sound per actor: GO then sends `soundpad.play {sound, at}` to armed actors and `cue.go {at}` to the others, with one `at`.

#### 8.2.3 Per-Actor Fire Time

```
fire_at = at + delay_ms[actor] − start_latency_ms[actor]   (the last term only if auto_compensate_latency)
```

- **`delay_ms`:** a manual per-actor offset in ms, positive or negative.
  - The director sets it (right-click actor → Set delay). It is stored on the server and delivered in `welcome` and `presence.roster`.
  - It covers differences in audio path or VRChat voice delay, and creative offsets. This is FEATURES-PLANNED Feature 3.
- **`start_latency_ms`:** measured on the actor's machine from the play command to the moment audio starts. It uses the median of the last 5 plays.
  - **Calibrate** runs one speakers-only play to seed it.
  - **How it's measured** (changed after the probe):
    - The status says `PLAYING` 2–11 ms after the command, before any audio.
    - The position stays 0 for about 180–220 ms and then moves in steps about 140 ms apart (§8.1.6). So "time to the first position above 0" overstates the latency by up to one step.
    - Instead, the agent polls status and position right after the command. At each of the first 3 position changes it takes `(time of the read − command time) − position`, then the median of those.
  - **Measured** on the test box (Windows 11, Soundpad 4.0.35; logged by the agent as `Soundpad start: …`):

    | Command | Plays | Audio start after the command | First position read |
    |---|---|---|---|
    | `DoPlaySound(5, …)` from the probe, 50 s WAV, three output-line settings | 3 | 51, 55, 79 ms | 179–216 ms |
    | `DoPlaySelectedSound()` via relay GO, 50 s WAV | 5 | 92, 67, 55, 49, 48 ms (median 55) | 177–222 ms |
    | `DoPlaySound(6)` via `*play:6`, 47 s MP3, first play of that file | 1 | 88 ms | 214 ms |

  - The first play of each sequence was slower (88–92 ms: the first GO, and the first play of the MP3); repeats settled around 50 ms. Proposed default before any calibration: **60 ms**. Other formats and machines are **unconfirmed**.
- **Late arrival:** if a message arrives more than 20 ms after `fire_at`, the agent acts immediately and reports `late_ms` in the ack. The director UI shows it per actor.
- As built (§20.2): the start-latency term applies to starts only (`cue.go`, `cue.play`, `soundpad.play`); every ack of a scheduled action carries `late_ms`; calibration without a sound uses the sound last played by number, else sound 1, since the selected sound can't be played on the speakers line alone.

#### 8.2.4 Limits

VRChat voice delay to each listener varies per listener and isn't measurable locally. `delay_ms` is tuned by ear from the director's position.

### 8.3 `osc` and the OSC Timeline Editor

#### 8.3.1 OSC Sender (Actor Agent)

- Uses `python-osc` `SimpleUDPClient`. **Config:** `host` (127.0.0.1), `port` (9000), `enabled`.
- **Value types** follow VRChat avatar parameter types: `bool` (T/F), `int` (0–255), `float` (−1.0..1.0). A value is sent with its declared type, never guessed.
- Keeps the shorthand rule: `RecIcon` → `/avatar/parameters/RecIcon`; a leading `/` means a full path.
- `osc.param {actions[], at?}` fires immediately or at `at`. This covers today's "OSC toggle on Go/Stop" feature.
- When OSC is disabled: log the skip and acknowledge with `status: skipped`.

#### 8.3.2 Cue List Model (`cuelist.v1`)

```json
{
  "schema": "cuelist.v1",
  "id": "cl_7Q2M",
  "name": "EP3 Scene 4 - Diego monologue",
  "sound": {"title": "EP3 Scene 4 - Diego.mp3", "sha256": "9f2c…", "duration_ms": 41230},
  "cues": [
    {
      "id": "c1", "at_ms": 2000, "label": "Rec on",
      "targets": {"characters": ["Diego"]},
      "actions": [
        {"param": "RecIcon", "type": "bool", "value": true},
        {"param": "MouthOpen", "type": "float", "value": 0.8, "hold_ms": 3000, "revert": 0.0}
      ]
    },
    {
      "id": "c2", "at_ms": 5000,
      "targets": {"actors": ["s_a11e", "s_b72d"]},
      "actions": [{"param": "/avatar/parameters/EyeClose", "type": "bool", "value": true}]
    }
  ],
  "on_stop": "revert"
}
```

- **Targets:** by character, resolved through the director's character → actor mapping (the same mapping as Audioscript file routing), or by actor directly.
  - Character targets let one cue list be reused when a different actor plays the role.
- **Actions:** one or more parameter changes per cue, so several toggles can fire at the same moment.
- **`hold_ms` + `revert`:** auto-revert after a duration.
- **`on_stop`:** `revert` sends each touched parameter's `revert` value (default: bool → opposite, number → 0); `none` leaves values as they are.

#### 8.3.3 Editor (Director UI)

- **Audio:** the director loads the sound file in the editor; the browser decodes it.
  - The SHA-256 is computed in the page with `SubtleCrypto` and keys the cue list to that sound.
  - When the file is sent to actors, cue lists for it are offered automatically.
- **Waveform:** wavesurfer.js v7 with the Regions plugin for cue markers and the Timeline plugin for a millisecond ruler. Zoom and a 10 ms snap grid.
- **Lanes:** one lane per character or actor, so who gets what, and when, is visible at a glance. A cue with several targets appears on each target's lane.
- **Editing:**
  - Click a lane or press **M** to add a cue at the playhead.
  - Drag to move; nudge ±10 or ±100 ms; copy and paste.
  - The inspector shows time, targets, actions (parameter, type, value, hold, revert) and a label.
- **Parameter help:** autocomplete and type checks from discovered avatar parameters (§8.3.5).
  - Warnings for unknown parameters, wrong types, and cues past the end of the sound.
- **Preview modes:**
  - **Preview:** audio plays in the director's UI; markers light up. No network traffic.
  - **Test OSC:** fires the actors' OSC on the timeline without Soundpad.
  - **Rehearse:** plays on the actors' Soundpad **speakers only** with OSC, so actors hear and see it but the audience doesn't.
- **Storage:** saved on the server (`cuelist.save`) and shared between directors. JSON import and export.

#### 8.3.4 Runtime on the Actor (Audio-Anchored Cues)

1. **Arm:** `osc.cue.load {cuelist_id, sound, cues}` carries only the cues for this actor, with characters already resolved by the director UI. The actor replies `osc.cue.ack {count, warnings}`.
2. **Go:** `soundpad.play {sound, at, cuelist_id}`.
3. **Anchor:**
   - After `DoPlaySound`, poll `GetPlaybackPositionInMs()` every 10 ms until the position is above 0.
   - Set `anchor = now − position`, then schedule each action at `anchor + at_ms`.
   - Soundpad's position moves in steps about 140 ms apart (§8.1.6), so `now` must be the read where the value changed. A read taken between steps is up to one step late.
   - Re-read the position every 250 ms and correct any drift above 15 ms.
4. **Pause / seek / stop:**
   - `PAUSED` freezes the cue clock.
   - A position jump reschedules: cues before the new position are skipped, and their final values are applied if `catch_up` is on.
   - `STOPPED` or `soundpad.stop` cancels the cues and applies `on_stop`.
5. **Fallback:** if Soundpad is unavailable or disabled, cues run on the wall clock from `fire_at` (plus `start_latency_ms` when known).
6. **Report:** `osc.cue.fired {cue_id, late_ms}`, batched every 250 ms. The director's timeline shows fired markers and lateness.

#### 8.3.5 Avatar Parameter Discovery (Optional)

- VRChat writes per-avatar OSC config JSON under `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\OSC\<user>\Avatars\`.
  - **Confirmed:** files are `usr_…\Avatars\avtr_….json`. Each has top-level keys `id`, `name`, `hash` and `parameters`. Each parameter has `name` and an `input` and/or `output` with `address` and `type` (`Float`, `Bool`, `Int`). The test avatar had 44 parameters, 16 of them settable.
- The agent reads the newest file, keeps only parameters that have an `input` (only those can be set over OSC), and sends `osc.params {avatar_name, params: [{name, address, type}]}`.
- Picking the newest file is a guess at the current avatar. Listening for VRChat's `/avatar/change` (OSC out, 9001) or OSCQuery is a later improvement, because port 9001 is often taken by other OSC apps.

### 8.4 `files`

- **Receive:**
  1. `file.offer` arrives.
  2. Apply the policy: auto-accept or a prompt, with the overwrite prompt when the file exists (v0.3.0 rules).
  3. Write chunks to a temp file in the target dir.
  4. Verify SHA-256.
  5. Rename atomically into place.
  6. Reply `file.ok` or `file.err`.
- **Auto-add to Soundpad:** when `auto_add_received` is on (full version only), the received file is added through the soundpad addon, and its SHA-256 → path mapping is recorded for `{sha256}` sound references.
- **Send:** in the desktop app the agent reads from disk; in hosted mode the browser reads the file. Both use the same `file.*` messages.
- **Cancel** stays usable for the whole batch, mid-file too. (The v0.3.3 director sends on its window thread, so its Cancel Batch only responds between files.)
- **Character routing** (`" - Character.ext"`) is director UI logic. Port `parse_character_name` (`director_client_ws.py:875`) to TypeScript with its examples as tests.
- As built (Phase 2 M1a, §20.2): one prompt per file when the offer arrives, saying when it replaces a copy (instead of v0.3's overwrite prompt after the data arrived); auto-accept keeps the v0.3 meaning. Received files go to `Documents\vrcActorSync` unless the actor picks another folder (the v0.3 `receive_dir` is imported). Any file type can be sent (hidden files skipped, 1 GiB per file). Received files are recorded in `received.json` and, since Phase 2 M2, added to Soundpad (full version, `auto_add_received`, on by default).

#### 8.4.1 Project Folder Sync (`vrcactorsync.yml`)

The director keeps one project folder, and the app keeps each actor's copy of their files up to date. Desktop app only: the agent reads the folder.

**Setup:**
1. The director selects the project folder.
2. If `vrcactorsync.yml` is missing, the app proposes one and writes it after the director confirms.
   - Each file's character comes from its name (`parse_character_name`). Files without a character are listed for the director to assign.
   - The cast comes from the session's character → actor mapping. Unknown characters prompt for an actor.

**Manifest (`project.v1`):**

```yaml
schema: project.v1
name: EP3
cast:                            # character → actor; recasting is a one-line change
  Diego: {actor: Coda, id: m_3f2a9c}
  Mira:  {actor: Rin,  id: m_81d0e4}
files:
  - path: "Scene 4 - Diego.mp3"  # relative, forward slashes
    to: [Diego]
  - glob: "sfx/*.wav"            # for shared folders; an explicit path wins over a glob
    to: [all]
  - path: "Scene 4 - ambience.wav"
    to: [Diego, Mira]
    normalize: false             # §8.4.2 opt-out; `gain_db: -3` offsets the target instead
```

- Files go to **characters**, not actors, so the project survives recasting. `to` also accepts `all` and `{actors: [...]}`.
- **Identity:** routing uses `id` (the actor's machine-based identity). `actor` is the label for humans and is refreshed from the roster. Display names never route (§5.2).
- **Hand edits:** the agent reads and writes with `ruamel.yaml` in round-trip mode, so comments and ordering survive. It re-reads before every write, writes atomically, and never overwrites a file it can't parse; it shows the line and column instead.

**Watching** (poll every 2 s, no extra dependency):
- **New file** that no entry matches → prompt "Who gets this?", pre-filled from the file name. The answer is added to the manifest.
- **Changed file** → marked outdated for its actors. Hashes are cached by size + mtime, so only changed files are re-hashed.
- **Deleted file** → offer to remove its entry. Actors keep their copies, shown as "removed from project".
- A file counts as settled once its size hasn't changed for 2 s, so half-written exports aren't sent.

**Status:**
- Each actor's agent records received files per project (path, SHA-256) and answers `file.inventory.request {project}` with `file.inventory {project, files: [{path, sha256}]}`. It sends a fresh inventory after every received file.
- The director sees a grid of actors × files: **up to date / outdated / missing / sending n % / failed**.
- **Sync** sends only missing and outdated files, one batch per actor. **Auto-sync** (off by default, open question 15) sends settled changes without asking.
- The ready check (§8.8.2) reports "files up to date" for each actor's assigned files.

**Actor side:**
- Files land in `<received files folder>/<project name>/<relative path>` and replace older versions atomically (§8.4 steps 3–5).
- The first sync from a project asks the actor once ("Allow EP3 to keep files in …"). Later syncs from that project are accepted automatically.
- Auto-add to Soundpad (§8.4) only for new paths. An updated file keeps its Soundpad entry because the path doesn't change. Whether Soundpad shows the old duration until it rescans is **unconfirmed** [probe follow-up].

**Relay:** needs the v2 relay (files addon and inventory). Until then, directors use the v0.3 director client's batch transfer, ideally with copies from **Normalize folder** (§8.4.2).

#### 8.4.2 Loudness Matching

Lines recorded at different levels sound uneven in a scene. The director's app measures each file's loudness and sends copies adjusted to one target. **High priority.**

**Measure** (in the director's UI page, so nothing is added to the download):
- Decode with Web Audio `decodeAudioData`, built into WebView2 and browsers: MP3, WAV, OGG and FLAC; AAC where the engine includes it. Everything is decoded at 48 kHz, so the math sees one rate and copies come out at 48 kHz. The agent streams the file to the page and writes the result back (`/api/folders/*`, `agent/folders.py`).
- Integrated loudness per ITU-R BS.1770-4 / EBU R128: K-weighting, 400 ms blocks with 75 % overlap, absolute gate −70 LUFS, relative gate −10 LU.
- True peak with 4× oversampling.
- Pure TypeScript in `web/src/lib/audio/loudness.ts`, unit-tested against the EBU Tech 3341 test signals.

**Adjust:**
- `gain = target − measured`, reduced if needed so the true peak stays at or below the ceiling. No limiter or compression, so dynamics stay as recorded. If the target can't be reached, the file is marked "quieter by n dB".
- Defaults: target **−16 LUFS**, ceiling **−1 dBTP** (open question 12). Per file: `normalize: false` or `gain_db` in the manifest (§8.4.1).
- Copies only; originals are never changed. Copies are cached in `<project>/.vrcas/normalized/`, keyed by the source SHA-256 and the settings, so unchanged files aren't processed twice.
- Output format (built): every copy is 16-bit WAV at 48 kHz with TPDF dither, mono or stereo as the source. Writing MP3 sources back as MP3 (256 kbps, in-page encoder) isn't built; it waits on open question 12.

**Where it's used:**
- **Project sync** (§8.4.1) sends the normalized copy. Inventories and the up-to-date check use the copy's SHA-256.
- **Normalize folder** (standalone, §15.1 step 1): the director picks a folder, and the app writes normalized copies to `<folder>/normalized/` and shows a table of file, measured loudness, gain and peak. It works right away with the v0.3 director client's batch transfer.
  - **Folder picker:** the desktop window's own dialog; in browser mode on Linux, `kdialog` (KDE) or `zenity`; otherwise a typed or pasted path.
  - **Limits on the agent side:** it reads only audio files inside folders opened in this run, writes only `.wav` files under `normalized/` (atomically), and refuses `..` and links leading outside.

**Limits:** this evens out the files, not the playback chain. Each actor's Soundpad volume (one global setting, §8.1.5), Windows mic level and VRChat mic volume still differ. A later "level check" step in the ready check could have each actor play a reference line for the director to judge by ear.

### 8.5 `obs` (Camera Operators)

#### 8.5.1 Connection

- Library: `simpleobsws` (asyncio, obs-websocket 5.x).
- **Config:** `url` (default `ws://127.0.0.1:4455`), `password`, `allow_remote_control`, `local_encoder`, `slate_scene_item`, `slate_media_input`.
- Sends `GetVersion` on connect and builds feature flags from `availableRequests`:

| Feature flag | Requires | Notes |
|---|---|---|
| `record_dir` | `SetRecordDirectory` | obs-websocket 5.3.0+ |
| `split` | `SplitRecordFile` | obs-websocket 5.5.0+ |
| `chapters` | `CreateRecordChapter` | obs-websocket 5.5.0+, **Hybrid MP4 only** (as of OBS 30.2) |

- Subscribes to `RecordStateChanged`, `StreamStateChanged`, `CurrentProfileChanged`, `ExitStarted`.

#### 8.5.2 Recording Profile Sync

```json
{
  "name": "VRC 1080p60",
  "video":     { "base": [1920, 1080], "output": [1920, 1080], "fps": [60, 1] },
  "recording": { "format": "hybrid_mp4", "codec": "h264", "rate_control": "CQP",
                 "quality": 20, "audio_bitrate_kbps": 192 },
  "filename_pattern": "{project}_S{scene}_T{take}_{camera}",
  "vrchat_window": { "match": false, "borderless": true },
  "strict": false
}
```

`vrchat_window` is the optional capture helper (§8.5.8).

**Apply algorithm:**
1. If an output is active, report `pending_idle` and retry once it stops.
2. Remember the operator's current profile, then switch to a dedicated `vrcActorSync` profile:
   - `CreateProfile` if it doesn't exist (this also switches to it), otherwise `SetCurrentProfile`.
   - **The operator's own profiles are never edited.**
3. `SetVideoSettings`.
4. `SetProfileParameter` for output mode, format, rate control, quality and audio bitrate.
   - **The encoder is a local setting** (`local_encoder`, chosen once by the operator). The profile only sets the codec family and quality.
5. Read everything back, compare, and report `obs.profile.status {compliant | mismatch | pending_idle | error, diffs}`.
6. `obs.profile.release`, or the operator's Release button, restores the remembered profile.

- The profile parameter keys per OBS version live in `agent/addons/obs/profile_keys.py`, filled in and checked in the OBS spike.
- The record directory stays local unless the director pushes one (needs `record_dir`).

#### 8.5.3 Roll → Speed → Action → Cut

```
Director UI                         Relay              Camera agent                 OBS
    │ obs.record.start {take_id,      │                     │                        │
    │   scene, take, at=now+1000ms}   │                     │                        │
    ├────────────────────────────────►├────────────────────►│ check consent/strict    │
    │                                 │                     │ set FilenameFormatting │
    │                                 │                     │ wait until `at` (§8.2) │
    │                                 │                     ├── StartRecord ────────►│
    │                                 │                     │◄─ RecordStateChanged ──┤ (STARTED)
    │◄── obs.record.state {rolling,   │◄────────────────────┤                        │
    │      started_at_server_ms}      │                     │                        │
    │ (all cameras rolling = "speed") │                     │                        │
    │ soundpad.play → actors (opt.)   │                     │                        │
    │ obs.record.stop {take_id}       │                     │                        │
    ├────────────────────────────────►├────────────────────►├── StopRecord ─────────►│
    │◄── obs.record.state {stopped,   │◄────────────────────┤◄─ {outputPath} ────────┤
    │      path, duration_ms, bytes}  │                     │                        │
```

**Camera states:** `offline`, `idle`, `armed`, `rolling`, `stopping`, `error`.

**Go on speed:**
1. Once every targeted camera reports `rolling`, wait for the pre-roll (default 2 s).
2. Then send `soundpad.play` to the selected actors (with their cue lists, if armed).
3. If a camera hasn't reported within 5 s, warn with **Go anyway** and **Cancel**.

**Marking takes:**
- `obs.mark {label}` → `CreateRecordChapter` when available. Otherwise the mark is only a take-log entry.
- When `split` is available, an optional **New take without stopping** calls `SplitRecordFile`.

**Errors and local control:**
- A `StartRecord` failure → `obs.record.state {error, message}`.
- The operator can always control OBS directly. The agent reports the real state from OBS events.

#### 8.5.4 Slate

OBS encoder startup varies, so aligned start requests don't give aligned frames. Shortly after `rolling`, the agent:
- Shows a configured slate scene item for about 2 frames (`SetSceneItemEnabled`)
- Restarts a configured beep media input (`TriggerMediaInputAction`)

This gives post-production a visual and audio sync point. The agent checks that the slate sources exist with `GetSceneItemId`.

#### 8.5.5 Status Telemetry

Every 2 s the agent sends `obs.status` with:
- From `GetRecordStatus`: `outputActive`, `outputDuration`, `outputBytes`
- From `GetStats`: `outputSkippedFrames`, `renderSkippedFrames`, `availableDiskSpace`, `activeFps`
- **Disk warning** below about 30 min at the current bitrate.

#### 8.5.6 Consent and Safety

- On a director's first `obs.*` command, the operator chooses **Allow for this session**, **Always allow this director**, or **Deny**.
- If the relay connection drops, recording keeps going and state re-syncs on reconnect.
- The agent never edits the operator's own profiles and never starts streaming without consent.

#### 8.5.7 Take Log

- Built from `obs.record.state`, `obs.mark`, `soundpad.*` and `cue.*` events.
- **CSV export columns:** date, project, scene, take, camera, file path, start (server time), duration, dropped frames, marks, sound played, notes.

#### 8.5.8 VRChat Window ↔ Recording Resolution (Capture Helper)

**Goal:** VRChat renders at exactly the OBS base resolution, so camera operators don't resize windows by hand and recordings aren't rescaled. Optionally VRChat renders *larger than the monitor* (e.g. 3840×2160 on a 2560×1440 screen).

**Why it matters:** OBS scales whatever it captures to the base resolution. A 1700×950 VRChat window recorded at 1920×1080 is upscaled and soft. A window at exactly 1920×1080 is captured pixel for pixel.

**Profile field** (optional, in the §8.5.2 profile):

```json
"vrchat_window": { "match": true, "borderless": true }
```

- The target size is `video.base`.
- `match: false` (the default) means nothing happens until the operator presses **Match VRChat window**.

**Two methods, chosen per machine:**

| Method | How | Restart VRChat? | Where |
|---|---|---|---|
| A. Live resize | Find the running VRChat window and set its inner (client) area to the target size | No | Windows; Linux X11; KDE Plasma on Wayland |
| B. Launch options | Generate the exact Steam launch-option line; the operator pastes it once | Yes | Everywhere |

**Method A per platform:**
- **Windows:**
  - Find the window owned by `VRChat.exe` with `EnumWindows` and a process lookup.
    - The process lookup is a Toolhelp snapshot, which gives names and ids only, so the agent never opens a handle to VRChat.
    - **Confirmed:** one visible window, class `UnityWndClass`, title `VRChat`.
  - The agent runs per-monitor DPI aware, so sizes are physical pixels and 150 % scaling doesn't turn 1920×1080 into 1280×720.
    - **Confirmed:** VRChat itself is per-monitor DPI aware, so Windows never stretches it. Its client size is its render size: OBS logged the swap chain at the client size after every change.
    - **Confirmed:** at 150 % a fresh start with the launch options gives exactly 1920×1080 physical pixels, and a live match to 1920×1080 at 150 % holds.
    - **Confirmed, needs handling:** changing Windows scaling *while VRChat runs* resizes it by the DPI ratio. At 125 % → 150 %, 1920×1080 became 2304×1296 and the render followed. So the agent re-checks the size on display or DPI changes (`WM_DISPLAYCHANGE`, or a poll every few seconds while matching is on) and reports `mismatch`.
  - Work out the outer size from the wanted client size (`AdjustWindowRectExForDpi`), call `SetWindowPos(…, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)`, then read `GetClientRect` back.
    - **Confirmed:** the bordered default window (`WS_OVERLAPPEDWINDOW`) needs +18×47 px at 125 %; a `-popupwindow` window needs none.
    - `SetWindowPos` returned in 36–58 ms; the operator saw a brief hitch.
    - The size still held at 0.5 s and 3 s; Unity didn't put it back.
    - Run `SetWindowPos` off the agent's event loop with a timeout, since it waits for VRChat's window thread.
  - Borderless: prefer the `-popupwindow` launch option (B). Changing another app's window style live is possible, but Unity may put it back (**unconfirmed**; not tried).
  - `tools/vrchat_window_probe.py` implements this (read-only by default; `--resize W H`, `--restore`).
- **Linux X11:** resize the window whose class is `steam_app_438100` (VRChat's Steam app id under Proton, to verify) with `xdotool` when it's installed; read the size back with `xwininfo`.
- **Linux Wayland:** Wayland doesn't let one app resize another app's window.
  - **KDE Plasma:** the agent loads a small KWin script over D-Bus (`org.kde.KWin`, `/Scripting`) that sets the VRChat window's client geometry.
  - **Other compositors** (GNOME etc.): Method B only.
- **Bigger than the monitor:** if Windows or Unity clamps the window, use Method B with gamescope (Linux) or driver super-resolution (AMD VSR / NVIDIA DSR on Windows), which the app explains but doesn't change.
  - **Confirmed on Windows: not clamped.** A 3840×2160 client area on a 2560×1600 monitor held at 3 s; the outer window was 3858×2207 with about a third of it off-screen.
  - OBS logged VRChat's swap chain at 3840×2160, so VRChat really renders at that size. 2560×1600 (taller than the screen once the title bar is added) also held.
  - VSR / DSR isn't needed on Windows for live resize.

**Method B lines** (built from `video.base`, plus the monitor size for gamescope):

| Platform | Steam launch options |
|---|---|
| Windows | `-screen-width 1920 -screen-height 1080 -screen-fullscreen 0 -popupwindow` |
| Linux (Proton), window = recording size | `%command% -screen-width 1920 -screen-height 1080 -screen-fullscreen 0 -popupwindow` |
| Linux, bigger than the monitor | `gamescope -w 3840 -h 2160 -W 2560 -H 1440 -- obs-gamecapture %command%`: VRChat renders at 3840×2160 inside a 2560×1440 window, and obs-vkcapture records the full 3840×2160 |

- Unity can remember the last resolution between runs, so the generated line always sets it explicitly.
- **Confirmed on Windows:** VRChat honours the Windows line.
  - With `-screen-width 1920 -screen-height 1080 -screen-fullscreen 0 -popupwindow` it started borderless (`WS_POPUP`, no caption) with a 1920×1080 client area at the monitor's top-left.
  - That held across two restarts, and again after a restart at 150 % scaling.
- `obs-gamecapture` comes with obs-vkcapture. Whether it works inside gamescope and next to Easy Anti-Cheat under Proton is **not tested** (Appendix C #7). The Linux lines are unverified.

**Capture source check:** the helper looks at the camera scene's sources (`GetInputList`) and warns when the source can't record the full render size:
- **Windows:** use **Game Capture**, which records the render output even where the window is off-screen. Window Capture may only show the visible part.
  - **Partly confirmed:** Game Capture hooked VRChat's 3840×2160 swap chain (shared-texture capture) while the window was larger than the screen. No recording file was checked.
  - What Window Capture records of an off-screen window is **unconfirmed**.
- **Linux:** use the obs-vkcapture source. PipeWire screen or window capture records what the compositor shows, which is the window size, not the render size.

**Flow:**
1. After a profile apply, or when the operator presses **Match VRChat window**, the agent finds VRChat and compares its client size and aspect ratio with `video.base`.
2. On a mismatch:
   - The operator sees "VRChat is 1700×950; recording is 1920×1080" with **Match now**, **Copy launch options** and **Ignore**.
   - The director sees ⚠ "window 1700×950" in that camera's profile status.
3. **Match now** (Method A) only works while the camera isn't recording, because resizing briefly stalls the game. The agent resizes, reads the size back and reports.
4. **Restore** puts the window back to its previous size and position.

**Consent and safety:**
- Needs the OBS consent from §8.5.6, plus a separate one-time "Allow vrcActorSync to resize the VRChat window" prompt.
- Never while recording.
- Never touches other windows.
- Never injects into VRChat: only standard window-manager calls, which matters with VRChat's Easy Anti-Cheat. OBS's own capture hook is outside the agent.
  - **Observed** with OBS 32.2.1: Game Capture hooked VRChat through its anti-cheat compatibility hook 8 times over about an hour, across 3 VRChat restarts and all the resizes. VRChat kept running and EAC raised nothing.
  - That's one machine and one session, not a guarantee.
- If VRChat isn't running, the state is `not_found` until the operator tries again.

**GPU cost:** rendering at 4K is expensive. While recording, if `renderSkippedFrames` / `outputSkippedFrames` (§8.5.5) keep rising, the operator sees "GPU can't keep up at 3840×2160", with a suggestion to switch to a smaller profile.

**Status:** `obs.profile.status` gains:

```json
"window": { "state": "matched | mismatch | not_found | unsupported | needs_restart | declined", "size": [1700, 950], "method": "live | launch_options" }
```

**Capabilities:** `obs.window.live` (Method A works on this machine) and `obs.window.launch` (always).

**Tests:** Appendix C.

### 8.6 `stream` (Future — P2P Preview)

**Build now:** reserve `rtc.*`, the `stream.publish` / `stream.view` capabilities, and `welcome.ice_servers`. Nothing else.

- **Option A (primary):**
  1. OBS's built-in WHIP output (`SetStreamServiceSettings` with type `whip_custom`, `{server, bearer_token}`) sends to a MediaMTX sidecar on the camera machine.
  2. Viewers pull over WHEP. The agent passes the WHEP handshake through the relay (`rtc.offer/answer`), and video flows peer-to-peer.
  3. It needs operator consent and refuses if OBS is already streaming, because OBS has one stream output.
- **Option B (fallback):** OBS Virtual Camera → `getUserMedia` in the operator's local UI page → `RTCPeerConnection`. The window or tab must stay open, and the video is re-encoded.
- **Option C (scale):** MediaMTX on the VPS as a relay server for many viewers. Not peer-to-peer.
- **NAT traversal:** STUN plus coturn TURN on the VPS. Tailscale peers usually connect directly.
- **Limits:** each viewer costs the operator one upload stream (estimated 2–4 Mbps at 720p).

### 8.7 `notify` (Headset Notifications)

People in VR can't see the desktop app, so the agent shows short status messages in their headset overlay. **On by default**; one switch in settings turns it off. All roles; Windows only for now.

| Message | When |
|---|---|
| **Standby** | The director sets `stage.state standby` (§8.8.1) |
| **Rolling** | The director sets `stage.state rolling` |
| **Not connected** | The relay connection has been down for more than 5 s |
| **Soundpad not detected** | Soundpad state `missing`, for actors with Soundpad enabled |
| **VRChat OSC is off** | OSCQuery doesn't find VRChat's OSC service (§8.9.1), for actors with OSC enabled |
| **OBS not detected** | The obs addon can't reach obs-websocket (camera operators, §8.5.1) |
| **Director is waiting** | A ready-check ping (§8.8.2) |
| **Connected**, **Soundpad found**, … | One of the errors above cleared |

- Nothing else goes to the headset: Go, Stop and chat stay out of it.
- **Rate limits:** an error is shown when it starts (after the 5 s grace period) and when it clears, and repeated at most once a minute while it lasts. Active errors ride along with Standby ("Standby · Soundpad not detected").
- **Not VRChat's chatbox:** `/chatbox/input` shows text above the avatar to everyone, so it would end up on camera.

**Targets** (adapters behind one `send(title, body, level)` call):
- **XSOverlay:** its notification API, JSON over UDP to localhost (port 42069 in current versions). **Unconfirmed** on the test box.
- **OVR Toolkit:** its local WebSocket API. **Unconfirmed** on the test box.
- The agent uses whichever one is running (Toolhelp process snapshot, as in `tools/vrchat_window_probe.py`) and skips quietly if neither is.
- Settings: on/off, `target: auto | xsoverlay | ovrtoolkit`, and a **Test notification** button.
- Linux (for example wlx-overlay-s) later.

**Later — "Your line next":** with character routing, each actor's file holds only their own lines, so a long silence in it means others are talking.
- The director UI finds silent gaps (below −50 dBFS for at least 4 s, both settable) while it measures loudness (§8.4.2), and sends them with the sound reference.
- The actor's agent follows the playback position as for audio-anchored cues (§8.3.4) and shows **Your line in 3** just before each gap ends.

### 8.8 Stage State and Ready Check

#### 8.8.1 Stage State

- `stage.state {state: "idle" | "standby" | "rolling", scene?}` from a director or assistant goes to everyone.
- The server keeps the current state and includes it in `welcome` and `presence.roster`, so late joiners see it.
- **Director UI:** **Standby**, **Rolling** and **Clear** buttons. Rolling is a signal only until the obs addon exists. Then Roll (§8.5.3) sets it automatically, and Cut returns to idle.
- Every app shows the state as a banner, and `notify` (§8.7) shows Standby and Rolling in the headset.
- **Compatibility mode** (v0.3 relay): the director's agent sends a chat line instead, `[stage] Standby`. v0.4 agents turn it into the state; v0.3 clients simply display it.

#### 8.8.2 Ready Check

1. The director presses **Ready check**, for everyone or for the targeted people: `ready.request {check_id, scene?}`.
2. Each agent runs its automatic checks and shows a checklist with a **Ready** button.
3. The agent sends `ready.status {check_id, ready, checks: [{id, ok, detail}]}`, and again whenever a check changes.
4. The director sees one row per person, with each check red or green and Ready or not, and a summary such as "5 of 6 ready".

| Role | Automatic check | Source |
|---|---|---|
| Actor | Soundpad found | soundpad state (§8.1.6) |
| Actor | Files up to date | project inventory (§8.4.1) |
| Actor | OSC on, VRChat OSC found | osc config; OSCQuery (§8.9.1) |
| Actor | Latency below the lead | RTT/2 vs. lead (§8.2.2) |
| Camera | OBS connected, profile applied, at least 30 min of disk | §8.5.1, §8.5.2, §8.5.5 |

- Being connected is implicit: someone who isn't connected shows as offline.
- **Ready** can also come from the avatar menu (§8.9.1), so actors don't need to leave VR.
- **Ping:** the director pings anyone not ready with `ready.ping {to}`. They get an in-app banner with a sound, a flashing taskbar button, and **Director is waiting** in the headset (§8.7). At most one ping per person every 5 s.
- Ready resets when a new check starts and when the stage returns to idle.
- **Go isn't blocked:** if anyone isn't ready, Go asks "2 not ready — Go anyway?" (open question 13).
- Needs the v2 relay: on a v0.3 relay camera operators are invisible and v0.3 clients can't answer.

### 8.9 `control` (Avatar Menu and Control Surfaces)

Trigger actions without touching the desktop app: from a VRChat avatar menu, a Stream Deck or a MIDI pad. Each input maps to an action the person's role can already send, and the relay enforces roles as usual (§5.5).

| Action | Roles |
|---|---|
| Go, Stop, Play in 3s | director, assistant |
| Standby, Rolling, Clear (§8.8.1) | director, assistant |
| Ready (§8.8.2) | actor, camera |

#### 8.9.1 VRChat Avatar Menu (OSC In)

- The avatar gets bool parameters `VRCAS_Go`, `VRCAS_Stop`, `VRCAS_Standby`, `VRCAS_Rolling` and `VRCAS_Ready`, set by **Button** controls in an expression menu.
  - They don't need network sync, which saves the synced-parameter budget. Whether VRChat sends unsynced parameters over OSC is **unconfirmed** [Windows check].
- VRChat sends parameter changes over OSC (`/avatar/parameters/<name>`). The agent acts on the rising edge (false → true) and ignores repeats within 500 ms.
- **No port clash:** VRChat sends to port 9001 by default, which face tracking and other OSC apps often hold. VRChat supports **OSCQuery**:
  - The agent opens an OSC server on a free port and advertises it over mDNS (`_osc._udp`, `_oscjson._tcp`, via `zeroconf`).
  - VRChat discovers it and sends to it alongside other apps.
  - Fallback: a manual port, or an OSC router.
- OSCQuery also tells the agent whether VRChat's OSC is on, for the ready check (§8.8.2) and `notify` (§8.7).
- **Setup:** ship a VRCFury prefab ("vrcActorSync menu") that adds the parameters and menu without editing the avatar by hand, plus manual instructions.
- **Safety:** by default, Go from the avatar menu only works during Standby (open question 14). Each action is confirmed in the headset ("Go sent").
- Off by default; each person turns it on in settings.

#### 8.9.2 Stream Deck and MIDI (Bitfocus Companion)

- Companion sends HTTP or OSC, and also covers MIDI controllers.
- **HTTP:** `POST /control/<action>` on the agent's local port with `Authorization: Bearer <control token>`.
  - The token is separate from the UI cookie (§7.7), shown once in settings, and can be regenerated.
  - The same Host check as the UI applies.
- **OSC:** `/vrcas/<action>` on a local UDP port bound to 127.0.0.1. OSC has no authentication, so it's off by default.

---

## 9. Web App

### 9.1 Stack and Port

- Svelte 5 + Vite + TypeScript, as in `origin/tauri` `client/`.
- Copy `client/src` to `web/src`, then:
  - Replace the ~33 `@tauri-apps/api` `invoke`/`listen` call sites across 15 components with `Transport` (§4.4).
  - Replace `@tauri-apps/plugin-dialog`:
    - `FileSender` → `<input type="file" multiple>`, or the agent's file dialog in the desktop app
    - `SoundpadConfig` → the agent's file dialog
- Keep the dark theme and the large, VR-friendly buttons.
- **New dependency:** wavesurfer.js v7 (Regions and Timeline plugins) for the editor.

### 9.2 Layout

```
web/src/
├── transport/   # Transport, RelayTransport, AgentTransport
├── protocol/    # generated types.ts
├── core/        # connection, chat/log, status bar, settings, update notifier, about
├── roles/       # director/, actor/, camera/ views
└── addons/
    ├── soundpad/  # actor transport + sound picker (director), local status (actor)
    ├── osc/       # timeline editor, cue list browser, param discovery
    ├── files/
    ├── obs/
    ├── stream/
    └── index.ts   # registry
```

### 9.3 Addon Panel Registry

```ts
registerPanel({
  id: "soundpad",
  roles: ["director", "assistant", "actor"],
  requiresCapability: "soundpad",    // shown only when a participant advertises it
  panel: SoundpadPanel,
  settings: SoundpadSettings,        // drawn from the addon's config schema
});
```

### 9.4 Overlay Routes (OBS Browser Sources)

| Route | Shows |
|---|---|
| `/overlay/tally` | Red border while this camera is rolling |
| `/overlay/cues` | Last triggered sounds and cues (ROADMAP "Soundboard overlay") |

### 9.5 Resilience

- Banners for "app disconnected" and "relay disconnected", with reconnect.
- State is restored from `GET /api/state` or `presence.roster`.

### 9.6 Stage Graph: Actor Output Visualizer

**Goal:** on the stage graph, an actor's node shows a small live level display while their Soundpad plays, so the director can see that sound is **actually coming out** when it's the actor's turn for a line. If Soundpad says `PLAYING` but nothing is audible, the node says so.

**Why not just show `PLAYING`:** the status reads `PLAYING` 5–6 ms after the command, before any audio (§8.1.6). It also stays `PLAYING` with the volume at 0, with the wrong output device, or with a muted line (mute on the mic line is unconfirmed, §8.1.5). The pipe has no level call, so the agent measures the level itself (§9.6.3).

**Rule: never fake it.** Bars are drawn only from measured samples. With no meter, the node keeps today's status-only look (§9.6.6).

#### 9.6.1 What the Director Sees

One state per actor node, decided on the **actor's agent** so every viewer sees the same thing:

| State | When | Node |
|---|---|---|
| Idle | `STOPPED`, no cue waiting | Unchanged. No visualizer |
| Cued | A cue arrived (`cue.ack`) and no audio yet. Normally under 0.1 s (§8.2.3); seconds with a scheduled start or the 3 s countdown (§8.2.2) | Slow pulse in the actor colour, flat bars |
| Playing | `PLAYING` and an audible sample (level above the floor) | Bars follow the level; the halo brightens with it |
| No sound | `PLAYING`, position advancing, and no audible sample in the first `silent_after_ms` (default 2000) after the position started moving | Flat amber line; sub text **No sound**, or the cause when Soundpad's state shows it: **Volume is 0**, **Muted**. Clears as soon as sound is heard |
| Paused | `PAUSED` | Bars frozen and dimmed; sub text **Paused** |
| Level unknown | No working meter (§9.6.6) | Today's look: halo, **Playing**, progress arc. No bars |

- **Natural pauses aren't flagged.** "No sound" only covers the start of a play: once sound has been heard, a gap in the performance doesn't warn. A file that opens with more than `silent_after_ms` of silence does trigger it (open question 17).
- **Whose turn:** every actor a cue targets runs its own state at the same time. The cue's packet animation to the node already marks the turn; the visualizer shows what happened next.
- The director gets no popup for "No sound" by default. It is on the node, and in the cast list row. (A headset or toast alert is open question 18.)

#### 9.6.2 Drawing It

- **Bars:** a short row of 5 thin bars under the node's circle, between the circle and the name. Each bar is one level sample, scrolling right to left over about 1 s. There is one number per sample, so it's a rolling level trace, **not** a spectrum analyser.
  - Bar height follows the level on a dB scale. Fast attack (~50 ms) and slow release (~300 ms), applied in the UI only.
  - The halo's opacity follows the smoothed level, so activity still reads when the bars are too small (phone width, small nodes). Below a size threshold only the halo and the arc show.
- **Progress arc:** a thin arc around the ring from `position_ms / duration_ms` (already in `soundpad.state`).
- **Same data elsewhere:** the cast list row (`CastPanel`) shows the state text and the same bars. The actor's **own** node shows its own bars from local data, with no relay involved.
- **UI rules (as for the rest of the UI):**
  - Sizes in `rem`; new colour tokens (`--level-ok`, `--level-silent`) in `app.css` for both themes.
  - Colour is never the only signal: the sub text and the `aria-label` carry the state. The label updates on state changes, not on every sample.
  - `[data-motion="reduce"]`: no scrolling or pulse; one static meter bar, redrawn at most twice a second.
  - A UI preference **Show output meters** (default on) hides the bars for people who find the motion distracting; the text states stay.

#### 9.6.3 Measuring the Level (Actor Agent, Windows)

- **Mechanism:** Windows Core Audio peak meters (`IAudioMeterInformation::GetPeakValue`). Reading a peak meter opens no audio stream and records nothing.
- **When:** sample every 50 ms only while Soundpad is `PLAYING`, `SEEKING` or `PAUSED`, plus a 1 s tail. No polling while idle.
- **Which meter**, by the output line (§8.1.4):

| `lines` | Who hears it | Meter (proposed) |
|---|---|---|
| `speakers` | The actor | Soundpad's own audio session on the playback device (per-process meter through `IAudioSessionManager2`) |
| `mic` | The audience in VRChat | Whatever carries Soundpad's microphone line: **unconfirmed** which device or session that is |
| `both` | Both | The `mic` meter, because what the audience hears matters most; the speakers session if there's none |

- **Per-process first.** A session meter hears only Soundpad, not VRChat or other apps. A meter on a microphone *endpoint* is used only if the probe shows that Soundpad's line has a device to itself. If the actor's real voice is mixed into the same device, the meter would light up for live speech and call it Soundpad output.
- **Level value:** the peak of each 125 ms window, converted to dBFS and mapped from −60…0 dBFS to an integer 0…100. **Audible** means at least −50 dBFS (proposed; tuned in the probe, above the noise of the virtual device).
- **Source label:** the agent reports `source` (`soundpad-session`, `mic-endpoint`, `none`). The node's tooltip shows what is being measured ("Meter: Soundpad speakers"), so nobody reads a speakers meter as proof that the audience heard it.
- **Unconfirmed [Windows check]:**
  - which meter matches each line, above all `mic` (§8.1.4);
  - whether the meter reads before or after Soundpad's volume and the Windows volume. If before, volume 0 would still show bars, and the agent would then report "No sound / Volume is 0" from the Soundpad state instead of from the meter;
  - whether reading a capture-endpoint meter trips Windows' microphone privacy indicator or setting;
  - which library to use (`pycaw` is a thin wrapper over the same COM calls, or `ctypes` directly), and whether it bundles cleanly with PyInstaller.

#### 9.6.4 Message and UI Contract

- **Fast samples:** `soundpad.level {level, source}` from the actor to directors and assistants only (§5.5), at most 8 per second, only while playing, ending with one `{level: 0}`.
  - Samples are lossy and never queued: if the connection is busy, the agent drops a sample rather than delay a `cue.ack` or any real message.
  - Roughly 50 small messages a second in total when six actors play at once.
- **Slow state:** `soundpad.state` (§8.1.6) gains `output: "cued" | "audible" | "silent" | "unknown"` and an optional `output_cause: "volume_zero" | "muted"`, sent on change like the rest of the state.
- **Capability** `soundpad.level` (§8.1.7). Directors draw bars only for actors that advertise it.
- **Not for timing.** What the director sees is late by RTT/2 plus up to 125 ms. It answers "is sound coming out", not "when did it start"; timing stays with §8.2.3 and §8.3.4.
- **UI contract** (all three sides change together, as in `AGENTS.md`):
  - `web/src/lib/protocol.ts`: `Peer` gains `output: {state, cause, source} | null`. Fast samples arrive as a separate event (`level {peerId, level, t}`) like the log and traffic events, **not** in the snapshot, so the whole state isn't re-sent 8 times a second.
  - `agent/core.py`: `snapshot()` fills `output`; the meter publishes `level` events through the hub. The actor's own node is fed directly.
  - `web/src/lib/demo/session.ts`: the demo session simulates a speaking actor and one whose volume is 0, so every state can be seen with `?demo=director`.
  - `web/src/lib/graph/level.ts` (new, pure, unit-tested like `layout.ts`) holds the smoothing and the sample history; `NodeGraph.svelte` only draws. `GraphNodeSpec` gains `output`. The per-node sample buffer is mutable like node positions, so template reads go through the `frame` counter.

#### 9.6.5 Settings and Privacy

- **`level_meter`** (soundpad config, §8.1.7): on by default. An actor can turn it off in Settings, which says: "Lets the director see whether your Soundpad is making sound. Sends a loudness number only, never audio, and never from your microphone." Off shows **Meter off** on the node and falls back to the status-only look.
- **Only Soundpad's output is measured.** The session meter is picked by Soundpad's process; the actor's real microphone and other apps are never read.
- **What leaves the PC:** an integer 0–100, up to 8 times a second, while Soundpad plays. It can't be turned back into audio. It does show how loud Soundpad's sound is over time (a line's rhythm), not its content.
- **`silent_after_ms`** (default 2000) is soundpad config on the actor's PC (§8.1.7), because the agent decides "No sound". Whether the director should set it per actor through `actor.settings` is open question 17.

#### 9.6.6 Fallbacks

| Situation | Result |
|---|---|
| Linux or macOS actor, or Soundpad simulated | No meter. Status-only look |
| No usable meter for the chosen `lines` (for example `mic` before the probe), or `level_meter` off | Capability not advertised, or `output: "unknown"`. Status-only look; the node says so in its tooltip |
| Legacy v0.3 actor (tkinter) | No capability. Status-only, as today |
| Compatibility mode (v0.3 relay) | A director sees no remote levels: the pipe protocol has nowhere to put them, and chat text would appear in v0.3 clients (§11.3). The actor's **own** node works fully |

**Alternatives rejected:**
- *Animate the bars from `PLAYING` alone.* It would show activity exactly when nothing is audible, which is the case the director needs to catch.
- *Soundpad's `GetRecordingPeak()`.* It belongs to Soundpad's recorder; using it would mean starting recordings on the actor's Soundpad.
- *WASAPI loopback of the whole playback device.* It hears every app and captures audio, where a peak meter reads one number.
- *Streaming the audio to the director.* That is the stream addon (§8.6), heavier, and a level is enough for "is it coming out".

#### 9.6.7 Testing

- `pytest`: the state machine (cued → audible → silent → paused), the floor and `silent_after_ms`, cause hints, rate limiting and dropping, all with a fake meter, like the fake pipe transport.
- `bun test`: `level.ts` smoothing, history and the reduced-motion path.
- Visual check on the demo session at desktop, 140 % VR and phone width, in both themes.
- **Windows only, can't be exercised on Linux:** the Core Audio meter itself. Appendix B steps 8–9.

---

## 10. Packaging, Installs and Updates

### 10.1 Builds

| | Installed | Portable |
|---|---|---|
| Artifact | `vrcActorSync-Setup-<ver>.exe` (Inno Setup 6) containing a PyInstaller **onedir** build | `vrcActorSync-<ver>-portable.exe` (PyInstaller **onefile**) |
| Install location | Per-user `%LOCALAPPDATA%\Programs\vrcActorSync` (`PrivilegesRequired=lowest`, no admin) | Anywhere (USB drive, Desktop folder) |
| Config and data | `%APPDATA%\vrcActorSync\` | `<exe folder>\vrcActorSync-data\` |
| Start menu, uninstaller, "Start with Windows" option | Yes | No |
| WebView2 | Installer runs the bundled Evergreen Bootstrapper if the runtime is missing | If missing → headless mode + browser |
| Updates | **Automatic** (§10.2) | **Notify only** (§10.3) |

- **Linux (directors):** an AppImage acting as the portable build, notify-only. Low priority.
- **Build detection:** an `unins000.exe` next to the exe (written by Inno Setup) means installed; otherwise portable. `--portable` forces portable mode.
- **Why onedir in the installer:** faster startup and fewer antivirus false positives than onefile.
- Keep the v0.3.3 SSL pattern (`certifi` hidden import, explicit `SSLContext`).
- pywebview on Windows depends on `pythonnet`. Pin the build's Python version to one supported by the pinned `pywebview` and `pythonnet` releases, and check this in CI.

### 10.2 Auto-Update (Installed)

1. **Check:** at startup, every 6 h, and whenever the relay sends `update.available`, read the manifest from the relay. A GitHub Releases URL in the manifest is optional.
2. **Download:** the installer goes to `%TEMP%`, with SHA-256 **and Ed25519 signature** verification. The public key is built into the app; the release workflow signs with a key kept in CI secrets. Up to 2 public keys are accepted, to allow key rotation.
3. **Apply:** only when idle — never while a sound is playing, a cue list is armed, or a camera is rolling.
   - Show "Update ready — restart now / later".
   - Run `Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /relaunch`. The installer's `[Run]` entry, gated on `/relaunch`, restarts the app.
4. **Rollback:** if the new version fails to start twice in a row, the next launch offers "Reinstall previous version". The last installer is kept in `%LOCALAPPDATA%\vrcActorSync\updates\`.
5. **Optional:** sign the installer and exes (for example Azure Trusted Signing, or SignPath for open source) to reduce SmartScreen warnings.

**Manifest additions** (old keys stay for legacy clients):

```json
"assets": {
  "agent-windows-x64-setup":    {"url": "…", "sha256": "…", "sig": "…"},
  "agent-windows-x64-portable": {"url": "…", "sha256": "…", "sig": "…"},
  "agent-linux-x64-appimage":   {"url": "…", "sha256": "…", "sig": "…"},
  "actor-windows-x64":          {"url": "…", "sha256": "…"},
  "director-windows-x64":       {"url": "…", "sha256": "…"}
}
```

### 10.3 Portable

- Everything stays in the exe folder. pywebview's `storage_path` and the logs go to `vrcActorSync-data\`; nothing is written to `%APPDATA%`.
- **Updates:** notify only, with a **Download** link and the release notes. The user swaps the exe; the downloaded file is verified the same way.
- Nothing is written to the registry.

---

## 11. Backward Compatibility (v0.3.x Clients)

### 11.1 Policy

- `/ws` keeps speaking the pipe protocol **with no removal date**. Its removal will only be considered after a full production cycle with no legacy sessions in the server logs.
- A server setting `legacy.enabled` (default `true`) can turn it off.
- Behaviour that stays the same: text frames, `PING`/`PONG` every 10 s, `REGISTER` with optional version/platform, `VERSION`/`UPDATE` replies, and base64 file chunks.

### 11.2 Translation

| Legacy | v2 |
|---|---|
| `MSG` | `chat.msg` |
| `PRIV` with `*`-prefixed text | `cue.*` to `{ids:[target]}` |
| `PRIV` other | `chat.priv` |
| `CMD` | `cue.*` to `{role:"actor"}` |
| `ACK` | `cue.ack` |
| `FILEREQ`…`FILEERR`, `BATCH_*` | `file.*` (the bridge converts base64 ⇄ binary and 64 KB ⇄ 256 KiB chunks; as built, §20.2: v0.3 directors' 64 KiB chunks pass through as they are) |
| `OSC_CUE` | `osc.param` |
| `APPROVE` / `DENY` / `FORGET_NAME` | `approval.*` |
| `STATUS` / `PENDING` / `USERS` | derived from `presence.roster` |
| `VERSION` / `UPDATE` | `welcome.version_status` / `update.available` |

### 11.3 Mixed Sessions

| Combination | Behaviour |
|---|---|
| New director → legacy actor | `soundpad.play {selected}` → `PRIV *go`; `{index: N}` → `*play:N`; `soundpad.stop` → `*stop` |
| | `path`, `lines`, `volume`, `seek` aren't possible; the director UI greys them out for actors with capability `legacy` |
| | **Scheduling emulation:** the server holds the message until `fire_at − RTT/2`, then sends it. Accuracy is network jitter, with no local clock sync |
| | **Cue lists:** the server sends each cue as an `OSC_CUE` message at its time. Legacy actors fire OSC on receipt, so timing is network-accurate rather than audio-anchored |
| | Files: full support through the bridge |
| Legacy director → new actor | `PRIV *go` → `cue.go` (play selected); `CMD` → all actors; `FILEREQ`… → `file.*`; `OSC_CUE` → `osc.param` |
| | New actors appear in `USERS`/`STATUS`/`PENDING`. Camera sessions are hidden from legacy directors |
| Legacy and new actors in one take | Both work. Timing on legacy actors is network-accurate; on new actors it is clock-synced |
| New app → v0.3.x server | Compatibility mode (§5.6): the agent speaks the pipe protocol. Directors cue by `PRIV *go` per targeted actor, like the v0.3 director; actors decline `FILEREQ` with a reason |
| New features → legacy clients | The bridge shows `stage.state` to legacy clients as a chat line (`[stage] Standby`, §8.8.1). `ready.*` and `file.inventory*` aren't translated: legacy actors show "no ready check" and an unknown sync status, and still receive files through the bridge |
| Output visualizer (§9.6) | `soundpad.level` has no pipe-protocol equivalent and isn't translated. Legacy actors have no meter, so their nodes keep the status-only look. In compatibility mode a v0.4 director sees no remote levels; an actor's own node works |

### 11.4 Migration Path for Existing Installs

- The existing v0.3 updater swaps one downloaded file over its own exe (`actor_client_ws.py:1098`). So the operator can point the manifest's `actor-windows-x64` asset at the **portable** v0.4 exe.
- Old actors then update themselves into the portable build. Their `config.json` next to the exe is imported on first run (§7.5).
- This is opt-in through the manifest, so the operator controls the rollout.

### 11.5 Compatibility Tests

- **Golden transcripts:** recorded v0.3.3 message sequences (register, approve, go/stop, play:N, batch transfer, OSC_CUE, forget) replayed through the bridge and compared byte for byte.
- **Scripted legacy client:** built on `shared.py` + `websocket-client`, run in integration tests next to v0.4 agents. (Built on the `websockets` sync client instead, an agent dependency: `tests/legacy_client.py`.)
- **Release checklist:** the real v0.3.3 tkinter clients against the new server.

---

## 12. Stability and Testing

| Layer | Tests |
|---|---|
| Protocol | Model round-trips; every legacy `MSG_TYPES` entry translates both ways |
| Server | Permission table (every role × type), routing, session mapping, approvals, cue list storage, legacy scheduling emulation |
| Agent core | Bus exception isolation, addon lifecycle, config migration, Host/Origin/token checks, scheduler (clock offset math, late handling, cancel) |
| Soundpad | **Fake Soundpad transport** (in-memory RC 1.1.2 responder, like the one used to check the probe): sound resolution, drift guard, trial limits, pause/seek idempotency, reconnect after a timeout |
| OSC | Address and type mapping; audio-anchored scheduling against the fake Soundpad's moving position (drift, pause, seek, stop → revert) |
| Files | Reassembly, SHA-256, atomic rename, auto-add hand-off |
| OBS | Fake obs-websocket v5 server: profile apply/diff, `pending_idle`, roll/cut, feature flags |
| Integration | Server + 2 agents + scripted legacy client: approve → scheduled play → cue list → file batch → roll/cut |
| UI | Playwright smoke tests for the desktop UI (in a browser) and hosted mode; editor model tests; `parse_character_name` tests |
| Packaging | Install → auto-update → config kept; portable writes nothing outside its folder; WebView2-missing → browser fallback |
| Windows test box | Appendix B, with real Soundpad, VRChat and OBS |
| Soak | 2-hour session with forced network drops: no lost approvals, no duplicate actors, recordings continue |

---

## 13. Feature Parity Matrix

| v0.3.3 feature | v0.4 home | Phase |
|---|---|---|
| Connect, auto-reconnect, keepalive | Agent `RelayClient` / `RelayTransport` | 1 |
| Director secret auth, approval, auto-approve known machine, forget | Server | 0 |
| Multi-director warning | `presence.roster` + UI banner | 2 |
| Chat, private messages | `chat.*` | 2 |
| `*go`, `*stop`, `*play:N` | `cue.*` + soundpad addon | 2 |
| Play in 3s countdown | Scheduled `at` (§8.2.2) | 2 |
| Per-actor checkboxes | `to.ids` | 2 |
| Latency dots | `presence.latency` | 2 |
| File transfer, batch, cancel, overwrite prompt, auto-accept, character routing | files addon + director UI | 2 |
| OSC toggle on Go/Stop | `osc.param` | 2 |
| Soundpad enable/disable, path, auto-detect | soundpad addon config | 2 |
| VRChat OSC host/port/enabled | osc addon config | 2 |
| Protocol versioning | `welcome.version_status` | 0 |
| Auto-updater (manifest + SHA-256) | Installed auto-update; portable notify (§10) | 5 |
| About / version display | UI | 2 |
| **New:** play a specific file, output lines, volume, mute, pause, seek, live status, sound picker | soundpad addon | 2 |
| **New:** per-actor delay, scheduled starts, latency calibration | §8.2 | 2 |
| **New:** OSC timeline editor with audio-anchored cues | osc addon + editor | 3 |
| **New:** OBS profile sync, roll/speed/cut, take log, tally | obs addon | 4 |
| **New:** VRChat window matched to the recording resolution | obs addon (§8.5.8) | 4 |
| **New:** browser access, hosted director mode | §4.2 | 1–2 |
| **New:** loudness matching, Normalize folder tool | director UI + files addon (§8.4.2) | §15.1 steps 1, 3 |
| **New:** headset notifications (Standby, Rolling, errors) | notify addon (§8.7) | §15.1 step 2 |
| **New:** stage state (Standby / Rolling) | `stage.*` (§8.8.1) | §15.1 step 2 |
| **New:** project folder sync (`vrcactorsync.yml`) | files addon (§8.4.1) | §15.1 step 3 |
| **New:** ready check with ping | `ready.*` (§8.8.2) | §15.1 step 4 |
| **New:** avatar-menu and Stream Deck / MIDI triggers | control addon (§8.9) | §15.1 step 5 |
| **New:** actor output visualizer on the stage graph, "No sound" warning | soundpad addon + web UI (§9.6) | §15.1 step 6 |
| **Future:** P2P camera preview | stream addon | later |
| **Future:** scene list, post-production export, "your line next" | — | later (§14) |

---

## 14. Rollout

| Release | Contents |
|---|---|
| v0.4.0-alpha | Phases 0–2. Portable build only, for the Windows test box. Legacy fully supported. Production helpers steps 1–4 (§15.1) |
| v0.4.0-beta | + OSC timeline editor + OBS addon + control input (§8.9) |
| v0.4.0 | + installer with auto-update, signed manifest; optional migration of v0.3 clients (§11.4) |
| later | stream addon; LAN/phone pairing; avatar-change detection; **scene list** ("run of show": ordered scenes, each with its cast, sounds, cue list and camera roll, run with Next + Go); **post-production export** (per take, a timeline of which clip started when on which actor, for DaVinci Resolve or Premiere, built on the take log §8.5.7); **"your line next"** (§8.7) |

- **Docs:** update README, ROADMAP and FEATURES-PLANNED. The v0.4.0 entry changes from "Tauri v2 + Svelte" to "Desktop web UI + local agent", and the OSC cue list spec points here.
- **`origin/tauri`:** tag it, keep it, and port the UI code and useful test cases.

---

## 15. Phases and Estimates

These are rough estimates for one developer.

| Phase | Work | Estimate |
|---|---|---|
| 0 | `vrcas_protocol`, server router + permissions + session IDs, legacy bridge with scheduling emulation, golden transcript tests | ~1–1.5 weeks |
| 1 | Agent core, pywebview shell + tray + browser access, local security, UI port to `Transport`, **portable dev build for the test box** | ~1–1.5 weeks |
| 2 | Soundpad addon (pipe client, full control, sound resolution, status), timing + delay compensation, osc + files addons, director/actor parity | ~2–2.5 weeks |
| 3 | OSC timeline editor (waveform, lanes, multi-parameter cues, anchoring, presets, parameter discovery) | ~1–1.5 weeks |
| 4 | OBS spike, then the obs addon, including the §8.5.8 window helper (~0.5 week of that) | ~1.5–2 weeks |
| 5 | Installer, auto-update with signatures, portable notify-only, legacy migration path, release checklist | ~1 week |
| later | stream addon + coturn | ~2–3 weeks |

**Through v0.4.0: about 7.5–10 weeks.** Phases 3 and 4 are independent and can be done in either order.

### 15.1 Production Helpers: Build Order

Agreed on 2026-10-20. Rough estimates for one developer, on top of the phases above.

| Step | Work | Depends on | Estimate |
|---|---|---|---|
| 1 | **Normalize folder** (§8.4.2): loudness measurement, gain, WAV/MP3 writing, results table | — | ~3–4 days |
| 2 | **Headset notifications** for errors (§8.7) and **stage state** with Standby / Rolling (§8.8.1), including the compatibility-mode chat line | Windows test box for the overlay APIs | ~3–4 days |
| 3 | **Project folder sync** (§8.4.1) with loudness matching on send | Phase 2 (files addon) | ~1–1.5 weeks |
| 4 | **Ready check and ping** (§8.8.2) | Phase 0 (v2 relay) | ~3–4 days |
| 5 | **Control input** (§8.9): avatar menu with OSCQuery and a VRCFury prefab, Companion endpoint | step 4 for Ready | ~1–1.5 weeks |
| 6 | **Actor output visualizer** (§9.6): Windows probe of the meters first, then the agent meter, `soundpad.level`, the node display and the demo session | Phase 2 (Soundpad status); Windows test box; v2 relay for directors | ~3–5 days, plus the probe session |

- Steps 1 and 2 don't need the v2 relay and can ship in the current preview.
- Step 6 can start with the pure parts (state machine, `level.ts`, demo session, node drawing) on Linux. The meter and the `mic`-line question wait for the probe. An actor's own node works on the current relay; directors seeing other actors needs the v2 relay.
- Later (§14): scene list, post-production export, "your line next".

---

## 16. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Local agent reachable by malicious websites | Remote control of Soundpad/OBS/files | §7.7 |
| Rapid Soundpad pipe requests break the pipe | Lost commands | One request at a time, ≥2 ms gap, reconnect on timeout |
| `SetVolume` is one volume for both lines (confirmed, §8.1.5) | Turning the actor's speakers down also makes the sound quieter for the audience | One "Volume" control, labelled as changing what everyone hears |
| Soundpad trial limits (`DoAddSound`) | No auto-add | Detect with `IsTrial()`; clear hint |
| Sound index drift after reordering | Wrong sound plays | Path references + drift guard (§8.1.3) |
| WebView2 missing or old | Blank or broken window | Registry check + headless fallback; installer bootstraps WebView2 |
| `pythonnet` / Python version mismatch | Build breaks | Pin versions; CI check |
| Unsigned installer | SmartScreen warnings | Optional code signing (§10.2) |
| Auto-update during a take | Session interrupted | Apply only when idle (§10.2) |
| OBS profile keys differ by version | Settings don't apply | Mapping table, read-back diff, OBS spike |
| Encoder startup variance | Cameras offset | Slate |
| Avatar detection by newest config file is wrong | Wrong autocomplete | Advisory only; manual entry always allowed |
| Protocol drift | Runtime errors | Shared pydantic package, generated TS, CI check |
| VRChat / Unity clamps the window to the screen size | No 4K-on-2K through live resize | Not clamped on the Windows test box (3840×2160 on 2560×1600 held). Otherwise: launch options; gamescope on Linux; driver super-resolution (VSR / DSR) on Windows |
| Windows scaling changes while VRChat runs | VRChat resizes itself by the DPI ratio and the match is lost | Re-check the size on display changes and report `mismatch` (§8.5.8) |
| Window control unavailable (Wayland outside KDE) | Operator sets the size by hand | Launch-option generator (§8.5.8 Method B) |
| Easy Anti-Cheat objects to a capture hook | VRChat won't start, or the capture is black | Agent uses window-manager calls only; test OBS Game Capture and obs-vkcapture with EAC (Appendix C) |
| XSOverlay or OVR Toolkit changes its notification API | No headset messages | Small adapters, **Test notification** button; the in-app banner always shows too (§8.7) |
| Headset notification spam | Distracted actors | Only Standby, Rolling, errors and pings; grace period and rate limits (§8.7) |
| VRChat doesn't find the agent over OSCQuery (mDNS blocked) | Avatar-menu triggers don't arrive | Manual port fallback; settings show whether VRChat was found (§8.9.1) |
| Accidental avatar-menu press | Unwanted Go | Go only during Standby by default; confirmation in the headset (§8.9.1) |
| Loudness matching evens out intended differences (whispers, quiet SFX) | Wrong mix | Per-file `normalize: false` and `gain_db`; originals untouched (§8.4.2) |
| The app rewrites a hand-edited manifest | Lost edits | Round-trip YAML, re-read before writing, atomic write, refuse on parse errors (§8.4.1) |
| No usable meter for Soundpad's `mic` line | Director can't see what the audience hears | Probe first (Appendix B step 8); fall back to the speakers session or `unknown` and say so on the node (§9.6.3, §9.6.6) |
| A microphone-endpoint meter also carries the actor's live voice | Shows "audible" for speech, not Soundpad | Per-process session meter first; endpoint meter only if Soundpad's line has its own device (§9.6.3) |
| Speakers meter taken as proof the audience heard it | False confidence | Source label on the node, `both` prefers the mic meter (§9.6.3) |
| "No sound" false alarm on a file that starts with silence | Director chases a non-problem | Warn only at the start of a play, `silent_after_ms` (§9.6.1); open question 17 |
| Level samples crowd real cue traffic | Delayed cues | Lossy, never queued, at most 8 per second, only while playing (§9.6.4) |

---

## 17. Existing Issues to Fix in v2 (Optional v0.3.x Hotfixes)

| # | Issue | Location | v2 fix |
|---|---|---|---|
| 1 | `APP_VERSION` is `"0.3.2"` but commit f4d3a76 says it bumped to 0.3.3 and `update_manifest.json` says 0.3.3, so 0.3.3 builds would be offered the update repeatedly | `shared.py:12` | One version constant checked against the manifest in CI; hotfix: `"0.3.3"` |
| 2 | No role checks on `CMD`, `PRIV`, `OSC_CUE`, `FILEREQ`; actors execute any private message starting with `*` | `server_ws.py:441`, `:457`, `:466`, `:634`; `actor_client_ws.py:614` | §5.5 table (also on legacy traffic) |
| 3 | Routing by display name | `server_ws.py:448`, `:472`, `:511`, `:638` | Session IDs |
| 4 | Server transfer table keyed by filename only | `server_ws.py:474` | Transfer UUID |
| 5 | Client-supplied `sender` is trusted | `server_ws.py:436` | Server sets `from` |
| 6 | "Forgotten" is detected by matching message text | `actor_client_ws.py:601` | `approval.forgotten` |
| 7 | `\|` in filenames breaks the pipe protocol | `shared.py` parser | JSON envelope |
| 8 | `set_volume` validates and sends 0.0–1.0, but Soundpad's `SetVolume` takes 0–100. The probe confirmed `SetVolume(0.5)` sets the volume to 0 | `soundpad.py:169-174` | §8.1.5; hotfix on main (0.3.3): scale to an int 0–100 |
| 9 | `find_update` treats any version mismatch as "update available", so a client *newer* than `latest_version` is offered a downgrade once the manifest has URLs | `server_ws.py:80-113` | Compare versions properly (offer only when `latest > client`); the v0.4 agent already ignores offers older than itself |

---

## 18. Open Questions

1. **Agent default port:** proposal `47800`, falling back to the next free port.
2. **Secrets storage:** keep them in `config.json` (as today) or move to the OS keyring?
3. **Take log location:** the server, the director UI, or both?
4. **MediaMTX for the stream addon:** bundle it or download on demand? Confirm the license and ICE config keys.
5. **Assistant director permissions:** may assistants roll cameras and play sounds? The §5.5 proposal says yes. **Built as proposed** (§20.1): assistants use the director secret and get the director's rights except approvals and `actor.settings`.
6. **Close button:** hide to the tray (proposed) or quit?
7. **Cue list storage:** on the server only (proposed), or also cached on the director's machine for offline editing?
8. **Auto-added files in Soundpad:** should they also go into a dedicated "vrcActorSync" category? This depends on whether `DoAddSound(url, category, position)` duplicates the entry in All sounds **[probe follow-up]**.
9. **Default `lines` per actor:** `both`, or `mic` for actors who don't want to hear their own cues?
10. **Window helper default:** only offer the match (proposed), or apply it automatically with each profile push once the operator has consented?
11. **Default Linux route for bigger-than-monitor recording:** gamescope (any compositor, needs a VRChat restart) or KWin live resize (KDE only, no restart)?
12. **Loudness defaults (§8.4.2):** target −16 LUFS (common for spoken word online, proposed) or −23 LUFS (broadcast)? Should MP3 sources be re-encoded as MP3 (small, a second lossy generation, proposed) or written as WAV (lossless, several times larger to send)?
13. **Ready check and Go (§8.8.2):** only warn (proposed), or block Go until everyone is ready?
14. **Avatar-menu Go (§8.9.1):** only during Standby (proposed), or always?
15. **Project auto-sync (§8.4.1):** off, with a Sync button (proposed), or on?
16. **Manifest name (§8.4.1):** `vrcactorsync.yml` (proposed, visible) or `.vrcactorsync.yml` (hidden by file browsers)?
17. **"No sound" timing (§9.6.1):** 2 s after the position starts moving (proposed), and set on each actor's PC (proposed) or per actor by the director through `actor.settings`? Lines that open with long silence need a longer value.
18. **"No sound" alert (§9.6.1):** only on the node and cast row (proposed), or also a toast for the director and a headset message (§8.7)?
19. **Meter on the `mic` line (§9.6.3):** if no meter for it exists, is the speakers meter shown for `both` with its source label (proposed), or is the node left at `unknown`?

---

## 19. Success Criteria

- [ ] On a clean Windows 10/11 machine: install → window opens → **Open in browser** shows the same live UI
- [ ] Without WebView2, the portable build falls back to the browser with a clear hint
- [ ] The director plays a **specific file** on 2 actors, **speakers only**, then **both**, and changes **volume**, with live position shown
- [ ] Scheduled play with `delay_ms` +150 ms on one actor: the measured fire-time difference is within ±20 ms of 150 ms (agent logs)
- [ ] An OSC cue list with 3 cues × 2 actors (one cue with 2 parameters) fires on the audio-anchored timeline; reported lateness ≤ 20 ms; pause and stop behave as specified
- [ ] The installed build auto-updates between two test versions while idle and keeps its config; it doesn't update during playback
- [ ] The portable build writes nothing outside its folder and only notifies about updates
- [ ] v0.3.3 tkinter clients and v0.4 apps work together on the same server (§11.3), including file transfer
- [ ] Any approved actor sending a cue or `PRIV *go` to another actor is rejected
- [ ] The director pushes an OBS profile to 3 cameras and gets `compliant` or a precise diff; Roll/Cut produces a take-log CSV
- [ ] On Windows, one click matches a camera operator's VRChat window to the profile resolution, and the director sees `matched` or the actual size
- [ ] An actor plays a line on `both`: the director's graph shows that actor's bars moving with the sound and returning to idle at the end. With Soundpad volume 0, the node says **No sound** within `silent_after_ms` and clears when the volume is raised
- [ ] The local agent rejects a foreign `Host`/`Origin` or a missing token
- [ ] The §12 test suite runs in CI

---

## Appendix A — Soundpad Remote Control Reference (RC 1.1.2)

Source: Leppsoft's `SoundpadRemoteControl.java` (client version 1.1.2), which Leppsoft keeps current as the complete list. Commands marked ✔ are used by the soundpad addon.

**Pipe protocol:**
- `\\.\pipe\sp_remote_control`, local only.
- Write the UTF-8 command and read the reply. Actions reply `R-<HTTP status>` (`R-200` = OK, `R-404` = not found); getters reply with a value or XML.
- One request at a time. The reference client keeps at least 1 ms between requests; the addon uses 2 ms.

| Command | Since | Returns | Use | Test box (Soundpad 4.0.35, 2026-10-19) |
|---|---|---|---|---|
| `IsAlive()` | 1.0.0 | `R-200` | ✔ health check | Confirmed; 0.10 ms round trip |
| `GetVersion()` | 1.0.0 | Soundpad version | ✔ diagnostics | Confirmed: `4.0.35` |
| `GetRemoteControlVersion()` | 1.0.0 | e.g. `1.1.2` | ✔ feature flags | Confirmed: `1.1.2` |
| `IsTrial()` | 1.1.2 | `1` / `0` | ✔ disables auto-add | Confirmed: `0` (full version); trial unconfirmed |
| `DoPlaySound(index)` | 1.0.0 | `R-200` if the index exists | ✔ legacy `*play:N` | Confirmed (agent, `*play:6`): plays on **both** lines (listen test). The answer for an index that doesn't exist is unconfirmed |
| `DoPlaySound(index, renderLine, captureLine)` | 1.0.0 | `R-200` | ✔ play with output lines (speakers = render, mic = capture) | Confirmed, all three line combinations by listen test (§8.1.4) |
| `DoPlaySelectedSound()` | 1.1.0 | `R-200` | ✔ legacy Go | Confirmed (agent, relay GO ×5): plays on **both** lines; audio ≈55 ms after the command (§8.2.3) |
| `DoPlaySoundFromCategory(cat, pos, render, capture)` | 1.1.1 | `R-200` | ✔ category references (`cat = -1` → current category) | Unconfirmed |
| `DoPlayCurrentSoundAgain()`, `DoPlayPreviouslyPlayedSound()`, `DoPlayPreviousSound()`, `DoPlayNextSound()` | 1.0/1.1 | `R-200` | — | Not tested |
| `DoPlayRandomSound(render, capture)`, `DoPlayRandomSoundFromCategory(cat, render, capture)` | 1.1.2 | `R-200` | — | Not tested |
| `DoStopSound()` | 1.0.0 | `R-200` | ✔ | Confirmed: `STOPPED` at the next read. Don't send it during `SEEKING` (§8.1.2) |
| `DoTogglePause()` | 1.0.0 | `R-200` | ✔ (wrapped to be idempotent) | Confirmed: `PAUSED` with the position frozen, then `PLAYING` again |
| `DoSeekMs(ms)` | 1.0.0 | `R-200` | ✔ absolute seek | Confirmed: `SEEKING` for 20–50 ms, then the exact target |
| `DoJumpMs(ms)` | 1.0.0 | `R-200` | ✔ relative jump (negative = back) | Unconfirmed |
| `GetPlayStatus()` | 1.0.0 | `STOPPED` / `PLAYING` / `PAUSED` / `SEEKING` | ✔ | Confirmed: all four seen. `PLAYING` 5–6 ms after a play command, before any audio |
| `GetPlaybackPositionInMs()` | 1.0.0 | number | ✔ cue anchoring, status | Confirmed: moves in steps about 140 ms apart; keeps the last value after a stop (§8.1.6) |
| `GetPlaybackDurationInMs()` | 1.0.0 | number | ✔ | Confirmed: exact ms while playing (49721 for a "0:50" sound); keeps the last value after a stop |
| `GetVolume()` / `SetVolume(0–100)` | 1.0.0 | number / `R-200` | ✔ volume of **both** lines (listen test) | Confirmed: 0–100. `SetVolume(0.5)` answers `R-200` and sets 0 |
| `IsMuted()` / `DoToggleMute()` | 1.0.0 | `1`/`0` / `R-200` | ✔ speakers | `IsMuted()` confirmed (`0`); `DoToggleMute()` unconfirmed |
| `GetSoundFileCount()` | 1.0.0 | number | ✔ change detection | Confirmed |
| `GetSoundlist()`, `GetSoundlist(from)`, `GetSoundlist(from, to)` | 1.0.0 | XML (All sounds; indices start at 1) | ✔ picker, path → index, drift guard | Confirmed: `GetSoundlist()` and `(from, to)`; attributes in §8.1.3. `(from)` unconfirmed |
| `GetCategories(withSounds, withIcons)`, `GetCategory(i, withSounds, withIcons)` | 1.1.0 | XML | ✔ category references | `GetCategories(false, false)` confirmed: `<Categories>` of `<Category index name type hidden>`, starting with the hidden "All sounds" (index 1). `GetCategory` unconfirmed |
| `DoAddSound("path")`, `DoAddSound("path", index)` | 1.0.0 | `R-200` | ✔ auto-add (**not in the trial**) | `DoAddSound("path")` confirmed: `R-200` at once, listed shortly after (§8.1.3). `(path, index)` unconfirmed |
| `DoAddSound("path", categoryIndex, position)` | 1.1.0 | `R-200` | Open question 8 | Unconfirmed |
| `DoAddCategory("name", parentIndex)`, `DoRemoveCategory(i)`, `DoSelectCategory(i)`, `DoSelectPreviousCategory()`, `DoSelectNextCategory()` | 1.1.0 | `R-200` | Open question 8 | Not tested |
| `DoSearch("term")`, `DoResetSearch()`, `DoSelectPreviousHit()`, `DoSelectNextHit()`, `DoSelectIndex(row)`, `DoScrollBy(rows)`, `DoScrollTo(row)` | 1.0.0 | `R-200` | — | `DoResetSearch()` through `Soundpad.exe -rc` only (179 ms) |
| `DoRemoveSelectedEntries(removeOnDisk)`, `DoUndo()`, `DoRedo()`, `DoSaveSoundlist()` | 1.0.0 | `R-200` | — (`DoRemoveSelectedEntries` not in the trial) | Not tested |
| `DoStartRecording()`, `DoStopRecording()`, `DoStartRecordingSpeakers()`, `DoStartRecordingMicrophone()`, `GetRecordingPositionInMs()`, `GetRecordingPeak()` | 1.0/1.1 | — | — | Not tested |
| `GetTitleText()`, `GetStatusBarText()` | 1.0.0 | text | diagnostics | Not tested |

**Not available through RC:**
- Playing a file that isn't in the sound list. It must be added first.
- Per-sound volume.
- A separate mic-line volume. `SetVolume` sets one volume for both lines (confirmed by listen test).

---

## Appendix B — Windows Test Plan

**Setup:**
- Windows 10/11 with Soundpad running and at least 3 sounds, one longer than 5 s.
- Python 3.8+ (only for the probe; the app itself won't need Python).
- VRChat and a second listener for the listen tests.

| # | Step | Confirms |
|---|---|---|
| 1 | `python tools\soundpad_probe.py --json probe-readonly.json` | Pipe access, RC version, trial/full, XML attribute names, pipe round-trip latency, VRChat OSC config format |
| 2 | `python tools\soundpad_probe.py --play <long sound #> --line speakers --json probe-play.json` | Start latency, position reporting, pause/seek/stop; the listener does **not** hear it |
| 3 | Same with `--line both`, then `--line mic` | The listener hears both; the actor hears `mic` only through VRChat (if at all) |
| 4 | `python tools\soundpad_probe.py --volume --json probe-volume.json`, then play on `both` at 40 vs 100 | 0–100 scale, what `SetVolume(0.5)` does (§17 #8), whether volume reaches the mic line |
| 5 | `python tools\soundpad_probe.py --add C:\path\test.mp3` (full version) | `DoAddSound` works; the new entry's `url`/`index` |
| 6 | `python tools\soundpad_probe.py --cli` | CLI cost compared with the pipe |
| 7 | Reorder sounds in Soundpad, run step 1 again | Index drift: indices change, `url` stays |
| 8 | Output meters (§9.6.3): play a long sound with `--line speakers`, then `mic`, then `both`. For each, read the peak of Soundpad's audio session on the playback device and of each capture endpoint (a small addition to the probe) | Which meter moves for which line; whether Soundpad's microphone line has a device or session of its own; whether the actor's real voice shares it; sampling cost at 50 ms |
| 9 | Same plays at Soundpad volume 0 and 100, with Windows' per-app volume lowered, and once muted; also check whether reading a capture-endpoint meter trips the Windows microphone privacy indicator | Whether the meter reads before or after volume (decides if "No sound / Volume is 0" must come from the Soundpad state); the audible floor above the device's noise; the privacy behaviour |

Send the JSON files back. Results update Appendix A, close the **[probe]** items, and set the defaults for latency compensation.

**Results (2026-10-19, Windows 11, Soundpad 4.0.35 full version, RC 1.1.2):**
- Steps 1–6 were run, with a listener in VRChat for steps 2–4. The findings are in §8.1, §8.2.3 and Appendix A.
- Step 4's 40 vs 100 on `both` was inconclusive, so it was repeated on `mic` at 5 vs 100, which was clear.
- Step 7 (reordering) wasn't run, so index drift is **unconfirmed**.
- Probe changes made along the way:
  - Positions count only after `PLAYING`, because the stale position after a stop otherwise looks like an instant start.
  - The probe records how often the position changes.
  - It seeks to 5 s, so a stale read can't pass.
  - `--add` waits for the list to grow.
- Raw JSON stays on the test box in `tools/probe-results/`. That folder is git-ignored because it holds sound titles and paths.

---

## Appendix C — Capture-Resolution Test Plan (§8.5.8)

**Setup:** VRChat in desktop mode (windowed) and OBS 30+. Windows: one 1440p monitor, if possible. Linux: KDE Plasma on Wayland, with gamescope and obs-vkcapture installed.

| # | Step | Confirms | Result (2026-10-19) |
|---|---|---|---|
| 1 | Windows: resize the VRChat window to the monitor size, then to 3840×2160 on a 1440p monitor (agent button or a small `SetWindowPos` script) | Live resize works; whether Windows or Unity clamp to the screen size | **Confirmed**: 2560×1600 and 3840×2160 on a 2560×1600 monitor both held; no clamping; swap chain followed |
| 2 | OBS Game Capture of the oversized window, base resolution 3840×2160 | The full render size is recorded, not only the visible part | **Partly**: Game Capture hooked the 3840×2160 swap chain; no recording made, so the file is unchecked |
| 3 | Same with Window Capture | Whether off-screen parts are captured (expected: no) | **Not tested** (recordings skipped) |
| 4 | Steam launch options `-screen-width 1920 -screen-height 1080 -screen-fullscreen 0 -popupwindow` | VRChat honours them, borderless, and still after a restart | **Confirmed**: borderless 1920×1080 at the top-left, after two restarts |
| 5 | Windows display scaling at 150 %, match to 1920×1080 | Physical pixels match (no 1280×720 surprise) | **Confirmed**: 1920×1080 physical both by live resize and by restart at 150 %. Also found: changing scaling while VRChat runs resizes it by the DPI ratio (§8.5.8) |
| 6 | KDE Wayland: KWin script resize of the `steam_app_438100` window | The KWin route works | **Not tested** (Windows box only) |
| 7 | Linux: `gamescope -w 3840 -h 2160 -W 2560 -H 1440 -- obs-gamecapture %command%` | VRChat starts under Proton with EAC; obs-vkcapture records 3840×2160 | **Not tested** (Windows box only) |
| 8 | Record 10 minutes at 4K in a busy world | GPU headroom; the dropped-frame warning fires when it should | **Not tested** (optional, skipped) |

Test box: Windows 11 24H2, one 2560×1600 60 Hz laptop display at 125 % (150 % for #5), RTX 3070 Laptop GPU, OBS 32.2.1, VRChat in desktop mode. Probe: `tools/vrchat_window_probe.py`. The swap-chain sizes come from OBS's own game-capture log lines (`DXGI_SWAP_CHAIN_DESC`).

Results close the **[window test]** items in §8.5.8.

---

## References

- Soundpad Remote Control: https://www.leppsoft.com/soundpad/en/rc/ and manual §3.9: https://www.leppsoft.com/soundpad/help/manual/tutorial/rc/
- Soundpad RC reference client (1.1.2): https://www.leppsoft.com/soundpad/files/rc/SoundpadRemoteControl.java
- pywebview API: https://pywebview.flowrl.com/api/ and web engines: https://pywebview.flowrl.com/guide/web_engine.html
- WebView2 distribution: https://developer.microsoft.com/en-us/microsoft-edge/webview2/
- obs-websocket 5.x protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
- simpleobsws: https://pypi.org/project/simpleobsws/
- OBS WHIP service (`whip_custom`, `bearer_token`): `plugins/obs-webrtc/whip-service.cpp` in obs-studio
- Previous design: `docs/superpowers/specs/2026-07-20-vrcActorSync-ssl-tauri-design.md`
- Reusable UI code: `origin/tauri` → `client/src/`
- Probe script: `tools/soundpad_probe.py`

---

## 20. Implementation Status (branch `feat/web-ui`, updated 2026-10-21)

| Area | Built | Verified |
|---|---|---|
| Web UI (`web/`, Svelte 5 + Vite, Bun) | Role onboarding (role remembered, app reopens in it), director / actor / camera views, animated node graph (stage layout, packets only while commands travel), dark / light / system theme, UI scale 75–200 % + VR mode, reduce motion, settings, activity & chat drawer, toasts, demo session | `bun test` (22), `svelte-check` 0 errors, visual checks at desktop, 140 % VR and phone width |
| Agent (`agent/`) | Config (installed / portable / v0.3 import), local server with Host/Origin/token guard, UI socket, pywebview window with browser fallback, compatibility-mode relay client, Soundpad named-pipe client with `-rc` fallback (live status, version info, start-latency logging), OSC | `pytest` (19) incl. end-to-end against the real `server_ws.py`; manual run of relay + director + actor agents in the browser |
| Relay v2 and the agent's v2 client (Phase 0, built on `feat/relay-v2` 2026-10-20, merged into `feat/web-ui` 2026-10-21) | `protocol/vrcas_protocol` + generated `web/src/protocol/types.ts`; `server/`: `/v2/ws` (handshake, session ids, routing, roster with cameras, approvals, `actor.settings`, `time.pong`, relay-measured latency), the §5.5 table on both endpoints, the `/ws` bridge with scheduling emulation; `agent/relay_v2.py` + `agent/relay.py` (v2 first, compatibility mode on a 403/404) | `pytest` 552: golden transcript from the frozen v0.3.3 relay replayed byte for byte (also with a v2 camera and assistant connected), every table row × role on `/v2/ws`, mixed sessions, scheduling on a fake clock, agents end to end with scripted v0.3 clients. Separate processes on port 5601 (relay, 3 agents, scripted v0.3 director and actor): 30/30 checks. Frozen Linux build connects over v2. Manual checklist part A (2026-10-21): the real v0.3.3 director and actor and a Windows build of the agent against a test relay, all pass (OSC skipped). The live relay runs this code since 2026-10-21 (checklist part B) |
| Agent build (`build_agent.py`) | PyInstaller, one file or one folder. Windows: windowed (pywebview + WebView2). Linux: a console program that opens the browser | Linux one-file build on CachyOS (glibc 2.35+ when built with uv's standalone Python). Windows one-file build on Windows 11: window without the browser fallback, Soundpad over the pipe while frozen (Go / Stop / `*play:N` 41–58 ms), `--portable`, an actor on the live `wss://` relay; a build of the relay v2 branch in the checklist (2026-10-21). Unsigned: SmartScreen blocks downloaded copies |
| Soundpad addon (§8.1, Phase 2 M2, built on `feat/phase2-soundpad`, merged into `feat/web-ui` 2026-10-21) | `vrcas_protocol` `soundpad.*` models (`SoundRef.key`, list pages, state, ack `command`); actor runtime: sound references (key, path, sha256, index, category, selected) with the drift guard, output lines, volume / pause / seek / jump / mute, the list and its changes, auto-add and auto-start (`agent/actor_runtime.py`, `agent/sounds.py`); `agent/soundpad_remote.py` (acks, list pages, `soundpad.state` to directors); director calls `play`, `playIndex`, `transport`, `requestSounds`; Soundpad panel per actor, Play #N in the cue deck, the actor's Soundpad card and settings | `pytest` 729 (in-memory Soundpad: resolution, drift guard, auto-add vs trial, lines arguments, idempotent pause / mute, stop during `SEEKING`, list paging and changes, state throttling, a closed Soundpad never reached through `-rc`; director ↔ actor end to end through a relay; a slow cue doesn't hold up the connection); `bun test` 77; UI in the browser (demo, desktop and 390 px). Windows 11 laptop (2026-10-21, plan §5.5) with Soundpad 4.0.35, a v0.4 director and actor and the v0.3.3 actor: all nine steps pass (the list matches Soundpad and the raw `soundpad.list` frame carries no paths; lines by the logs and the actor's card; transport; a moved sound still plays; a received file is added and plays; Play #N on both actor versions; Soundpad closed and back; Detect and auto-start; the default line). Its findings (a GO with Soundpad closed started and then killed it; cues blocked the receive loop; toasts hidden behind drawers; 0:49 vs 0:50; seek bar jumps; no repeat guard) are fixed, and the re-check passed: a GO with Soundpad closed fails in ~120 ms and starts nothing, latency stays ~50 ms, auto-start starts Soundpad and keeps it, the toast shows over Settings, lengths read 0:50, no backward steps in 64 frames, a held Enter gave 3 plays instead of ~350. Not checked: the audience side of the `mic` / `both` lines in VRChat |
| Timing (§8.2, Phase 2 M3, built on `feat/phase2-timing`, merged into `feat/web-ui` 2026-10-22) | `agent/timesync.py` (clock sync), `agent/scheduler.py` (actions at server times, cancel by group, ~1 ms timers), `agent/cues.py` (who gets what on GO); actors run `at + delay − start latency` and cancel on Stop; GO at now + lead, Play in 3s at now + 3 s with the countdown on every agent; directors hold cues for builds without `schedule`; per-actor delay (`actor.settings`); `soundpad.calibrate` and saved start latencies; armed sounds; `vrcas_protocol` `soundpad.calibrate` model and `soundpad.ack.start_latency_ms` | `pytest` 756 (sync math with asymmetric and noisy samples, the lowest round trip, the scheduler on a fake clock, the GO plan; end to end through a relay: two actors at 0 and +150 ms fire 148–150 ms apart, Play in 3s cancelled at 1 s on a v2 and a scripted v0.3 actor, armed sounds with one `at` and a v0.3 actor armed by number, an older build held by the director, late and too-far cues, calibration against the in-memory Soundpad; armed by number in compatibility mode); `bun test` 88; separate processes on port 5601 (relay, director, two actors): GO gaps 149–150 ms in the actors' `agent.log` lines, the countdown cancelled everywhere, two armed sounds sent at the same server time; UI in the browser (demo, desktop and 390 px). Windows 11 laptop (2026-10-21, plan §6.2; Python 3.12, Soundpad 4.0.35, two v0.4 actors, a v0.4 director and the v0.3.3 actor on one PC): a +150 ms delay gave 150–151 ms between the actors' sound-due times on all 8 GOs, every send exactly on its planned time, no late starts; the three apps agreed on the clock within 6 ms (9.18 s behind the relay); Play in 3s cancelled at 1 s on every actor, the v0.3.3 one included; calibration speakers-only, 29–31 ms; two armed actors 0 ms apart, the v0.3.3 actor armed by number. Its three UI findings are fixed (§20.2) and the re-check passed (2026-10-22) |
| Files between v0.3 clients and v0.4 apps (§11.2, Phase 2 M1b, built on `feat/phase2-files-bridge`, merged into `feat/web-ui` 2026-10-21) | `server/file_bridge.py`: both directions, batches, cancel, clean-up when either side leaves; the director's agent ends a file on a relay `error` | `pytest`: `tests/test_files_bridge.py` (22, frame by frame), agent end to end with scripted v0.3 clients in both directions; golden transcript unchanged. Windows 11 laptop (2026-10-21, plan §4.4) with the real v0.3.3 director and actor, a v0.4 director and a v0.4 actor: all seven steps pass (both directions, batches, a single send, cancel between files and mid-file, a declined overwrite, v0.3 ↔ v0.3 regression), hashes match, no partial files; the relay's log agrees |
| Files between v0.4 apps (§8.4, Phase 2 M1a, built on `feat/phase2-files`, merged into `feat/web-ui` 2026-10-21) | `vrcas_protocol` `file.*` models + `chunks.py`; `server/transfers.py` (transfer table, chunk forwarding, clean-up, one `server.log` line per transfer); `agent/files.py` (Receiver, Sender); Send files panel, actor prompt and Files card, receive settings; `parseCharacterName` in TypeScript | `pytest`: relay (`tests/test_files_v2.py`, 15), agent (`agent/tests/test_files.py`, 47, incl. end to end through a relay with a cancel mid-file); `bun test` (character routing, demo session); separate processes on port 5601 (relay, director and actor agents): a 3 MB file arrives with the same SHA-256 and the relay logs it; UI in headless Chromium (demo). Windows 11 laptop (2026-10-21, plan §3.7): director and actor as desktop windows over a v2 test relay; three files with a replace, a 900 MB cancel mid-file, a decline, auto-accept, and closing the actor mid-file all pass, hashes match, no partial files left; the relay's log agrees |
| Not built yet | OSC timeline editor (§8.3), OBS addon (§8.5, including the §8.5.8 window helper), stream addon (§8.6), actor output visualizer (§9.6), the other production helpers (§15.1 steps 2–5), tray, installer, auto-update | — |
| Soundpad on Windows (2026-10-19) | Probe (Appendix B) and the agent's pipe client against Soundpad 4.0.35 | Relay GO / STOP and `*play:N` end to end: Soundpad played and stopped, the actor view showed Playing with position and went back to Ready; `pytest` adds 15 tests against an in-memory Soundpad |
| VRChat window probe (§8.5.8) | `tools/vrchat_window_probe.py`: window-manager calls only, read-only by default, `--resize` / `--restore` | Windows rows of Appendix C on the test box (2026-10-19); the agent-side helper isn't built |
| Normalize folder (§8.4.2, 2026-10-20) | `web/src/lib/audio/` (BS.1770 loudness, 4× true peak, 16-bit WAV writer, worker), `NormalizePanel` in the director view, `agent/folders.py` + `/api/folders/*`, demo folder | EBU Tech 3341 cases 1–5 and true-peak sweeps in `bun test`; agrees with ffmpeg's `ebur128` within 0.1 LU / 0.3 dB. End to end in headless Chromium against the agent: MP3, WAV, OGG, M4A and FLAC sources; ffmpeg reads the copies at −16.0 LUFS, or −17.0 LUFS at exactly −1.0 dBTP when peak-limited. Frozen Linux build serves the endpoints |
| Not verified | A Windows PC without WebView2 (WebView2 detection and the browser fallback); the Normalize folder dialog inside the desktop window (Windows, Linux `--window`) | The window itself works on Windows 11 (agent build row); Normalize folder's browser-mode pickers (`kdialog`, `zenity`, typed path) work |

### 20.1 Phase 0 as Built: Deviations and Decisions

Choices made while building the v2 relay (`feat/relay-v2`) where §5, §6 and §11 left room or said otherwise:

**Protocol (§5)**
- `to: "all"` and `{role}` exclude the sender, so chat isn't echoed; the agent logs its own messages.
- `welcome` adds `name` and `role`. `ice_servers` is always `[]` until ICE/TURN is built.
- Join requests are a `pending` list in `presence.roster`, filled only for directors and assistants. `approval.approve` / `approval.deny` take `{machine_id}`; `approval.forget` takes `{id}` (session) or `{machine_id}`. Approved actors and cameras with no connection are an `offline` list (`{machine_id, name, role, approved_at?}`, directors and assistants only, added 2026-10-22) so a director can forget someone who has left. A v2 `approval.forget` of a machine with no connection just removes it; a connected one goes back to `pending` as on the v0.3 relay.
- The relay measures latency itself: every 10 s it sends `time.ping` to each v2 session, which answers `time.pong` (`reply_to` = the ping). Directors and assistants get `presence.latency {sessions: [{id, latency_ms, timed_out}]}` after each round; v0.3 directors keep getting `STATUS`, now including v2 actors.
- Session ids (`s_` + 8 hex) are kept per machine id and role for as long as the relay runs, so a reconnecting agent keeps its id. They're not saved across relay restarts. Two live sessions from one machine in the same role (two directors on a test PC) get different ids.
- A second connection from an approved machine in the same role replaces the first, which gets `denied {reason: "Reconnected from another location"}` (the v0.3 rule, which applied to actors only, now covers v2 cameras too).
- Close codes: 4400 bad or missing hello, 4401 wrong secret, 4403 denied / forgotten / replaced, 4408 no hello within 10 s.
- Types missing from the permission table are rejected (`unknown_type`). That's narrower than G3 ("a new addon needs no relay change"): a new addon needs rows in `server/permissions.py`, which is data only.
- `cuelist.*` passes the permission check and then gets `error unsupported` until cue-list storage exists. `stage.*` and `ready.*` are routed but not stored, and the bridge doesn't show `stage.state` to v0.3 clients yet (§15.1 steps 2 and 4).
- Binary frames on `/v2/ws` carry file chunks (Phase 2 as built, below). Text frames are limited to 256 KiB.
- Version check for v2 clients ignores suffixes (`0.4.0-dev`) and the patch number: a different major is `unsupported`, a different minor `warning`.
- `soundpad.level` (§9.6, added to §5.4 and §5.5 while the relay was being built) has no row in `server/permissions.py` and no model yet, so the relay answers `unknown_type`. It gets both with the visualizer (§15.1 step 6).

**Relay (§6)**
- `/` keeps the v0.3 health JSON (`{status, clients, approved}`) because the web app isn't hosted yet; `/health` is unchanged.
- `server_ws.py` keeps its CLI and adds `--data-dir` (default: next to the script, as before) and `--no-legacy` (§11.1 `legacy.enabled`).
- `approved_actors.json` gains `role` (written only for non-actors) and `delay_ms`; `actor.settings.display_name` renames the entry. The v0.3 relay ignores the extra keys, so going back still works.

**Bridge (§11)**
- `/ws` reports the v0.3 protocol version (`VERSION|ok|0.3.3|` for v0.3.3 clients); `welcome.server_version` is the relay's own (`0.4.0-dev`).
- v0.3 ↔ v0.3 traffic keeps every v0.3.3 quirk, because the golden transcript requires it: `CMD` echoes to directors, the client-supplied sender name is passed on, a forgotten actor stays in `USERS` until it hangs up, a reconnecting actor is announced "joined" and then "left", and ACKs never reach v0.3 directors. v2 recipients get the sender's real session id instead.
- Permission notices on `/ws` stay exactly as before (`Permission denied: only the director can send X` for the v0.3 director-only types). Messages the table newly rejects (a director's `FILEACK`, a camera's `ACK`) are dropped and logged.
- Cameras are hidden from `/ws`: not in `USERS` or `PENDING`, no joined/left lines, and not reachable by name. So a v0.3 director can't approve a camera; a v2 director (or assistant) has to.
- A v0.3 actor's `ACK` reaches v2 directors and assistants as `cue.ack`.
- A v2 `chat.priv` whose text starts with `*` reaches v0.3 clients with a leading space, so a v0.3 actor doesn't run it as a cue.
- Files between v0.3 and v2 aren't translated yet: a v0.3 director's `FILEREQ` to a v2 actor is answered with `FILEDENY` and a reason; `BATCH_*` to a v2 actor is dropped.
- v2 actions a v0.3 actor can't carry (`soundpad.play` with `path`, `sha256`, `lines` other than `both`, `volume` or `start_ms`; other `soundpad.*`) get `error unsupported` naming the sessions.
- Scheduling emulation sends at `at + delay_ms − RTT/2` (RTT from the v0.3 `PING`/`PONG` average; no start-latency term). A stop cancels the actor's held go/play cues: at once without `at`, at its own send time with `at`. Held cues are dropped when the actor disconnects. Sends more than 20 ms late are logged.

**Agent**
- Every connection attempt tries `/v2/ws` first and continues on `/ws` when the relay answers 403 or 404, so an upgraded relay is picked up at the next reconnect.
- Actors announce `capabilities: ["soundpad", "osc"]`. Assistants aren't a UI role yet; a v2 roster shows them as directors.
- `Connection.legacy` is `false` until a relay turns out to be v0.3 (it used to be fixed at `true`).
- The scripted v0.3 client uses the `websockets` sync client, not `websocket-client` (§11.5).

**§17 status on the v2 relay:** #2 fixed (the table applies to `/ws` too); #3 and #5 fixed for v2 sessions, while v0.3 clients keep name routing and client-supplied sender names among themselves; #4 fixed for v2 transfers (keyed by transfer UUID, §20.2), while v0.3 transfers are still keyed by file name; #6 fixed (`approval.forgotten`); #7 fixed for v2 messages (JSON), and v2 names are cleaned of `|` before they reach `/ws`.

### 20.2 Phase 2 as Built: Deviations and Decisions

Phase 2 is built in milestones on branches (plan: `docs/superpowers/plans/2026-10-21-phase2-plan.md`, decisions D1–D12 there).

**Files between v0.4 apps (M1a, §5.7, §8.4)**
- `file.offer` goes to exactly one session (`{ids: [one]}`); anything else is `invalid`. The relay keeps one entry per offer: chunk frames pass only from the offer's sender, only to its recipient, and only after that recipient's `file.accept`. Replies (`accept`, `deny`, `progress`, `ok`, `err`) always go back to the offer's sender, whatever their `to` says.
- `chunk_size` is declared per offer (16–256 KiB; v0.4 apps use 256 KiB), so the bridge can pass a v0.3 director's 64 KiB chunks through without re-chunking (M1b). `md5` is optional next to `sha256`, for v0.3 actors' `FILEEND`. Files are limited to 1 GiB; one sender may have 16 transfers open.
- A chunk past the end of the file, or either side disconnecting, ends the transfer; whoever is left gets `file.err` from the relay. `file.batch.cancel` ends every transfer of that batch.
- The relay writes one `server.log` line per transfer with its result (`File Mira → Coda: Scene 4 - Diego.wav (3.0 MB): ok`), never file contents (decision D5).
- Every send from a v0.4 director is a batch, even one file. Files go one at a time per actor; batches to different actors run side by side. A stall (no `file.progress` for 60 s) ends the batch.
- The actor is asked once per file, when the offer arrives (decision D4); "Accept all N" accepts the rest of that batch; "accept automatically" turns auto-accept on. The receiver refuses names that aren't a plain file name (folders, `..`, characters Windows can't store, `CON`/`NUL`/…), files bigger than the free disk space, and a second offer with an open transfer id.
- Actors announce the capability `files`; the director UI offers files only to actors that have it, or that run v0.3 (decision D7).
- A refused offer gets a `file.err` besides the `error`, so the sender can tie it to its transfer; the agent also ends a file on an `error` about its offer.

**Files between v0.3 and v0.4 (M1b, §11.2)**
- v0.3 director → v0.4 actor: `FILEREQ` becomes `file.offer` with `chunk_size` 64 KiB and the request's MD5; `FILESTART` is swallowed; each `FILECHUNK` becomes one binary frame; `FILEEND` becomes `file.end {md5}`; `BATCH_*` become `file.batch.*` with a batch id the bridge makes up. The actor's replies reach the v0.3 director as `FILEACK|name|1|` (empty save_dir), `FILEDENY`, `FILEOK|name|<folder>/<file>` and `FILEERR`; `file.progress` is dropped. v0.4 builds without `files` still get a `FILEDENY` (now asking for an update).
- v0.4 director → v0.3 actor: the frames a v0.3.3 director sends, in its order: `BATCH_START` (left out for a batch of one file, decision D12), `FILEREQ` naming the real director, `FILESTART`, four 64 KiB `FILECHUNK`s per 256 KiB chunk, `FILEEND` with the offer's MD5 (or the MD5 of what passed), `BATCH_END`. The director is paced with `file.progress` once a chunk's frames have gone out. Names with `|`, `/`, `\`, control characters or `..` are refused (a v0.3 actor joins the name onto its folder unchecked), as are a second file of the same name while one is open (v0.3 keys transfers by name) and out-of-order chunks.
- Cancel mid-file stops the chunks and sends `BATCH_CANCEL`, so a v0.3 actor never gets `FILEEND` and writes nothing. When a transfer ends from the relay's side, a v0.3 director gets `FILEERR` and a v0.3 actor `BATCH_CANCEL` with the reason.
- v0.3 ↔ v0.3 transfers keep the v0.3 relay's own path (keyed by file name); the golden transcript is unchanged.
- Limits of the v0.3.3 actor, seen on the laptop and not fixable on the relay (the v0.3 clients aren't changed): it appends every chunk to one in-memory buffer, so a big file arrives slowly (900 MB: about 1.5 MB/s, one core busy) and prints a progress line every 640 KB; after a cancel it keeps the partial file in memory until it restarts. Send files warns about files over 50 MB to a v0.3 actor. A cancel shows up there once the chunks already on the way are processed (3.6 s in the test).
- The default cancel reason is the v0.3.3 director's own, "Cancelled by director".

**Soundpad addon (M2, §8.1)**
- Directors pick sounds by `key`, not `path` (decision D6). `soundpad.list` carries `index`, `key`, `title` and `duration_ms` per sound and no paths, because paths contain Windows user names. A key is the first 16 hex digits of the SHA-1 of the path (case-folded, backslashes); `SoundRef` gains `key` (additive). The actor maps a key to the current index through its cached list and checks `GetSoundlist(i,i)` before playing (drift guard). `path` references still work.
- `soundpad.list` comes in pages of at most 500 sounds (`first`, `total`, `last`; categories on the first page), well under the 256 KiB frame limit. An actor sends its list when asked (`soundpad.list.request`) and again to those directors when `GetSoundFileCount()` changes. Durations are whole seconds (Soundpad's `m:ss`). The director's agent hands lists to the UI as a separate `sounds` event, not in the state snapshot.
- `soundpad.ack {status, error?, command}`: `status` is `"ok"` or an error code: `not_found`, `not_in_soundpad`, `trial_limit`, `soundpad_offline`, `timeout` (§8.1.2), plus `unsupported` (the selected sound on a line other than `both`; `soundpad.calibrate` until M3), `invalid` (a payload that doesn't validate), `skipped` (Soundpad turned off on that PC) and `error` (a stop through `-rc` failed). `command` names the message answered. A failed ack shows as a warning in the director's log. `late_ms` waits for M3.
- Capabilities are fixed per build (decision D7): v0.4 actors announce `soundpad`, `soundpad.lines`, `soundpad.position`, `soundpad.list`, `soundpad.add`, `osc` and `files` whether or not Soundpad runs (§8.1.7 tied them to the pipe and the full version). Whether Soundpad answers comes live in `soundpad.state.available` with a `detail`; announcing it again would need a new core message.
- `soundpad.state` goes to the session ids of the v2 directors and assistants in the roster (`{role: "director"}` would skip assistants): at most twice a second while playing, on any other change, every 10 s, and at once to a director who just joined. v0.3 directors get nothing new. The director's UI runs the position on between reports; v2 actors show as Playing in the cast and graph while their Soundpad plays.
- Go (`cue.go`) and `*play:N` (`cue.play`) keep their v0.3 meaning and always play on both lines; the actor's `default_lines` applies to `soundpad.play` without `lines`. Play #N in the director UI sends `cue.play {index}`, so v0.3 actors get `PRIV *play:N` through the bridge, and compatibility mode sends the `PRIV` itself.
- Volume is a whole number 0–100 (the models reject anything else); pause and mute toggle only when needed; stop waits for `SEEKING` to end (up to 250 ms).
- `auto_add_received` is on by default: a received file is added to Soundpad once (full version; the trial logs a hint), and "Sent this session" in the director's panel plays it by `sha256`. `auto_launch` (off by default) starts Soundpad.exe once per run when its pipe is missing. Settings → Actor has Detect for the path.
- The relay validates `soundpad.*` with the new models: a malformed message gets `error invalid` instead of being routed. No permission rows changed. The bridge answers `unsupported` for v0.3 actors on the new types and on `soundpad.play` with `key`, as it does for `path`.
- From the laptop run:
  - **Soundpad closed:** `Soundpad.exe -rc` starts Soundpad and keeps running as it, and soundpad.py's 5 s timeout then killed it (the cue played for up to 5 s and was reported as failed). The agent now tells "no pipe" (Soundpad isn't running) from other open failures: GO and `*play:N` fail at once with "Soundpad isn't running" (`soundpad_offline` for `soundpad.play`), STOP succeeds, and nothing runs `-rc`. Only `auto_launch` starts Soundpad: once per run, at startup, when Soundpad closes, or on a cue. The actor's UI state is `closed` ("Not running"). `-rc` remains for a running Soundpad whose pipe can't be opened, through the agent's own runner, which never kills the process; soundpad.py (shared with the v0.3 clients) is unchanged.
  - **Actions off the receive loop:** an actor's cues, `soundpad.*` and `osc.param` (and `PRIV` / `CMD` / `OSC_CUE` in compatibility mode) run one at a time, in arrival order, on a queue per connection. Awaiting them inline held up `time.ping` (1–1.5 s latency on the laptop), STOP and everything else while Soundpad was slow.
  - **Repeats:** the director's agent drops a cue or Soundpad control identical to the previous one within 150 ms (a stuck key sent ~350 plays 35–40 ms apart), and the UI ignores a held Enter's key repeats.
  - **Display:** sound lengths round to the second like Soundpad's list; positions count whole seconds. After a seek, jump or volume change the panel shows the requested value for 1.5 s, and a running position doesn't step back by less than 0.5 s. For 3.5 s after a failed cue the actor's card says "Cue failed" with the reason.
  - **Finding Soundpad again:** while there's no pipe at all the agent looks every 1 s (§8.1.1's backoff, 0.5 → 10 s, stays for a Soundpad that opens but doesn't answer), so a Soundpad started by hand or by auto-start is picked up within about a second instead of up to 10 s.

**Timing (M3, §8.2)**
- Clock sync: `time.ping` every 1 s for the first 5 s after `welcome`, then every 10 s; 8 samples; the offset of the one with the lowest round trip. Local times are `time.perf_counter()`: Python 3.12 on Windows (the laptop) moves `time.time()` and `time.monotonic()` in 15.6 ms steps, and perf_counter doesn't jump when Windows sets its clock. The wire `t0` stays Unix ms. `welcome.server_time` gives a rough offset until the first pong. Directors, actors and cameras all sync; the agent log says "Clock synced with the relay: round trip N ms; this PC's clock is X s behind the relay's".
- Scheduler: `loop.call_later` for most of the wait and the last 30 ms slept in a worker thread (`time.sleep` uses a high-resolution timer on Windows since Python 3.11; asyncio's timers follow the 15.6 ms tick before 3.13). A due action joins the actor's action queue (M2), so a Stop that arrives while it waits cancels it instead of waiting behind it. Linux: 148–150 ms apart for a +150 ms delay.
- Actors announce `schedule` and `soundpad.calibrate`. Starts (`cue.go`, `cue.play`, `soundpad.play`) run at `at + delay_ms − start_latency_ms`; `cue.stop`, `soundpad.stop`, `soundpad.pause` and `osc.param` at `at + delay_ms`. `delay_ms` comes from `welcome`, then the actor's own roster entry. A Stop without `at` cancels everything still waiting (OSC too); with `at` it does that at its time. An action more than 60 s ahead is refused (`soundpad.ack` `invalid` / `cue.ack` `ok: false`), since that's a wrong clock rather than a cue. Every ack of a scheduled action carries `late_ms` (0 when on time); the director logs starts later than 20 ms and the cast row shows "Last start N ms late". A start at least 1 s ahead shows the countdown on the actor.
- Evidence: one agent-log line per scheduled action, in server time: `⏱ *go sent 22:35:31.320 server time; sound due 22:35:31.380 (at 22:35:31.230, +150 ms delay, −60 ms start latency)`. The director logs `▶ GO → Nova, Vega for 22:35:31.230 server time (+300 ms)`.
- Directors: GO is `at = server now + lead` (decision D8: 300 ms, Settings → Director, 0–2000, 0 = at once); Play in 3s is `at = now + 3000`, with the countdown from that time. Before the first clock sample, and in compatibility mode, GO goes out at once and Play in 3s counts down locally (v0.3 behaviour). One message per distinct payload. v0.4 builds without `schedule` are held by the director's agent and get the cue without `at` at `at + their delay − (director round trip + actor round trip) / 2`. v0.3 actors get `at` and the relay's emulation (unchanged). Stop goes to the targeted actors plus those of a GO still waiting, and cancels held messages and the countdown. The cue deck warns when a targeted actor's trip (half of each round trip) exceeds 80 % of the lead less 60 ms.
- Per-actor delay: the cast row's timer button and the actor's Soundpad panel send `actor.settings {id, delay_ms}` (−10 000 to 10 000); shown on the cast row and on the actor's Timing card. Not available on a v0.3 relay.
- Calibration: `soundpad.calibrate {sound?}` plays the sound on the speakers line only (`DoPlaySound(i, true, false)`), measures the start as for any play (§8.2.3), stops it after 1.5 s unless something else started, and answers `soundpad.ack {status, start_latency_ms, command}` with the median of the last 5. Only the start goes through the action queue. Without `sound`: the sound last played by number, else sound 1 (`DoPlaySelectedSound` can't choose the line). The director's panel calibrates with the armed sound or the one playing. Every measured start (calibration or cue) is kept in the actor's config (`soundpad.start_latencies`, last 5); compensation uses their median, else 60 ms, and can be turned off (`auto_compensate_latency`, Settings → Actor and the Timing card).
- Armed sounds (added to M3): a director arms one sound per actor from that actor's Soundpad panel ("Arm" next to Play in the list, under "Sent this session" and next to Play #N; the panel's line choice is kept with it). GO and Play in 3s then send `soundpad.play {sound, lines?, at}` to each targeted actor with an armed sound and `cue.go {at}` to the others, with one `at`. v0.3 apps and older builds can only be armed by number and get `cue.play {index, at}` (`PRIV *play:N` through the bridge); a sound such an app can't play falls back to GO with a warning. In compatibility mode an armed number goes out as `PRIV *play:N`. Armed sounds stay armed after GO until cleared, in the director's memory (not saved); they show on the cast row with a clear button, in the panel and as "N armed" in the cue deck. No relay change.
- Protocol: a `soundpad.calibrate` model (`sound?`) and `soundpad.ack.start_latency_ms` (additive). The relay now validates `soundpad.calibrate`; nothing in `server/` changed.
- UI contract: `AppState.clock {synced, offsetMs, rttMs}` (top level, not in `ActorLocal.timing` as planned, since directors sync too), `ActorLocal.timing {startLatencyMs, measured, samples, autoCompensate, delayMs}`, `DirectorLocal.leadMs` / `armed`, `Peer.delayMs` / `lastLateMs`, `PeerSoundpad.startLatencyMs`; calls `setDirectorLocal {leadMs}`, `setDelay {id, ms}`, `calibrate {id?, sound?}`, `arm {id, sound, label, lines?}`, `disarm {id}`, `setActorLocal {autoCompensateLatency}`.
- Not changed: the relay's emulation for v0.3 actors has no start-latency term (§20.1), so their sound starts about their own start latency after v0.4 actors'. OSC toggles with GO come in M4.
- From the laptop run (plan §6.2):
  - **Timing holds on Windows** (Python 3.12, where asyncio's own timers tick in 15.6 ms): 150–151 ms for a +150 ms delay, sends exactly at their planned server time.
  - **Start latency:** Soundpad 4.0.35 started sounds 25–35 ms after `DoPlaySound` on that PC (calibration 29 / 31 ms), below the probe's 48–92 ms (§8.2.3) and the 60 ms default, which is only used until the first measured play. Two agents on one Soundpad cut each other's plays and skew the measurement (158–194 ms samples): a test-setup effect, since each actor has their own Soundpad in production.
  - **Fixed:** the shared `Button` defaults to `type="button"` (inside a form it also submitted: "Reset to 0" saved the old delay again, "Arm #N" also played); an actor without Soundpad playback status says "Stopped" after a Stop instead of "GO!". Re-checked on the laptop (2026-10-22).
  - An actor shows as playing whenever its own Soundpad plays, whoever started the sound (the pipe's status). With two agents on one test PC that marks the wrong one; with one Soundpad per actor it also shows sounds the actor starts by hand, which is wanted.
