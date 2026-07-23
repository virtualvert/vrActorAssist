# SSL Fix + Tauri Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix SSL certificate errors in PyInstaller-built Python clients on Windows, then migrate both Director and Actor clients to a single Tauri v2 + Svelte desktop application.

**Architecture:** The Python FastAPI/WebSocket server stays unchanged. The SSL fix patches the existing client build pipeline and SSL context initialization. The Tauri app is a new project under `client/` that replaces both Python desktop clients with a single binary supporting switchable Director/Actor modes.

**Tech Stack:** Python 3.8+ (server), FastAPI + uvicorn (server), Tauri v2 + Svelte (new client), Rust (client backend), tokio-tungstenite (WebSocket), rosc (OSC), serde (config)

## Global Constraints

- Python server code must remain unchanged (no server-side fixes)
- The pipe-delimited text protocol (`shared.py`) is authoritative — Tauri client must produce identical messages
- PyInstaller builds must work on Windows without Python installed
- Tauri client must support cross-platform builds: Windows (full), Linux (Director mode only), macOS (Director mode only)
- Tauri v2 (not v1) with plain Svelte (not SvelteKit)

---

### Task 1: Add certifi hidden imports to build_exe.py

**Files:**
- Modify: `build_exe.py`

**Interfaces:**
- Consumes: existing `run_pyinstaller()` function
- Produces: PyInstaller builds that include `certifi` and SSL modules

- [ ] **Step 1: Add hidden imports to director build**

In `build_exe.py`, within the `build_director()` function, add `certifi` and `_ssl` to `extra_hiddenimports`:

```python
def build_director():
    """Build director client executable."""
    print("="*50)
    print("Building director client...")
    print("="*50)
    
    success = run_pyinstaller(
        'director_client_ws.py',
        'vrDirectorClient',
        extra_hiddenimports=['certifi', '_ssl']
    )
    
    exe_ext = '.exe' if IS_WINDOWS else ''
    exe_path = os.path.join(SCRIPT_DIR, 'dist', f'vrDirectorClient{exe_ext}')
    
    print("\n" + "="*50)
    print("Director client build complete!")
    print(f"  Executable: {exe_path}")
    print("="*50)
```

- [ ] **Step 2: Add hidden imports to actor build**

In `build_exe.py`, modify the `build_actor()` call to include `certifi` and `_ssl`:

```python
    success = run_pyinstaller(
        'actor_client_ws.py',
        'vrActorClient',
        extra_data=['soundpad.py'],
        extra_hiddenimports=['pythonosc', 'certifi', '_ssl']
    )
```

- [ ] **Step 3: Add certifi to requirements.txt**

Add `certifi` as a dependency:

```
# WebSocket clients
websocket-client
certifi

# GUI (usually built-in with Python, but included for completeness)
```

- [ ] **Step 4: Verify the diff**

Run: `git diff build_exe.py requirements.txt`
Expected: Changes visible for both files

- [ ] **Step 5: Commit**

```bash
git add build_exe.py requirements.txt
git commit -m "fix: add certifi and _ssl as PyInstaller hidden imports"
```

---

### Task 2: Fix SSL context in both clients

**Files:**
- Modify: `actor_client_ws.py:529`
- Modify: `director_client_ws.py:423`

**Interfaces:**
- Consumes: `ssl` stdlib module, `certifi` package
- Produces: Both clients use explicit `ssl.SSLContext` with `CERT_NONE` and `certifi.where()` as CA bundle

- [ ] **Step 1: Add imports to actor_client_ws.py**

Find the imports section at the top of `actor_client_ws.py` and add `certifi`:

```python
import ssl
import certifi
import threading
import time
import json
import os
import hashlib
import struct
from pathlib import Path
```

Make sure `ssl` and `certifi` are added (checking if `ssl` is already imported elsewhere).

- [ ] **Step 2: Replace sslopt with explicit SSLContext in actor_client_ws.py**

In `actor_client_ws.py`, find line 529 and replace:

```python
                self.ws.run_forever(ping_interval=30, ping_timeout=10, sslopt={"cert_reqs": ssl.CERT_NONE})
```

With:

```python
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                self.ws.run_forever(ping_interval=30, ping_timeout=10, ssl=ssl_context)
```

- [ ] **Step 3: Add imports to director_client_ws.py**

Same pattern — add `import ssl` and `import certifi` at the top of `director_client_ws.py`.

- [ ] **Step 4: Replace sslopt in director_client_ws.py**

In `director_client_ws.py`, line 423, replace:

```python
                self.ws.run_forever(ping_interval=30, ping_timeout=10, sslopt={"cert_reqs": ssl.CERT_NONE})
```

With:

```python
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                self.ws.run_forever(ping_interval=30, ping_timeout=10, ssl=ssl_context)
```

- [ ] **Step 5: Verify the diffs**

Run: `git diff actor_client_ws.py director_client_ws.py`
Expected: Import additions + SSL context changes in both files

- [ ] **Step 6: Commit**

