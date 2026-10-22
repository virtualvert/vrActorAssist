# Tester prep: new logo, readiness for new testers

**Date:** 2026-10-22 · **Base:** `feat/web-ui` @ 1216537 · **Branch:** `feat/new-logo` @ deb8f29 (pushed)

What has to happen before new testers get invited: the new app icon checked on Windows and merged, then the blockers in
section 2 cleared, then the tester guide (section 3) shared.

---

## 1. Laptop prompt: app icon on Windows

Runs on the Windows 11 box "laptop" (phase 2 plan §0 for its setup). No test relay: the icon checks need none, and the
smoke test at the end uses the live relay on purpose, as an actor with its own machine id, which the user approves and
forgets again.

```text
You're checking the new vrcActorSync app icon on this Windows 11 box (the barking head: indigo→teal head with amber,
violet and teal bark lines). The branch is feat/new-logo. The user looks and clicks; you set up, build, watch and
record what you see.

Rules
- Don't change code. Report what you see.
- Steps 1-5 need no relay. Only step 6 connects, to the live relay wss://doggoos.tail73c00a.ts.net, as the actor
  "IconCheck" with machine id laptop-logo-exe. Never start anything else against the live relay, and leave the v0.3.3
  clients alone (don't start, close or change them).
- Don't change Windows settings yourself. The display scale in step 4 is the user's change.
- Capture stderr with cmd /c "... 2>> file", never PowerShell's 2>> (it drops what's printed after Ctrl+C).
  Highlighted text in the console freezes output and swallows Ctrl+C; press Esc first if anything looks stuck.

Setup
1. In your vrActorAssist checkout: git fetch origin; git worktree add ..\vrcas-logo origin/feat/new-logo; cd ..\vrcas-logo
   git log --oneline -1   # expect deb8f29 "feat: barking-head logo and app icon (exe, window, taskbar)"
   py -3.12 -m venv .venv; .\.venv\Scripts\python -m pip install -r agent\requirements-dev.txt pyinstaller
   bun --cwd=web install
2. .\.venv\Scripts\python build_agent.py
   Expect: it ends with dist\vrcActorSync.exe and no error. Write down the exe's size.

Steps (after each: pass or fail, and what the user saw; a screenshot if the user can take one)
1. Explorer. Open dist\ in Explorer, View → Extra large icons, then Large, Medium, Small, Details.
   Expect: the new head at every size, crisp, no white box, no generic exe icon. Right-click → Properties: the same
   icon top left. (If Explorer shows an old or generic icon, copy the exe to a new folder and look there: Explorer
   caches icons by path. Say whether you had to.)
2. The exe's window. mkdir $env:TEMP\vrcas-logo-exe; then
     $env:VRCAS_MACHINE_ID="laptop-logo-exe"
     .\dist\vrcActorSync.exe --role actor --name IconCheck --data-dir $env:TEMP\vrcas-logo-exe --port 47840
   (no --server yet, so it connects nowhere). The desktop window opens (not the browser).
   Expect: the head in the window's title bar (top left), on the taskbar button, in Alt-Tab (hold Alt, press Tab),
   and in Win+Tab. Hover the taskbar button: the thumbnail's title says vrcActorSync with the head.
   The in-app logo (top left of the page) is the same head in theme colours. Close the window: the process ends
   (Task Manager has no vrcActorSync left).
3. Pinned shortcut. Make a copy with no saved settings so it can't connect anywhere:
     mkdir $env:TEMP\vrcas-logo-pin; copy dist\vrcActorSync.exe $env:TEMP\vrcas-logo-pin\
     New-Item $env:TEMP\vrcas-logo-pin\portable.flag
   Double-click $env:TEMP\vrcas-logo-pin\vrcActorSync.exe. It opens on the first-run screen; don't connect.
   Right-click its taskbar button → Pin to taskbar. Close the window. Click the pinned button.
   Expect: the pin shows the head; the window opens ON the pinned button (one button, not a second one next to it).
   Close it. Leave the pin for now (step 4 uses it); the user unpins it at the end if they want.
4. Scaling (only if the user agrees to change it). The user sets Settings → System → Display → Scale to 150%
   (or 125% if 150% isn't offered), then starts the pinned copy again.
   Expect: title bar, taskbar, pin and Alt-Tab icons sharp at the bigger size (not blurry or blocky). Write down the
   scale used and the scale it was before. The user sets the scale back afterwards.
5. From source (the taskbar app id). mkdir $env:TEMP\vrcas-logo-src; then
     $env:VRCAS_MACHINE_ID="laptop-logo-src"
     cmd /c ".venv\Scripts\python -m agent --role actor --name IconSrc --data-dir %TEMP%\vrcas-logo-src --port 47841 2>> %TEMP%\vrcas-logo-src\stderr.txt"
   Expect: the window's taskbar button shows the head, not the Python icon, and it is its own button (not grouped
   with any other python.exe window). Don't pin this one (a pin of a source run points at python.exe). Close the
   window; the cmd returns. Report stderr.txt (expect empty or only harmless lines).
6. Smoke test on the live relay (exe from step 2, same machine id and data dir):
     $env:VRCAS_MACHINE_ID="laptop-logo-exe"
     .\dist\vrcActorSync.exe --role actor --name IconCheck --server wss://doggoos.tail73c00a.ts.net `
       --data-dir $env:TEMP\vrcas-logo-exe --port 47840
   Soundpad running (full version) with a sound selected.
   a) Expect: "Awaiting approval" in the top bar. The user approves IconCheck in their director app; IconCheck shows connected.
   b) The user ticks only IconCheck and presses GO. Expect: IconCheck shows GO! and Soundpad plays the selected sound.
   c) The user presses STOP. Expect: Soundpad stops; IconCheck shows Stopped.
   d) While IconCheck is still connected, the user forgets it in the director (cast row → trash button, click twice:
      "Forget?") so the live relay doesn't keep the test machine approved. Then close IconCheck's window.
      (Forget only works on a connected row: the cast comes from the live roster.)

