# Relay v2: Manual Checklist and Switch-Over

**Date:** 2026-10-20 · **Branch:** `feat/relay-v2` · **Spec:** §5, §6, §11, §20.1

The automated tests cover the protocol, every permission row, mixed sessions and a recorded v0.3.3
session replayed byte for byte. What they can't cover: the real v0.3.3 tkinter clients, Windows
and Soundpad, and the live relay behind Tailscale Funnel. That's this checklist (~30 min).

## A. Real v0.3.3 clients against the new relay (spare port, live relay untouched)

**Setup**

1. On the relay machine, from a checkout of `feat/relay-v2` (the worktree works:
   `.claude/worktrees/relay-v2`), start a test relay on a spare port with its own data folder:

   ```bash
   venv/bin/python server_ws.py --port 5600 --secret <test secret> --data-dir /tmp/vrcas-relay-test
   ```

   Add `--host <tailscale IP>` (or `0.0.0.0`) if the clients run on other machines, and point them
   at `ws://<that address>:5600/ws`. Keep the `/ws`: the v0.3.3 director uses a `ws://` address
   as typed, and without the path it gets a 403 (the v0.3.3 relay too). Optional: copy
   `update_manifest.json` into the data folder to test update offers.
2. Have ready: the v0.3.3 director client, the v0.3.3 actor client on the Windows test box (with
   Soundpad), and a build of this branch (`build_agent.py`) for the mixed checks.
3. Every client on one PC shares a machine id (derived from the host name), and the relay matches
   connections by machine id. Start each new-app instance with its own `VRCAS_MACHINE_ID`,
   `--data-dir` and `--port`, or it replaces the v0.3.3 client in the same role and is
   auto-approved:

   ```powershell
   $env:VRCAS_MACHINE_ID="laptop-v04-actor"; .\dist\vrcActorSync.exe --role actor --name Nova --server ws://<address>:5600 --data-dir $env:TEMP\vrcas-v04-actor --port 47812
   ```

**v0.3.3 clients only** (they must behave exactly as on the old relay)