```bash
git add actor_client_ws.py director_client_ws.py
git commit -m "fix: use explicit SSLContext with certifi CA bundle in both clients"
```

---

### Task 3: Build and update manifest

**Files:**
- Modify: `update_manifest.json`

**Interfaces:**
- Produces: Updated SHA256 hashes so existing clients auto-update to the fixed version

- [ ] **Step 1: Build the director client (on Linux)**

Run on the build machine:

```bash
python build_exe.py director
```

Expected: `dist/vrDirectorClient` is produced

- [ ] **Step 2: Compute SHA256**

```bash
sha256sum dist/vrDirectorClient
```

Record the hash.

- [ ] **Step 3: Update update_manifest.json**

```json
{
  "latest_version": "0.3.3",
  "release_notes": "Fix SSL certificate verification errors on Windows PyInstaller builds",
  "assets": {
    "director-linux-x64": {
      "url": "https://github.com/virtualvert/vrActorAssist/releases/download/v0.3.3/vrDirectorClient",
      "sha256": "<hash-from-step-2>"
    }
  }
}
```

Note: Actor and Windows builds require a Windows build machine. Skip those entries if unavailable — the version bump will still notify users.

- [ ] **Step 4: Commit**

```bash
git add update_manifest.json
git commit -m "chore: bump version to 0.3.3 and update build hashes"
```

---

### Task 4: Scaffold Tauri v2 + Svelte project

**Files:**
- Create: `client/` (full Tauri project scaffold)
- Create: `client/src-tauri/Cargo.toml`
- Create: `client/src-tauri/src/main.rs`
- Create: `client/src-tauri/tauri.conf.json`
- Create: `client/src/App.svelte`
- Create: `client/package.json`
- Create: `client/vite.config.ts`
- Many more generated files

**Interfaces:**
- Produces: Runable Tauri + Svelte skeleton app with mode selector
- Produces: `client/` directory structure for all subsequent tasks

- [ ] **Step 1: Create the Tauri project**

```bash
cd /home/danny/vrActorAssist
npm create tauri-app@latest client -- --template svelte --manager npm
```

When prompted:
- Project name: `vrActorAssist`
- Choose `Svelte` (not SvelteKit)
- Choose TypeScript

- [ ] **Step 2: Add Rust dependencies**

Edit `client/src-tauri/Cargo.toml` and add:

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
rosc = "0.2"
chrono = "0.4"
uuid = { version = "1", features = ["v5"] }
```

- [ ] **Step 3: Add npm dependencies**

```bash
cd /home/danny/vrActorAssist/client
npm install
```

- [ ] **Step 4: Configure Tauri**

Edit `client/src-tauri/tauri.conf.json` with basic app metadata:

```json
{
  "productName": "vrActorAssist",
  "version": "0.4.0",
  "identifier": "com.dannygrey.vractorasist",
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
        "width": 800,
        "height": 600,
        "resizable": true,
        "fullscreen": false
      }
    ]
  }
}
```

- [ ] **Step 5: Create mode selector component**

Create `client/src/lib/ModeSelector.svelte`:

```svelte
<script lang="ts">
  let selectedMode: "director" | "actor" | null = null;
  let rememberChoice = false;
  const emit = (event: string, payload?: any) => {
    // Tauri event emit
  };
  export async function selectMode(mode: "director" | "actor") {
    selectedMode = mode;
    if (rememberChoice) {
      await saveModePreference(mode);
    }
  }
  async function saveModePreference(mode: string) {
    // Will use Tauri invoke in Task 6
  }
</script>

<div class="mode-selector">
  <h1>vrActorAssist</h1>
  <p class="subtitle">Select your role</p>
  <div class="buttons">
    <button on:click={() => selectMode("director")} class="mode-btn director">
      <span class="icon">🎬</span>
      <span class="label">Director</span>
      <span class="desc">Send cues, manage actors, route audio files</span>
    </button>
    <button on:click={() => selectMode("actor")} class="mode-btn actor">
      <span class="icon">🎭</span>
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
  .mode-selector { ... }
