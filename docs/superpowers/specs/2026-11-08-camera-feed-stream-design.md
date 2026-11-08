# vrcActorSync: Camera Feed Stream

**Date:** 2026-11-08
**Status:** Final draft for `W2-feed-stream` (week of 2026-11-09). Danny's decisions from 2026-11-08 are in. Nothing is built.
**Builds on:** the main spec, `2026-10-17-vrcActorSync-web-ui-agent-design.md`: §5 (protocol v2), §8.5 (obs), §8.6 (stream, reserved names only).
- For the first build this document replaces §8.6's plan.
- §8.6 Option A and the talkback spec's LiveKit previews (`2026-10-24-built-in-player-and-talkback-design.md`, B.6 step 3) stay as the route to many viewers.

**Confirmed** means a primary source or this repo's code says so. **Unconfirmed** means a Windows session has to show it. `D1`… refer to the decisions in §11.

---

## 1. Goal

- **Gate** (`gate-W2`, 2026-11-15): a live camera feed visible to a second operator during a take.
  - Tested with a **remote camera operator** at their place while Danny watches as director (D20).
- **Kill switch** (`kill-feed-stream`): no feed reaching a second operator by the end of W2.
- **Who shares:** camera operators. They share OBS's output, exactly what gets recorded (D15). Sharing is off until they turn it on (D8).
- **Who watches:**
  - **Directors**, right away: their Cameras panel is open by default (D2, D7).
  - **Camera operators, actors and assistants** who opt in (D2, D19).
  - Actors only once the relay runs on the VPS: it needs a permission change and a relay restart (D5).
- **What the feed is for:** checking framing and blocking, and an all-day multiview (D3).
  - Typical shoot: 1–2 cameras, 1–2 viewers (D4).
  - Sizes: 1280×720 at 30 fps for large tiles, 640×360 at 15 fps for small ones.
  - Delay: about 300 ms from camera to screen (**unconfirmed**; M0 measures it).

**Not in this build:**
- Sound (D18): later, and how the audio gets captured is still open (§11).
- TURN (D11).
- A media server.
- Linux cameras: M3 (D24).
- Recording the feed.
- More than 4 viewers per camera.

## 2. What the Design Has to Live With

1. **Today the live relay sits behind Tailscale Funnel.** Funnel carries TCP only, and "Traffic sent over a Funnel is subject to non-configurable bandwidth limits" (Tailscale docs, **confirmed**).
   - A third-party write-up repeats a forum user's report: video above about 1 Mbps didn't stream reliably through Funnel (anecdotal).
   - **The relay moves to the DGP-Server VPS during W2** (D9): OVHcloud, Beauharnois, Caddy on 80/443 with a public IP.
   - The video path below doesn't depend on that move. Actors watching (D5) and a later TURN server (D11) do.
2. **The live relay already carries the signalling.** At `df69d38` (live since 2026-10-22), any `rtc.<anything>` from a director, assistant or camera gets through (**confirmed** in code):
   - It matches the `rtc.*` row (`server/permissions.py`).
   - It has no model, so nothing validates its data (`validate()` returns `None`).
   - It goes to its `to` sessions (`server/router.py`, `route()`).
   - The same goes for `obs.record.state` from a camera, which has its own row.
   - Capabilities from `hello` reach `presence.roster` too.
   - **So M1 needs no relay change and no restart.**
3. **The camera PC is the busiest machine in the session.** Crews record at 1440p and 4K (D16), with VRChat matched to the canvas (§8.5.8), and OBS recording at the same time. Nothing the feed does may cost OBS a frame.
4. **OBS has one stream output.** Its stream service settings live in the operator's profile, which the app never edits (§8.5.2). WHIP would take both.
5. **OBS's virtual camera is video only.** Feed sound needs a second capture path (§11, still open).
6. **Crews sit on home internet, far apart** (D10). Direct connections work for most pairs with STUN; some routers and mobile networks will block them.
7. **WebRTC is already in every UI we ship:** WebView2 on Windows, Chrome or Firefox for the Linux browser mode. WebKitGTK (`--window`) has WebRTC off by default (talkback B.3).

## 3. Options

