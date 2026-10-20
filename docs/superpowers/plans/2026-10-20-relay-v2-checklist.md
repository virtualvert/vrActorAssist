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
   at `ws://<that address>:5600`. Optional: copy `update_manifest.json` into the data folder to
   test update offers.
2. Have ready: the v0.3.3 director client, the v0.3.3 actor client on the Windows test box (with
   Soundpad), and a build of this branch (`build_agent.py`) for the mixed checks.

**v0.3.3 clients only** (they must behave exactly as on the old relay)

| # | Do | Expect |
|---|---|---|
| 1 | Connect the v0.3.3 director with the secret | Approved; "Server version: v0.3.3"; no update dialog |
| 2 | Connect the director with a wrong secret | "Invalid secret", no reconnect loop |
| 3 | Connect the v0.3.3 actor (a machine not approved on this relay) | The director lists it as pending |
| 4 | Approve it | The actor shows "Approved by director!", and the director's actor list shows it |
| 5 | GO, Stop, Play in 3s | Soundpad plays, stops, and plays after the countdown; Stop during the countdown cancels it |
| 6 | Untick the actor, press GO | Nothing plays |
| 7 | OSC toggle on GO / Stop (if you use it) | The avatar parameter changes in VRChat |
| 8 | Send a batch of 2 files, one already on the actor | Overwrite prompt, both arrive, batch summary on the director |
| 9 | Start a batch and cancel it midway | The batch stops on both sides, as it did on the old relay |
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
