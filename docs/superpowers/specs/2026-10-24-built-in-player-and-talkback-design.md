# vrcActorSync: Built-in Sound Player and Crew Talkback (Future Updates)

**Status:** proposal from research, 2026-10-24. Not scheduled. Nothing here is built.
**Research:** two web-research passes (sources at the end), plus checks against this repo and the sources that decisions rest on.
- **Confirmed** means a primary source or this repo's code says so.
- **Unconfirmed** means inferred or reported second-hand. A real Windows PC (or the Linux box with VRChat under Proton) has to show it.

Two ideas, one shared foundation:

- **Part A — Built-in sound player.** The agent plays lines and effects into a virtual microphone itself, on Windows and Linux. Soundpad is no longer needed.
- **Part B — Crew talkback.** A voice channel between the director, actors and camera operators, like a Discord call, built into the app. It carries the camera previews later (§8.6 of the main spec).

**Recommended order:** A first, then B.
- A removes a paid, Windows-only dependency and brings Linux actors in.
- A also builds the piece B needs to be safe: once the agent sits between the actor's real mic and VRChat, it can keep crew talk out of the recording without touching VRChat's mute state (§C).

---

## Part A — Built-in Sound Player

### A.1 Why

| Today (Soundpad, §8.1) | Built-in player |
|---|---|
| Windows only; Linux actors can't take cues | Windows and Linux |
| Paid (the trial can't add sounds, §8.1.1) | Free; received files always go in the library |
| Start latency 30–60 ms, measured by calibration (§8.2.3) | Start scheduled to the sample in the output callback; latency reported by the audio API |
| One volume for both lines (§8.1.5, confirmed) | Separate volume for the actor's headphones and for the audience |
| No level API; §9.6.3 needs a Windows probe to find a meter for the `mic` line | The agent has the samples: the level of what goes to the audience is exact (answers open question 19) |
| Position polled every 250 ms in ~140 ms steps (§8.1.6) | Exact position; pause and seek are plain sample offsets |
| Index drift, `DoAddSound` delays, trial checks (§8.1.3) | Our own library, keyed as today (`agent/sounds.py`) |

### A.2 The core problem: VRChat takes one microphone

VRChat records from **one** input device. A sound only reaches the audience if it is in that device's stream, together with the actor's live voice.

**How Soundpad does it.** It mixes its sounds into the default recording device through its own audio driver; the author wrote his own driver after using a third-party one (Leppsoft's About page). No source shows it hooking VRChat. Whether the driver is kernel mode is **unconfirmed**.

**What we can't do:**
- Inject into VRChat or hook it: Easy Anti-Cheat, ban risk. Off the table, as with the window helper (§8.5.8).
- Ship our own Windows audio driver, for now:
  - Retail Windows with Secure Boot needs a Microsoft-signed driver.
  - Attestation signing needs an EV certificate (about $290–500 a year, **unconfirmed**) and is meant for testing.
  - Retail drivers go through HLK/WHCP.
  - Open-source drivers (VirtualDrivers/Virtual-Audio-Driver, Scream) need test signing, which means Secure Boot off. That's a non-starter for actors.
- Create a virtual microphone from user mode on Windows: no such API was found (Microsoft's core-audio docs; OSR forum). `MFCreateVirtualCamera` is video only.

**So:**
- **Windows:** a virtual audio cable that the actor installs once. VRChat's mic becomes the cable's output; the agent feeds the cable.
- **Linux:** PipeWire creates the virtual mic at run time. No root and no driver.

### A.3 Windows: VB-CABLE

**Why VB-CABLE:** it is widely used with VRChat, free for users, and may be bundled.

**Licence** (VB-Audio licensing page, **confirmed** on 2026-10-24):
- **Allowed:**
  - Distributing the standard VB-CABLE package with a free or commercial app.
  - Installing it silently from our installer.
- **Conditions:**
  - Credit vb-cable.com and say it's donationware.
  - The user must be able to tell it's a VB-Audio app and donate.
- **Paid licence needed** where users "can't see VB-CABLE or pay for it" (professional settings): €2.50–3.61 per unit.
- VB-CABLE A+B and C+D may **not** be bundled.
- Section 3.4 of VB-Audio's General Terms governs. Ask VB-Audio in writing before shipping it (larger distributors are asked to donate $500–2000).

**Alternatives considered:**
- VAC (Muzychenko): paid; Lite/Trial may only be redistributed for non-commercial use.
- Steam Streaming Microphone: not always present, undocumented; don't depend on it.

**Signal path (proposed):**

```
real mic ──(WASAPI shared capture)──► voice bridge ──► CABLE Input ──► CABLE Output = VRChat's mic
sound files ──► player (agent) ─────────────────────► CABLE Input        (Windows mixes both streams)
           └──────────────────────────────────────────► actor's headphones (the `speakers` line)
```

- **Voice bridge:** a small separate process (same exe, `--voice-bridge`), started and watched by the agent. Its only job is mic → cable.
  - If the agent restarts or crashes, the actor's voice keeps flowing.
  - If the bridge itself dies, the agent restarts it at once and the actor sees "Voice bridge stopped".
- **Mixing:** both the bridge and the player render to CABLE Input in shared mode, and Windows mixes them, so the player never touches the voice. Whether VB-CABLE mixes several render clients like any shared endpoint is **unconfirmed** [Windows check].
- **Fallback without the bridge:** Windows' "Listen to this device" on the real mic, set to CABLE Input. There's then no process in the voice path at all, but no gating either (§C). The actor ticks it; the app never changes system settings itself.
- **Added voice latency:** estimated 15–30 ms with small buffers, 40 ms or more with 10 ms WASAPI defaults (**unconfirmed**; measure with a loopback pulse).
  - VRChat's own voice delay to listeners is far larger (§8.2.4).
  - Visemes come from the delayed stream, so lip sync holds.
- **Never exclusive mode.** It locks Discord and others out of the device.
- **48 kHz everywhere.** Check the cable's format at setup.

**Setup wizard (actor):**
1. Install VB-CABLE: bundled installer, UAC prompt, possibly a reboot.
2. Pick the real mic and the headphones.
3. In VRChat, choose **CABLE Output** as the microphone. The app can't change VRChat's settings; it shows how.
4. **Check the chain:** the agent plays a short tone into CABLE Input and captures CABLE Output. A "✓ VRChat will hear your sounds" result only appears if the tone comes back.
5. **Warning:** VRChat's noise suppression and activation threshold (default 5 %) can cut quiet effects and line tails. This is the same with Soundpad; suggest lowering the threshold.

### A.4 Linux: PipeWire virtual mic

Created when the agent starts, removed when it quits, no root:

```bash
pactl load-module module-null-sink sink_name=vrcas_mic media.class=Audio/Source/Virtual
pactl load-module module-loopback source=<real mic> sink=vrcas_mic latency_msec=10
```

- **The player** writes to `vrcas_mic`; VRChat under Proton picks it as its input.
- **The loopback lives in `pipewire-pulse`, not in our process.** The actor's voice survives an agent crash.
- **Leftover modules:** on start, the agent unloads stale `vrcas_mic` modules by name.
- **Gating for talkback** (§C): mute the loopback's sink input (`pactl set-sink-input-mute`).
- **Volume caveat:** null devices ignore volume unless `monitor.channel-volumes=true`.
- **Known crash:** a remap-source set as the *default* input crashed apps (PipeWire issue 1734). Don't make `vrcas_mic` the system default; VRChat selects it by name.
- **Unconfirmed [Linux check]:**
  - Proton/Wine (winepulse) lists the virtual source and VRChat can select it.
  - The latency at the default quantum (1024 frames ≈ 21 ms).
  - Behaviour on SteamOS, Bazzite and CachyOS PipeWire versions.

### A.5 Engine (agent)

**Libraries:**
- `sounddevice` (PortAudio, MIT) for output and capture on both OSes.
- `soundfile` (libsndfile ≥ 1.1: WAV, FLAC, Ogg, MP3; wheels bundle the library) for decoding, plus a resampler to 48 kHz.
- `pyminiaudio` is the alternative: it decodes and resamples, but has no PipeWire backend (Pulse works).
- PyInstaller bundling of each is **unconfirmed** [build check].

**Design:**
- **Two output streams per actor:** `monitor` (headphones) and `mic` (the cable or `vrcas_mic`). The existing `lines` map onto them unchanged: `speakers` → monitor, `mic` → mic, `both` → both.
- **Callback mixer:** a NumPy mixer per stream, with ~5–10 ms blocks.
- **Starts at a server time** (§8.2.2): the scheduler hands the mixer a start time. The callback converts it to a frame using PortAudio's `outputBufferDacTime`, so starts are accurate to the frame, not to a block.
  - Start latency becomes a reported number: no calibration play is needed.
  - `soundpad.calibrate` answers from the stream's latency.
- **Decoding:** off the audio thread. On **Arm** (or the first play) the first 2 s are decoded into memory and the rest streams from disk, so GO never waits on the disk.
- **Volume:** one control per line, so the actor can turn their own headphones down without making the audience hear less. Mute works the same way.
- **Levels** (§9.6): peak per 125 ms window of the `mic` stream (the player's own output, before Windows mixes in the voice), reported as `soundpad.level` with `source: "player-mic"`.
  - No Core Audio session meters, and no privacy-indicator question (§9.6.3).
- **Library:**
  - A folder the actor picks, plus everything received through the files addon.
  - An actor-set order gives "sound N" (for `*play:N` from v0.3 directors) and a selected sound (for `cue.go`).
  - Keys are hashes of the path as today (`agent/sounds.py`), so paths still never leave the actor's PC.
- **Possible shortcut, Windows only:** play in the web UI with `AudioContext.setSinkId()` (Chromium 110+; WebView2 likely, **unconfirmed**). Rejected as the main path:
  - WebKitGTK has no `AudioContext.setSinkId`.
  - Timing and the voice bridge belong in the agent anyway.

### A.6 Protocol and code changes

- **Keep the `soundpad.*` message types.** v0.4 directors already speak them, the permission rows exist (`server/permissions.py:22`), and scheduling already treats `soundpad.play` as a start (`agent/relay_v2.py:47`).
  - A director on an older build can drive a built-in-player actor unchanged.
  - The name becomes historical: the UI says "Sounds".
  - A rename to `sound.*` can come later, through aliases.
- **`soundpad.state` gains `engine: "soundpad" | "player"`** plus `mic_ready` (chain check passed) and `voice_bridge` (`ok` / `stopped` / `off`).
  - Directors on older builds ignore the new fields.
  - Capabilities stay fixed per build (§20.2 D7); the engine is runtime state.
- **New error codes:** `no_virtual_mic` (setup not done or chain check failed) and `device_lost` (headphones or cable gone).
- **Agent seam:** `ActorRuntime` (`agent/actor_runtime.py:128`) calls the Soundpad pipe directly today.
  - Split it into a `SoundBackend` interface covering play, stop, pause, seek, volume, mute, list, state and latency.
  - Back it with `SoundpadBackend` (today's code, moved) and `PlayerBackend`.
  - `soundpad_remote.py` and `relay_v2.py` talk to the interface.
- **Config:**
  - `sound.engine`: `soundpad` / `player` / `auto`. `auto` means the player on Linux, and Soundpad on Windows until the switch-over (A.7 step 4).
  - Plus the device choices.
- **v0.3 actors are unaffected.** The UI contract changes follow the usual rule: `protocol.ts`, `core.py` and `demo/session.ts` change together.

### A.7 Phases (one developer)

| Step | Work | Estimate |
|---|---|---|
| 0 | **Probe** (`tools/virtual_mic_probe.py`): on Windows, VB-CABLE install, two render clients mixing, voice-bridge latency by loopback pulse, VRChat (EAC) launches and hears the cable. On Linux, `vrcas_mic` in VRChat under Proton | ~2–3 days + a Windows session |
| 1 | `SoundBackend` seam, with Soundpad moved behind it. No behaviour change; existing tests pass | ~2 days |
| 2 | Player engine (decode, mixer, frame-accurate starts, lines, volume, pause, seek, levels) and the library, tested against a fake device; PipeWire setup and teardown | ~1 week |
| 3 | Windows: VB-CABLE install step, voice bridge with supervisor, chain check, setup wizard | ~1 week |
| 4 | UI (library on the actor; director panels already work through `soundpad.*`), demo session, the §9.6 visualizer on real levels. Default switches to the player on Windows after a test day with real actors | ~4–5 days |

**About 3–4 weeks.** Linux actors can use it after step 2. Soundpad stays selectable for at least a few releases.

### A.8 Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Voice bridge or cable fails | The actor goes silent in VRChat (worse than a missed cue) | Separate supervised bridge; "Listen to this device" fallback; the chain check; a headset notification (§8.7) "Your mic isn't reaching VRChat" |
| Added voice latency | 15–40 ms on the actor's voice (**unconfirmed**) | Measure in step 0; small buffers; never exclusive mode |
| Bundling terms | VB-Audio could read film productions as "professional" | Ask VB-Audio in writing; credit and a donate link in the app |
| VRChat's gate eats quiet sounds | Missing effects | Same as with Soundpad; setup warns, and the level meter shows that the player sent sound |
| EAC and virtual audio drivers | None reported; VB-CABLE and Voicemeeter are common in VRChat | Check in step 0 |
| Proton doesn't see `vrcas_mic` | No Linux path | Step 0 on the Linux box before building step 2 |

---

## Part B — Crew Talkback (Voice Intercom)

### B.1 Why not just Discord

Discord is free, mature and has good echo cancellation. Build this only for what Discord can't do:

1. **Keep crew talk out of the recording.** When an actor answers the director, VRChat must not hear it (§C). Discord can't know about VRChat.
2. **Director talkback** to everyone or to one actor, tied to the cast panel and the stage (Standby / Rolling, §8.8).
3. **Ducking** the actor's headphone playback (never the audience line) while the director talks, as broadcast IFB does.
4. **Camera previews in the same window** with the same people (§8.6).
5. **No Discord accounts and no extra server invites.** Approvals come from the relay.

**Recommendation:** a spike first (B.6 step 0). If auto-gating and talkback-to-one turn out not to matter on set, Discord stays the answer.

### B.2 Server: LiveKit on the VPS

**Mesh vs SFU** (rough maths, 15 people):
- **Mesh:** each client sends its voice 14 times (~450 kbps each way, audio only). That's fine for audio, but one 3 Mbps camera to 14 viewers needs 42 Mbps of upload. Mesh breaks once previews exist.
- **SFU:** each client uploads once. Audio egress on the server is about 15 × 14 × 32 kbps ≈ 6.7 Mbps.

| Option | Licence | Voice rooms | Camera previews | TURN | Verdict |
|---|---|---|---|---|---|
| **LiveKit** | Apache-2.0 | Yes (SFU, simulcast, speaker detection, per-track subscribe permissions) | WHIP ingress; **confirmed:** WHIP is forwarded without transcoding by default, at minimal CPU | Built in | **Recommended** |
| MediaMTX | MIT | No rooms | WHIP/WHEP per path | Not built in | Previews only (the current §8.6 plan) |
| mediasoup | ISC | If we build signalling and rooms | — | — | Too much to build beside a Python relay |
| Janus | GPL-3.0 | AudioBridge plugin | Streaming plugin | Optional | Possible, copyleft, older |
| Jitsi | Apache-2.0 | Yes | Yes | Yes | A whole platform; too heavy |

**The relay's job:**
- It stays the authority. A `voice.join` request from an approved session gets a short-lived LiveKit token, whose grants follow the role:
  - **Director:** publish and subscribe to everything.
  - **Actor:** publish audio; subscribe to audio.
  - **Camera:** publish audio and video.
- LiveKit does its own signalling, so the reserved `rtc.*` messages (§8.6) stay unused for this.
- A JWT (HS256) can be minted with PyJWT or `livekit-api`. The relay gets the LiveKit API key and secret in its settings.

**Hosting caveat:**
- The live relay sits behind Tailscale Funnel, which carries TCP only.
- LiveKit wants public UDP (a port range, or one muxed UDP port), with TCP and TURN/TLS as fallbacks.
- So it needs the VPS's public IP and open firewall ports, with Caddy or its own TLS for the signalling and TURN domain.
- Check the VPS's bandwidth quota before previews.

### B.3 Where the WebRTC runs

**Windows (WebView2, Chromium):** `getUserMedia` and `RTCPeerConnection` work.
- pywebview 6.2 has no `PermissionRequested` handler (checked in this repo's venv), so WebView2 shows its own permission prompt.
- An optional handler on the native `CoreWebView2` could allow the mic for our own origin only (**unconfirmed** how pywebview exposes it).

**Linux:** the build already runs in the user's browser, which has full WebRTC.
- `http://127.0.0.1` counts as a secure context, so `getUserMedia` works without TLS.
- WebKitGTK (`--window` from source) has WebRTC off by default since 2.38, and distro support is unclear. Voice there is unsupported.

**Split:**
- **The UI owns** the mic, the speakers and WebRTC, through the LiveKit JS SDK, with Chromium's echo cancellation and noise suppression.
- **The agent owns** push-to-talk inputs, gating (§C), ducking, headset notifications, and VRChat OSC.
- The Python LiveKit SDK (`livekit.rtc`, with its own echo canceller) stays an option if the UI path falls short.

### B.4 Push-to-talk from a headset

People in VR can't click the window. In order of cost:

1. **Global hotkey** in the agent: Windows `RegisterHotKey`; Linux through the GlobalShortcuts portal, **unconfirmed** per desktop.
2. **Stream Deck, foot pedal or MIDI** through Companion (§8.9.2), with a press and a release endpoint (`/control/talk/down`, `/up`). This is the usual broadcast setup.
3. **Avatar menu:** a `VRCAS_Talk` parameter beside `VRCAS_Go` (§8.9.1), read over OSC. Hold vs toggle behaviour of menu Buttons is **unconfirmed**.
4. **SteamVR controller binding:** needs an OpenVR action manifest. Later.

**Visible state:**
- A "mic live" state in the UI, and in the headset (§8.7: "Talking to crew", "Director talking").
- The director sees who is talking: LiveKit's active speakers.

### B.5 Features

**MVP:**
- One crew room.
- **Director talkback:** hold to talk to everyone, or to one person from their cast row (LiveKit per-track subscribe permissions, **unconfirmed** for fast switching).
- **Actors and cameras:** push-to-talk to the director.
- Mic-live indicators.
- **Headphone check at join:** a speakers test with a "did you hear it through headphones?" question.
- **No recording anywhere:** the relay and LiveKit store no audio.

**Later:**
- IFB ducking of the actor's monitor line while the director talks (needs Part A's player).
- Per-role channels (camera crew only).
- A Standby tone tied to the stage state.
- An optional noise suppression toggle.

### B.6 Phases (one developer)

| Step | Work | Estimate |
|---|---|---|
| 0 | **Spike:** LiveKit on a test port of the VPS (not the live relay), token minting, two browsers plus WebView2, the permission prompt, the OSC mute test (§C) on Windows | ~2–3 days |
| 1 | MVP: `voice.join` / `voice.token` (models in `vrcas_protocol`, permission rows), Talk panel, talkback to all/one, push-to-talk inputs 1–3, gating (§C), indicators, headset messages | ~1.5–2 weeks |
| 2 | IFB ducking, channels, stage tie-ins | ~1 week |
| 3 | **Camera previews on the same LiveKit:** OBS WHIP output → LiveKit ingress (forwarded, not transcoded; needs Redis and the ingress service) → director sees one camera full size and the rest as thumbnails. Replaces §8.6 Option A's MediaMTX sidecar; MediaMTX stays the fallback if ingress misbehaves. The OBS-has-one-stream-output limit and operator consent (§8.6) stay | ~1–1.5 weeks |

**About 3.5–4.5 weeks after the spike.** Step 3 fits well beside the obs addon (Phase 4).

### B.7 Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Crew talk leaks into VRChat | Ruins a take | §C: gate in the player's voice bridge first; OSC fallback; mic-live always visible |
| Talkback audio leaks into the actor's mic | Echo in the recording | Headphones required (join check); Chromium echo cancellation; talkback never routed to the virtual mic |
| Windows ducks other apps when we capture | VRChat or sounds drop by 80 % during a call (Windows default for communication streams, **unconfirmed** that it triggers) | Opt out of ducking; test in step 0 |
| No public UDP on the VPS | No media, or TURN/TCP only (higher latency) | Check in step 0 |
| VPS bandwidth with previews | Throttling or cost | Selective subscription: one full-size feed, thumbnails via simulcast |

---

## C. How the Two Fit Together: Keeping Crew Talk Out of the Recording

| | With Part A's player (voice bridge) | Without it (Soundpad or a plain mic) |
|---|---|---|
| Actor talks to crew | The agent gates its own voice bridge (Linux: mutes the loopback). VRChat hears silence. There's no VRChat state to get wrong, and a crash leaves the voice *on*, not muted | VRChat OSC `/input/Voice` (**confirmed** behaviour below) |
| Talkback audio | Plays on the monitor device only; the agent refuses to route it to the virtual mic | Headphones and echo cancellation only |

**VRChat's `/input/Voice`** (docs.vrchat.com, **confirmed**):
- With **Toggle Voice on**, a change from 0 to 1 *toggles* mute, and it must be set back to 0. While it's held at 1, keyboard and controller mute are blocked.
- With **Toggle Voice off**, it works like push-to-mute: 0 is muted, 1 is unmuted.

**Why the OSC fallback is weak:**
- Most actors use toggle mode, where a toggle without knowing the current state can *unmute* someone.
- The agent would have to read `MuteSelf` over OSC output, which is **unconfirmed**, and re-toggle on a mismatch.
- A community report says OSC toggling can break keyboard and controller mute until OSC is reset.
- So without Part A, talkback for actors should be listen-only by default, with the OSC route offered as an experiment.

---

## D. Open Questions (for the user)

1. **VB-CABLE:** bundle it under the donationware terms (credit plus a donate link, and ask VB-Audio in writing), or have actors install it from vb-cable.com themselves?
2. **Soundpad:** keep it as a selectable engine permanently, or remove it once the player has passed a test day on Windows?
3. **VPS:** does it have a public IP with UDP ports we can open for LiveKit, beside Tailscale Funnel?
4. **Talkback scope:** does auto-gating plus talkback-to-one justify the build over Discord, or should B start only with camera previews?

---

## Sources

**Part A**
- Soundpad About (own driver history): https://www.leppsoft.com/soundpad/en/about/
- VB-Audio licensing (bundling, donationware, prices): https://vb-audio.com/Services/licensing.htm
- VB-Audio forum, latency notes: https://forum.vb-audio.com/viewtopic.php?p=165 ; 24H2 report: https://forum.vb-audio.com/viewtopic.php?p=7505
- VAC redistribution: https://vac.muzychenko.net/en/manual/distrib.htm
- Microsoft driver signing: https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-reqs , https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-attestation
- Microsoft user-mode audio components: https://learn.microsoft.com/en-us/windows/win32/coreaudio/user-mode-audio-components
- Microsoft low-latency audio (loopback measurement): https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio
- Virtual-Audio-Driver: https://github.com/VirtualDrivers/Virtual-Audio-Driver ; Scream: https://github.com/duncanthrax/scream
- Soundux: https://github.com/Soundux/Soundux
- PipeWire loopback: https://docs.pipewire.org/page_module_loopback.html ; remap-source: https://docs.pipewire.org/page_pulse_module_remap_source.html ; issue 1734: https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/1734
- VRChat noise suppression and threshold (2022 update): https://ask.vrchat.com/t/developer-update-4-august-2022/11583
- sounddevice: https://pypi.org/project/sounddevice/ ; pyminiaudio: https://pypi.org/project/miniaudio
- AudioContext.setSinkId: https://developer.chrome.com/blog/audiocontext-setsinkid

**Part B and §C**
- VRChat OSC as input controller (`/input/Voice`): https://docs.vrchat.com/docs/osc-as-input-controller
- VRChat OSC avatar parameters: https://docs.vrchat.com/docs/osc-avatar-parameters ; Expressions (`MuteSelf`): https://wiki.vrchat.com/wiki/Expressions
- VRChat feedback, `/input/Voice` breaking bindings: https://feedback.vrchat.com/bug-reports/p/osc-input-for-input-voice-breaks-keyboard-and-controller-bindings
- LiveKit: https://github.com/livekit/livekit ; self-hosting: https://docs.livekit.io/transport/self-hosting/deployment.md ; ingress: https://docs.livekit.io/transport/self-hosting/ingress.md ; transcoding: https://docs.livekit.io/transport/media/ingress-egress/ingress/transcode.md ; tokens: https://docs.livekit.io/frontends/reference/tokens-grants.md
- MediaMTX: https://github.com/bluenviron/mediamtx ; mediasoup: https://github.com/versatica/mediasoup ; Janus: https://github.com/meetecho/janus-gateway
- WebView2 permission requests: https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/winrt/microsoft_web_webview2_core/corewebview2permissionrequestedeventargs
- WebKitGTK `enable-webrtc`: https://webkitgtk.org/reference/webkit2gtk/stable/property.Settings.enable-webrtc.html
- Secure contexts: https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts
- Windows stream attenuation (ducking): https://learn.microsoft.com/en-us/windows/win32/coreaudio/stream-attenuation
- OBS WHIP: https://obsproject.com/kb/whip-streaming-guide
- Clear-Com IFB: https://clearcom.com/News-Events/Details/interruptible-fold-back-aka-ifb
- VDO.Ninja group chat: https://docs.vdo.ninja/guides/how-does-group-chat-work
- OpenVR action manifest: https://github.com/ValveSoftware/openvr/wiki/Action-Manifest
