mod config;
mod director;
mod file_transfer;
mod osc;
mod protocol;
mod soundpad;
mod state;
mod ws_client;

use config::Config;
use file_transfer::{split_into_chunks, md5_hex};
use protocol::Message;
use state::AppState;
#[allow(unused_imports)]
use tauri::{Emitter, Manager, State};
use tauri_plugin_updater::UpdaterExt;
use ws_client::ConnectionState;

#[tauri::command]
async fn get_config(state: State<'_, AppState>) -> Result<Config, String> {
    Ok(state.config.lock().await.clone())
}

#[tauri::command]
async fn save_config(state: State<'_, AppState>, new_config: Config) -> Result<(), String> {
    new_config.save(&state.config_path)?;
    *state.config.lock().await = new_config;
    Ok(())
}

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
    let buffers_for_msg = state.receive_buffers.clone();
    let cfg_mode = cfg.mode.clone();
    let cfg_receive_dir = cfg.receive_dir.clone();
    let cfg_actor_name = cfg.actor_name.clone();
    let cfg_soundpad_enabled = cfg.soundpad_enabled;
    let cfg_soundpad_path = cfg.soundpad_path.clone();
    let cfg_osc_enabled = cfg.osc_enabled;
    let cfg_osc_host = cfg.osc_host.clone();
    let cfg_osc_port = cfg.osc_port;

    let app_for_msg = app.clone();
    let app_for_state = app.clone();
    let ws_for_file = ws.clone();

    ws.connect(
        &url,
        move |msg: Message| {
            match &msg {
                Message::Pending { actors_json } => {
                    if let Ok(entries) = serde_json::from_str::<Vec<PendingEntry>>(actors_json) {
                        if let Ok(mut reg) = actors_for_msg.lock() {
                            for e in entries {
                                reg.upsert_pending(&e.name, &e.machine_id);
                            }
                        }
                    }
                }
                Message::Status { actors_json } => {
                    if let Ok(entries) = serde_json::from_str::<Vec<StatusEntry>>(actors_json) {
                        if let Ok(mut reg) = actors_for_msg.lock() {
                            for e in entries {
                                reg.upsert_from_status(&e.name, e.latency_ms);
                            }
                        }
                    }
                }
                Message::Approved => {
                    // Server confirms an actor's approval only to that actor's own
                    // connection; the director learns of it via the next Pending/Status
                    // broadcast, so no registry update is needed on this branch.
                }
                Message::Denied { reason: _ } => {
                    let _ = app_for_msg.emit("protocol-message", &msg);
                }
                Message::Forget { machine_id } => {
                    if let Ok(mut reg) = actors_for_msg.lock() {
                        reg.actors.retain(|_, a| &a.machine_id != machine_id);
                    }
                    let _ = app_for_msg.emit("protocol-message", &msg);
                }
                Message::FileChunk { filename, chunk_num, data } => {
                    if cfg_mode == "actor" {
                        if let Ok(mut buffers) = buffers_for_msg.lock() {
                            let buf = buffers.entry(filename.clone()).or_default();
                            let _ = buf.add_chunk(*chunk_num, data);
                        }
                    }
                }
                Message::FileEnd { filename, checksum } => {
                    if cfg_mode == "actor" {
                        if let Ok(mut buffers) = buffers_for_msg.lock() {
                            if let Some(buf) = buffers.remove(filename) {
                                match buf.finalize(checksum) {
                                    Ok(bytes) => {
                                        let save_path = std::path::Path::new(&cfg_receive_dir).join(filename);
                                        match std::fs::write(&save_path, &bytes) {
                                            Ok(_) => {
                                                let ws = ws_for_file.clone();
                                                let saved = save_path.to_string_lossy().to_string();
                                                let fn_ = filename.clone();
                                                tokio::spawn(async move {
                                                    let _ = ws.send(&Message::FileOk { filename: fn_, saved_path: saved }).await;
                                                });
                                            }
                                            Err(e) => {
                                                let ws = ws_for_file.clone();
                                                let err = format!("Write failed: {}", e);
                                                let fn_ = filename.clone();
                                                tokio::spawn(async move {
                                                    let _ = ws.send(&Message::FileErr { filename: fn_, error: err }).await;
                                                });
                                            }
                                        }
                                    }
                                    Err(error) => {
                                        let ws = ws_for_file.clone();
                                        let fn_ = filename.clone();
                                        tokio::spawn(async move {
                                            let _ = ws.send(&Message::FileErr { filename: fn_, error }).await;
                                        });
                                    }
                                }
                            }
                        }
                    }
                }
                Message::Priv { target, text, .. } => {
                    if *target == cfg_actor_name && cfg_mode == "actor" {
                        if cfg_soundpad_enabled {
                            let cmd = text.clone();
                            let sp = cfg_soundpad_path.clone();
                            let app = app_for_msg.clone();
                            tokio::spawn(async move {
                                if let Err(e) = soundpad::send_command(&cmd, &sp) {
                                    log::warn!("Soundpad error: {}", e);
                                    let _ = app.emit("protocol-message", &Message::FileErr {
                                        filename: "Soundpad".to_string(),
                                        error: e,
                                    });
                                }
                            });
                        }
                    }
                }
                Message::OscCue { target, parameter, value } => {
                    if *target == cfg_actor_name && cfg_mode == "actor" {
                        if cfg_osc_enabled {
                            let host = cfg_osc_host.clone();
                            let port = cfg_osc_port;
                            let param = parameter.clone();
                            let val = value.clone();
                            tokio::spawn(async move {
                                if let Err(e) = osc::send_param(&host, port, &param, &val) {
                                    log::warn!("OSC error: {}", e);
                                }
                            });
                        }
                    }
                }
                Message::Msg { sender, text } => {
                    if sender == "SERVER" {
                        if let Some(name) = text.strip_suffix(" left") {
                            if let Ok(mut reg) = actors_for_msg.lock() {
                                reg.actors.remove(name);
                            }
                        } else if let Some(name) = text.strip_suffix(" joined") {
                            if let Ok(mut reg) = actors_for_msg.lock() {
                                reg.upsert_from_status(name, 0);
                            }
                        }
                    }
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

/// Sends a command (e.g. "*go") to each target via PRIV. If targets is empty, this is a no-op.
#[tauri::command]
async fn send_command(state: State<'_, AppState>, command: String, targets: Vec<String>) -> Result<(), String> {
    for target in targets {
        state.ws.send(&Message::Priv { sender: "Director".to_string(), target, text: command.clone() }).await?;
    }
    Ok(())
}

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
    state.actors.lock().map_err(|e| e.to_string())?.remove(&name);
    state.ws.send(&Message::ForgetName { name }).await
}

#[tauri::command]
async fn set_actor_enabled(state: State<'_, AppState>, name: String, enabled: bool) -> Result<(), String> {
    state.actors.lock().map_err(|e| e.to_string())?.set_enabled(&name, enabled);
    Ok(())
}

#[tauri::command]
async fn list_actors(state: State<'_, AppState>) -> Result<Vec<crate::director::ActorInfo>, String> {
    Ok(state.actors.lock().map_err(|e| e.to_string())?.all())
}

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

#[tauri::command]
async fn play_soundpad(state: State<'_, AppState>, command: String) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    if !cfg.soundpad_enabled {
        return Ok(());
    }
    soundpad::send_command(&command, &cfg.soundpad_path).map(|_| ())
}

#[tauri::command]
fn detect_soundpad() -> Option<String> {
    soundpad::detect_soundpad()
}

#[tauri::command]
async fn send_osc(state: State<'_, AppState>, parameter: String, value: String) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    if !cfg.osc_enabled {
        return Ok(());
    }
    osc::send_param(&cfg.osc_host, cfg.osc_port, &parameter, &value)
}

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

#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    if let Ok(Some(update)) = updater.check().await {
        update.download_and_install(|_chunk, _total| {}, || {}).await.map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
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
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .manage(AppState::new(cfg, config_path))
        .invoke_handler(tauri::generate_handler![
            get_config,
            save_config,
            connect,
            disconnect,
            send_chat,
            send_command,
            approve_actor,
            deny_actor,
            forget_actor,
            set_actor_enabled,
            list_actors,
            send_file,
            respond_to_file_request,
            play_soundpad,
            detect_soundpad,
            send_osc,
            check_for_update,
            install_update,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
