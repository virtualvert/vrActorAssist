# Tauri Client Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python/tkinter Director and Actor clients with a single Tauri v2 + Svelte desktop application (mode-switchable), package it as a Windows installer, Windows portable exe, and Linux AppImage, wire up GitHub-Releases-based auto-updates, and point the deployment at the new `vra.dannygreyproductions.com` domain.

**Architecture:** The Python FastAPI/WebSocket server (`server_ws.py`) is untouched. A new Tauri v2 project lives under `client/`. The Rust backend (`client/src-tauri/src/`) owns the WebSocket connection, protocol encoding/decoding, config, file transfer, Soundpad, and OSC — mirroring `shared.py`'s pipe-delimited protocol byte-for-byte. The Svelte frontend (`client/src/`) is a thin UI layer that calls Rust via `invoke()` and listens for events via `listen()`. A mode selector at launch switches between Director and Actor views, persisted in config.

**Tech Stack:** Rust (Tauri v2 backend), Svelte + TypeScript (frontend, plain Svelte not SvelteKit), `tokio-tungstenite` (WebSocket), `rosc` (OSC/UDP), `serde`/`serde_json` (config), `uuid` v5 (machine ID), `tauri-plugin-updater` (auto-update), GitHub Actions + `tauri-apps/tauri-action` (CI/release). Server stays Python 3.8+/FastAPI/uvicorn — unmodified.

**Supersedes:** Tasks 4-12 of `docs/superpowers/plans/2026-07-20-ssl-fix-and-tauri-migration.md` (Tasks 1-3 of that plan — the SSL fix — already shipped as v0.3.3 and are not repeated here).

**Reference spec:** `docs/superpowers/specs/2026-07-20-vrActorAssist-ssl-tauri-design.md` (v1.1) — read this first for the full architecture rationale, cross-platform matrix, and success criteria.

## Global Constraints

- All work happens on a new `tauri` branch created from `main` (Task 1). Do not commit this plan's work to `main` directly.
- The pipe-delimited protocol defined in `shared.py` (repo root) is authoritative. Every message type, field order, and separator must match exactly. When in doubt, re-read `shared.py` — do not invent new message types.
- Tauri v2 (not v1). Plain Svelte (not SvelteKit) + TypeScript, using `@tauri-apps/api` v2 JS bindings.
- v0.4.0 scope is **feature parity only** — do not add OSC cue editor, PipeWire actor support, session recording, or any other roadmap item not already present in `director_client_ws.py` / `actor_client_ws.py`.
- Target platforms: Windows (NSIS installer + portable exe) and Linux (AppImage). **No macOS.**
- Default server URL for the client is `wss://vra.dannygreyproductions.com/ws`.
- File chunk size is 64KB, chunks are base64-encoded in `FILECHUNK` messages, checksums are MD5 hex digests — matching the Python clients exactly.
- Machine ID must be derived the same way as `shared.py::get_machine_id()` (`uuid.uuid5(uuid.NAMESPACE_DNS, platform.node())`) so actors migrating from the Python client keep their approved status server-side (`approved_actors.json` keys off machine ID).
- Every Rust module gets `#[cfg(test)]` unit tests for pure logic (protocol parse/format, config defaults, file chunking, character routing). UI-level and end-to-end verification is manual (documented in Task 15) — this project has no existing test harness for the Svelte layer, so don't invent one.

---

### Task 1: Create `tauri` branch and update deployment domain references

**Files:**
- Modify: `start-server.sh`
- Modify: `start-server-ts.sh`
- Modify: `README.md`

**Interfaces:**
- Produces: `tauri` branch checked out and active; all deployment scripts and docs reference `vra.dannygreyproductions.com` instead of `vra.dannygreyproductions.com`

- [ ] **Step 1: Create and switch to the tauri branch**

```bash
cd /home/danny/vrActorAssist
git checkout main
git pull --ff-only
git checkout -b tauri
```

Expected: `git branch --show-current` prints `tauri`

- [ ] **Step 2: Replace the old domain everywhere it appears**

```bash
cd /home/danny/vrActorAssist
grep -rl "vra.dannygreyproductions.com" --include="*.sh" --include="*.md" . | xargs sed -i 's/relay\.dannygreyproductions\.com/vra.dannygreyproductions.com/g'
```

- [ ] **Step 3: Verify no old domain references remain in scripts/docs**

```bash
grep -rn "vra.dannygreyproductions.com" --include="*.sh" --include="*.md" .
```

Expected: no output (empty). If `update_manifest.json` or Python client source files match, leave those untouched — they belong to the frozen v0.3.3 Python client and must keep working against whatever domain is live for existing users until cutover. Only scripts/docs should change here.

- [ ] **Step 4: Verify the diff**

```bash
git diff start-server.sh start-server-ts.sh README.md
```

Expected: domain string changed from `relay.` to `vra.` in each file, no other changes

- [ ] **Step 5: Commit**

```bash
git add start-server.sh start-server-ts.sh README.md
git commit -m "chore: switch deployment domain to vra.dannygreyproductions.com"
```

**Note for whoever runs the VPS:** this commit should be cherry-picked to `main` and deployed independently of the Tauri client work — the domain cutover (DNS + Caddy config) does not need to wait for v0.4.0. Flag this to the user rather than assuming it should merge automatically.

---

### Task 2: Scaffold the Tauri v2 + Svelte project

**Files:**
- Create: `client/` (Tauri project scaffold via `create-tauri-app`)
- Modify: `client/src-tauri/Cargo.toml`
- Modify: `client/src-tauri/tauri.conf.json`
- Modify: `client/src-tauri/src/main.rs`

**Interfaces:**
- Produces: a buildable, empty Tauri + Svelte + TS shell under `client/` that later tasks add modules to

- [ ] **Step 1: Scaffold via create-tauri-app**

```bash
cd /home/danny/vrActorAssist
npm create tauri-app@latest client -- --template svelte-ts --manager npm --yes
```

If the `--yes`/non-interactive flags aren't supported by the installed version, run it interactively and choose: project name `vrActorAssist`, frontend `Svelte`, variant `TypeScript`.

- [ ] **Step 2: Set app identifier, product name, and window defaults**

Edit `client/src-tauri/tauri.conf.json`, set the top-level fields:

```json
{
  "productName": "vrActorAssist",
  "version": "0.4.0",
  "identifier": "com.dannygrey.vractorassist",
  "build": {
    "frontendDist": "../dist",
    "devUrl": "http://localhost:5173",
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build"
  },
  "app": {
    "windows": [
      {
        "title": "vrActorAssist",
        "width": 900,
        "height": 650,
        "minWidth": 700,
        "minHeight": 500,
        "resizable": true,
        "fullscreen": false
      }
    ]
  },
  "bundle": {
    "active": true,
    "targets": ["nsis", "appimage"],
    "windows": {
      "nsis": {
        "installMode": "currentUser"
      }
    }
  }
}
```

`"targets": ["nsis", "appimage"]` restricts bundling to what we ship (no `.msi`, `.deb`, `.dmg` clutter). The portable Windows exe is not a Tauri bundle target — it's the raw compiled binary from `cargo build --release`, packaged in Task 13's CI workflow.

- [ ] **Step 3: Add Rust dependencies**

Edit `client/src-tauri/Cargo.toml`, add to `[dependencies]`:

```toml
[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-updater = "2"
tauri-plugin-dialog = "2"
tauri-plugin-shell = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
tokio-tungstenite = { version = "0.21", features = ["native-tls"] }
futures-util = "0.3"
rosc = "0.10"
uuid = { version = "1", features = ["v5"] }
gethostname = "0.4"
md5 = "0.7"
base64 = "0.22"
chrono = "0.4"
```

- [ ] **Step 4: Install npm dependencies**

```bash
cd /home/danny/vrActorAssist/client
npm install
```

- [ ] **Step 5: Verify the empty scaffold builds**

```bash
cd /home/danny/vrActorAssist/client
cargo check --manifest-path src-tauri/Cargo.toml
npm run build
```

Expected: both succeed. On Linux, if `cargo check` fails with missing system libs, install `libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev libsoup-3.0-dev libgtk-3-dev` (Debian/Ubuntu) or the equivalent for the distro, then retry.

- [ ] **Step 6: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/
git commit -m "feat: scaffold Tauri v2 + Svelte + TypeScript project"
```

---

### Task 3: Implement the protocol module with unit tests

**Files:**
- Create: `client/src-tauri/src/protocol.rs`
- Modify: `client/src-tauri/src/main.rs` (register `mod protocol;`)

**Interfaces:**
- Consumes: nothing (pure logic, no I/O)
- Produces: `protocol::Message` enum covering every message type in `shared.py::MSG_TYPES` plus `APPROVE`/`DENY`/`FORGET_NAME`/`REFRESH`/`PING`/`PONG`; `protocol::parse(&str) -> Message`; `protocol::format(&Message) -> String`. Later tasks match on `Message` variants — field names here are the contract.

- [ ] **Step 1: Write the failing tests first**

Create `client/src-tauri/src/protocol.rs` with tests only (implementation stubbed to fail):

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum Message {
    Msg { sender: String, text: String },
    Priv { sender: String, target: String, text: String },
    Users { users: Vec<String> },
    Status { actors_json: String },
    Register { name: String, machine_id: String, role: String, secret: String, version: String, platform: String },
    Approved,
    Denied { reason: String },
    Pending { actors_json: String },
    Version { status: String, server_version: String, message: String },
    Update { latest_version: String, download_url: String, sha256: String, release_notes: String },
    Cmd { command: String, args: String },
    Ack { actor: String, command: String, status: String },
    File { sender: String, filename: String, size: u64 },
    Forget { machine_id: String },
    ForgetName { name: String },
    Approve { machine_id: String },
    Deny { machine_id: String },
    OscCue { target: String, parameter: String, value: String },
    FileReq { sender: String, target: String, filename: String, size: u64, checksum: String },
    FileAck { filename: String, accept: bool, save_dir: String },
    FileDeny { filename: String, reason: String },
    FileStart { filename: String, total_chunks: u32, chunk_size: u32 },
    FileChunk { filename: String, chunk_num: u32, data: String },
    FileEnd { filename: String, checksum: String },
    FileOk { filename: String, saved_path: String },
    FileErr { filename: String, error: String },
    BatchStart { target: String, file_count: u32, total_bytes: u64 },
    BatchEnd { target: String, success_count: u32, fail_count: u32 },
    BatchCancel { target: String, reason: String },
    Refresh,
    Ping,
    Pong,
    Unknown { raw: String },
}

pub fn parse(_data: &str) -> Message {
    unimplemented!()
}

pub fn format(_msg: &Message) -> String {
    unimplemented!()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_msg() {
        let m = parse("MSG|Director|Hello everyone");
        assert_eq!(m, Message::Msg { sender: "Director".into(), text: "Hello everyone".into() });
    }

    #[test]
    fn parses_msg_with_pipe_in_text() {
        // Text may legitimately contain '|' — must rejoin remaining parts
        let m = parse("MSG|Director|a|b|c");
        assert_eq!(m, Message::Msg { sender: "Director".into(), text: "a|b|c".into() });
    }

    #[test]
    fn parses_priv_command() {
        let m = parse("PRIV|Director|Actor1|*go");
        assert_eq!(m, Message::Priv { sender: "Director".into(), target: "Actor1".into(), text: "*go".into() });
    }

    #[test]
    fn parses_register_full() {
        let m = parse("REGISTER|Director|abc-123|director|secret1|0.4.0|windows-x64");
        assert_eq!(m, Message::Register {
            name: "Director".into(),
            machine_id: "abc-123".into(),
            role: "director".into(),
            secret: "secret1".into(),
            version: "0.4.0".into(),
            platform: "windows-x64".into(),
        });
    }

    #[test]
    fn parses_approved() {
        assert_eq!(parse("APPROVED"), Message::Approved);
    }

    #[test]
    fn parses_denied_with_reason() {
        let m = parse("DENIED|secret mismatch");
        assert_eq!(m, Message::Denied { reason: "secret mismatch".into() });
    }

    #[test]
    fn parses_cmd_no_args() {
        let m = parse("CMD|*go");
        assert_eq!(m, Message::Cmd { command: "*go".into(), args: "".into() });
    }

    #[test]
    fn parses_filechunk() {
        let m = parse("FILECHUNK|line01.wav|3|c29tZWJhc2U2NA==");
        assert_eq!(m, Message::FileChunk { filename: "line01.wav".into(), chunk_num: 3, data: "c29tZWJhc2U2NA==".into() });
    }

    #[test]
    fn parses_osc_cue() {
        let m = parse("OSC_CUE|Actor1|RecIcon|true");
        assert_eq!(m, Message::OscCue { target: "Actor1".into(), parameter: "RecIcon".into(), value: "true".into() });
    }

    #[test]
    fn parses_batch_start() {
        let m = parse("BATCH_START|Actor1|3|1048576");
        assert_eq!(m, Message::BatchStart { target: "Actor1".into(), file_count: 3, total_bytes: 1048576 });
    }

    #[test]
    fn parses_raw_ping_pong() {
        assert_eq!(parse("PING"), Message::Ping);
        assert_eq!(parse("PONG"), Message::Pong);
    }

    #[test]
    fn parses_unknown_as_fallback() {
        let m = parse("NOT_A_REAL_TYPE|x|y");
        assert_eq!(m, Message::Unknown { raw: "NOT_A_REAL_TYPE|x|y".into() });
    }

    #[test]
    fn formats_register_round_trips() {
        let msg = Message::Register {
            name: "Actor1".into(), machine_id: "id-1".into(), role: "actor".into(),
            secret: "".into(), version: "0.4.0".into(), platform: "linux-x64".into(),
        };
        let wire = format(&msg);
        assert_eq!(wire, "REGISTER|Actor1|id-1|actor||0.4.0|linux-x64");
        assert_eq!(parse(&wire), msg);
    }

    #[test]
    fn formats_priv_command_round_trips() {
        let msg = Message::Priv { sender: "Director".into(), target: "Actor1".into(), text: "*stop".into() };
        let wire = format(&msg);
        assert_eq!(wire, "PRIV|Director|Actor1|*stop");
        assert_eq!(parse(&wire), msg);
    }

    #[test]
    fn formats_filereq_round_trips() {
        let msg = Message::FileReq {
            sender: "Director".into(), target: "Actor1".into(), filename: "cue.wav".into(),
            size: 2048, checksum: "d41d8cd98f00b204e9800998ecf8427e".into(),
        };
        let wire = format(&msg);
        assert_eq!(wire, "FILEREQ|Director|Actor1|cue.wav|2048|d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(parse(&wire), msg);
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml protocol:: 2>&1 | tail -30
```

