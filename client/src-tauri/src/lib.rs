mod config;
mod protocol;
mod state;
mod ws_client;

use config::Config;
use protocol::Message;
use state::AppState;
#[allow(unused_imports)]
use tauri::{Emitter, Manager, State};
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
