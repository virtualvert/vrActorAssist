# Orchestrator Kickoff Prompt — vrActorAssist Tauri Migration

This file contains a single ready-to-paste prompt for starting a **new, separate session** that orchestrates the Tauri client migration using fresh subagents per task. Copy everything in the fenced block below as your first message in that session.

---

## Paste this as your first message in the new session:

````
Use the superpowers:subagent-driven-development skill to execute an implementation plan in the vrActorAssist repository at /home/danny/vrActorAssist.

## Required reading (read both in full before dispatching Task 1)

1. Design spec: docs/superpowers/specs/2026-07-20-vrActorAssist-ssl-tauri-design.md (v1.1 — read the whole file, especially §2 Scope, §4.10-4.14, §5 Phases, §6 Success Criteria)
2. Implementation plan: docs/superpowers/plans/2026-07-23-tauri-client-migration.md (15 tasks, supersedes Tasks 4-12 of the older 2026-07-20 plan — the SSL fix in that older plan already shipped as v0.3.3, do not redo it)

## Context you need before starting

- This migrates the Python/tkinter Director + Actor clients to a single Tauri v2 + Svelte desktop app with a mode selector, per the spec. The Python FastAPI server (server_ws.py) is NOT touched except for the domain-reference change in Task 1.
- The pipe-delimited protocol in shared.py (repo root) is authoritative — every Rust protocol.rs message must match it exactly. If you find a discrepancy between the plan's code and shared.py, shared.py wins; flag the discrepancy to the human rather than silently picking one.
- All work happens on a new `tauri` branch, never on `main`.

## Worktree setup (do this before Task 1)

Per subagent-driven-development's required workflow skills, use superpowers:using-git-worktrees to create an isolated worktree for this work before dispatching any implementer. The plan's Task 1, Step 1 also says `git checkout -b tauri` — if using-git-worktrees already creates and checks out the `tauri` branch in the new worktree, treat that as satisfying Task 1 Step 1 and start the implementer at Task 1 Step 2 instead (don't create the branch twice).

## Model selection hints for this specific plan

- Tasks 2, 3, 4, 5, 9 contain complete, ready-to-transcribe code in the plan text (scaffold commands, protocol parser, config struct, WebSocket client, file transfer) — these are good candidates for your cheapest capable model tier.
- Tasks 6, 8, 10, 11, 12 involve multi-file integration, closures capturing shared state, and reconciling earlier tasks' interfaces (e.g. Task 8's Arc<Mutex<ActorRegistry>> threading, Task 12's updater wiring) — use a standard-or-higher model for these.
- Task 14 (CI/release workflow) and Task 15 (end-to-end verification) benefit from a standard model since they involve real command execution and interpreting output, not just code transcription.
- Use your most capable available model for the final whole-branch review, per the skill's own rule — don't downgrade this step.

## Hard stop-and-ask gates — do NOT do these without explicit human approval, even if a task's steps technically call for them

1. **Domain cutover** (Task 1 note): committing the `vra.dannygreyproductions.com` change to the `tauri` branch is fine, but do NOT cherry-pick it to `main` or touch the live VPS/Caddy config yourself — flag it to the human as a separate deployment action they need to take.
2. **Signing key password** (Task 12, Step 1): after generating the updater keypair, tell the human the password needs to be saved somewhere safe (e.g. a password manager) — do not proceed assuming it's stored anywhere durable.
3. **Never commit the private signing key file** (`~/.tauri/vrActorAssist.key` lives outside the repo). Before every commit in Task 12 onward, verify `git status` doesn't include a `.key` file under `client/`.
4. **GitHub repo secrets** (Task 14, Step 1): setting `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` via `gh secret set` touches repo-level configuration outside the codebase — confirm with the human before running this, even though the plan describes it as a step.
5. **Pushing a version tag** (Task 14 end note, Task 15): pushing any `v0.4.*` tag triggers real GitHub Actions builds and creates (draft) release artifacts. Stop and ask before pushing the first tag.
6. **Publishing the draft GitHub Release**: this is explicitly a human action (per Task 14's release process doc) — do not click/call anything that publishes it.
7. **Merging `tauri` → `main`**: this is a decision point after Task 15 passes, not a plan task. When all 15 tasks are reviewed and complete, stop and use superpowers:finishing-a-development-branch to present merge/PR options to the human rather than merging unilaterally.

## Definition of done

All 15 tasks in the plan reviewed and marked complete in the progress ledger, the final whole-branch review passed, and the spec's §6 Success Criteria checklist updated (Task 15, Step 10) to reflect what was actually verified. At that point, stop and report back to the human — do not proceed into merge/release without them per gate 7 above.

Read the plan's "What's Deliberately Not in This Plan" section at the end of docs/superpowers/plans/2026-07-23-tauri-client-migration.md before you start — it lists everything intentionally out of scope so you don't accidentally add it back in.
````

---

## Notes for you (not part of the paste block)

- This prompt assumes the new session has the same superpowers skill set installed/available. If the orchestrator session reports it can't find `subagent-driven-development`, `using-git-worktrees`, or `finishing-a-development-branch`, that's an environment problem to fix before continuing, not something to route around.
- The seven "stop-and-ask" gates above are deliberately explicit because the orchestrator session starts with zero memory of this conversation — everything we decided together (unsigned builds, GitHub Releases, domain replacement, frozen Python clients, no macOS) is already baked into the spec and plan documents, but the *process* guardrails around secrets/tags/merges are easy to lose without restating them here.
- If you'd rather review progress periodically instead of letting it run fully autonomously, you can add a line like "Check in with me after every 3 tasks" — but note this works against subagent-driven-development's "continuous execution" design (it's built to run all tasks without pausing). The gates above already cover the points that most need a human in the loop.