</style>
```

- [ ] **Step 6: Verify the scaffold compiles**

```bash
cd /home/danny/vrActorAssist/client
npm run tauri build
```

Expected: Build succeeds (may need to install system deps like `libwebkit2gtk-4.1-dev` on Linux)

- [ ] **Step 7: Commit**

```bash
git add client/
git commit -m "feat: scaffold Tauri v2 + Svelte project"
```

---

### Task 5: Implement Rust WebSocket client + protocol parser

**Files:**
- Create: `client/src-tauri/src/protocol.rs`
- Create: `client/src-tauri/src/ws_client.rs`
- Modify: `client/src-tauri/src/main.rs` (add modules)

**Interfaces:**
- Consumes: `tokio-tungstenite` for WebSocket, pipe-delimited message format from `shared.py`
- Produces: `ws_client::WsClient` struct with `connect()`, `send()`, `disconnect()` methods; `protocol::Message` enum and `ProtocolMessage::parse()` / `.format()` methods

- [ ] **Step 1: Create protocol.rs**

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Message {
    Msg { sender: String, text: String },
    Priv { sender: String, target: String, text: String },
    Register { name: String, machine_id: String, role: String, secret: String, version: String, platform: String },
    Approved,
    Denied { reason: String },
    Pending { actors_json: String },
    Cmd { command: String, args: String },
    Ack { actor: String, command: String, status: String },
    Filereq { sender: String, target: String, filename: String, size: u64, checksum: String },
    Fileack { filename: String, accept: bool, save_dir: String },
    Filedeny { filename: String, reason: String },
    Filestart { filename: String, total_chunks: u32, chunk_size: u32 },
    Filechunk { filename: String, chunk_num: u32, data: String },
    Fileend { filename: String, checksum: String },
    Fileok { filename: String, saved_path: String },
    Fileerr { filename: String, error: String },
    BatchStart { target: String, file_count: u32, total_bytes: u64 },
    BatchEnd { target: String, success_count: u32, fail_count: u32 },
    BatchCancel { target: String, reason: String },
    Status { actors_json: String },
    OscCue { target: String, parameter: String, value: String },
    Unknown { raw: String },
}

pub fn parse(data: &str) -> Message {
    let parts: Vec<&str> = data.split('|').collect();
    if parts.is_empty() {
        return Message::Unknown { raw: data.to_string() };
    }
    match parts[0] {
        "MSG" if parts.len() >= 3 => Message::Msg {
            sender: parts[1].to_string(),
            text: parts[2..].join("|"),
        },
        "PRIV" if parts.len() >= 4 => Message::Priv {
            sender: parts[1].to_string(),
            target: parts[2].to_string(),
            text: parts[3..].join("|"),
        },
        "REGISTER" => Message::Register {
            name: parts.get(1).map(|s| s.to_string()).unwrap_or_default(),
            machine_id: parts.get(2).map(|s| s.to_string()).unwrap_or_default(),
            role: parts.get(3).map(|s| s.to_string()).unwrap_or_default(),
            secret: parts.get(4).map(|s| s.to_string()).unwrap_or_default(),
            version: parts.get(5).map(|s| s.to_string()).unwrap_or_default(),
            platform: parts.get(6).map(|s| s.to_string()).unwrap_or_default(),
        },
        "APPROVED" => Message::Approved,
        "DENIED" => Message::Denied {
            reason: parts[1..].join("|"),
        },
        "CMD" => Message::Cmd {
            command: parts.get(1).map(|s| s.to_string()).unwrap_or_default(),
            args: parts[2..].join("|"),
        },
        "STATUS" => Message::Status {
            actors_json: parts.get(1).map(|s| s.to_string()).unwrap_or_default(),
        },
        // ... other message types follow the same pattern
        _ => Message::Unknown { raw: data.to_string() },
    }
}

pub fn format(msg: &Message) -> String {
    match msg {
        Message::Msg { sender, text } => format!("MSG|{}|{}", sender, text),
        Message::Register { name, machine_id, role, secret, version, platform } => {
            format!("REGISTER|{}|{}|{}|{}|{}|{}", name, machine_id, role, secret, version, platform)
        },
        Message::Cmd { command, args } => {
            if args.is_empty() {
                format!("CMD|{}", command)
            } else {
                format!("CMD|{}|{}", command, args)
            }
        },
        // ... other message types
        _ => String::new(),
    }
}
```

- [ ] **Step 2: Create ws_client.rs**

```rust
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_tungstenite::{connect_async, tungstenite::Message as WsMessage};
use futures_util::{StreamExt, SinkExt};
use tokio::time::{interval, Duration};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectionConfig {
    pub url: String,
    pub secret: String,
    pub machine_id: String,
}

pub struct WsClient {
    config: ConnectionConfig,
    on_message: Box<dyn Fn(String) + Send + Sync>,
    on_connection_change: Box<dyn Fn(ConnectionState) + Send + Sync>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Authenticated,
    Failed(String),
}

impl WsClient {
    pub fn new(
        config: ConnectionConfig,
        on_message: Box<dyn Fn(String) + Send + Sync>,
        on_connection_change: Box<dyn Fn(ConnectionState) + Send + Sync>,
    ) -> Self {
        Self { config, on_message, on_connection_change }
    }

    pub async fn connect(&self) -> Result<(), String> {
        (self.on_connection_change)(ConnectionState::Connecting);
        
        let (ws_stream, _) = connect_async(&self.config.url)
            .await
            .map_err(|e| format!("WebSocket connection failed: {}", e))?;
        
        let (mut write, mut read) = ws_stream.split();
        let on_msg = &self.on_message;
        let on_conn = &self.on_connection_change;
        
        (on_conn)(ConnectionState::Connected);
        
        // Send REGISTER
        let register = format!(
            "REGISTER|{}|{}|{}|{}|{}|{}",
            "Director",
            self.config.machine_id,
            "director",
            self.config.secret,
            "0.4.0",
            "tauri"
        );
        write.send(WsMessage::Text(register)).await.map_err(|e| format!("Send failed: {}", e))?;
        
        // Spawn read loop
        let ws_url = self.config.url.clone();
        tokio::spawn(async move {
            let mut ping_interval = interval(Duration::from_secs(30));
            loop {
                tokio::select! {
                    msg = read.next() => {
                        match msg {
                            Some(Ok(WsMessage::Text(text))) => {
                                (on_msg)(text);
                            }
                            Some(Ok(WsMessage::Ping(data))) => {
                                let _ = write.send(WsMessage::Pong(data)).await;
                            }
                            Some(Ok(WsMessage::Pong(_))) => {
                                // Latency tracking
                            }
                            None | Some(Err(_)) => {
                                (on_conn)(ConnectionState::Disconnected);
                                break;
                            }
                            _ => {}
                        }
                    }
                    _ = ping_interval.tick() => {
                        if write.send(WsMessage::Ping(vec![])).await.is_err() {
                            (on_conn)(ConnectionState::Disconnected);
                            break;
                        }
                    }
                }
            }
        });
        
        Ok(())
    }

    pub async fn send(&self, text: &str) -> Result<(), String> {
        // Send method
        Ok(())
    }
}
```