Report per step: pass or fail and what the user saw, the exe size, the scale values from step 4, whether you had to
copy the exe in step 1, stderr.txt from step 5, and the last 30 lines of $env:TEMP\vrcas-logo-exe\logs\agent.log.
At the end, list anything that looked wrong even if it isn't in the steps (an old icon anywhere, a blurry size, a
second taskbar button).
```

(Step 6d was "close, then forget" in the run; it's corrected above, see the results.)

### 1.1 Laptop results (2026-10-22): all six steps pass

Windows 11 IoT Enterprise LTSC 2024 (10.0.26100), 2560×1600 at 125 %; Python 3.12.10, PyInstaller 6.22.3, pywebview
6.2.1, Bun 1.4.2, Soundpad 4.0.35 (full version, remote control 1.1.2), WebView2 present.

- **Build:** `build_agent.py` exit 0 (only PyInstaller's usual hidden-import warnings); `dist\vrcActorSync.exe`
  17,563,434 bytes. `agent/tests/test_icons.py` 4 passed there. The exe's `RT_GROUP_ICON` holds the .ico's nine 32 bpp
  frames (16, 20, 24, 32, 40, 48, 64, 128, 256).
- **1 Explorer:** the head at every view size and in Properties; no stale icon cache (no copy needed).
- **2 Window:** title bar, taskbar, hover thumbnail, Alt-Tab, Win+Tab; in-app logo matches. `WM_GETICON` at 125 %:
  small 20×20, big 40×40 (exact frames). Closing the window ended both one-file processes and WebView2.
- **3 Pin:** the pin shows the head and the window opens on the pinned button. Windows stamped
  `System.AppUserModel.ID = vrcActorSync.App` into the pin's `.lnk`.
- **4 Scaling:** 125 % → 150 % → back to 125 %. Sharp at 150 %; title bar uses the exact 24 px frame; the taskbar
  (~36 px) is scaled down from a bigger frame, smooth, with the bark lines reading as three small blocks.
- **5 Source run:** the head on the taskbar, never Python's icon (the window belongs to the base `python.exe`). It lit
  up the step 3 pin instead of getting its own button (same app id). stderr only had the normal log lines.
- **6 Live relay:** approved, four GOs through the named pipe (PLAYING after 2–3 ms, audio 28–44 ms after the command,
  start-latency compensation 60 → 44 → 36 → 29 ms), STOP stopped. 6d needed the order above: after a close the
  director's cast had no IconCheck row; IconCheck restarted and rejoined without approval (still approved), then was
  forgotten while online (06:43:01) and closed.

**Findings**

1. A director can't forget someone who has disconnected (no row, no trash button); they keep their approval in
   `approved_actors.json`. Readiness item S4.
2. The exe and a source run share the taskbar id `vrcActorSync.App`, so a source run groups onto a pinned exe and the
   pin then focuses the dev window. Option: a separate id for source runs (`vrcActorSync.Dev`). Left as is for now.
3. No 30 / 36 px frames (the Windows 11 taskbar sizes at 125 % / 150 %). Clean, but the bark lines merge at 36 px.
   Optional: add those frames from `icon-small.svg` in `scripts/gen_icons.py`.
4. Left on the laptop: `%TEMP%\vrcas-logo-pin` was used as the director, so its `vrcActorSync-data\config.json` holds
   the live director secret; delete the folder. Also the taskbar pin, the worktree `vrcas-logo` and the
   `%TEMP%\vrcas-logo-exe` / `-src` data dirs. After the forget the relay listed `laptop-logo-exe` as pending again;
   deny it if it still shows under "Waiting to join".

---

## 2. Readiness check

Checked 2026-10-22 against `feat/web-ui` @ 1216537 (`feat/new-logo` changes no relay files).

### 2.1 Blockers (before the first invite)

| # | What | Why it blocks | Fix | Who |
|---|---|---|---|---|
| B1 | **No v0.4 download.** GitHub releases end at v0.3.1 (pre-release) / v0.3.0 (latest). | Testers have nothing to download; the guide needs a link. | A GitHub pre-release (e.g. `v0.4.0-preview.1`) with `vrcActorSync.exe` built on the laptop from `feat/web-ui` after the logo merge. Pre-release, so the v0.3 "Latest" stays. | User's go (outward-facing); laptop builds |
| B2 | **The live relay is older than the app.** Started 2026-10-21 11:42 from 11e9682; M1a / M1b came later (`server/transfers.py`, `server/file_bridge.py`). | Send files between v0.4 apps and the v0.3 ⇄ v0.4 file bridge don't work on it. Soundpad remote and timed GO already work (their rows existed; the relay forwards unknown fields). | Restart from the main checkout (already on `feat/web-ui` @ 1216537): part B of the relay checklist, `./start-server-ts.sh restart` (asks for the secret and sudo; kills every `server_ws.py`, test relays too). | User runs it |
| B3 | **Every build says `0.4.0-dev`.** `agent/__init__.py` `APP_VERSION`; shown in the top bar and Settings → About. | Bug reports can't tell one tester build from the next. | `APP_VERSION = "0.4.0-preview.1"` for the tester build, bumped for each re-download. The relay ignores suffixes (`server/updates.py` `parse_version`), so version checks don't change. ~5 min. | Code change, needs the user's OK |

**B2 smoke run (2026-10-22, this machine):** the main checkout's code with the live `venv` (FastAPI 0.150, pydantic 2.14.1,
uvicorn 0.54.0) on 127.0.0.1:5610, own data dir, a copy of the live `approved_actors.json`: `/health` healthy, start line
`Starting vrcActorSync relay v0.4.0-dev … (v2 on /v2/ws; v0.3 clients on /ws, as v0.3.3)`, a v2 actor hello answered with
`approval.pending`. Stopped afterwards; the live relay (PID 3783269) wasn't touched.

**What changes for connected clients at the restart (B2):**

- Everyone is disconnected for a few seconds. v0.3 clients retry every 5 s; v0.4 apps reconnect by themselves.
- Pending join requests are lost (they ask again); approved machines come straight back (`approved_actors.json` stays).
- Session ids start over (directors' cast lists rebuild; nothing to do).
- New: Send files between v0.4 apps; a v0.4 director's files reach v0.3 actors and a v0.3 director's batches reach v0.4
  actors (through the bridge). v0.3 ↔ v0.3 transfers work as before.
- v0.3.3 clients see nothing else: `/ws` still replays the golden session byte for byte.
- Rollback: stop the relay, `git switch --detach 11e9682` in the main checkout (the code it runs today), start it again.

### 2.2 Should fix (testers will hit these)

| # | What | Fix | Effort |
|---|---|---|---|
| S1 | The UI doesn't say where the log file is. It's `<data dir>\logs\agent.log`: `%APPDATA%\vrcActorSync\logs\agent.log` for the exe (`vrcActorSync-data\logs\` beside it with `--portable`). | The guide gives the path. Better: an "Open log folder" button in Settings → About (a new call: `protocol.ts` + `core.py` + `demo/session.ts`). | ~30 min |
| S2 | A bare host name becomes `ws://` (`agent/relay_legacy.py` `ws_url`), which Tailscale Funnel doesn't serve. `doggoos.tail73c00a.ts.net` alone fails; `wss://doggoos.tail73c00a.ts.net` works. | The guide gives the full `wss://` address. Better: no scheme and no port → `wss://`. | ~15 min + tests |
| S3 | One machine id per PC (`shared.get_machine_id`: a uuid5 of the host name). A v0.3.3 actor and the v0.4 app as actor on one PC replace each other; the v0.3.3 client reconnects and wins, the v0.4 app stops with "Replaced by a newer connection from this computer". | The guide: close the old v0.3 app before starting the new one in the same role. Different roles on one PC work (and share one approval, item 2.3). | Guide only |
| S4 | A director can forget only someone who is connected: the cast comes from the live roster (`agent/relay_v2.py` `peers()`), so a tester who has left can't be removed and stays approved. The relay already forgets by machine id (`server/router.py` `_forget`). | List approved machines that are offline in the cast (or Settings) with a Forget button. Until then: forget testers while they're online. | ~1–2 h (contract change + relay sends the approved list) |