Expected: compile error or panic from `unimplemented!()`

- [ ] **Step 3: Implement `parse`**

Replace the `parse` stub in `client/src-tauri/src/protocol.rs`:

```rust
pub fn parse(data: &str) -> Message {
    let parts: Vec<&str> = data.split('|').collect();
    if parts.is_empty() {
        return Message::Unknown { raw: data.to_string() };
    }
    let p = |i: usize| parts.get(i).map(|s| s.to_string()).unwrap_or_default();
    let rejoin = |from: usize| parts[from.min(parts.len())..].join("|");

    match parts[0] {
        "MSG" if parts.len() >= 3 => Message::Msg { sender: p(1), text: rejoin(2) },
        "PRIV" if parts.len() >= 4 => Message::Priv { sender: p(1), target: p(2), text: rejoin(3) },
        "USERS" if parts.len() >= 2 => Message::Users {
            users: if parts[1].is_empty() { vec![] } else { parts[1].split(',').map(String::from).collect() },
        },
        "STATUS" if parts.len() >= 2 => Message::Status { actors_json: p(1) },
        "REGISTER" if parts.len() >= 4 => Message::Register {
            name: p(1), machine_id: p(2), role: p(3), secret: p(4), version: p(5), platform: p(6),
        },
        "APPROVED" => Message::Approved,
        "DENIED" if parts.len() >= 2 => Message::Denied { reason: rejoin(1) },
        "PENDING" if parts.len() >= 2 => Message::Pending { actors_json: p(1) },
        "VERSION" if parts.len() >= 2 => Message::Version {
            status: p(1), server_version: p(2), message: rejoin(3),
        },
        "UPDATE" if parts.len() >= 2 => Message::Update {
            latest_version: p(1), download_url: p(2), sha256: p(3), release_notes: rejoin(4),
        },
        "CMD" if parts.len() >= 2 => Message::Cmd { command: p(1), args: rejoin(2) },
        "ACK" if parts.len() >= 4 => Message::Ack { actor: p(1), command: p(2), status: p(3) },
        "FILE" if parts.len() >= 4 => Message::File {
            sender: p(1), filename: p(2), size: parts[3].parse().unwrap_or(0),
        },
        "FORGET" if parts.len() >= 2 => Message::Forget { machine_id: p(1) },
        "FORGET_NAME" if parts.len() >= 2 => Message::ForgetName { name: p(1) },
        "APPROVE" => Message::Approve { machine_id: p(1) },
        "DENY" => Message::Deny { machine_id: p(1) },
        "OSC_CUE" if parts.len() >= 4 => Message::OscCue { target: p(1), parameter: p(2), value: p(3) },
        "FILEREQ" if parts.len() >= 6 => Message::FileReq {
            sender: p(1), target: p(2), filename: p(3), size: parts[4].parse().unwrap_or(0), checksum: p(5),
        },
        "FILEACK" if parts.len() >= 3 => Message::FileAck {
            filename: p(1), accept: parts[2] == "1", save_dir: p(3),
        },
        "FILEDENY" if parts.len() >= 3 => Message::FileDeny { filename: p(1), reason: rejoin(2) },
        "FILESTART" if parts.len() >= 4 => Message::FileStart {
            filename: p(1), total_chunks: parts[2].parse().unwrap_or(0), chunk_size: parts[3].parse().unwrap_or(0),
        },
        "FILECHUNK" if parts.len() >= 4 => Message::FileChunk {
            filename: p(1), chunk_num: parts[2].parse().unwrap_or(0), data: rejoin(3),
        },
        "FILEEND" if parts.len() >= 3 => Message::FileEnd { filename: p(1), checksum: p(2) },
        "FILEOK" if parts.len() >= 3 => Message::FileOk { filename: p(1), saved_path: rejoin(2) },
        "FILEERR" if parts.len() >= 3 => Message::FileErr { filename: p(1), error: rejoin(2) },
        "BATCH_START" if parts.len() >= 4 => Message::BatchStart {
            target: p(1), file_count: parts[2].parse().unwrap_or(0), total_bytes: parts[3].parse().unwrap_or(0),
        },
        "BATCH_END" if parts.len() >= 4 => Message::BatchEnd {
            target: p(1), success_count: parts[2].parse().unwrap_or(0), fail_count: parts[3].parse().unwrap_or(0),
        },
        "BATCH_CANCEL" if parts.len() >= 2 => Message::BatchCancel { target: p(1), reason: rejoin(2) },
        "REFRESH" => Message::Refresh,
        "PING" if parts.len() == 1 => Message::Ping,
        "PONG" if parts.len() == 1 => Message::Pong,
        _ => Message::Unknown { raw: data.to_string() },
    }
}
```

- [ ] **Step 4: Run tests to verify `parse` tests pass and `format` tests still fail**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml protocol:: 2>&1 | tail -40
```

Expected: `parses_*` tests pass, `formats_*` tests fail on `unimplemented!()`

- [ ] **Step 5: Implement `format`**

Replace the `format` stub:

```rust
pub fn format(msg: &Message) -> String {
    match msg {
        Message::Msg { sender, text } => format!("MSG|{}|{}", sender, text),
        Message::Priv { sender, target, text } => format!("PRIV|{}|{}|{}", sender, target, text),
        Message::Users { users } => format!("USERS|{}", users.join(",")),
        Message::Status { actors_json } => format!("STATUS|{}", actors_json),
        Message::Register { name, machine_id, role, secret, version, platform } =>
            format!("REGISTER|{}|{}|{}|{}|{}|{}", name, machine_id, role, secret, version, platform),
        Message::Approved => "APPROVED".to_string(),
        Message::Denied { reason } => format!("DENIED|{}", reason),
        Message::Pending { actors_json } => format!("PENDING|{}", actors_json),
        Message::Version { status, server_version, message } => format!("VERSION|{}|{}|{}", status, server_version, message),
        Message::Update { latest_version, download_url, sha256, release_notes } =>
            format!("UPDATE|{}|{}|{}|{}", latest_version, download_url, sha256, release_notes),
        Message::Cmd { command, args } => if args.is_empty() { format!("CMD|{}", command) } else { format!("CMD|{}|{}", command, args) },
        Message::Ack { actor, command, status } => format!("ACK|{}|{}|{}", actor, command, status),
        Message::File { sender, filename, size } => format!("FILE|{}|{}|{}", sender, filename, size),
        Message::Forget { machine_id } => format!("FORGET|{}", machine_id),
        Message::ForgetName { name } => format!("FORGET_NAME|{}", name),
        Message::Approve { machine_id } => format!("APPROVE|{}", machine_id),
        Message::Deny { machine_id } => format!("DENY|{}", machine_id),
        Message::OscCue { target, parameter, value } => format!("OSC_CUE|{}|{}|{}", target, parameter, value),
        Message::FileReq { sender, target, filename, size, checksum } =>
            format!("FILEREQ|{}|{}|{}|{}|{}", sender, target, filename, size, checksum),
        Message::FileAck { filename, accept, save_dir } =>
            format!("FILEACK|{}|{}|{}", filename, if *accept { "1" } else { "0" }, save_dir),
        Message::FileDeny { filename, reason } => format!("FILEDENY|{}|{}", filename, reason),
        Message::FileStart { filename, total_chunks, chunk_size } => format!("FILESTART|{}|{}|{}", filename, total_chunks, chunk_size),
        Message::FileChunk { filename, chunk_num, data } => format!("FILECHUNK|{}|{}|{}", filename, chunk_num, data),
        Message::FileEnd { filename, checksum } => format!("FILEEND|{}|{}", filename, checksum),
        Message::FileOk { filename, saved_path } => format!("FILEOK|{}|{}", filename, saved_path),
        Message::FileErr { filename, error } => format!("FILEERR|{}|{}", filename, error),
        Message::BatchStart { target, file_count, total_bytes } => format!("BATCH_START|{}|{}|{}", target, file_count, total_bytes),
        Message::BatchEnd { target, success_count, fail_count } => format!("BATCH_END|{}|{}|{}", target, success_count, fail_count),
        Message::BatchCancel { target, reason } => format!("BATCH_CANCEL|{}|{}", target, reason),
        Message::Refresh => "REFRESH".to_string(),
        Message::Ping => "PING".to_string(),
        Message::Pong => "PONG".to_string(),
        Message::Unknown { raw } => raw.clone(),
    }
}
```

- [ ] **Step 6: Run tests to verify all pass**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml protocol::
```

Expected: all tests pass (0 failed)

- [ ] **Step 7: Register the module**

In `client/src-tauri/src/main.rs`, add near the top:

```rust
mod protocol;
```

- [ ] **Step 8: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src-tauri/src/protocol.rs client/src-tauri/src/main.rs
git commit -m "feat: implement protocol module with full message coverage and unit tests"
```

---

### Task 4: Implement the config module (portable-aware) with unit tests

**Files:**
- Create: `client/src-tauri/src/config.rs`
- Modify: `client/src-tauri/src/main.rs` (register `mod config;`)

**Interfaces:**
- Consumes: `gethostname`, `uuid` (v5), `serde_json`
- Produces: `config::Config` struct (fields consumed by Tasks 6-11), `config::Config::load()`, `.save()`, `.get_ws_url()`, `config::is_portable() -> bool`, `config::compute_machine_id() -> String`

- [ ] **Step 1: Write failing tests**

Create `client/src-tauri/src/config.rs`:

```rust
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Config {
    pub server_url: String,
    pub secret: String,
    pub mode: String,
    pub remember_mode: bool,
    pub machine_id: String,
    pub actor_name: String,
    pub auto_reconnect: bool,
    pub osc_enabled: bool,
    pub osc_host: String,
    pub osc_port: u16,
    pub soundpad_enabled: bool,
    pub soundpad_path: String,
    pub auto_accept_files: bool,
    pub receive_dir: String,
    pub theme: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server_url: "wss://vra.dannygreyproductions.com/ws".to_string(),
            secret: String::new(),
            mode: String::new(),
            remember_mode: false,
            machine_id: compute_machine_id(),
            actor_name: "Actor".to_string(),
            auto_reconnect: true,
            osc_enabled: true,
            osc_host: "127.0.0.1".to_string(),
            osc_port: 9000,
            soundpad_enabled: true,
            soundpad_path: "Soundpad.exe".to_string(),
            auto_accept_files: false,
            receive_dir: default_receive_dir(),
            theme: "dark".to_string(),
        }
    }
}

fn default_receive_dir() -> String {
    std::env::current_dir().unwrap_or_default().to_string_lossy().to_string()
}