| # | Do | Expect |
|---|---|---|
| 1 | Connect the v0.3.3 director with the secret | Approved; "Server version: v0.3.3"; no update dialog |
| 2 | Connect the director with a wrong secret | "✗ Denied: Invalid secret", then a retry every 5 s until you fix the secret or press Disconnect (the v0.3.3 director doesn't stop on a denial, on any relay) |
| 3 | Connect the v0.3.3 actor (a machine not approved on this relay) | The director lists it as pending |
| 4 | Approve it | The actor shows "Approved by director!", and the director's actor list shows it |
| 5 | GO, Stop, Play in 3s | Soundpad plays, stops, and plays after the countdown; Stop during the countdown cancels it |
| 6 | Untick the actor, press GO | Nothing plays |
| 7 | OSC toggle on GO / Stop (if you use it) | The avatar parameter changes in VRChat |
| 8 | Send a batch of 2 files, one already on the actor | Overwrite prompt, both arrive, batch summary on the director |
| 9 | Start a batch and cancel it midway (press Cancel Batch while the actor's accept or overwrite prompt is open: the v0.3.3 director sends file data on its window thread, so the button doesn't respond mid-file) | The batch stops on both sides, as it did on the old relay |
| 10 | Chat both ways | Lines appear on both sides |
| 11 | Forget the actor, then reconnect it | "You have been forgotten"; after reconnecting it's pending again |
| 12 | Close and reopen the actor | Auto-approved; "Coda joined" on the director |
| 13 | Open a second director | Both directors get the "already connected" / "another director" warning |
| 14 | Leave everything idle 30 s | Latency dots stay green on the director |

**Mixed with the new app** (a build of this branch)

| # | Do | Expect |
|---|---|---|
| 15 | Start the new app as director against `:5600` | Connects; no "v0.3 relay" tag in the connection pill; the v0.3.3 director gets the "another director" warning |
| 16 | New app as actor on the Windows box (Soundpad running) | Pending in both directors; approve from either |
| 17 | GO / Stop / Play in 3s from the new director | Both the v0.3.3 actor and the new actor play and stop |
| 18 | GO / Stop from the v0.3.3 director | Both actors play and stop |
| 19 | New app as camera | Pending only in the new director (the v0.3.3 director never sees cameras); after approval it shows in the new director's cast |
| 20 | Send a file from the v0.3.3 director to the new actor | Declined: "… uses vrcActorSync 0.4, which can't receive files from a v0.3 director yet" |

Anything that differs from these expectations: note the step and send `/tmp/vrcas-relay-test/server.log`.

### Results, 2026-10-21: part A passes (step 7 skipped)

- **Relay:** the `feat/relay-v2` worktree with the live relay's `venv` (FastAPI 0.150, pydantic 2.14) on the relay host's
  Tailscale IP, port 5600, `--data-dir /tmp/vrcas-relay-test` with a copy of `update_manifest.json` (latest 0.3.3).
  It ran 95ead55 until 11:21, then 9896410 (the log-wording fix below) for the redo of steps 12 and 17.
- **Clients:** all on the Windows 11 test box: the v0.3.3 director and actor (Soundpad 4.0.35), and a one-file build of
  95ead55 (Python 3.12.10, PyInstaller 6.22.3, pydantic 2.13.5; `vrcas_protocol` bundled) as Mira2 (director),
  Nova (actor) and Cam (camera), each with its own `VRCAS_MACHINE_ID`.
- **Times** are the relay host's (`server.log`). The test box's clock runs about 9 s behind it.
- **"log"** means `server.log` confirms the step. Cues, chat and files aren't logged, so those steps rest on what the
  tester saw on the clients and in the agent logs.

| # | Result | Notes |
|---|---|---|
| 1 | Pass | log 10:42:38: v0.3.3 director authenticated; no update offer |
| 2 | Pass | "Invalid secret". The director then retried every 5 s (log 10:42:59, 10:43:05) until the secret was fixed (10:43:10). That's the v0.3.3 director's own behaviour on any relay; the expectation said "no reconnect loop" and is corrected above |
| 3 | Pass | log 10:43:56: pending |
| 4 | Pass | log 10:44:07: approved |
| 5 | Pass | tester |
| 6 | Pass | tester |
| 7 | Skipped | VRChat not running |
| 8 | Pass | tester |
| 9 | Pass | Cancelled while the actor's prompt was open; Cancel Batch doesn't respond mid-file (now noted in the step) |
| 10 | Pass | tester |
| 11 | Pass | log: forgotten 10:46:08, pending again on reconnect 10:46:11, approved 10:46:13 |
| 12 | Pass | log 11:28:45: auto-approved (known machine_id). No v0.3.3 director was connected after the relay restart, so the "OldActor joined" line wasn't seen; the golden transcript covers that broadcast |
| 13 | Pass | log 10:46:23: the second director was warned |
| 14 | Pass | tester |
| 15 | Pass | log 10:59:11: Mira2 over v2; no "v0.3 relay" tag; the v0.3.3 director showed "⚠ Warning: Mira2 has connected as another director" |
| 16 | Pass | log 11:01:02 pending, 11:02:09 approved (from Mira2); Soundpad over the named pipe, no `-rc` fallback |
| 17 | Pass | GO, Stop, and Stop during the countdown (twice). An uninterrupted Play in 3s (after the restart): Mira2's GO at the end of its countdown reached Nova 48 ms later, audio ≈80 ms after that; the v0.3.3 actor played too |
| 18 | Pass | Three GO/Stop rounds; no "has no v2 equivalent" in the log, so every cue reached Nova as v2; audio ≈80 ms |
| 19 | Pass | log 11:09:14 pending, 11:09:42 approved; Cam showed only in Mira2 |
| 20 | Pass | "File transfer denied: Nova uses vrcActorSync 0.4, which can't receive files from a v0.3 director yet"; nothing reached Nova |

**Found, and what changed:**

- The v0.3.3 director needs `…:5600/ws`; without the path it gets a 403 (the v0.3.3 relay too). Setup step 1 says so now.
- A new-app instance sharing the PC's machine id replaces the v0.3.3 client in the same role. Setup step 3 now
  gives each instance its own id.
- `server.log` said "Actor approved by director: Cam" for a camera. Fixed in 9896410: approve, deny and forget name the role.
- Importing the v0.3 settings copied the director secret into actor and camera configs. Neither role sent it, but the
  file held it. Fixed in 137446b: with `--role actor` or `camera` the secret isn't imported. With both v0.3 configs
  present and no `--role`, it still is, since the user may pick director.
- The v0.3.3 director's Cancel Batch only responds between files. Spec §8.4 now asks the files addon to keep Cancel
  usable for the whole batch.

**Not covered:** a v0.4 preview build (`feat/windows-build`) in compatibility mode against the new relay (no preview exe
was left on the test box), OSC (step 7), and the v0.3.3 clients on Linux.

## B. Switch the live relay over

The live relay runs from `/home/dannygrey/vrActorAssist` (branch `feat/web-ui`) with
`venv/bin/python server_ws.py --host 127.0.0.1 --secret …` on port 5555, behind Tailscale Funnel.
Its `venv` already has everything the new relay needs (FastAPI 0.150, pydantic 2.14; the golden
session and a v2 handshake were run with that interpreter on a spare port).

1. Pick a quiet moment. Everyone is disconnected for a few seconds; v0.3 clients retry every 5 s.
2. Back up: `cp approved_actors.json approved_actors.json.bak`.
3. Bring the code into the live checkout: `git merge feat/relay-v2` while on `feat/web-ui`
   (the branch is checked out in the worktree, so merge it rather than checking it out).
4. Restart the relay the way you normally do (`./start-server-ts.sh restart`, or stop the
   process and start the same command). The command line doesn't change; the data stays next to
   `server_ws.py`.
5. Check:
   - `curl http://127.0.0.1:5555/health` → `{"status":"healthy"}`
   - `server.log` starts with `Starting vrcActorSync relay v0.4.0-dev … (v2 on /v2/ws; v0.3 clients on /ws, as v0.3.3)`
   - a v0.3.3 actor reconnects and is auto-approved.
6. Roll back if needed: stop the relay, `git switch --detach <commit before the merge>` (or revert
   the merge), start it again. `approved_actors.json` stays compatible: the v0.3.3 relay ignores
   the new `role` / `delay_ms` keys.

**What testers will notice**

- **v0.3.3 tkinter clients:** nothing, apart from the restart. Same version line (v0.3.3), same
  messages, same quirks; the recorded session is identical byte for byte.
- **The current v0.4 preview builds** (they only speak v0.3): keep working in compatibility mode.
  One difference: a preview build connecting as camera is no longer announced "X joined" / "X left"
  to everyone, since cameras are hidden from `/ws`.
- **Builds of this branch:** connect over v2 by themselves. Directors see camera operators in the
  cast, the "v0.3 relay" tag disappears, and latency comes from the relay's own pings. A v0.3.3
  director can't see or approve cameras; a new director has to.
- Pending join requests are lost on restart, as before; approved machines come straight back.