### 2.3 Tell testers (no change needed now)

- **SmartScreen:** the exe is unsigned; a downloaded copy shows "Windows protected your PC" → More info → Run anyway.
  Antivirus can flag PyInstaller one-file builds too.
- **WebView2:** built into Windows 11 (and on most Windows 10 PCs through Edge). Without it the app opens in the browser
  instead of its window, and then the only way to quit is Task Manager. A PC without it hasn't been tried.
- **Soundpad:** actors need Soundpad running. "Start Soundpad when it isn't running" is off by default (with it off, cues
  fail at once with "Soundpad isn't running"). The full version adds received files to Soundpad; the trial doesn't
  (add them by hand). Soundpad 4.0.35 is the tested version.
- **Approval:** the director approves each new PC once (cast list → Approve). Only a v0.4 director sees and approves
  cameras. A PC approved in one role is approved in every role (phase 2 plan §10, open decision).
- **Gaps:** no tray icon (closing the window quits the app), no auto-updater for v0.4 (re-download the exe), the camera
  role only shows presence (no OBS yet), no OSC timeline; OSC avatar parameters aren't part of this round (M4 next).
- **Logs** may contain sound titles and folder names; testers should look before sharing.
- **Machine ids** stay per PC: re-downloading the exe keeps the approval.