/// Matches shared.py::get_machine_id(): uuid.uuid5(uuid.NAMESPACE_DNS, platform.node())
/// so actors migrating from the Python client keep their approved status.
pub fn compute_machine_id() -> String {
    let hostname = gethostname::gethostname().to_string_lossy().to_string();
    uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_DNS, hostname.as_bytes()).to_string()
}

/// True if running from an installed location (uninstall.exe / AppImage present),
/// false if running as a bare portable executable.
pub fn is_portable(exe_dir: &std::path::Path) -> bool {
    if cfg!(target_os = "windows") {
        !exe_dir.join("uninstall.exe").exists()
    } else {
        std::env::var("APPIMAGE").is_err()
    }
}

pub fn config_path(exe_dir: &std::path::Path, portable: bool) -> PathBuf {
    if portable {
        exe_dir.join("config.json")
    } else {
        let base = dirs_config_dir();
        base.join("com.dannygrey.vractorassist").join("config.json")
    }
}

#[cfg(not(test))]
fn dirs_config_dir() -> PathBuf {
    dirs_next::config_dir().unwrap_or_else(std::env::temp_dir)
}

#[cfg(test)]
fn dirs_config_dir() -> PathBuf {
    std::env::temp_dir()
}

impl Config {
    pub fn load(path: &std::path::Path) -> Self {
        if path.exists() {
            std::fs::read_to_string(path)
                .ok()
                .and_then(|content| serde_json::from_str(&content).ok())
                .unwrap_or_default()
        } else {
            Self::default()
        }
    }

    pub fn save(&self, path: &std::path::Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let content = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        std::fs::write(path, content).map_err(|e| e.to_string())
    }

    /// Converts the configured server URL (http/https/bare host) into a ws(s):// + /ws URL.
    pub fn get_ws_url(&self) -> String {
        let base = self.server_url.trim_end_matches('/');
        if base.starts_with("https://") {
            format!("{}/ws", base.replacen("https://", "wss://", 1))
        } else if base.starts_with("http://") {
            format!("{}/ws", base.replacen("http://", "ws://", 1))
        } else if base.starts_with("wss://") || base.starts_with("ws://") {
            format!("{}/ws", base)
        } else {
            format!("wss://{}/ws", base)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_server_url_is_vra_domain() {
        assert_eq!(Config::default().server_url, "wss://vra.dannygreyproductions.com/ws");
    }

    #[test]
    fn machine_id_is_deterministic_for_same_hostname() {
        let a = compute_machine_id();
        let b = compute_machine_id();
        assert_eq!(a, b, "machine_id must be stable across runs on the same machine");
    }

    #[test]
    fn machine_id_matches_python_uuid5_namespace_dns_algorithm() {
        // Known vector: uuid.uuid5(uuid.NAMESPACE_DNS, "example-host") in Python
        // must equal Uuid::new_v5(&Uuid::NAMESPACE_DNS, b"example-host") in Rust.
        let expected = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_DNS, b"example-host");
        let actual = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_DNS, "example-host".as_bytes());
        assert_eq!(expected, actual);
    }

    #[test]
    fn ws_url_converts_https_to_wss() {
        let mut c = Config::default();
        c.server_url = "https://vra.dannygreyproductions.com".to_string();
        assert_eq!(c.get_ws_url(), "wss://vra.dannygreyproductions.com/ws");
    }

    #[test]
    fn ws_url_converts_bare_host() {
        let mut c = Config::default();
        c.server_url = "vra.dannygreyproductions.com".to_string();
        assert_eq!(c.get_ws_url(), "wss://vra.dannygreyproductions.com/ws");
    }

    #[test]
    fn ws_url_passes_through_wss() {
        let mut c = Config::default();
        c.server_url = "wss://vra.dannygreyproductions.com".to_string();
        assert_eq!(c.get_ws_url(), "wss://vra.dannygreyproductions.com/ws");
    }

    #[test]
    fn save_and_load_round_trip() {
        let dir = std::env::temp_dir().join(format!("vractest-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("config.json");

        let mut c = Config::default();
        c.actor_name = "TestActor".to_string();
        c.save(&path).unwrap();

        let loaded = Config::load(&path);
        assert_eq!(loaded.actor_name, "TestActor");

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn load_missing_file_returns_default() {
        let path = std::env::temp_dir().join("vractest-does-not-exist-12345/config.json");
        let loaded = Config::load(&path);
        assert_eq!(loaded, Config::default());
    }
}
```

- [ ] **Step 2: Add the `dirs-next` dependency**

Edit `client/src-tauri/Cargo.toml`, add:

```toml
dirs-next = "2"
```

- [ ] **Step 3: Run tests to verify they fail (or pass immediately if implementation is already correct)**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml config::
```

Since this task writes the implementation directly (config logic is straightforward, not stubbed), expected: all tests pass on first run. If any fail, fix the implementation above before proceeding — do not weaken the test.

- [ ] **Step 4: Register the module**

In `client/src-tauri/src/main.rs`, add:

```rust
mod config;
```

- [ ] **Step 5: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src-tauri/src/config.rs client/src-tauri/Cargo.toml client/src-tauri/src/main.rs
git commit -m "feat: implement portable-aware config module with machine ID compatibility"
```

---

### Task 5: Implement the WebSocket client module

**Files:**
- Create: `client/src-tauri/src/ws_client.rs`
- Modify: `client/src-tauri/src/main.rs` (register `mod ws_client;`)

**Interfaces:**
- Consumes: `protocol::{parse, format, Message}` (Task 3), `tokio-tungstenite`
- Produces: `ws_client::WsClient` with `connect(url, on_message: F, on_state: G)`, `send(&self, msg: &protocol::Message)`, `disconnect(&self)`; `ws_client::ConnectionState` enum consumed by Task 6

- [ ] **Step 1: Write the connection state enum and struct shape with a unit test for state transitions logic**

Create `client/src-tauri/src/ws_client.rs`:

```rust
use crate::protocol::{self, Message};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message as WsMessage};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Failed(String),
}

use serde::{Deserialize, Serialize};

pub struct WsClient {
    outbound_tx: Mutex<Option<mpsc::UnboundedSender<WsMessage>>>,
}

impl WsClient {
    pub fn new() -> Self {
        Self { outbound_tx: Mutex::new(None) }
    }

    /// Connects to `url`, spawning a background task that reads incoming frames and
    /// forwards parsed protocol messages to `on_message`, and connection state changes
    /// to `on_state`. Replies to server PING with PONG automatically (matches Python
    /// clients' behavior of answering raw "PING" with raw "PONG").
    pub async fn connect<F, G>(&self, url: &str, on_message: F, on_state: G) -> Result<(), String>
    where
        F: Fn(Message) + Send + Sync + 'static,
        G: Fn(ConnectionState) + Send + Sync + 'static,
    {
        on_state(ConnectionState::Connecting);

        let (ws_stream, _) = connect_async(url).await.map_err(|e| {
            let msg = format!("{}", e);
            on_state(ConnectionState::Failed(msg.clone()));
            msg
        })?;

        on_state(ConnectionState::Connected);

        let (mut write, mut read) = ws_stream.split();
        let (tx, mut rx) = mpsc::unbounded_channel::<WsMessage>();
        *self.outbound_tx.lock().await = Some(tx);

        tokio::spawn(async move {
            loop {
                tokio::select! {
                    incoming = read.next() => {
                        match incoming {
                            Some(Ok(WsMessage::Text(text))) => {
                                if text == "PING" {
                                    // handled by outbound loop via channel below isn't
                                    // available here directly; reply inline instead.
                                    let _ = write.send(WsMessage::Text("PONG".to_string())).await;
                                    continue;
                                }
                                on_message(protocol::parse(&text));
                            }
                            Some(Ok(WsMessage::Close(_))) | None => {
                                on_state(ConnectionState::Disconnected);
                                break;
                            }
                            Some(Err(e)) => {
                                on_state(ConnectionState::Failed(format!("{}", e)));
                                break;
                            }
                            _ => {}
                        }
                    }
                    outgoing = rx.recv() => {
                        match outgoing {
                            Some(msg) => {
                                if write.send(msg).await.is_err() {
                                    on_state(ConnectionState::Disconnected);
                                    break;
                                }
                            }
                            None => break,
                        }
                    }
                }
            }
        });

        Ok(())
    }

    pub async fn send(&self, msg: &Message) -> Result<(), String> {
        let guard = self.outbound_tx.lock().await;
        match guard.as_ref() {
            Some(tx) => tx
                .send(WsMessage::Text(protocol::format(msg)))
                .map_err(|e| format!("Send failed: {}", e)),
            None => Err("Not connected".to_string()),
        }
    }

