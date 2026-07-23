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