### 2.4 Decisions for the user

**Answered 2026-10-22:** push (done: `feat/web-ui` @ df69d38, `feat/new-logo` @ e56ac74); B1: the user publishes the
pre-release; B2: restart now (done, below); B3 and S1 / S2 / S4: yes (built on `feat/tester-prep`, section 4).

**B2 done, 2026-10-22 06:57:** `./start-server-ts.sh restart` from the main checkout at df69d38 (the user typed the sudo
password and the secret in the terminal panel). Backup: `approved_actors.2026-10-22.json.bak` (2 entries). Nobody was
connected but the user's old v0.4 preview director, which reconnected over `/ws` at 06:58:04. Checks: `/health` healthy
on 127.0.0.1:5555 and through `https://doggoos.tail73c00a.ts.net/health`; start line `Starting vrcActorSync relay
v0.4.0-dev … (v2 on /v2/ws; v0.3 clients on /ws, as v0.3.3)` at 06:57:34. S4 changes the relay, so it needs one more
restart after `feat/tester-prep` merges.

Original questions:

1. Publish the v0.4 download as a GitHub pre-release (B1)? Which tag?
2. Restart the live relay (B2), and when?
3. Set the tester version (B3) and add S1 / S2 before the build?
4. Put the relay address in the tester guide, or leave it to the invite message? (The guide's link can be passed on.)

---

## 3. Tester guide

Published 2026-10-22 as a private Artifact: https://claude.ai/artifact/9fXHjpe4ETuNzRTH5iYsMe (share it from its
Share menu once B1 and B2 are done). Contents: what to install (Soundpad, WebView2), download from the releases page,
SmartScreen, relay address `wss://doggoos.tail73c00a.ts.net`, approval, what to try per role, common problems, what to
send in a report (version, `%APPDATA%\vrcActorSync\logs\agent.log`), limits of the preview. No director or relay secret.
Its download step points at the GitHub releases page and expects a "vrcActorSync 0.4 preview" release there (B1).