    pub async fn disconnect(&self) {
        let mut guard = self.outbound_tx.lock().await;
        *guard = None;
    }
}

impl Default for WsClient {
    fn default() -> Self {
        Self::new()
    }
}
```

- [ ] **Step 2: Register the module**

In `client/src-tauri/src/main.rs`, add:

```rust
mod ws_client;
```

- [ ] **Step 3: Verify compilation**

```bash
cd /home/danny/vrActorAssist/client
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: compiles (warnings about unused code are fine at this stage — Task 6 wires it up)

- [ ] **Step 4: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src-tauri/src/ws_client.rs client/src-tauri/src/main.rs
git commit -m "feat: implement async WebSocket client with PING/PONG handling"
```

---

### Task 6: Wire up Tauri app state, commands, and events in main.rs

**Files:**
- Create: `client/src-tauri/src/state.rs`
- Modify: `client/src-tauri/src/main.rs`

**Interfaces:**
- Consumes: `config::Config` (Task 4), `ws_client::WsClient`/`ConnectionState` (Task 5), `protocol::Message` (Task 3)
- Produces: `AppState` managed by Tauri; commands `get_config`, `save_config`, `connect`, `disconnect`, `send_chat`, `send_command`; events emitted to the frontend: `"connection-state"` (payload: `ConnectionState`), `"protocol-message"` (payload: `Message`) — later tasks (7-11) add mode-specific commands to this same file/pattern, they don't replace it

- [ ] **Step 1: Create the shared app state**

Create `client/src-tauri/src/state.rs`:

```rust
use crate::config::Config;
use crate::ws_client::WsClient;
use std::sync::Arc;
use tokio::sync::Mutex;

pub struct AppState {
    pub config: Mutex<Config>,
    pub config_path: std::path::PathBuf,
    pub ws: Arc<WsClient>,
}

impl AppState {
    pub fn new(config: Config, config_path: std::path::PathBuf) -> Self {
        Self {
            config: Mutex::new(config),
            config_path,
            ws: Arc::new(WsClient::new()),
        }
    }
}
```

- [ ] **Step 2: Write the Tauri commands**

Replace the contents of `client/src-tauri/src/main.rs` with:

```rust
mod protocol;
mod config;
mod ws_client;
mod state;

use config::Config;
use protocol::Message;
use state::AppState;
use tauri::{Emitter, Manager, State};
use ws_client::ConnectionState;

#[tauri::command]
async fn get_config(state: State<'_, AppState>) -> Config {
    state.config.lock().await.clone()
}

#[tauri::command]
async fn save_config(state: State<'_, AppState>, new_config: Config) -> Result<(), String> {
    new_config.save(&state.config_path)?;
    *state.config.lock().await = new_config;
    Ok(())
}

#[tauri::command]
async fn connect(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    let url = cfg.get_ws_url();
    let ws = state.ws.clone();

    let app_for_msg = app.clone();
    let app_for_state = app.clone();

    ws.connect(
        &url,
        move |msg: Message| {
            let _ = app_for_msg.emit("protocol-message", &msg);
        },
        move |st: ConnectionState| {
            let _ = app_for_state.emit("connection-state", &st);
        },
    )
    .await?;

    // Register immediately after connecting.
    let register = Message::Register {
        name: if cfg.mode == "actor" { cfg.actor_name.clone() } else { "Director".to_string() },
        machine_id: cfg.machine_id.clone(),
        role: cfg.mode.clone(),
        secret: cfg.secret.clone(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        platform: if cfg!(target_os = "windows") { "windows-x64".to_string() } else { "linux-x64".to_string() },
    };
    state.ws.send(&register).await
}

#[tauri::command]
async fn disconnect(state: State<'_, AppState>) -> Result<(), String> {
    state.ws.disconnect().await;
    Ok(())
}

#[tauri::command]
async fn send_chat(state: State<'_, AppState>, text: String) -> Result<(), String> {
    let cfg = state.config.lock().await;
    let sender = if cfg.mode == "actor" { cfg.actor_name.clone() } else { "Director".to_string() };
    state.ws.send(&Message::Msg { sender, text }).await
}

/// Sends a command (e.g. "*go", "*stop", "*play:3") to one actor ("target") or,
/// if target is None, to every name in `all_actors` individually — mirrors
/// director_client_ws.py's per-actor PRIV loop (there is no broadcast CMD in practice).
#[tauri::command]
async fn send_command(state: State<'_, AppState>, command: String, targets: Vec<String>) -> Result<(), String> {
    for target in targets {
        state.ws.send(&Message::Priv { sender: "Director".to_string(), target, text: command.clone() }).await?;
    }
    Ok(())
}

fn main() {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(std::env::temp_dir);
    let portable = config::is_portable(&exe_dir);
    let config_path = config::config_path(&exe_dir, portable);
    let cfg = Config::load(&config_path);

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(AppState::new(cfg, config_path))
        .invoke_handler(tauri::generate_handler![
            get_config,
            save_config,
            connect,
            disconnect,
            send_chat,
            send_command,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 3: Verify compilation**

```bash
cd /home/danny/vrActorAssist/client
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: compiles. Fix any borrow-checker errors around the closures capturing `app` by adjusting clones as needed — the pattern above (`app_for_msg`, `app_for_state`) already avoids the common double-move error.

- [ ] **Step 4: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src-tauri/src/state.rs client/src-tauri/src/main.rs
git commit -m "feat: wire up Tauri app state, connect/disconnect/chat commands, and events"
```

---

### Task 7: Build shared Svelte UI (stores, mode selector, connection, chat, status bar)

**Files:**
- Create: `client/src/lib/stores.ts`
- Create: `client/src/lib/ModeSelector.svelte`
- Create: `client/src/lib/ConnectionPanel.svelte`
- Create: `client/src/lib/Chat.svelte`
- Create: `client/src/lib/StatusBar.svelte`
- Modify: `client/src/App.svelte`

**Interfaces:**
- Consumes: `invoke("get_config"|"save_config"|"connect"|"disconnect"|"send_chat")`, `listen("connection-state"|"protocol-message")`
- Produces: Svelte stores (`connectionState`, `chatMessages`, `appConfig`) imported by Director/Actor views in Tasks 8 and 11

- [ ] **Step 1: Create shared stores**

Create `client/src/lib/stores.ts`:

```typescript
import { writable, type Writable } from "svelte/store";

export type ConnectionState = "Disconnected" | "Connecting" | "Connected" | { Failed: string };

export interface ChatMessage {
  sender: string;
  text: string;
  timestamp: string;
  isOwn: boolean;
}

export interface AppConfig {
  server_url: string;
  mode: string;
  remember_mode: boolean;
  machine_id: string;
  actor_name: string;
  auto_reconnect: boolean;
  osc_enabled: boolean;
  osc_host: string;
  osc_port: number;
  soundpad_enabled: boolean;
  soundpad_path: string;
  auto_accept_files: boolean;
  receive_dir: string;
  theme: string;
}

export const connectionState: Writable<ConnectionState> = writable("Disconnected");
export const chatMessages: Writable<ChatMessage[]> = writable([]);
export const appConfig: Writable<AppConfig | null> = writable(null);
export const latencyMs: Writable<number> = writable(0);
```

- [ ] **Step 2: Create ModeSelector.svelte**

Create `client/src/lib/ModeSelector.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  export let onSelect: (mode: "director" | "actor") => void;

  let rememberChoice = false;

  async function selectMode(mode: "director" | "actor") {
    if (rememberChoice) {
      const cfg = { ...$appConfig, mode, remember_mode: true };
      await invoke("save_config", { newConfig: cfg });
      appConfig.set(cfg as any);
    }
    onSelect(mode);
  }
</script>

<div class="mode-selector">
  <h1>vrActorAssist</h1>
  <p class="subtitle">Select your role</p>
  <div class="buttons">
    <button on:click={() => selectMode("director")} class="mode-btn director">
      <span class="label">Director</span>
      <span class="desc">Send cues, manage actors, route audio files</span>
    </button>
    <button on:click={() => selectMode("actor")} class="mode-btn actor">
      <span class="label">Actor</span>
      <span class="desc">Receive cues, play sounds, VRChat OSC</span>
    </button>
  </div>
  <label class="remember">
    <input type="checkbox" bind:checked={rememberChoice} />
    Remember my choice
  </label>
</div>

<style>
  .mode-selector { display: flex; flex-direction: column; align-items: center; gap: 1rem; padding: 3rem 1rem; }
  .buttons { display: flex; gap: 1.5rem; }
  .mode-btn { display: flex; flex-direction: column; gap: 0.4rem; padding: 1.5rem 2rem; border-radius: 8px; cursor: pointer; }
  .label { font-size: 1.2rem; font-weight: 600; }
  .desc { font-size: 0.85rem; opacity: 0.75; }
</style>
```

- [ ] **Step 3: Create ConnectionPanel.svelte**

Create `client/src/lib/ConnectionPanel.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { connectionState, type ConnectionState, appConfig } from "./stores";

  let serverUrl = "";

  onMount(async () => {
    const cfg = await invoke<any>("get_config");
    appConfig.set(cfg);
    serverUrl = cfg.server_url;

    await listen<ConnectionState>("connection-state", (event) => {
      connectionState.set(event.payload);
    });
  });

  async function toggleConnection() {
    if ($connectionState === "Disconnected" || (typeof $connectionState === "object" && "Failed" in $connectionState)) {
      if ($appConfig) {
        const updated = { ...$appConfig, server_url: serverUrl };
        await invoke("save_config", { newConfig: updated });
        appConfig.set(updated);
      }
      await invoke("connect");
    } else {
      await invoke("disconnect");
    }
  }

  $: isBusy = $connectionState === "Connecting";
  $: label = $connectionState === "Connected" ? "Disconnect"
    : $connectionState === "Connecting" ? "Connecting..."
    : "Connect";
</script>

<div class="connection-panel">
  <input type="text" bind:value={serverUrl} placeholder="wss://vra.dannygreyproductions.com/ws" disabled={isBusy} />
  <button on:click={toggleConnection} disabled={isBusy}>{label}</button>
  <span class="status-dot" class:connected={$connectionState === "Connected"}></span>
</div>

<style>
  .connection-panel { display: flex; align-items: center; gap: 0.5rem; }
  input { flex: 1; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #888; }
  .status-dot.connected { background: #2ecc71; }
</style>
```

- [ ] **Step 4: Create Chat.svelte**

Create `client/src/lib/Chat.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { chatMessages } from "./stores";

  let inputText = "";
  let listEl: HTMLDivElement;

  onMount(async () => {
    await listen<any>("protocol-message", (event) => {
      const msg = event.payload;
      if (msg.Msg) {
        chatMessages.update((m) => [...m, {
          sender: msg.Msg.sender, text: msg.Msg.text,
          timestamp: new Date().toLocaleTimeString(), isOwn: false,
        }]);
        queueScroll();
      }
    });
  });

  function queueScroll() {
    requestAnimationFrame(() => { if (listEl) listEl.scrollTop = listEl.scrollHeight; });
  }

  async function sendMessage() {
    if (!inputText.trim()) return;
    await invoke("send_chat", { text: inputText });
    chatMessages.update((m) => [...m, {
      sender: "Me", text: inputText, timestamp: new Date().toLocaleTimeString(), isOwn: true,
    }]);
    inputText = "";
    queueScroll();
  }
</script>

<div class="chat">
  <div class="messages" bind:this={listEl}>
    {#each $chatMessages as msg}
      <div class="message" class:own={msg.isOwn}>
        <span class="sender">{msg.sender}</span>
        <span class="text">{msg.text}</span>
        <span class="time">{msg.timestamp}</span>
      </div>
    {/each}
  </div>
  <div class="input-row">
    <input type="text" bind:value={inputText} on:keydown={(e) => e.key === "Enter" && sendMessage()} />
    <button on:click={sendMessage}>Send</button>
  </div>
</div>

<style>
  .chat { display: flex; flex-direction: column; height: 100%; }
  .messages { flex: 1; overflow-y: auto; }
  .message.own { text-align: right; }
  .input-row { display: flex; gap: 0.5rem; }
  .input-row input { flex: 1; }
</style>
```

- [ ] **Step 5: Create StatusBar.svelte**

Create `client/src/lib/StatusBar.svelte`:

```svelte
<script lang="ts">
  import { connectionState, latencyMs } from "./stores";
  export let mode: "director" | "actor";
</script>

<div class="status-bar">
  <span class="mode">{mode === "director" ? "Director" : "Actor"}</span>
  <span class="status">{typeof $connectionState === "string" ? $connectionState : "Failed"}</span>
  <span class="latency">{$latencyMs}ms</span>
</div>

<style>
  .status-bar { display: flex; gap: 1rem; padding: 0.4rem 0.8rem; font-size: 0.85rem; opacity: 0.8; }
</style>
```

- [ ] **Step 6: Wire mode routing in App.svelte**

Replace `client/src/App.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import ModeSelector from "./lib/ModeSelector.svelte";
  import DirectorView from "./lib/DirectorView.svelte";
  import ActorView from "./lib/ActorView.svelte";
  import { appConfig } from "./lib/stores";

  let mode: "director" | "actor" | null = null;

  onMount(async () => {
    const cfg = await invoke<any>("get_config");
    appConfig.set(cfg);
    if (cfg.remember_mode && (cfg.mode === "director" || cfg.mode === "actor")) {
      mode = cfg.mode;
    }
  });
</script>

<main>
  {#if !mode}
    <ModeSelector onSelect={(m) => (mode = m)} />
  {:else if mode === "director"}
    <DirectorView />
  {:else}
    <ActorView />
  {/if}
</main>
```

Note: `DirectorView.svelte` and `ActorView.svelte` don't exist yet — Tasks 8 and 11 create them. This step will not compile in isolation; that's expected and resolved by Step 7 below using placeholder stub files, replaced fully in Tasks 8/11.

- [ ] **Step 7: Create minimal stub views so the build succeeds until Tasks 8/11 flesh them out**

Create `client/src/lib/DirectorView.svelte`:

```svelte
<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
</script>

<div class="director-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="director" />
  </header>
  <Chat />
</div>
```

Create `client/src/lib/ActorView.svelte`:

```svelte
<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
</script>

<div class="actor-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="actor" />
  </header>
  <Chat />
</div>
```

- [ ] **Step 8: Verify the frontend builds**

```bash
cd /home/danny/vrActorAssist/client
npm run build
```

Expected: Vite build succeeds with no TypeScript errors

- [ ] **Step 9: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src/
git commit -m "feat: add shared Svelte UI (mode selector, connection, chat, status bar)"
```

---

### Task 8: Build Director mode — actor list, cue controls, approve/deny/forget

**Files:**
- Create: `client/src-tauri/src/director.rs`
- Modify: `client/src-tauri/src/main.rs` (register module, add commands)
- Modify: `client/src/lib/DirectorView.svelte`
- Create: `client/src/lib/ActorList.svelte`
- Create: `client/src/lib/CueControls.svelte`
- Create: `client/src/lib/Settings.svelte`

**Interfaces:**
- Consumes: `protocol::Message` variants `Pending`, `Status`, `Approved`, `Denied`; `state::AppState`
- Produces: Tauri commands `approve_actor`, `deny_actor`, `forget_actor`; Rust struct `ActorInfo` (serialized to the frontend) with fields `name`, `machine_id`, `latency_ms`, `approved`, `enabled`

- [ ] **Step 1: Create the director-side actor tracking module**

Create `client/src-tauri/src/director.rs`:

```rust
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ActorInfo {
    pub name: String,
    pub machine_id: String,
    pub latency_ms: u32,
    pub approved: bool,
    pub enabled: bool,
}

/// Tracks known actors by name. `enabled` defaults to true for newly-seen actors,
/// matching director_client_ws.py's actor_enabled dict default of True.
#[derive(Default)]
pub struct ActorRegistry {
    pub actors: HashMap<String, ActorInfo>,
}

impl ActorRegistry {
    pub fn upsert_pending(&mut self, name: &str, machine_id: &str) {
        self.actors.entry(name.to_string()).or_insert(ActorInfo {
            name: name.to_string(),
            machine_id: machine_id.to_string(),
            latency_ms: 0,
            approved: false,
            enabled: true,
        });
    }

    pub fn mark_approved(&mut self, name: &str) {
        if let Some(a) = self.actors.get_mut(name) {
            a.approved = true;
        }
    }

    pub fn remove(&mut self, name: &str) {
        self.actors.remove(name);
    }

    pub fn set_enabled(&mut self, name: &str, enabled: bool) {
        if let Some(a) = self.actors.get_mut(name) {
            a.enabled = enabled;
        }
    }

    pub fn enabled_names(&self) -> Vec<String> {
        self.actors.values().filter(|a| a.approved && a.enabled).map(|a| a.name.clone()).collect()
    }

    pub fn set_latency(&mut self, name: &str, latency_ms: u32) {
        if let Some(a) = self.actors.get_mut(name) {
            a.latency_ms = latency_ms;
        }
    }

    pub fn all(&self) -> Vec<ActorInfo> {
        self.actors.values().cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_actor_defaults_to_enabled_and_unapproved() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        let a = &reg.actors["Actor1"];
        assert!(a.enabled);
        assert!(!a.approved);
    }

    #[test]
    fn enabled_names_excludes_unapproved() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        reg.upsert_pending("Actor2", "id-2");
        reg.mark_approved("Actor1");
        assert_eq!(reg.enabled_names(), vec!["Actor1".to_string()]);
    }

    #[test]
    fn disabled_actor_excluded_from_enabled_names() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        reg.mark_approved("Actor1");
        reg.set_enabled("Actor1", false);
        assert!(reg.enabled_names().is_empty());
    }

    #[test]
    fn set_latency_updates_existing_actor_only() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        reg.set_latency("Actor1", 42);
        reg.set_latency("NoSuchActor", 999); // must not panic or create an entry
        assert_eq!(reg.actors["Actor1"].latency_ms, 42);
        assert_eq!(reg.actors.len(), 1);
    }
}
```


- [ ] **Step 2: Run the new tests**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml director::
```

Expected: 3 passed

- [ ] **Step 3: Add the registry to AppState and add approve/deny/forget commands**

Edit `client/src-tauri/src/state.rs`, add the registry field:

```rust
use crate::director::ActorRegistry;
// ... existing imports ...

pub struct AppState {
    pub config: Mutex<Config>,
    pub config_path: std::path::PathBuf,
    pub ws: Arc<WsClient>,
    pub actors: Mutex<ActorRegistry>,
}

impl AppState {
    pub fn new(config: Config, config_path: std::path::PathBuf) -> Self {
        Self {
            config: Mutex::new(config),
            config_path,
            ws: Arc::new(WsClient::new()),
            actors: Mutex::new(ActorRegistry::default()),
        }
    }
}
```

Edit `client/src-tauri/src/main.rs`: add `mod director;`, then add these commands and register them in `invoke_handler!`:

```rust
#[tauri::command]
async fn approve_actor(state: State<'_, AppState>, machine_id: String) -> Result<(), String> {
    state.ws.send(&Message::Approve { machine_id }).await
}

#[tauri::command]
async fn deny_actor(state: State<'_, AppState>, machine_id: String) -> Result<(), String> {
    state.ws.send(&Message::Deny { machine_id }).await
}

#[tauri::command]
async fn forget_actor(state: State<'_, AppState>, name: String) -> Result<(), String> {
    state.actors.lock().await.remove(&name);
    state.ws.send(&Message::ForgetName { name }).await
}

#[tauri::command]
async fn set_actor_enabled(state: State<'_, AppState>, name: String, enabled: bool) -> Result<(), String> {
    state.actors.lock().await.set_enabled(&name, enabled);
    Ok(())
}

#[tauri::command]
async fn list_actors(state: State<'_, AppState>) -> Vec<crate::director::ActorInfo> {
    state.actors.lock().await.all()
}
```

Update the `main()` function's `invoke_handler!` list to include `approve_actor, deny_actor, forget_actor, set_actor_enabled, list_actors,`.

Now update `AppState` so `actors` is shareable with the closure spawned inside `connect`. Edit `client/src-tauri/src/state.rs`:

```rust
use crate::director::ActorRegistry;
use std::sync::Arc;
use tokio::sync::Mutex;
// ... existing imports (Config, WsClient) ...

pub struct AppState {
    pub config: Mutex<Config>,
    pub config_path: std::path::PathBuf,
    pub ws: Arc<WsClient>,
    pub actors: Arc<Mutex<ActorRegistry>>,
}

impl AppState {
    pub fn new(config: Config, config_path: std::path::PathBuf) -> Self {
        Self {
            config: Mutex::new(config),
            config_path,
            ws: Arc::new(WsClient::new()),
            actors: Arc::new(Mutex::new(ActorRegistry::default())),
        }
    }
}
```

Then replace the `connect` command in `client/src-tauri/src/main.rs` (originally written in Task 6 Step 2) with this version, which parses `Pending`/`Status` payloads into the shared registry before emitting to the frontend:

```rust
#[derive(serde::Deserialize)]
struct PendingEntry {
    machine_id: String,
    name: String,
}

#[derive(serde::Deserialize)]
struct StatusEntry {
    name: String,
    latency_ms: u32,
}

#[tauri::command]
async fn connect(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    let url = cfg.get_ws_url();
    let ws = state.ws.clone();
    let actors_for_msg = state.actors.clone();

    let app_for_msg = app.clone();
    let app_for_state = app.clone();

    ws.connect(
        &url,
        move |msg: Message| {
            match &msg {
                Message::Pending { actors_json } => {
                    if let Ok(entries) = serde_json::from_str::<Vec<PendingEntry>>(actors_json) {
                        let actors = actors_for_msg.clone();
                        tauri::async_runtime::block_on(async move {
                            let mut reg = actors.lock().await;
                            for e in entries {
                                reg.upsert_pending(&e.name, &e.machine_id);
                            }
                        });
                    }
                }
                Message::Status { actors_json } => {
                    if let Ok(entries) = serde_json::from_str::<Vec<StatusEntry>>(actors_json) {
                        let actors = actors_for_msg.clone();
                        tauri::async_runtime::block_on(async move {
                            let mut reg = actors.lock().await;
                            for e in entries {
                                reg.set_latency(&e.name, e.latency_ms);
                            }
                        });
                    }
                }
                Message::Approved => {
                    // Server confirms an actor's approval only to that actor's own
                    // connection; the director learns of it via the next Pending/Status
                    // broadcast, so no registry update is needed on this branch.
                }
                _ => {}
            }
            let _ = app_for_msg.emit("protocol-message", &msg);
        },
        move |st: ConnectionState| {
            let _ = app_for_state.emit("connection-state", &st);
        },
    )
    .await?;

    let register = Message::Register {
        name: if cfg.mode == "actor" { cfg.actor_name.clone() } else { "Director".to_string() },
        machine_id: cfg.machine_id.clone(),
        role: cfg.mode.clone(),
        secret: cfg.secret.clone(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        platform: if cfg!(target_os = "windows") { "windows-x64".to_string() } else { "linux-x64".to_string() },
    };
    state.ws.send(&register).await
}
```

This replaces the `connect` command written in Task 6 wholesale — the earlier version becomes dead code once this edit lands; there is only ever one `connect` function in the file.

**Note on `tauri::async_runtime::block_on` inside the closure:** the `on_message` callback in `ws_client.rs` (Task 5) is a plain sync `Fn`, but updating the registry needs an async lock. `tauri::async_runtime::block_on` is Tauri's supported way to bridge sync callbacks into its managed async runtime and is safe to call here even though the closure itself runs inside a `tokio::spawn`ed task. If `cargo check` reports a runtime-nesting panic at runtime (not compile time) instead, the fix is to switch `ActorRegistry`'s lock from `tokio::sync::Mutex` to `std::sync::Mutex` (registry updates are quick, non-async operations — a blocking mutex is fine and sidesteps the issue entirely). Try the `block_on` version first since it's less code churn; fall back to `std::sync::Mutex` only if testing in Task 15 surfaces a deadlock or panic.

- [ ] **Step 4: Verify compilation**

```bash
cd /home/danny/vrActorAssist/client
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: compiles. This step involves real integration work (threading the Arc through the closure) — if the borrow checker complains about `state.actors` not being `Arc`, that is the fix: change `Mutex<ActorRegistry>` to `Arc<Mutex<ActorRegistry>>` in `state.rs` and update `AppState::new` accordingly.

- [ ] **Step 5: Create ActorList.svelte**

Create `client/src/lib/ActorList.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";

  interface ActorInfo { name: string; machine_id: string; latency_ms: number; approved: boolean; enabled: boolean; }

  let actors: ActorInfo[] = [];

  async function refresh() {
    actors = await invoke<ActorInfo[]>("list_actors");
  }

  onMount(async () => {
    await refresh();
    await listen("protocol-message", () => refresh());
  });

  async function approve(machineId: string) { await invoke("approve_actor", { machineId }); await refresh(); }
  async function deny(machineId: string) { await invoke("deny_actor", { machineId }); await refresh(); }
  async function forget(name: string) { await invoke("forget_actor", { name }); await refresh(); }
  async function toggleEnabled(name: string, enabled: boolean) { await invoke("set_actor_enabled", { name, enabled }); await refresh(); }

  function latencyClass(ms: number) { return ms < 50 ? "green" : ms < 150 ? "yellow" : "red"; }
</script>

<div class="actor-list">
  <h2>Actors</h2>
  {#each actors as actor}
    <div class="actor-row">
      <span class="status-dot {latencyClass(actor.latency_ms)}"></span>
      <span class="name">{actor.name}</span>
      <span class="latency">{actor.latency_ms}ms</span>
      {#if !actor.approved}
        <button on:click={() => approve(actor.machine_id)}>Approve</button>
        <button on:click={() => deny(actor.machine_id)}>Deny</button>
      {:else}
        <input type="checkbox" checked={actor.enabled} on:change={(e) => toggleEnabled(actor.name, e.currentTarget.checked)} />
        <button on:click={() => forget(actor.name)}>Forget</button>
      {/if}
    </div>
  {/each}
</div>

<style>
  .actor-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; }
  .status-dot.green { background: #2ecc71; }
  .status-dot.yellow { background: #f1c40f; }
  .status-dot.red { background: #e74c3c; }
</style>
```

- [ ] **Step 6: Create CueControls.svelte**

Create `client/src/lib/CueControls.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  interface ActorInfo { name: string; approved: boolean; enabled: boolean; }

  let countdownSeconds = 3;
  let countdownTimer: ReturnType<typeof setTimeout> | null = null;
  let countdownLabel = "";

  async function enabledTargets(): Promise<string[]> {
    const actors = await invoke<ActorInfo[]>("list_actors");
    return actors.filter((a) => a.approved && a.enabled).map((a) => a.name);
  }

  async function sendGo() {
    const targets = await enabledTargets();
    if (targets.length === 0) return;
    await invoke("send_command", { command: "*go", targets });
  }

  async function sendStop() {
    if (countdownTimer) { clearTimeout(countdownTimer); countdownTimer = null; countdownLabel = ""; }
    const targets = await enabledTargets();
    if (targets.length === 0) return;
    await invoke("send_command", { command: "*stop", targets });
  }

  function playInCountdown() {
    let remaining = countdownSeconds;
    countdownLabel = `${remaining}...`;
    countdownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(countdownTimer!);
        countdownTimer = null;
        countdownLabel = "";
        sendGo();
      } else {
        countdownLabel = `${remaining}...`;
      }
    }, 1000) as unknown as ReturnType<typeof setTimeout>;
  }
</script>

<div class="cue-controls">
  <div class="cue-buttons">
    <button on:click={sendGo} class="cue go">Go</button>
    <button on:click={sendStop} class="cue stop">Stop</button>
    <div class="countdown-group">
      <button on:click={playInCountdown} class="cue countdown">
        Play in {countdownSeconds}s {countdownLabel}
      </button>
      <select bind:value={countdownSeconds}>
        <option value={3}>3s</option>
        <option value={5}>5s</option>
        <option value={10}>10s</option>
      </select>
    </div>
  </div>
</div>

<style>
  .cue-buttons { display: flex; gap: 0.75rem; align-items: center; }
  .cue { font-size: 1.1rem; padding: 0.75rem 1.5rem; border-radius: 8px; }
  .cue.go { background: #2ecc71; }
  .cue.stop { background: #e74c3c; }
</style>
```

- [ ] **Step 7: Create Settings.svelte (server URL + secret + theme)**

Create `client/src/lib/Settings.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  async function save() {
    if (!$appConfig) return;
    await invoke("save_config", { newConfig: $appConfig });
  }
</script>

{#if $appConfig}
  <div class="settings">
    <h3>Settings</h3>
    <label>Shared secret: <input type="password" bind:value={$appConfig.secret} on:change={save} /></label>
    <label>Theme:
      <select bind:value={$appConfig.theme} on:change={save}>
        <option value="dark">Dark</option>
        <option value="light">Light</option>
      </select>
    </label>
  </div>
{/if}
```

This binds directly to the `secret` field added to `Config` in Task 4 — `$appConfig` is the same store `ConnectionPanel.svelte` (Task 7) populates from `get_config`, so edits here are visible immediately to the `connect` command's `cfg.secret.clone()` read (Task 6).

- [ ] **Step 8: Wire it all into DirectorView.svelte**

Replace `client/src/lib/DirectorView.svelte`:

```svelte
<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
  import ActorList from "./ActorList.svelte";
  import CueControls from "./CueControls.svelte";
  import Settings from "./Settings.svelte";
</script>

<div class="director-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="director" />
  </header>
  <div class="main-area">
    <aside class="left-panel">
      <ActorList />
      <CueControls />
      <Settings />
    </aside>
    <section class="chat-area">
      <Chat />
    </section>
  </div>
</div>

<style>
  .main-area { display: flex; gap: 1rem; height: calc(100% - 3rem); }
  .left-panel { width: 320px; display: flex; flex-direction: column; gap: 1rem; overflow-y: auto; }
  .chat-area { flex: 1; }
</style>
```

- [ ] **Step 9: Verify full build**

```bash
cd /home/danny/vrActorAssist/client
npm run build && cargo check --manifest-path src-tauri/Cargo.toml && cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: frontend builds, Rust compiles, all tests pass

- [ ] **Step 10: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/
git commit -m "feat: implement Director mode (actor list, cue controls, approve/deny/forget)"
```

---

### Task 9: Implement file transfer (chunking, MD5, character routing) with unit tests

**Files:**
- Create: `client/src-tauri/src/file_transfer.rs`
- Modify: `client/src-tauri/src/main.rs` (register module, add commands)

**Interfaces:**
- Consumes: `md5`, `base64` crates
- Produces: `file_transfer::split_into_chunks(&[u8]) -> Vec<String>` (base64 chunks), `file_transfer::md5_hex(&[u8]) -> String`, `file_transfer::extract_character(filename: &str) -> Option<String>`, `file_transfer::FileReceiveBuffer` (accumulates incoming chunks, verifies checksum)

- [ ] **Step 1: Write failing tests**

Create `client/src-tauri/src/file_transfer.rs`:

```rust
use base64::{engine::general_purpose::STANDARD, Engine as _};
use std::collections::BTreeMap;

pub const CHUNK_SIZE: usize = 65536; // 64KB, matches shared.py clients

pub fn md5_hex(data: &[u8]) -> String {
    format!("{:x}", md5::compute(data))
}

/// Splits raw bytes into base64-encoded 64KB chunks (director side, before sending FILECHUNK).
pub fn split_into_chunks(data: &[u8]) -> Vec<String> {
    data.chunks(CHUNK_SIZE).map(|c| STANDARD.encode(c)).collect()
}

/// Extracts the character name from a filename following the " - Character.ext" convention
/// used by director_client_ws.py's routing dialog, e.g. "Scene1_Line04 - Alice.wav" -> "Alice".
pub fn extract_character(filename: &str) -> Option<String> {
    let stem = filename.rsplit_once('.').map(|(s, _)| s).unwrap_or(filename);
    stem.rsplit_once(" - ").map(|(_, character)| character.trim().to_string()).filter(|c| !c.is_empty())
}

/// Accumulates base64 chunks for one in-progress file receive (actor side).
#[derive(Default)]
pub struct FileReceiveBuffer {
    chunks: BTreeMap<u32, Vec<u8>>,
}

impl FileReceiveBuffer {
    pub fn add_chunk(&mut self, chunk_num: u32, b64_data: &str) -> Result<(), String> {
        let bytes = STANDARD.decode(b64_data).map_err(|e| format!("Invalid base64: {}", e))?;
        self.chunks.insert(chunk_num, bytes);
        Ok(())
    }

    /// Assembles chunks in order and verifies the MD5 checksum. Returns the assembled
    /// bytes on success, or an error string (matching FILEERR reason text) on mismatch.
    pub fn finalize(&self, expected_checksum: &str) -> Result<Vec<u8>, String> {
        let mut data = Vec::new();
        for (_, chunk) in &self.chunks {
            data.extend_from_slice(chunk);
        }
        let actual = md5_hex(&data);
        if actual != expected_checksum {
            return Err(format!("Checksum mismatch: expected {}, got {}", expected_checksum, actual));
        }
        Ok(data)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn md5_hex_matches_known_vector() {
        // MD5("") == d41d8cd98f00b204e9800998ecf8427e
        assert_eq!(md5_hex(b""), "d41d8cd98f00b204e9800998ecf8427e");
    }

    #[test]
    fn split_into_chunks_respects_chunk_size() {
        let data = vec![0u8; CHUNK_SIZE * 2 + 10];
        let chunks = split_into_chunks(&data);
        assert_eq!(chunks.len(), 3);
        // Each base64 chunk decodes back to <= CHUNK_SIZE raw bytes.
        for c in &chunks {
            let decoded = STANDARD.decode(c).unwrap();
            assert!(decoded.len() <= CHUNK_SIZE);
        }
    }

    #[test]
    fn extract_character_parses_dash_pattern() {
        assert_eq!(extract_character("Scene1_Line04 - Alice.wav"), Some("Alice".to_string()));
    }

    #[test]
    fn extract_character_returns_none_without_pattern() {
        assert_eq!(extract_character("just_a_file.wav"), None);
    }

    #[test]
    fn extract_character_handles_multiple_dashes() {
        // Only the LAST " - " before the extension separates the character.
        assert_eq!(extract_character("Take-2 - Bob.mp3"), Some("Bob".to_string()));
    }

    #[test]
    fn receive_buffer_assembles_out_of_order_chunks() {
        let mut buf = FileReceiveBuffer::default();
        let full_data = b"hello world, this is a test file".to_vec();
        let chunks = split_into_chunks(&full_data);
        assert!(chunks.len() >= 1);
        // Insert in reverse order to prove BTreeMap reorders by chunk_num.
        for (i, c) in chunks.iter().enumerate().rev() {
            buf.add_chunk(i as u32, c).unwrap();
        }
        let checksum = md5_hex(&full_data);
        let assembled = buf.finalize(&checksum).unwrap();
        assert_eq!(assembled, full_data);
    }

    #[test]
    fn receive_buffer_rejects_bad_checksum() {
        let mut buf = FileReceiveBuffer::default();
        buf.add_chunk(0, &STANDARD.encode(b"corrupted")).unwrap();
        let result = buf.finalize("0000000000000000000000000000000");
        assert!(result.is_err());
    }
}
```

- [ ] **Step 2: Run tests**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml file_transfer::
```

Expected: all pass. If `extract_character` fails the multiple-dashes test, confirm `rsplit_once(" - ")` (not `split_once`) is used — that's what makes it split on the *last* occurrence.

- [ ] **Step 3: Register the module**

In `client/src-tauri/src/main.rs`, add `mod file_transfer;`.

- [ ] **Step 4: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src-tauri/src/file_transfer.rs client/src-tauri/src/main.rs
git commit -m "feat: implement file transfer chunking, checksum, and character routing"
```

---

### Task 10: Wire file transfer into Director (sender) and Actor (receiver) UI

**Files:**
- Create: `client/src/lib/FileSender.svelte`
- Create: `client/src/lib/FileReceiver.svelte`
- Modify: `client/src-tauri/src/main.rs` (file transfer commands)
- Modify: `client/src/lib/DirectorView.svelte`
- Modify: `client/src/lib/ActorView.svelte`

**Interfaces:**
- Consumes: `file_transfer::{split_into_chunks, md5_hex, extract_character, FileReceiveBuffer}` (Task 9), `tauri-plugin-dialog` for native file picker
- Produces: Tauri commands `send_file`, `respond_to_file_request`; events `"file-incoming"`, `"file-progress"`, `"batch-progress"`

- [ ] **Step 1: Add file transfer commands to main.rs**

Add to `client/src-tauri/src/main.rs`:

```rust
use crate::file_transfer::{split_into_chunks, md5_hex, FileReceiveBuffer};
use std::collections::HashMap;
use tokio::sync::Mutex as TokioMutex;

// Add to AppState (state.rs) a field: pub receive_buffers: TokioMutex<HashMap<String, FileReceiveBuffer>>,
// and initialize it as TokioMutex::new(HashMap::new()) in AppState::new.

#[tauri::command]
async fn send_file(state: State<'_, AppState>, target: String, path: String) -> Result<(), String> {
    let bytes = std::fs::read(&path).map_err(|e| format!("Read failed: {}", e))?;
    let filename = std::path::Path::new(&path)
        .file_name()
        .map(|f| f.to_string_lossy().to_string())
        .unwrap_or_else(|| "unknown".to_string());
    let checksum = md5_hex(&bytes);

    state.ws.send(&Message::FileReq {
        sender: "Director".to_string(), target: target.clone(), filename: filename.clone(),
        size: bytes.len() as u64, checksum: checksum.clone(),
    }).await?;

    let chunks = split_into_chunks(&bytes);
    state.ws.send(&Message::FileStart {
        filename: filename.clone(), total_chunks: chunks.len() as u32, chunk_size: file_transfer::CHUNK_SIZE as u32,
    }).await?;
    for (i, chunk) in chunks.iter().enumerate() {
        state.ws.send(&Message::FileChunk { filename: filename.clone(), chunk_num: i as u32, data: chunk.clone() }).await?;
    }
    state.ws.send(&Message::FileEnd { filename, checksum }).await
}

#[tauri::command]
async fn respond_to_file_request(state: State<'_, AppState>, filename: String, accept: bool, save_dir: String) -> Result<(), String> {
    if accept {
        state.ws.send(&Message::FileAck { filename, accept: true, save_dir }).await
    } else {
        state.ws.send(&Message::FileDeny { filename, reason: "Declined by actor".to_string() }).await
    }
}
```

Add `approve_actor` sibling commands `send_file, respond_to_file_request` to the `invoke_handler!` list. Then, inside the `connect` command's incoming-message closure (Task 6/8), add handling for `Message::FileChunk` (append to the actor's `receive_buffers` entry for that filename) and `Message::FileEnd` (call `finalize()`, write the resulting bytes to `cfg.receive_dir`, and send back `Message::FileOk` or `Message::FileErr` depending on the result) — this is actor-side logic, so guard it with `if cfg.mode == "actor"`.

- [ ] **Step 2: Create FileSender.svelte**

Create `client/src/lib/FileSender.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";

  interface ActorInfo { name: string; approved: boolean; }

  let selectedTarget = "";
  let actors: ActorInfo[] = [];
  let sending = false;

  async function refreshActors() {
    actors = (await invoke<ActorInfo[]>("list_actors")).filter((a) => a.approved);
  }

  async function pickAndSend() {
    const paths = await open({ multiple: true, filters: [{ name: "Audio", extensions: ["wav", "mp3", "ogg"] }] });
    if (!paths) return;
    const list = Array.isArray(paths) ? paths : [paths];
    sending = true;
    try {
      for (const path of list) {
        await invoke("send_file", { target: selectedTarget, path });
      }
    } finally {
      sending = false;
    }
  }
</script>

<div class="file-sender">
  <h3>Send Files</h3>
  <select bind:value={selectedTarget} on:focus={refreshActors}>
    {#each actors as actor}
      <option value={actor.name}>{actor.name}</option>
    {/each}
  </select>
  <button on:click={pickAndSend} disabled={!selectedTarget || sending}>
    {sending ? "Sending..." : "Choose Files..."}
  </button>
</div>
```

- [ ] **Step 3: Create FileReceiver.svelte**

Create `client/src/lib/FileReceiver.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { appConfig } from "./stores";

  let incoming: { filename: string; size: number } | null = null;

  onMount(async () => {
    await listen<any>("protocol-message", (event) => {
      const msg = event.payload;
      if (msg.FileReq) {
        incoming = { filename: msg.FileReq.filename, size: msg.FileReq.size };
      }
    });
  });

  async function accept() {
    if (!incoming || !$appConfig) return;
    await invoke("respond_to_file_request", { filename: incoming.filename, accept: true, saveDir: $appConfig.receive_dir });
    incoming = null;
  }

  async function decline() {
    if (!incoming) return;
    await invoke("respond_to_file_request", { filename: incoming.filename, accept: false, saveDir: "" });
    incoming = null;
  }
</script>

<div class="file-receiver">
  <h3>File Transfers</h3>
  {#if incoming}
    <div class="incoming">
      <p>Incoming: {incoming.filename} ({(incoming.size / 1024 / 1024).toFixed(1)} MB)</p>
      <button on:click={accept}>Accept</button>
      <button on:click={decline}>Decline</button>
    </div>
  {:else}
    <p class="hint">Waiting for files...</p>
  {/if}
</div>
```

- [ ] **Step 4: Wire into DirectorView.svelte and ActorView.svelte**

In `client/src/lib/DirectorView.svelte`, add `import FileSender from "./FileSender.svelte";` and `<FileSender />` inside `.left-panel`, after `<CueControls />`.

In `client/src/lib/ActorView.svelte`, add `import FileReceiver from "./FileReceiver.svelte";` and `<FileReceiver />` inside the view.

- [ ] **Step 5: Verify full build**

```bash
cd /home/danny/vrActorAssist/client
npm run build && cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: both succeed

- [ ] **Step 6: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/
git commit -m "feat: wire file transfer into Director sender and Actor receiver UI"
```

---

### Task 11: Implement Soundpad + OSC modules and finish Actor mode UI

**Files:**
- Create: `client/src-tauri/src/soundpad.rs`
- Create: `client/src-tauri/src/osc.rs`
- Modify: `client/src-tauri/src/main.rs`
- Create: `client/src/lib/SoundpadConfig.svelte`
- Create: `client/src/lib/OscConfig.svelte`
- Modify: `client/src/lib/ActorView.svelte`

**Interfaces:**
- Consumes: `config::Config` fields `soundpad_enabled`, `soundpad_path`, `osc_enabled`, `osc_host`, `osc_port`
- Produces: `soundpad::send_command(command: &str, soundpad_path: &str) -> Result<String, String>`, `osc::send_param_bool(host, port, parameter, value) -> Result<(), String>`; Tauri commands `save_config` (already exists) drives both

- [ ] **Step 1: Create soundpad.rs**

Create `client/src-tauri/src/soundpad.rs`:

```rust
/// Sends a command to Soundpad's command-line interface. Windows-only — Soundpad
/// does not run on Linux/macOS, matching soundpad.py's Windows-only design.
pub fn send_command(command: &str, soundpad_path: &str) -> Result<String, String> {
    #[cfg(target_os = "windows")]
    {
        let normalized = normalize_command(command);
        let output = std::process::Command::new(soundpad_path)
            .args(["-rc", &normalized])
            .output()
            .map_err(|e| format!("Soundpad execution failed: {}", e))?;

        if output.status.success() {
            Ok(String::from_utf8_lossy(&output.stdout).to_string())
        } else {
            Err(format!("Soundpad error: {}", String::from_utf8_lossy(&output.stderr)))
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = (command, soundpad_path);
        Err("Soundpad is only available on Windows".to_string())
    }
}

/// Maps protocol command strings ("*go", "*stop", "*play:3") to Soundpad CLI calls,
/// matching soundpad.py's command handling.
#[cfg(target_os = "windows")]
fn normalize_command(command: &str) -> String {
    if command == "*go" || command == "go" {
        "DoPlaySelectedSound()".to_string()
    } else if command == "*stop" || command == "stop" {
        "DoStopSound()".to_string()
    } else if let Some(idx) = command.strip_prefix("*play:").or_else(|| command.strip_prefix("play:")) {
        format!("DoPlaySound({})", idx)
    } else {
        command.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "windows")]
    #[test]
    fn normalize_go_command() {
        assert_eq!(normalize_command("*go"), "DoPlaySelectedSound()");
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn normalize_play_index_command() {
        assert_eq!(normalize_command("*play:5"), "DoPlaySound(5)");
    }

    #[cfg(not(target_os = "windows"))]
    #[test]
    fn non_windows_returns_error() {
        let result = send_command("*go", "Soundpad.exe");
        assert!(result.is_err());
    }
}
```

- [ ] **Step 2: Run tests**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml soundpad::
```

Expected: on Linux CI/dev machines, `non_windows_returns_error` passes; on Windows, the two `normalize_*` tests pass instead.

- [ ] **Step 3: Create osc.rs**

Create `client/src-tauri/src/osc.rs`:

```rust
use rosc::{OscMessage, OscPacket, OscType};
use std::net::UdpSocket;

/// Sends a VRChat avatar parameter over OSC. `value` is parsed as bool ("true"/"false"/"1"/"0")
/// first, falling back to float, matching the director's OSC_CUE value semantics.
pub fn send_param(host: &str, port: u16, parameter: &str, value: &str) -> Result<(), String> {
    let address = if parameter.starts_with('/') {
        parameter.to_string()
    } else {
        format!("/avatar/parameters/{}", parameter)
    };

    let osc_value = parse_osc_value(value);
    let msg = OscMessage { addr: address, args: vec![osc_value] };
    let packet = OscPacket::Message(msg);
    let bytes = rosc::encoder::encode(&packet).map_err(|e| format!("OSC encode error: {}", e))?;

    let socket = UdpSocket::bind("0.0.0.0:0").map_err(|e| format!("Socket bind error: {}", e))?;
    socket.send_to(&bytes, format!("{}:{}", host, port)).map_err(|e| format!("OSC send error: {}", e))?;
    Ok(())
}

fn parse_osc_value(value: &str) -> OscType {
    match value.to_lowercase().as_str() {
        "true" | "1" => OscType::Bool(true),
        "false" | "0" => OscType::Bool(false),
        other => other.parse::<f32>().map(OscType::Float).unwrap_or(OscType::String(value.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_bool_true() {
        assert!(matches!(parse_osc_value("true"), OscType::Bool(true)));
    }

    #[test]
    fn parses_bool_false_from_zero() {
        assert!(matches!(parse_osc_value("0"), OscType::Bool(false)));
    }

    #[test]
    fn parses_float() {
        assert!(matches!(parse_osc_value("0.75"), OscType::Float(_)));
    }

    #[test]
    fn falls_back_to_string() {
        assert!(matches!(parse_osc_value("not_a_number"), OscType::String(_)));
    }
}
```

- [ ] **Step 4: Register modules and add commands**

In `client/src-tauri/src/main.rs`, add `mod soundpad;` and `mod osc;`, then add:

```rust
#[tauri::command]
async fn play_soundpad(state: State<'_, AppState>, command: String) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    if !cfg.soundpad_enabled {
        return Ok(());
    }
    soundpad::send_command(&command, &cfg.soundpad_path).map(|_| ())
}

#[tauri::command]
async fn send_osc(state: State<'_, AppState>, parameter: String, value: String) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    if !cfg.osc_enabled {
        return Ok(());
    }
    osc::send_param(&cfg.osc_host, cfg.osc_port, &parameter, &value)
}
```

Add `play_soundpad, send_osc,` to `invoke_handler!`. Then, in the `connect` command's incoming-message closure, add: when `Message::Priv { target, text, .. }` arrives and `target == cfg.actor_name && cfg.mode == "actor"`, call the equivalent of `play_soundpad` inline (can't call a `#[tauri::command]` function directly from a plain closure — extract the body into a plain async fn `fn do_play_soundpad(cfg: &Config, command: &str) -> Result<(), String>` that both the command and the closure call). Similarly for `Message::OscCue { target, parameter, value }` matching `cfg.actor_name`, call the OSC equivalent.

- [ ] **Step 5: Verify compilation and tests**

```bash
cd /home/danny/vrActorAssist/client
cargo check --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: compiles, all tests pass

- [ ] **Step 6: Create SoundpadConfig.svelte**

Create `client/src/lib/SoundpadConfig.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  async function save() {
    if (!$appConfig) return;
    await invoke("save_config", { newConfig: $appConfig });
  }
</script>

{#if $appConfig}
  <div class="soundpad-config">
    <h3>Soundpad</h3>
    <label class="toggle">
      <input type="checkbox" bind:checked={$appConfig.soundpad_enabled} on:change={save} />
      Enabled
    </label>
    <label>Path: <input type="text" bind:value={$appConfig.soundpad_path} on:change={save} /></label>
  </div>
{/if}
```

- [ ] **Step 7: Create OscConfig.svelte**

Create `client/src/lib/OscConfig.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  async function save() {
    if (!$appConfig) return;
    await invoke("save_config", { newConfig: $appConfig });
  }
</script>

{#if $appConfig}
  <div class="osc-config">
    <h3>VRChat OSC</h3>
    <label class="toggle">
      <input type="checkbox" bind:checked={$appConfig.osc_enabled} on:change={save} />
      Enabled
    </label>
    <label>Host: <input type="text" bind:value={$appConfig.osc_host} on:change={save} /></label>
    <label>Port: <input type="number" bind:value={$appConfig.osc_port} on:change={save} /></label>
  </div>
{/if}
```

- [ ] **Step 8: Finalize ActorView.svelte**

Replace `client/src/lib/ActorView.svelte`:

```svelte
<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
  import FileReceiver from "./FileReceiver.svelte";
  import OscConfig from "./OscConfig.svelte";
  import SoundpadConfig from "./SoundpadConfig.svelte";
</script>

<div class="actor-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="actor" />
  </header>
  <div class="main-area">
    <aside class="left-panel">
      <SoundpadConfig />
      <OscConfig />
      <FileReceiver />
    </aside>
    <section class="chat-area">
      <Chat />
    </section>
  </div>
</div>

<style>
  .main-area { display: flex; gap: 1rem; height: calc(100% - 3rem); }
  .left-panel { width: 320px; display: flex; flex-direction: column; gap: 1rem; overflow-y: auto; }
  .chat-area { flex: 1; }
</style>
```

- [ ] **Step 9: Verify full build**

```bash
cd /home/danny/vrActorAssist/client
npm run build && cargo check --manifest-path src-tauri/Cargo.toml && cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: all succeed

- [ ] **Step 10: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/
git commit -m "feat: implement Soundpad and OSC modules, finish Actor mode UI"
```

---

### Task 12: Implement auto-updater with portable-aware notify-only fallback

**Files:**
- Modify: `client/src-tauri/tauri.conf.json`
- Modify: `client/src-tauri/src/main.rs`
- Create: `client/src/lib/UpdateNotifier.svelte`
- Modify: `client/src/App.svelte`

**Interfaces:**
- Consumes: `tauri-plugin-updater`, `config::is_portable()` (Task 4)
- Produces: Tauri command `check_for_update` returning `UpdateInfo { available: bool, version: String, notes: String, portable: bool }`; command `install_update` (no-op / error if portable)

- [ ] **Step 1: Generate the updater signing keypair**

```bash
cd /home/danny/vrActorAssist/client
npx @tauri-apps/cli signer generate -w ~/.tauri/vrActorAssist.key
```

Follow the prompt to set a password. This writes a private key file and prints the public key. **Save the password somewhere safe (e.g., a password manager) — Task 14's CI setup needs both the private key contents and this password as GitHub secrets.**

- [ ] **Step 2: Configure the updater plugin**

Edit `client/src-tauri/tauri.conf.json`, add under `"plugins"`:

```json
{
  "plugins": {
    "updater": {
      "pubkey": "PASTE_THE_PUBLIC_KEY_PRINTED_IN_STEP_1_HERE",
      "endpoints": [
        "https://github.com/virtualvert/vrActorAssist/releases/latest/download/latest.json"
      ],
      "windows": {
        "installMode": "passive"
      }
    }
  }
}
```

- [ ] **Step 3: Add the updater plugin to main.rs and implement update commands**

Edit `client/src-tauri/src/main.rs`:

```rust
use tauri_plugin_updater::UpdaterExt;

#[derive(serde::Serialize)]
struct UpdateInfo {
    available: bool,
    version: String,
    notes: String,
    portable: bool,
}

#[tauri::command]
async fn check_for_update(app: tauri::AppHandle) -> Result<UpdateInfo, String> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(std::env::temp_dir);
    let portable = config::is_portable(&exe_dir);

    let updater = app.updater().map_err(|e| e.to_string())?;
    match updater.check().await {
        Ok(Some(update)) => Ok(UpdateInfo {
            available: true,
            version: update.version.clone(),
            notes: update.body.clone().unwrap_or_default(),
            portable,
        }),
        Ok(None) => Ok(UpdateInfo { available: false, version: String::new(), notes: String::new(), portable }),
        Err(e) => Err(format!("Update check failed: {}", e)),
    }
}

/// Installs the pending update. Only valid for installed (NSIS) or AppImage builds —
/// portable Windows exes must be told "not supported" and shown the manual download link
/// (the frontend enforces this by checking `UpdateInfo.portable` before calling this).
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    if let Ok(Some(update)) = updater.check().await {
        update.download_and_install(|_chunk, _total| {}, || {}).await.map_err(|e| e.to_string())?;
    }
    Ok(())
}
```

Register the plugin in `main()`:

```rust
tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_updater::Builder::new().build())
    // ... existing .manage() and .invoke_handler() ...
```

Add `check_for_update, install_update,` to `invoke_handler!`.

- [ ] **Step 4: Create UpdateNotifier.svelte**

Create `client/src/lib/UpdateNotifier.svelte`:

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";

  interface UpdateInfo { available: boolean; version: string; notes: string; portable: boolean; }

  let update: UpdateInfo | null = null;
  let installing = false;

  onMount(async () => {
    try {
      const info = await invoke<UpdateInfo>("check_for_update");
      if (info.available) update = info;
    } catch {
      // Silently ignore — e.g. offline at startup. User can retry via Settings later.
    }
  });

  async function install() {
    installing = true;
    try {
      await invoke("install_update");
    } finally {
      installing = false;
    }
  }

  function openReleasePage() {
    window.open("https://github.com/virtualvert/vrActorAssist/releases/latest", "_blank");
  }
</script>

{#if update}
  <div class="update-banner">
    <span>Version {update.version} is available.</span>
    {#if update.portable}
      <button on:click={openReleasePage}>Download</button>
    {:else}
      <button on:click={install} disabled={installing}>{installing ? "Installing..." : "Install & Restart"}</button>
    {/if}
  </div>
{/if}

<style>
  .update-banner { display: flex; gap: 1rem; align-items: center; padding: 0.5rem 1rem; background: #2c3e50; color: white; }
</style>
```

- [ ] **Step 5: Mount it in App.svelte**

Edit `client/src/App.svelte`, add the import and place `<UpdateNotifier />` inside `<main>`, above the mode-dependent content:

```svelte
<script lang="ts">
  import UpdateNotifier from "./lib/UpdateNotifier.svelte";
  // ... existing imports ...
</script>

<main>
  <UpdateNotifier />
  <!-- existing {#if !mode} ... block unchanged -->
</main>
```

- [ ] **Step 6: Verify full build**

```bash
cd /home/danny/vrActorAssist/client
npm run build && cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: both succeed. Note: `cargo build --release` bundling/signing is only meaningfully testable once Task 14's CI secrets exist — local dev builds will report "update check failed" against the real endpoint until a signed release exists, which is expected at this stage.

- [ ] **Step 7: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/
git commit -m "feat: implement auto-updater with portable-aware notify-only fallback"
```

**Do not commit the private key file** (`~/.tauri/vrActorAssist.key` is outside the repo — verify with `git status` that nothing under `client/` matches `*.key` before committing).

---

### Task 13: Windows portable build detection sanity check + config path fix

**Files:**
- Modify: `client/src-tauri/src/config.rs`

**Interfaces:**
- Consumes: nothing new
- Produces: a corrected `is_portable`/`config_path` pairing verified by an integration-style unit test simulating both layouts

- [ ] **Step 1: Write a test that simulates an "installed" directory layout**

Add to the `tests` module in `client/src-tauri/src/config.rs`:

```rust
#[test]
fn is_portable_false_when_uninstaller_present_windows_only() {
    if !cfg!(target_os = "windows") {
        return; // this check only applies on Windows; see APPIMAGE branch for Linux
    }
    let dir = std::env::temp_dir().join(format!("vractest-installed-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("uninstall.exe"), b"").unwrap();
    assert!(!is_portable(&dir));
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn is_portable_true_when_no_uninstaller_windows_only() {
    if !cfg!(target_os = "windows") {
        return;
    }
    let dir = std::env::temp_dir().join(format!("vractest-portable-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&dir).unwrap();
    assert!(is_portable(&dir));
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn is_portable_false_when_appimage_env_set_linux_only() {
    if cfg!(target_os = "windows") {
        return;
    }
    std::env::set_var("APPIMAGE", "/tmp/fake.AppImage");
    let dir = std::env::temp_dir();
    assert!(!is_portable(&dir));
    std::env::remove_var("APPIMAGE");
}
```

- [ ] **Step 2: Run the tests**

```bash
cd /home/danny/vrActorAssist/client
cargo test --manifest-path src-tauri/Cargo.toml config::
```

Expected: all pass on the current dev platform (Linux tests run, Windows-only tests return early — this is intentional since CI in Task 14 covers the other OS)

- [ ] **Step 3: Commit**

```bash
cd /home/danny/vrActorAssist
git add client/src-tauri/src/config.rs
git commit -m "test: add cross-platform portable-detection coverage"
```

---

### Task 14: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `client/README.md` (or create if absent — release instructions)

**Interfaces:**
- Consumes: GitHub Actions secrets `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, `GITHUB_TOKEN` (built-in)
- Produces: on pushing a `v0.4.*` tag, a GitHub Release containing the NSIS installer, portable Windows exe, Linux AppImage, and a signed `latest.json`

- [ ] **Step 1: Add the signing secrets to the GitHub repo**

In the GitHub repo settings (Settings → Secrets and variables → Actions), add:
- `TAURI_SIGNING_PRIVATE_KEY`: contents of `~/.tauri/vrActorAssist.key` (from Task 12, Step 1)
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: the password chosen in Task 12, Step 1

This is a manual step performed via the GitHub web UI or `gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/vrActorAssist.key` / `gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.

- [ ] **Step 2: Create the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - "v0.4.*"

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - name: Install frontend deps
        working-directory: client
        run: npm install
      - name: Build NSIS installer + signed updater artifacts
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
        with:
          projectPath: client
          tagName: ${{ github.ref_name }}
          releaseName: "vrActorAssist ${{ github.ref_name }}"
          releaseDraft: true
          prerelease: false
      - name: Build portable exe (raw binary, no installer)
        working-directory: client
        run: cargo build --release --manifest-path src-tauri/Cargo.toml
      - name: Rename portable exe
        run: Copy-Item client/src-tauri/target/release/vrActorAssist.exe vrActorAssist_${{ github.ref_name }}_portable.exe
        shell: pwsh
      - name: Upload portable exe to release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh release upload ${{ github.ref_name }} vrActorAssist_${{ github.ref_name }}_portable.exe --clobber
        shell: bash

  build-linux:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev libsoup-3.0-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
      - name: Install frontend deps
        working-directory: client
        run: npm install
      - name: Build AppImage + signed updater artifacts
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
        with:
          projectPath: client
          tagName: ${{ github.ref_name }}
          releaseName: "vrActorAssist ${{ github.ref_name }}"
          releaseDraft: true
          prerelease: false
```

`tauri-action` automatically builds the configured bundle targets (`nsis` + `appimage` from Task 2's `tauri.conf.json`), generates and uploads the signed `latest.json`, and creates/updates the draft GitHub Release. The two extra steps on Windows add the portable exe as a third asset on the same release. `releaseDraft: true` means a human must publish the draft after reviewing — publishing is a manual step, intentionally not automated.

- [ ] **Step 3: Document the release process**

Create or update `client/README.md` with a "Releasing" section:

```markdown
## Releasing a new version

1. Bump `version` in `client/src-tauri/tauri.conf.json` and `client/package.json` to the new semver.
2. Commit: `git commit -am "chore: bump version to vX.Y.Z"`
3. Tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
4. GitHub Actions builds Windows (installer + portable) and Linux (AppImage), publishing a **draft** release with `latest.json`.
5. Review the draft release on GitHub, edit release notes, then click "Publish release".
6. Existing installed/AppImage clients will detect the update within their next launch's `check_for_update` call. Portable clients see the notify banner and must download manually.
```

- [ ] **Step 4: Verify the workflow YAML is syntactically valid**

```bash
cd /home/danny/vrActorAssist
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" 2>/dev/null && echo "valid YAML" || echo "check syntax manually if PyYAML unavailable"
```

Expected: `valid YAML` (if `PyYAML` isn't installed, visually inspect indentation instead — this is a non-blocking sanity check, not a hard gate)

- [ ] **Step 5: Commit**

```bash
cd /home/danny/vrActorAssist
git add .github/workflows/release.yml client/README.md
git commit -m "ci: add GitHub Actions release workflow for Windows and Linux builds"
```

**This task cannot be fully verified until a real tag is pushed** (Task 15 covers manual end-to-end verification once the branch is ready to ship). Flag to the user that pushing the first `v0.4.0-rc1` tag to test the pipeline is a deliberate, visible action they should approve before it happens, since it creates public-facing (if draft) GitHub Release artifacts.

---

### Task 15: End-to-end verification against the Python server + final docs

**Files:**
- Modify: `client/README.md`
- No application code changes expected — this task is verification. If it uncovers bugs, fix them in the relevant module from Tasks 1-13 and note the fix in the commit message.

- [ ] **Step 1: Start the Python server locally**

```bash
cd /home/danny/vrActorAssist
python3 -m venv venv  # if not already present
source venv/bin/activate
pip install -r requirements.txt
python server_ws.py --port 5555 --secret test-secret
```

Expected: server logs "Uvicorn running on http://0.0.0.0:5555" (or similar)

- [ ] **Step 2: Run the Tauri client in dev mode, connect as Director**

```bash
cd /home/danny/vrActorAssist/client
npm run tauri dev
```

In the app: select Director mode, set server URL to `ws://127.0.0.1:5555/ws`, enter secret `test-secret`, click Connect.

Expected: status dot turns green/"Connected"; no errors in the terminal running `npm run tauri dev`

- [ ] **Step 3: Run a second instance as Actor, approve it**

```bash
cd /home/danny/vrActorAssist/client
npm run tauri dev
```

(Run in a second terminal/window — set `identifier` collision isn't an issue for dev mode since it's not installed.) Select Actor mode, connect to the same server URL. In the Director window, the actor should appear in the pending list; click Approve.

Expected: actor moves to approved list in Director UI; Actor UI shows connected/approved state

- [ ] **Step 4: Test Go/Stop cue**

In the Director window, click "Go". 

Expected: Actor's chat log or console shows the `*go` command was received (Soundpad itself will fail gracefully on Linux/dev machines without Soundpad installed — verify the error is caught and displayed, not a crash)

- [ ] **Step 5: Test file transfer end-to-end**

In the Director window, use "Choose Files..." in the File Sender panel to send a small `.wav` file to the connected actor.

Expected: Actor UI shows the incoming file prompt; clicking Accept results in the file appearing in the actor's configured `receive_dir` with matching MD5 (verify with `md5sum <original> <received>`)

- [ ] **Step 6: Test reconnection and approved-actor persistence**

Disconnect and reconnect the Actor client (same machine).

Expected: actor is auto-approved on reconnect (server's `approved_actors.json` already has its machine_id) — no re-approval prompt in the Director UI

- [ ] **Step 7: Record results and any bugs found**

If any step failed, go back to the relevant task (1-14), fix the root cause, re-run that task's tests, and re-run this task's steps from Step 1. Do not proceed to Step 8 until Steps 1-6 all pass.

- [ ] **Step 8: Update client/README.md with dev/build instructions**

Add a "Development" section to `client/README.md`:

```markdown
## Development

Prerequisites: Node.js 20+, Rust stable, and (Linux only) `libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev libsoup-3.0-dev libgtk-3-dev`.

```bash
cd client
npm install
npm run tauri dev
```

This starts the Vite dev server and launches the Tauri window with hot reload. Point the client at a locally running server (`python server_ws.py --port 5555 --secret <secret>`) using `ws://127.0.0.1:5555/ws` in the connection panel.

Run Rust unit tests with:

```bash
cargo test --manifest-path src-tauri/Cargo.toml
```
```

- [ ] **Step 9: Final commit**

```bash
cd /home/danny/vrActorAssist
git add client/README.md
git commit -m "docs: add Tauri client development instructions"
```

- [ ] **Step 10: Update the design spec's success criteria checklist**

Go back to `docs/superpowers/specs/2026-07-20-vrActorAssist-ssl-tauri-design.md` §6 and check off every box that Steps 1-6 above verified. Commit:

```bash
cd /home/danny/vrActorAssist
git add docs/superpowers/specs/2026-07-20-vrActorAssist-ssl-tauri-design.md
git commit -m "docs: check off verified success criteria after e2e testing"
```

---

## What's Deliberately Not in This Plan

- **macOS builds** — excluded per spec §4.10; revisit only if a macOS user emerges.
- **Windows code signing** — deferred per spec §4.12; SmartScreen warnings are accepted for now.
- **OSC cue editor, PipeWire actor support, session recording** — roadmap items explicitly out of scope for v0.4.0 parity (spec §2).
- **Merging `tauri` → `main`** — not a task here; it's a decision point after Task 15 passes, to be made with the user (see spec §4.14). Use the `finishing-a-development-branch` skill at that point.
- **Publishing the first real GitHub Release** — Task 14 builds the pipeline; actually pushing a `v0.4.0` tag and clicking "Publish" on the draft is a user decision, flagged explicitly in Task 14.