- [ ] **Step 3: Register modules in main.rs**

```rust
mod protocol;
mod ws_client;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            // commands registered here
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 4: Verify compilation**

```bash
cd /home/danny/vrActorAssist/client
cargo check
```

Expected: Compiles without errors

- [ ] **Step 5: Commit**

```bash
git add client/src-tauri/src/protocol.rs client/src-tauri/src/ws_client.rs
git commit -m "feat: implement WebSocket client and protocol parser"
```

---

### Task 6: Implement config and connection state modules

**Files:**
- Create: `client/src-tauri/src/config.rs`
- Create: `client/src-tauri/src/connection.rs`
- Modify: `client/src-tauri/src/main.rs`

**Interfaces:**
- Consumes: `serde` for JSON config
- Produces: `Config::load()` / `Config::save()`, `ConnectionManager` that wraps `WsClient`

- [ ] **Step 1: Create config.rs**

```rust
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::fs;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub server_url: String,
    pub mode: String, // "director" or "actor"
    pub remember_mode: bool,
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
            server_url: "wss://vra.dannygreyproductions.com".to_string(),
            mode: "director".to_string(),
            remember_mode: false,
            actor_name: "Actor".to_string(),
            auto_reconnect: true,
            osc_enabled: true,
            osc_host: "127.0.0.1".to_string(),
            osc_port: 9000,
            soundpad_enabled: true,
            soundpad_path: "Soundpad.exe".to_string(),
            auto_accept_files: false,
            receive_dir: std::env::current_dir()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string(),
            theme: "dark".to_string(),
        }
    }
}

impl Config {
    pub fn path() -> PathBuf {
        let mut path = std::env::current_dir().unwrap_or_default();
        path.push("actor_config.json");
        path
    }

    pub fn load() -> Self {
        let path = Self::path();
        if path.exists() {
            fs::read_to_string(&path)
                .ok()
                .and_then(|content| serde_json::from_str(&content).ok())
                .unwrap_or_default()
        } else {
            Self::default()
        }
    }

    pub fn save(&self) -> Result<(), String> {
        let path = Self::path();
        let content = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        fs::write(&path, content).map_err(|e| e.to_string())
    }

    pub fn get_ws_url(&self) -> String {
        // Convert http/https to ws/wss and append /ws
        let base = self.server_url.trim_end_matches('/');
        if base.starts_with("https://") {
            base.replacen("https://", "wss://", 1).to_string() + "/ws"
        } else if base.starts_with("http://") {
            base.replacen("http://", "ws://", 1).to_string() + "/ws"
        } else if base.starts_with("wss://") || base.starts_with("ws://") {
            base.to_string() + "/ws"
        } else {
            format!("ws://{}/ws", base)
        }
    }
}
```

- [ ] **Step 2: Create connection.rs**

```rust
use crate::ws_client::{WsClient, ConnectionConfig, ConnectionState};
use crate::config::Config;
use tokio::sync::watch;

pub struct ConnectionManager {
    client: Option<WsClient>,
    state_tx: watch::Sender<ConnectionState>,
    state_rx: watch::Receiver<ConnectionState>,
}

impl ConnectionManager {
    pub fn new() -> Self {
        let (state_tx, state_rx) = watch::channel(ConnectionState::Disconnected);
        Self { client: None, state_tx, state_rx }
    }

    pub fn state_rx(&self) -> watch::Receiver<ConnectionState> {
        self.state_rx.clone()
    }