---

## 4. Tester build: B3, S1, S2, S4 (`feat/tester-prep`, from `feat/web-ui` @ df69d38)

| Commit | What |
|---|---|
| 42f73d4 | B3: `APP_VERSION = "0.4.0-preview.1"` |
| 4a911b1 | S2: no scheme and no port → `wss://` (`ws_url`); the connect form's hint says so |
| 43e763c | S1: `AppState.logDir`, call `openLogFolder`, Settings → About shows the path and "Open log folder". S4: `presence.roster.offline` (relay), "Approved, not connected" in the cast with Forget; a v2 forget of a machine with no connection leaves no pending entry |

Checks on the branch: pytest 767 passed, bun 93 pass, svelte-check 0 / 0, build, `gen_ts_types.py --check`. Seen in
the app here (scratch relay on 127.0.0.1:5601 with two offline approvals, director in browser mode): the collapsed
section with both rows, Forget removes one (the relay log says "Actor forgotten by name: Sable", the file loses it,
no "Waiting to join"), Settings → About shows `0.4.0-preview.1` and the log path. Not clicked here: "Open log folder"
(it would open a file manager on the desktop); the laptop run covers it on Windows.

**What changes for connected clients** when this merges and the live relay restarts: directors on this build see
"Approved, not connected" (older builds ignore the new roster field); a v2 forget of someone who has left no longer
leaves them in "Waiting to join". v0.3 clients: nothing (the golden session passes). The restart itself: everyone
drops for a few seconds, as in B2.

### 4.1 Laptop prompt: the tester build