| | How | For | Against | Verdict |
|---|---|---|---|---|
| **A** | **WebRTC from the camera's app:** OBS Virtual Camera → `getUserMedia` in the camera's UI → one `RTCPeerConnection` per viewer. Signalling goes over `rtc.*` through the relay | Video never touches the relay. No relay change. No new binary or dependency. WebRTC adapts to loss and bandwidth. Viewers see exactly what OBS outputs | One encode per viewer on the camera PC. Some network pairs can't connect without TURN. OBS's virtual camera has to run | **Chosen** (D1) |
| B | OBS WHIP output → a MediaMTX sidecar (§8.6 A) or LiveKit ingress (talkback B.6 step 3) | OBS encodes once, in hardware. A server fans out | Takes OBS's only stream output and edits its stream settings. Needs a server binary. LiveKit needs public UDP, and DGP-Server's rule is "only Caddy publishes public ports" | Later, if crews grow past ~4 viewers a camera |
| C | The agent captures VRChat with ffmpeg `gfxcapture` and encodes H.264 in hardware. The relay fans out binary frames (a new kind byte, §5.7); viewers decode with WebCodecs | No NAT trouble. One encode per camera. The ShaderMotion prototype (`proto/shadermotion-preview`) already captures this way | All video goes through the relay's process. Needs a relay deploy, and ffmpeg ≥ 8.1 on every camera PC. Skips OBS's overlays (D15) | Fallback once the relay is on the VPS, if 4K fails M0 or P2P fails often |
| D | `GetSourceScreenshot` polling, sent over the relay | Tiny | A few frames a second. Each screenshot renders on OBS's graphics thread during the take | No |
| E | VDO.Ninja links | No code | A third-party service, outside the app's approvals | Diagnosis only (D25, §9) |

---

## 4. Design

```
Camera PC                                                 Viewer PC (director, camera, actor)
OBS ── virtual camera ──► camera UI (WebView2)            viewer UI
                          getUserMedia                    │
                          RTCPeerConnection ◄═══ video, peer to peer (UDP) ═══► RTCPeerConnection → <video>
                               │ rtc.answer, rtc.ice                    ▲ rtc.offer, rtc.ice, rtc.quality
                          camera agent ◄──── relay /v2/ws: rtc.*, obs.record.state ────► viewer agent
```

Once a connection is up, its video doesn't depend on the relay. Whether a live feed survives a relay reconnect is **unconfirmed** (M2).

### 4.1 Messages

- Every `rtc.*` payload carries `pc`, except `rtc.ready` and `rtc.ask`. `pc` is an id the viewer makes for this connection: 32 hex characters, like transfer ids.
- `to` is `{"ids": [one session]}` unless the table says otherwise.

| Type | From → to | Data | Meaning |
|---|---|---|---|
| `rtc.offer` | viewer → camera | `pc`, `sdp`, `quality` | Watch this camera (receive-only video) |
| `rtc.answer` | camera → viewer | `pc`, `sdp` | |
| `rtc.ice` | both | `pc`, `candidate` (`RTCIceCandidateInit`, or `null` at the end) | Trickle ICE |
| `rtc.quality` | viewer → camera | `pc`, `quality` | `full`, `thumb` or `off` (paused). No renegotiation |
| `rtc.bye` | both | `pc`, `reason` | `closed`, `not_sharing`, `waiting_for_cut`, `no_obs`, `no_virtual_camera`, `full`, `error` |
| `rtc.ready` | camera → viewers it turned away | none | "Offer again" |
| `rtc.ask` | director → camera | none | "Please share your feed" (D27) |
| `obs.record.state` | camera → `{"role": "director"}` and its other viewers | `state` (`rolling` / `idle`), `since` (server ms) | The REC tally (D17); main spec §8.5.3 |

- **Reserved already:** `offer`, `answer`, `ice` and `bye` (§5.4). `quality`, `ready` and `ask` are new names in the same namespace; the live relay's `rtc.*` row covers them.
- **When `obs.record.state` goes out:** whenever the camera's recording state changes, and to each viewer whose connection goes live.
- **Protocol package:**
  - A model for every `rtc.*` type in `vrcas_protocol` (`sdp` ≤ 64 KB) and for `obs.record.state`.
  - Then run `scripts/gen_ts_types.py`.
  - The live relay routes them unvalidated until its next restart, and validates them after that.
  - `extra="ignore"` lets newer fields through, so §8.5.3's later fields (`take_id`, …) fit.