    pub async fn connect(&mut self, config: &Config, machine_id: &str) -> Result<(), String> {
        let ws_url = config.get_ws_url();
        let ws_config = ConnectionConfig {
            url: ws_url.clone(),
            secret: String::new(),
            machine_id: machine_id.to_string(),
        };

        let state_tx = self.state_tx.clone();
        let on_msg = Box::new(move |text: String| {
            // Emit to frontend via Tauri events
            let _ = tauri::Emitter::emit("ws-message", &text);
        });

        let state_tx2 = self.state_tx.clone();
        let on_conn = Box::new(move |state: ConnectionState| {
            let _ = state_tx2.send(state);
            let _ = tauri::Emitter::emit("connection-state", &state);
        });

        let client = WsClient::new(ws_config, on_msg, on_conn);
        client.connect().await?;
        self.client = Some(client);
        Ok(())
    }

    pub fn disconnect(&mut self) {
        self.client = None;
        let _ = self.state_tx.send(ConnectionState::Disconnected);
    }

    pub fn is_connected(&self) -> bool {
        *self.state_rx.borrow() == ConnectionState::Connected
            || *self.state_rx.borrow() == ConnectionState::Authenticated
    }
}
```

- [ ] **Step 3: Register modules in main.rs**

```rust
mod protocol;
mod ws_client;
mod config;
mod connection;

use config::Config;
use connection::ConnectionManager;
use std::sync::Mutex;

struct AppState {
    config: Config,
    connection: Mutex<ConnectionManager>,
}