```text
You're checking the vrcActorSync tester build on this Windows 11 box before it's published as a pre-release.
The branch is feat/tester-prep: version 0.4.0-preview.1, an "Open log folder" button in Settings, a bare relay host
name now means wss://, and directors can forget testers who have left. The user looks and clicks; you set up, build,
watch and record.

Rules
- Don't change code. Report what you see.
- Only steps 3-4 connect, to the live relay doggoos.tail73c00a.ts.net, as the actor "PrepCheck" with machine id
  laptop-prep-exe. Never start anything else against the live relay; leave the v0.3.3 clients alone.
- Capture stderr with cmd /c "... 2>> file", never PowerShell's 2>>.

Setup
1. In your vrActorAssist checkout: git fetch origin; git worktree add ..\vrcas-prep origin/feat/tester-prep; cd ..\vrcas-prep
   git log --oneline -1   # expect "docs: tester build …" or newer on that branch
   py -3.12 -m venv .venv; .\.venv\Scripts\python -m pip install -r agent\requirements-dev.txt pyinstaller
   bun --cwd=web install
2. .\.venv\Scripts\python build_agent.py
   Expect: dist\vrcActorSync.exe, no error. Write down its size and Get-FileHash dist\vrcActorSync.exe (SHA-256).

Steps (after each: pass or fail, and what the user saw)
1. Version. mkdir $env:TEMP\vrcas-prep-exe; then
     $env:VRCAS_MACHINE_ID="laptop-prep-exe"
     .\dist\vrcActorSync.exe --role actor --name PrepCheck --data-dir $env:TEMP\vrcas-prep-exe --port 47860
   (no --server: it connects nowhere yet). The window opens with the new icon.
   Expect: the top bar shows v0.4.0-preview.1. Settings (gear) → About: Version 0.4.0-preview.1, and Logs with the
   data dir's logs folder (%TEMP%\vrcas-prep-exe\logs, possibly with the short 8.3 user name).
2. Open log folder. Settings → About → Open log folder.
   Expect: an Explorer window on that logs folder, with agent.log in it. No error in the Activity drawer. Press it
   once more: Explorer comes up again (same or new window), still no error.
3. Bare host name. Settings → Relay server: type only  doggoos.tail73c00a.ts.net  (no wss://, no /ws) →
   Save & reconnect. Soundpad running (full version) with a sound selected.
   Expect: "Awaiting approval" in the top bar; agent.log says "Connected to doggoos.tail73c00a.ts.net, registering
   as actor…". The user approves PrepCheck in their director (a v0.4 director).
4. GO / STOP. The user ticks only PrepCheck, presses GO, then STOP.
   Expect: GO! and Soundpad plays; STOP stops it. Then, while PrepCheck is still connected, the user forgets it in
   the director (cast row → trash button, twice: "Forget?"). Close PrepCheck.
5. SmartScreen, as a tester sees it. Make a copy marked as downloaded from the internet, with its own data folder
   (portable.flag) so it can't pick up saved settings and connect anywhere:
     mkdir $env:TEMP\vrcas-prep-dl; copy dist\vrcActorSync.exe $env:TEMP\vrcas-prep-dl\
     New-Item $env:TEMP\vrcas-prep-dl\portable.flag
     Set-Content -Path $env:TEMP\vrcas-prep-dl\vrcActorSync.exe -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
   The user double-clicks the exe in Explorer.
   Expect: "Windows protected your PC"; More info shows "Run anyway"; Run anyway starts the app on the first-run
   screen (if it shows anything else, close it at once and say so). Close it without connecting. Write down the
   dialog's exact wording and whether Defender or anything else complained. Delete $env:TEMP\vrcas-prep-dl afterwards.

Report per step: pass or fail and what the user saw, the exe size and SHA-256, the SmartScreen wording, and the last
20 lines of $env:TEMP\vrcas-prep-exe\logs\agent.log. Keep dist\vrcActorSync.exe: if everything passes, it's the file
for the pre-release. With the user's OK, delete $env:TEMP\vrcas-logo-pin from the icon check (its config holds the
live director secret) once it's no longer used as the director, and $env:TEMP\vrcas-prep-exe.
```