- **Capability:** cameras announce `stream.publish` in `hello`. Today only actors send capabilities (`agent/relay_v2.py`).
  - Viewers start every connection, so nobody needs `stream.view`; it stays reserved.
- **Actors as viewers (D5):** with the VPS relay, an actor may send `rtc.offer`, `rtc.ice`, `rtc.quality` and `rtc.bye`, but only to cameras.
  - That's a new row in `server/permissions.py` plus a recipient check in the router: the relay drops other recipients and answers `forbidden`.
  - The ShaderMotion prototype has a per-type version of that check (`RECIPIENTS`); this one depends on the sender's role.
  - **Merge it before the move,** so the VPS relay starts with it. That's the only relay change in this build.

### 4.2 Camera Operator

**Share my feed:** a toggle in the camera view.
- Config `obs.share_feed`: off by default, remembered between runs (D8). This toggle is the operator's consent.
- One line under it: "Viewers connect to your PC directly and can see its IP address" (D12).

**Turning it on:**
1. The agent checks that OBS is connected and asks for the virtual camera's state (`GetVirtualCamStatus`).
   - If the virtual camera is off, it calls `StartVirtualCam` and remembers that it started it.
   - It follows `VirtualcamStateChanged` (all three requests and the event are in obs-websocket 5.0, **confirmed**).
2. **Never while recording** (D13). While OBS records, the agent doesn't start or stop the virtual camera.
   - Turning sharing on mid-take shows "Sharing starts after Cut".
   - Turning it off mid-take ends the connections at once, but the virtual camera stops only after Cut.
3. The camera's UI opens the device labelled **OBS Virtual Camera** with `getUserMedia`:
   - Video only. Height 720 (ideal), at most 30 fps.
   - No width, so a non-16:9 canvas is scaled, not cropped (**unconfirmed**, M0).
   - It remembers the device id (`remember()`, `vrcas` prefix), so later runs don't open the default webcam first to get device labels.
   - Never `getDisplayMedia`, and never any other camera.
4. WebView2 asks once for camera permission (pywebview 6.2 has no permission handler; talkback B.3).
   - Whether the answer sticks across runs on port 47800 is **unconfirmed** (M0).

**Answering viewers:**
- **When the feed isn't ready**, the agent answers an offer itself with `rtc.bye`:
  - `not_sharing`, `waiting_for_cut`, `no_obs` or `no_virtual_camera`.
  - It remembers who asked, and sends them `rtc.ready` when the feed becomes ready.
- **When it's ready**, the agent passes the offer to the camera UI that most recently claimed the feed (`feed.claim`, sent when a camera view opens). It adds the sender's name and role from the roster. Two open windows or tabs must never answer the same offer.
- **Routing:** the agent sends each connection's later messages to the UI that took its offer.
  - When that UI closes, the agent sends `rtc.bye {closed}` for its connections, and the viewers offer again.
- **Per offer, the UI:**
  - Makes one `RTCPeerConnection` and adds the virtual camera's track.
  - Sets the sender's encoding for the requested quality (§4.4), answers and trickles ICE.
- **At most 4 viewers, directors first** (D6):
  - When a fifth viewer offers and it's a director, the UI closes the newest opt-in viewer's connection with `rtc.bye {full}` and takes the director.
  - Anyone else, or a camera full of directors, gets `rtc.bye {full}`.
- **A viewer that leaves the roster** loses its connections at once. The UI watches the roster; ICE alone would take about 30 s to notice.

**Ask to share (D27):**
- A director's `rtc.ask` pops a prompt in the camera app: "Mira asks you to share your camera feed. **Share** · **Not now**".
- **Share** turns the toggle on, so it's remembered. **Not now** closes the prompt and sends nothing back.
- The agent takes `rtc.ask` only from directors, and shows at most one prompt per director every 30 s.

**Turning it off:**
- The UI closes every connection with `rtc.bye {not_sharing}`.
- The agent stops the virtual camera if it started it. If OBS is recording, that waits until after Cut.

**When OBS changes:**
- If the virtual camera stops while sharing and the agent didn't stop it, the agent turns sharing off. The camera view says "Sharing stopped: OBS's virtual camera was turned off".
- When OBS disconnects, the feed goes to `no_obs`.