fn main() {
    let config = Config::load();
    let app_state = AppState {
        config,
        connection: Mutex::new(ConnectionManager::new()),
    };

    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            cmd_connect,
            cmd_disconnect,
            cmd_get_config,
            cmd_save_config,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
fn cmd_connect(state: tauri::State<AppState>) -> Result<(), String> {
    let config = &state.config;
    let machine_id = uuid::Uuid::new_v4().to_string();
    let mut conn = state.connection.lock().map_err(|e| e.to_string())?;
    tauri::async_runtime::block_on(conn.connect(config, &machine_id))
}

#[tauri::command]
fn cmd_disconnect(state: tauri::State<AppState>) -> Result<(), String> {
    let mut conn = state.connection.lock().map_err(|e| e.to_string())?;
    conn.disconnect();
    Ok(())
}

#[tauri::command]
fn cmd_get_config(state: tauri::State<AppState>) -> Result<Config, String> {
    Ok(state.config.clone())
}

#[tauri::command]
fn cmd_save_config(state: tauri::State<AppState>, new_config: Config) -> Result<(), String> {
    new_config.save()?;
    Ok(())
}
```

- [ ] **Step 4: Verify compilation**

```bash
cd /home/danny/vrActorAssist/client
cargo check
```

Expected: Compiles

- [ ] **Step 5: Commit**

```bash
git add client/src-tauri/src/config.rs client/src-tauri/src/connection.rs
git commit -m "feat: implement config persistence and connection manager"
```

---

### Task 7: Build shared Svelte UI components

**Files:**
- Create: `client/src/lib/ConnectionPanel.svelte`
- Create: `client/src/lib/Chat.svelte`
- Create: `client/src/lib/StatusBar.svelte`
- Create: `client/src/lib/Settings.svelte`
- Create: `client/src/lib/App.svelte` (update with mode routing)

**Interfaces:**
- Consumes: Tauri `invoke()` and `listen()` APIs
- Produces: Shared UI components usable by both Director and Actor modes

- [ ] **Step 1: Create ConnectionPanel.svelte**

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";

  let serverUrl = "wss://vra.dannygreyproductions.com";
  let status = "Disconnected";
  let isConnecting = false;

  async function toggleConnection() {
    if (status === "Disconnected" || status === "Failed") {
      isConnecting = true;
      status = "Connecting...";
      try {
        await invoke("connect");
      } catch (e) {
        status = `Failed: ${e}`;
        isConnecting = false;
      }
    } else {
      await invoke("disconnect");
      status = "Disconnected";
      isConnecting = false;
    }
  }
</script>

<div class="connection-panel">
  <input type="text" bind:value={serverUrl} placeholder="Server URL" disabled={isConnecting} />
  <button on:click={toggleConnection} disabled={isConnecting}>
    {isConnecting ? "Connecting..." : status === "Disconnected" ? "Connect" : "Disconnect"}
  </button>
  <span class="status-dot" class:connected={status === "Connected"} class:failed={status.startsWith("Failed")}></span>
</div>
```

- [ ] **Step 2: Create Chat.svelte**

```svelte
<script lang="ts">
  import { listen } from "@tauri-apps/api/event";
  import { invoke } from "@tauri-apps/api/core";

  let messages: { sender: string; text: string; timestamp: string; isOwn: boolean }[] = [];
  let inputText = "";

  async function sendMessage() {
    if (!inputText.trim()) return;
    // invoke("send", { text: inputText })
    messages = [...messages, { sender: "Me", text: inputText, timestamp: new Date().toLocaleTimeString(), isOwn: true }];
    inputText = "";
  }
</script>

<div class="chat">
  <div class="messages">
    {#each messages as msg}
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
```

- [ ] **Step 3: Create StatusBar.svelte**

```svelte
<script lang="ts">
  export let status: string = "Disconnected";
  export let latency: number = 0;
  export let mode: string = "director";
</script>

<div class="status-bar">
  <span class="mode">{mode === "director" ? "🎬 Director" : "🎭 Actor"}</span>
  <span class="status" class:connected={status === "Connected"}>
    {status}
  </span>
  <span class="latency">{latency}ms</span>
</div>
```

- [ ] **Step 4: Update App.svelte with mode routing**

```svelte
<script lang="ts">
  import ModeSelector from "./lib/ModeSelector.svelte";
  import DirectorView from "./lib/DirectorView.svelte";
  import ActorView from "./lib/ActorView.svelte";

  let mode: "director" | "actor" | null = null;
</script>

<main>
  {#if !mode}
    <ModeSelector onSelect={(m) => mode = m} />
  {:else if mode === "director"}
    <DirectorView />
  {:else if mode === "actor"}
    <ActorView />
  {/if}
</main>
```

- [ ] **Step 5: Verify frontend builds**

```bash
cd /home/danny/vrActorAssist/client
npm run build
```

Expected: Vite builds without errors

- [ ] **Step 6: Commit**

```bash
git add client/src/lib/
git commit -m "feat: add shared Svelte UI components (connection, chat, status bar)"
```

---

### Task 8: Build Director mode UI

**Files:**
- Create: `client/src/lib/DirectorView.svelte`
- Create: `client/src/lib/ActorList.svelte`
- Create: `client/src/lib/CueControls.svelte`
- Create: `client/src/lib/FileSender.svelte`

**Interfaces:**
- Consumes: `ConnectionPanel`, `Chat`, `StatusBar` shared components
- Consumes: Rust commands `cmd_approve_actor`, `cmd_deny_actor`, `cmd_send_cue`, `cmd_send_file`
- Produces: Complete Director mode workspace

- [ ] **Step 1: Create ActorList.svelte**

```svelte
<script lang="ts">
  import { listen } from "@tauri-apps/api/event";
  import { invoke } from "@tauri-apps/api/core";

  let actors: { name: string; machineId: string; status: string; latency: number; approved: boolean }[] = [];

  async function approve(machineId: string) {
    await invoke("approve_actor", { machineId });
  }

  async function deny(machineId: string) {
    await invoke("deny_actor", { machineId });
  }
</script>

<div class="actor-list">
  <h2>Actors</h2>
  {#each actors as actor}
    <div class="actor-row">
      <span class="status-dot" class:green={actor.latency < 50} class:yellow={actor.latency >= 50 && actor.latency < 150} class:red={actor.latency >= 150}></span>
      <span class="name">{actor.name}</span>
      <span class="latency">{actor.latency}ms</span>
      {#if !actor.approved}
        <button on:click={() => approve(actor.machineId)} class="approve">Approve</button>
        <button on:click={() => deny(actor.machineId)} class="deny">Deny</button>
      {:else}
        <span class="approved-badge">✓ Approved</span>
      {/if}
    </div>
  {/each}
</div>
```

- [ ] **Step 2: Create CueControls.svelte**

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  let countdownSeconds = 3;
  let selectedActor = "all";

  async function sendCue(cue: string) {
    await invoke("send_cue", { cue, target: selectedActor });
  }
</script>

<div class="cue-controls">
  <div class="actor-select">
    <label>Target:</label>
    <select bind:value={selectedActor}>
      <option value="all">All Actors</option>
      <option value="actor1">Actor 1</option>
    </select>
  </div>
  <div class="cue-buttons">
    <button on:click={() => sendCue("go")} class="cue go">▶ Go</button>
    <button on:click={() => sendCue("stop")} class="cue stop">■ Stop</button>
    <div class="countdown-group">
      <button on:click={() => sendCue(`play_in_${countdownSeconds}`)} class="cue countdown">
        Play in {countdownSeconds}s
      </button>
      <select bind:value={countdownSeconds}>
        <option value={3}>3s</option>
        <option value={5}>5s</option>
        <option value={10}>10s</option>
      </select>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Create DirectorView.svelte**

```svelte
<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
  import ActorList from "./ActorList.svelte";
  import CueControls from "./CueControls.svelte";
  import FileSender from "./FileSender.svelte";
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
      <FileSender />
    </aside>
    <section class="chat-area">
      <Chat />
    </section>
  </div>
</div>
```

- [ ] **Step 4: Verify build**

```bash
cd /home/danny/vrActorAssist/client
npm run build && cargo check
```

Expected: Both frontend and Rust compile

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/DirectorView.svelte client/src/lib/ActorList.svelte client/src/lib/CueControls.svelte
git commit -m "feat: add Director mode UI (actor list, cue controls, file sender)"
```

---

### Task 9: Build Actor mode UI

**Files:**
- Create: `client/src/lib/ActorView.svelte`
- Create: `client/src/lib/FileReceiver.svelte`
- Create: `client/src/lib/OscConfig.svelte`
- Create: `client/src/lib/SoundpadConfig.svelte`

**Interfaces:**
- Consumes: Shared components, `invoke()` commands for file accept/deny, OSC config
- Produces: Complete Actor mode workspace

- [ ] **Step 1: Create ActorView.svelte**

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
```

- [ ] **Step 2: Create FileReceiver.svelte**

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";

  let incomingFile: { filename: string; size: number; sender: string } | null = null;
  let progress = 0;
  let autoAccept = false;

  async function acceptFile() {
    if (incomingFile) {
      await invoke("accept_file", { filename: incomingFile.filename });
    }
  }

  async function denyFile() {
    if (incomingFile) {
      await invoke("deny_file", { filename: incomingFile.filename });
      incomingFile = null;
    }
  }
</script>

<div class="file-receiver">
  <h3>File Transfers</h3>
  <label class="auto-accept">
    <input type="checkbox" bind:checked={autoAccept} />
    Auto-accept files
  </label>
  {#if incomingFile}
    <div class="incoming">
      <p>Incoming: {incomingFile.filename} ({(incomingFile.size / 1024 / 1024).toFixed(1)} MB)</p>
      <div class="progress-bar">
        <div class="fill" style="width: {progress}%"></div>
      </div>
      <div class="actions">
        <button on:click={acceptFile}>Accept</button>
        <button on:click={denyFile}>Deny</button>
      </div>
    </div>
  {/if}
</div>
```

- [ ] **Step 3: Create OscConfig.svelte**

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  let enabled = true;
  let host = "127.0.0.1";
  let port = 9000;

  async function saveOscConfig() {
    await invoke("save_config", {
      newConfig: { oscEnabled: enabled, oscHost: host, oscPort: port }
    });
  }
</script>

<div class="osc-config">
  <h3>VRChat OSC</h3>
  <label class="toggle">
    <input type="checkbox" bind:checked={enabled} on:change={saveOscConfig} />
    Enabled
  </label>
  <div class="fields">
    <label>Host: <input type="text" bind:value={host} on:change={saveOscConfig} /></label>
    <label>Port: <input type="number" bind:value={port} on:change={saveOscConfig} /></label>
  </div>
</div>
```

- [ ] **Step 4: Create SoundpadConfig.svelte**

```svelte
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  let enabled = true;
  let soundpadPath = "Soundpad.exe";

  async function saveSoundpadConfig() {
    await invoke("save_config", {
      newConfig: { soundpadEnabled: enabled, soundpadPath }
    });
  }
</script>

<div class="soundpad-config">
  <h3>Soundpad</h3>
  <label class="toggle">
    <input type="checkbox" bind:checked={enabled} on:change={saveSoundpadConfig} />
    Enabled
  </label>
  <div class="fields">
    <label>Path: <input type="text" bind:value={soundpadPath} on:change={saveSoundpadConfig} /></label>
  </div>
  <p class="hint">Soundpad must be running. Commands: go, stop, play_in_X</p>
</div>
```

- [ ] **Step 5: Verify build**

```bash
cd /home/danny/vrActorAssist/client
npm run build && cargo check
```

Expected: Builds cleanly

- [ ] **Step 6: Commit**

```bash
git add client/src/lib/ActorView.svelte client/src/lib/FileReceiver.svelte client/src/lib/OscConfig.svelte client/src/lib/SoundpadConfig.svelte
git commit -m "feat: add Actor mode UI (file receiver, OSC config, Soundpad config)"
```

---

### Task 10: Implement file transfer, Soundpad, and OSC in Rust

**Files:**
- Create: `client/src-tauri/src/file_transfer.rs`
- Create: `client/src-tauri/src/soundpad.rs`
- Create: `client/src-tauri/src/osc.rs`
- Modify: `client/src-tauri/src/main.rs`

**Interfaces:**
- Consumes: `Config` for OSC and Soundpad settings
- Produces: `file_transfer::FileTransfer` (chunker/assembler), `soundpad::send_command()`, `osc::send_cue()`

- [ ] **Step 1: Create file_transfer.rs**

```rust
use sha2::{Sha256, Digest};
use std::path::Path;

pub struct FileTransfer;

impl FileTransfer {
    pub fn chunk_size() -> u32 {
        65536 // 64KB
    }

    pub fn split_file(path: &Path) -> Result<(Vec<Vec<u8>>, String), String> {
        let data = std::fs::read(path).map_err(|e| format!("Read error: {}", e))?;
        
        // Compute MD5 checksum (Python clients use MD5)
        let checksum = format!("{:x}", md5::compute(&data));
        
        let chunks: Vec<Vec<u8>> = data
            .chunks(Self::chunk_size() as usize)
            .map(|c| c.to_vec())
            .collect();
        
        Ok((chunks, checksum))
    }

    pub fn assemble_file(chunks: Vec<Vec<u8>>) -> Vec<u8> {
        let total_size: usize = chunks.iter().map(|c| c.len()).sum();
        let mut result = Vec::with_capacity(total_size);
        for chunk in chunks {
            result.extend_from_slice(&chunk);
        }
        result
    }

    pub fn verify_checksum(data: &[u8], expected: &str) -> bool {
        let actual = format!("{:x}", md5::compute(data));
        actual == expected
    }
}
```

Add to `Cargo.toml`:
```toml
sha2 = "0.10"
md5 = "0.7"
```

- [ ] **Step 2: Create soundpad.rs**

```rust
#[cfg(target_os = "windows")]
use std::process::Command;

pub fn send_command(command: &str, soundpad_path: &str) -> Result<String, String> {
    #[cfg(target_os = "windows")]
    {
        let output = Command::new(soundpad_path)
            .args(["-rc", command])
            .output()
            .map_err(|e| format!("Soundpad execution failed: {}", e))?;
        
        if output.status.success() {
            Ok(String::from_utf8_lossy(&output.stdout).to_string())
        } else {
            Err(format!(
                "Soundpad error: {}",
                String::from_utf8_lossy(&output.stderr)
            ))
        }
    }
    
    #[cfg(not(target_os = "windows"))]
    {
        Err("Soundpad is only available on Windows".to_string())
    }
}
```

- [ ] **Step 3: Create osc.rs**

```rust
use rosc::{OscPacket, OscMessage, OscType};
use std::net::UdpSocket;

pub fn send_cue(host: &str, port: u16, address: &str, value: f32) -> Result<(), String> {
    let msg = OscMessage {
        addr: address.to_string(),
        args: vec![OscType::Float(value)],
    };
    
    let packet = OscPacket::Message(msg);
    let bytes = rosc::encoder::encode(&packet).map_err(|e| format!("OSC encode error: {}", e))?;
    
    let socket = UdpSocket::bind("0.0.0.0:0").map_err(|e| format!("Socket bind error: {}", e))?;
    socket
        .send_to(&bytes, format!("{}:{}", host, port))
        .map_err(|e| format!("OSC send error: {}", e))?;
    
    Ok(())
}

pub fn send_go(host: &str, port: u16) -> Result<(), String> {
    send_cue(host, port, "/avatar/parameters/Go", 1.0)
}

pub fn send_stop(host: &str, port: u16) -> Result<(), String> {
    send_cue(host, port, "/avatar/parameters/Stop", 1.0)
}
```

- [ ] **Step 4: Register commands in main.rs**

```rust
mod file_transfer;
mod soundpad;
mod osc;

// Add Tauri commands:
// - cmd_send_cue — sends command via WebSocket
// - cmd_play_soundpad — calls soundpad::send_command
// - cmd_send_osc — calls osc::send_cue
```

- [ ] **Step 5: Compiler check**

```bash
cd /home/danny/vrActorAssist/client
cargo check
```

Expected: Compiles

- [ ] **Step 6: Commit**

```bash
git add client/src-tauri/src/file_transfer.rs client/src-tauri/src/soundpad.rs client/src-tauri/src/osc.rs
git commit -m "feat: implement file transfer, Soundpad, and OSC modules"
```

---

### Task 11: Implement auto-update and polish

**Files:**
- Modify: `client/src-tauri/tauri.conf.json`
- Modify: `client/src-tauri/src/main.rs`
- Create: (stub for CI/release workflow)

**Interfaces:**
- Produces: Tauri updater configuration that checks GitHub releases

- [ ] **Step 1: Configure Tauri updater**

Edit `client/src-tauri/tauri.conf.json`:

```json
{
  "plugins": {
    "updater": {
      "pubkey": "<your-public-key>",
      "endpoints": [
        "https://github.com/virtualvert/vrActorAssist/releases/latest/download/update.json"
      ],
      "windows": {
        "installMode": "passive"
      }
    }
  }
}
```

- [ ] **Step 2: Generate signing keys**

```bash
cd /home/danny/vrActorAssist/client
npx @tauri-apps/cli signer generate -w ~/.tauri/vrActorAssist.key
```

- [ ] **Step 3: Commit**

```bash
git add client/src-tauri/tauri.conf.json
git commit -m "feat: configure Tauri auto-updater"
```

---

### Task 12: End-to-end testing and documentation

**Files:**
- Create: `client/README.md` (Tauri-specific build/run instructions)
- No code changes

- [ ] **Step 1: Test Tauri Director mode against Python server**

```bash
# Terminal 1: Start Python server
cd /home/danny/vrActorAssist
python server_ws.py --port 5555 --secret test

# Terminal 2: Run Tauri app in dev mode
cd /home/danny/vrActorAssist/client
npm run tauri dev
```

Expected: Director connects, sends register, can chat, send cues

- [ ] **Step 2: Test Tauri Actor mode against Python server**

Same setup, switch to Actor mode. Expected: Actor connects, appears in pending, can be approved.

- [ ] **Step 3: Test file transfer end-to-end**

Send a small audio file from Director to Actor. Verify it arrives and checksum matches.

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: post-migration cleanup and documentation"
```