**Closing the app** works like the window helper (§8.5.8): the agent stops a virtual camera it started. If OBS is recording, it leaves it running and writes that in agent.log.

**Status line in the camera view** (D26): "Sharing · Mira, Coda · 720p30 · 2.3 Mbps up · hardware encoder".
- The names come from the open connections.
- The encoder comes from `getStats` (`encoderImplementation`, `powerEfficientEncoder`).

**REC tally:** the camera already polls OBS's recording state (`camera.py`). On each change it sends `obs.record.state` (§4.1).

### 4.3 Viewers

**Who sees the Cameras panel:**
- **Directors:** open by default in the director view (D7). It watches every camera that announces `stream.publish` as soon as the app opens (D2).
- **Opt-in viewers** (camera operators, actors, assistants): a **Watch camera feeds** toggle in their view, off by default and remembered (`remember()`; D19). Turning it on shows the same panel.
  - A camera operator's panel leaves out their own camera.
  - Before the relay allows actors (D5), an actor's toggle shows "Your relay doesn't let actors watch yet" (the relay answers `forbidden`).

**Watching and pausing:**
- The panel watches only while it's on screen (D22).
- Collapsing the panel, or the app window being hidden, sends `rtc.quality off` to every camera; the cameras then stop encoding for that viewer.
- Showing it again restores the quality (back in about a second).
- Covering the app with a full-screen VRChat may count as hidden (Chromium's occlusion tracking, **unconfirmed**). A director who wants feeds all day keeps the app on a second monitor.

**Quality follows the tile.** A tile at least 960 device pixels wide gets `full`; smaller tiles get `thumb`. With 1–2 cameras, both usually get `full`.
- Clicking a tile enlarges it; the others shrink to `thumb`.

**On the tile** (D17):
- **Always visible:**
  - The camera's name.
  - A red **REC** badge while its OBS records (from `obs.record.state`).
  - The framing overlays the viewer turned on.
- **On hover:**
  - Delay and fps ("~220 ms · 30 fps").
  - The overlay menu.
  - **Pause / Resume**: `rtc.quality off`, then back.
  - **Full screen.**
- **Later:** the **sound** button arrives with sound (D18). It isn't shown before then.
- **Full screen** uses the tile's `requestFullscreen()`. In WebView2 under pywebview, it may only fill the window, not the screen (**unconfirmed**, M1).

**Framing overlays** (D23), each one toggled per tile and remembered per camera on the viewer's PC:
- Rule of thirds.
- Safe areas: action-safe 93 % and title-safe 90 %.
- A centre cross.
- Aspect guides: 2.39:1, 2:1, 1.85:1, 4:3 and 9:16.
  - Wider than the frame → letterbox lines; narrower → pillarbox lines.
  - The geometry is a pure function (`overlays.ts`).

**Tile states:**

| State | Tile says |
|---|---|
| `connecting` | Connecting… |
| `live` | the video |
| `paused` | Paused (with **Resume**) |
| `not_sharing` | Cam 2 isn't sharing, with **Ask to share** for directors (D27). After asking: "Asked · waiting for Cam 2" for 60 s |
| `waiting_for_cut` | Cam 2 shares after Cut |
| `no_obs`, `no_virtual_camera` | Cam 2's OBS isn't ready |
| `full` | Cam 2 is full |
| `unreachable` | Can't reach Cam 2 directly; one of your networks blocks peer-to-peer video |
| `old_app` (no `stream.publish`) | Cam 2's app can't share its feed; it needs an update |
| `no_relay` (compatibility mode) | Camera feeds need the v2 relay |

- **Retries:**
  - `unreachable` and `error` retry after 10 s, after 30 s, then every 60 s.
  - `full` retries every 60 s.
  - `rtc.ready`, or a camera rejoining the roster, sends a new offer at once.
- **~latency on the tile** = RTT/2 + jitter buffer + decode time + one frame, from `getStats`. It's labelled as an estimate; M0 checks it once against a phone video of both screens.

### 4.4 Quality

| Quality | Size | fps | Max bitrate | Used for |
|---|---|---|---|---|
| `full` | 1280×720 | 30 | 2.5 Mbps | large tiles |
| `thumb` | ÷2 (640×360) | 15 | 0.5 Mbps | small tiles; every viewer while OBS drops frames (§5) |
| `off` | — | — | 0 | paused or hidden (D22) |

- **Per viewer:** `RTCRtpSender.setParameters` with `scaleResolutionDownBy`, `maxFramerate` and `maxBitrate`, or `active: false` for `off`. WebRTC's congestion control goes lower on its own when the link needs it.
- **Camera upload:** two `full` viewers come to about 5 Mbps.
- **Codec:** M1 uses whatever the peers negotiate (Chromium offers VP8 first).
  - M0 compares VP8 and H.264 CPU use on the camera PC.
  - If H.264 runs on the GPU there, the camera prefers it with `setCodecPreferences`.

### 4.5 ICE

- **STUN:** `welcome.ice_servers` when the relay sends any (it sends `[]` today, §20.1). Otherwise built-in defaults: `stun:stun.l.google.com:19302` and `stun:stun.cloudflare.com:3478`.
- **Same LAN or same tailnet:** peers connect over host candidates.
- **No TURN in W2** (D11). A pair that can't connect sees `unreachable`, and agent.log records the candidate types each side found.
- **If the remote gate test hits that:** retry from another network first, for example a phone hotspot (D20).
- **TURN after W2 needs the VPS** and one of these:
  - coturn on public UDP 3478 and TCP/TLS 5349. That's an exception to DGP-Server's "only Caddy publishes public ports".
  - TURN over TLS on 443, through Caddy's layer-4 module.

  Either way the relay mints short-lived credentials into `welcome.ice_servers` (main spec §6).
- **TURN credentials go to the UI**, because the browser's `RTCPeerConnection` needs them. They're short-lived and aren't the director secret, which still never reaches the UI.

### 4.6 Changes by File

**Agent**
- `agent/relay_v2.py`:
  - Cameras announce `stream.publish`.
  - Incoming `rtc.*` and `obs.record.state` go to core. Relay errors about `rtc.*` (for example `unknown_target` when a camera has just left) go to the UIs.
- `agent/camera.py`:
  - The virtual camera rules (§4.2) and `share_feed`.
  - `obs.record.state` on each change, plus the `GetStats` frame guard (§5).
  - The feed state in `view()`.
- `agent/core.py`:
  - `_call_rtc_send`. It takes only the `rtc.*` types of §4.1:
    - `offer`, `quality` and `ask` only to a camera with `stream.publish` (`ask` only from a director).
    - `answer` and `ready` only from a camera.
    - `data` under 64 KB.
    - Refused in compatibility mode.
  - `_call_feed_share` and `_call_feed_claim`.
  - The `pc` → UI routing, and the `rtc.ask` prompt with its 30 s limit.
  - Peers get `recording`.
- `agent/hub.py`: send an event to one UI, not just to all of them.
- `agent/config.py`: `obs.share_feed`, default off.

**UI contract**
- `web/src/lib/protocol.ts`:
  - `CameraLocal.feed`: `{share, state: off | waiting_for_cut | no_obs | no_virtual_camera | ready, startedVirtualCam, dropping}`.
  - `Peer.recording` and `AppState.iceServers`.
  - Events: `rtc {type, from, fromName, fromRole, data}` and `feed.ask {from, fromName}`.
  - Calls: `rtc.send {type, to, data}`, `feed.share {on}`, `feed.claim`.
- `agent/core.py` and `web/src/lib/demo/session.ts` change in the same commit (AGENTS.md).

**Web**
- `web/src/lib/feeds/`:
  - `viewer.ts`: one connection per camera; its state machine and retry schedule are pure.
  - `publisher.ts`: the camera side, including the viewer cap and directors-first.
  - `quality.ts`: presets and tile width → encodings (pure).
  - `overlays.ts`: guide geometry (pure).
  - `stats.ts`: `getStats` → tile text (pure).
- `web/src/lib/views/FeedsPanel.svelte`: tiles, hover bar, overlays and full screen, using container queries, `rem` and tokens.
  - The **Share my feed** toggle, the watcher names and the ask prompt go in `CameraView.svelte`.
  - The **Watch camera feeds** toggle goes in the camera and actor views.
- **Demo session:** demo cameras answer offers in the page with a canvas test pattern (name plus a running clock) through a loopback `RTCPeerConnection`. One of them "records" now and then, and one isn't sharing, so the tally and Ask to share show. So `bun run dev` runs the real viewer code.

**Relay:** nothing for M1. Actors (D5) need a permission row and a recipient check, merged before the VPS move (§4.1). The protocol package gets the models (§4.1).

### 4.7 Compatibility

- **v0.3 clients:** untouched. `/ws` and the golden transcript don't change.
- **v0.3 relay (compatibility mode):** there's no `rtc.*`, so the panel says feeds need the v2 relay.
- **Older v0.4 cameras:** they don't announce `stream.publish`, so their tile shows `old_app`. They send no tally.
- **Older directors:** they never offer, so their cameras just aren't watched. They ignore `obs.record.state`.
- **Actors before the VPS relay:** their offers are forbidden, and their toggle says so (§4.3).

### 4.8 Security and Privacy

- **Local server rules don't change** (§7.7). The UI reaches the relay only through its agent, and the agent checks every `rtc.send` (§4.6).
- **Who can send `rtc.*`:** only approved directors, assistants and cameras, plus actors (to cameras only) once the VPS relay allows it. A camera's UI only answers offers its own agent passed on.
- **Who can ask to share:** `rtc.ask` comes only from directors (the agent checks the sender's role), at most once every 30 s per director.
- **What goes out:** OBS's virtual camera and nothing else. No desktop, no webcam, no sound in this build.
- **IP addresses:** peer-to-peer means peers learn each other's IP addresses; the toggle says so (D12).
- **Logs:** agent.log records connection results and candidate types (host / srflx / relay). SDP and candidates stay out, since they hold addresses.

---

## 5. Recording Safety

**What the feed costs the camera PC:**
- OBS's virtual camera, an extra OBS output. Its frames are OBS's output size, so 3840×2160 on a 4K setup.
- Chromium's capture, scaling and encoding: one encode per viewer.

**M0 go/no-go:** a 10-minute recording at **1440p**, then at **3840×2160** with the window matched (D16), with two `full` viewers and one `thumb`.
- OBS Stats ("Frames missed due to rendering lag", "Skipped frames due to encoding lag") stay at 0.
- VRChat's frame rate drops by less than 5 %.
- **If 4K fails:** 4K cameras share `thumb` only (if that passes), or move to option C, where the GPU scales before anything reaches the CPU. Decided after M0 with Danny.

**While sharing:**
- The camera polls `GetStats`.
- If `outputSkippedFrames` or `renderSkippedFrames` rise, the camera view says "OBS is dropping frames while you share", and every viewer of that camera drops to `thumb` (D14).
- Full quality comes back after a minute without new skipped frames.

The virtual camera is never started or stopped while OBS records (D13).

## 6. Milestones

| | Work | Pass | Estimate |
|---|---|---|---|
| **M0** | Spike on laptop-windows: a dev-only loopback page in the camera's app (`?feedtest`): virtual camera → a local `RTCPeerConnection` pair at two `full` plus one `thumb` | §5 go/no-go at 1440p and 4K. Also records: whether WebView2's permission sticks; whether a minimized window, or one behind VRChat, keeps sending; that a non-16:9 canvas isn't cropped; hardware or software encoder; VP8 vs H.264 CPU | ~0.5 day, plus a Windows session (~1.5 h) |
| **M1** | Signalling; Share my feed with the virtual camera rules; directors-first cap; watcher names; REC tally; the frame guard; the Cameras panel for directors (pause while hidden) and opt-in viewers; tile states; the demo; tests. Plus a Windows one-file build for the tester (`build_agent.py`) | **`gate-W2`:** a remote camera operator records a 10-minute take at their usual 1440p or 4K, and Danny (director) sees the feed the whole time. Their OBS skips 0 frames, and ~latency is ≤ 500 ms (aim: 300). If the networks can't connect: another network first (D20), VDO.Ninja to diagnose (§9) | ~3 days, plus the remote session (~2 h) |
| **M2** | Framing overlays; full screen; Ask to share; reconnects after a relay drop, an app restart, a VRChat restart and an OBS restart; actors watching once the relay is on the VPS (the permission change goes in before the move); the soak | **Soak** (D21): 2 cameras × 2 viewers for 3 hours with takes, and no manual fixes. Every feed comes back within 10 s of each disruption; no other stall over 2 s; OBS skips 0 frames | ~2–3 days, plus the soak session (~3.5 h) |
| **M3** (later) | **Linux camera on doggoos** (D24): OBS's virtual camera through v4l2loopback, the UI in the browser. Then sound (once its capture path is chosen), and TURN on the VPS | Linux: one take shared from doggoos to a director | — |

The relay move to the VPS (D9) is its own W2 task. M1 runs on either relay; the tester's build needs whichever address is live on the test day.

## 7. Tests

**Relay** (`tests/test_relay_v2.py`):
- `rtc.offer` from a director to a camera and `rtc.answer` back both route.
- `rtc.quality`, `rtc.ready`, `rtc.ask` and `obs.record.state` pass.
- An actor's `rtc.offer` is forbidden on today's table (already in `tests/test_permissions.py`).
- With the D5 change: an actor's `rtc.offer` to a camera routes; to a director, it's forbidden.

**Agent:**
- Cameras announce `stream.publish`.
- The `rtc.send` checks: type, target, role, size, compatibility mode.
- Incoming `rtc.*` reaches only the UI that holds the connection.
- The agent's own `rtc.bye` and `rtc.ready` while the feed isn't ready.
- `rtc.ask` only from directors, with the 30 s limit.
- The virtual camera rules against a fake OBS: start when idle, wait for Cut, stop only what it started, shut down while recording.
- `obs.record.state` on each change; the frame guard.

**Web** (`bun test`):
- The viewer state machine and retry schedule.
- Tile width → quality.
- Directors-first: a director bumps the newest opt-in viewer, and nobody bumps a director.
- Overlay geometry (letterbox and pillarbox in a 16:9 frame).
- Stats text.
- The demo session answering an offer. Bun has no `RTCPeerConnection`, so the demo's WebRTC part is checked in the browser.

**Manual:** the M0–M2 sessions (§6) on Windows, plus Linux viewers in Chrome and Firefox on doggoos (M1).

## 8. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| The virtual camera and the browser's encoding cost the recording frames, likeliest at 4K | A ruined take | M0 go/no-go at 1440p and 4K. Never started or stopped while recording. The frame guard (§5). `thumb`-only or option C for 4K |
| A NAT blocks P2P for a pair | No feed for that pair | STUN; a clear tile message; another network first; TURN on the VPS after W2 |
| The remote tester's PC or network is unknown | The gate test fails for reasons outside the app | M0 on laptop-windows first; send the tester the M0 checklist; VDO.Ninja to diagnose (§9) |
| One encode per viewer on the camera PC | CPU rises with each viewer | At most 4 viewers; `thumb` for small tiles; `off` while hidden |
| WebView2 asks for the camera on every run | Friction for operators | The port stays 47800. M0 checks. Later, a pywebview permission handler that allows only our own origin |
| A minimized or covered window throttles WebRTC | The camera's feed freezes while the operator plays | M0 checks. If it does, keep the window open behind VRChat, or start WebView2 with background throttling off |
| Full screen fills only the window in WebView2 | A smaller "full screen" | M1 checks; maximize the window first, or a pywebview full-screen call |
| The relay moves mid-week | The tester's build points at the old address | Test on whichever relay is live; the move doesn't block M1 |
| The virtual camera is missing, or another app uses it | No feed | A clear `no_virtual_camera` state. Whether several apps can read it at once is **unconfirmed** |
| Two camera UIs answer the same offer | Broken connections | Offers go only to the UI that last claimed the feed (§4.2) |

## 9. If the Gate Slips

**By Thursday 2026-11-13, if M1 isn't passing:**
1. Run one test with VDO.Ninja between the same two PCs: the camera's Chrome sends from the OBS virtual camera, and the viewer opens the view link. That shows whether P2P works between those networks at all. It's a diagnosis only (D25); the gate still needs the in-app feed.
2. Then decide with Danny: fix the in-app path, add TURN early, switch to C (needs the VPS relay), or cut per the plan.

## 10. Changes to the Main Spec

- §8.6 points here.
- §5.4: `rtc.*` gains `quality`, `ready` and `ask`.
- §5.5, with the VPS relay: actors may send `rtc.offer`, `rtc.ice`, `rtc.quality` and `rtc.bye`, to cameras only.
- `stream.publish` becomes a camera capability; `stream.view` stays reserved.
- §8.5.3's `obs.record.state` is built early, for the tally.

## 11. Decisions (Danny, 2026-11-08)

| # | Decision |
|---|---|
| D1 | Video goes peer to peer from the camera's app (option A) |
| D2 | Directors see feeds right away; camera operators, actors and assistants opt in |
| D3 | Feeds are for framing and blocking, and an all-day multiview |
| D4 | Typical shoot: 1–2 cameras, 1–2 viewers |
| D5 | Actors can watch once the relay runs on the VPS (permission change + restart there) |
| D6 | At most 4 viewers a camera, directors first: a director bumps the newest opt-in viewer ("Cam 2 is full") |
| D7 | The director's feeds live in a Cameras panel in the director view (no separate window) |
| D8 | Sharing: a toggle, off by default, remembered |
| D9 | The relay moves to the DGP-Server VPS during W2 |
| D10 | Crews sit on home internet, far apart |
| D11 | No TURN in W2: a clear error now, TURN later |
| D12 | Peers seeing each other's IP is fine, with a note under the toggle |
| D13 | The virtual camera is never started or stopped while recording; sharing turned on mid-take starts after Cut |
| D14 | OBS dropping frames while sharing: warn the operator and drop that camera's viewers to `thumb` |
| D15 | The feed is OBS's output (the virtual camera) |
| D16 | Crews record at 1440p and 4K |
| D17 | Tiles: REC tally and toggled overlays always visible; on hover: delay + fps, full screen, pause/resume, and sound later |
| D18 | Sound: optional and off by default, but not in W2 |
| D19 | Opt-in viewers use a "Watch camera feeds" toggle in their view, off by default and remembered |
| D20 | The gate is tested with a remote camera operator, Danny watching; if the networks can't connect, another network first |
| D21 | The soak: 3 hours, 2 cameras, 2 viewers |
| D22 | A hidden panel or window pauses the feeds |
| D23 | Overlays, per tile, remembered: thirds, safe areas, centre cross, aspect guides at 2.39:1, 2:1, 1.85:1, 4:3, 9:16 |
| D24 | Linux cameras: Danny on doggoos, a later milestone (M3) |
| D25 | VDO.Ninja only to diagnose |
| D26 | The camera operator sees who's watching, by name |
| D27 | Directors get **Ask to share** on a camera that isn't sharing |

**Still open (not needed for W2):**
1. **How feed sound gets its audio.** OBS's virtual camera has none. One choice is the camera agent capturing VRChat's own audio (Windows per-app loopback, more code). The other is the operator routing OBS's monitoring to a virtual cable (setup on every camera PC).
2. **How TURN reaches the VPS:** coturn on its own public ports (an exception to the only-Caddy rule), or TURN over TLS on 443 through Caddy.
3. **What a 4K camera shares if M0 fails at 4K:** `thumb` only, or option C.

---

## Sources

- Tailscale Funnel (TCP proxy, bandwidth limits, ports 443/8443/10000): https://tailscale.com/kb/1223/funnel
- Funnel limits, third-party summary with the forum report: https://www.ssdnodes.com/learn/tailscale-funnel-limits-and-ports
- obs-websocket 5 protocol (`GetVirtualCamStatus`, `StartVirtualCam`, `StopVirtualCam`, `VirtualcamStateChanged`, `GetStats` fields): https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
- ffmpeg `gfxcapture` (option C; D3D11 frames out, `window_title`, since 8.1): https://ayosec.github.io/ffmpeg-filters-docs/8.1/Sources/Video/gfxcapture.html
- WebCodecs AVC registration (option C; Annex B): https://w3c.github.io/webcodecs/avc_codec_registration.html
- `RTCRtpSender.setParameters`: https://developer.mozilla.org/en-US/docs/Web/API/RTCRtpSender/setParameters
- WebView2 permission requests: https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/winrt/microsoft_web_webview2_core/corewebview2permissionrequestedeventargs
- VDO.Ninja: https://docs.vdo.ninja/
- This repo: `server/permissions.py`, `server/router.py`, `protocol/vrcas_protocol/messages.py`, `protocol/vrcas_protocol/chunks.py`, `agent/relay_v2.py`, `agent/camera.py`; branch `proto/shadermotion-preview` (`agent/shadermotion.py`, `RECIPIENTS`)
- DGP-Server (VPS plan, Caddy rules): `C:\Users\Danny Grey\DGP-Server\README.md`
