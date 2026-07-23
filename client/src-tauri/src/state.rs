use crate::config::Config;
use crate::director::ActorRegistry;
use crate::ws_client::WsClient;
use std::sync::{Arc, Mutex};

pub struct AppState {
    pub config: tokio::sync::Mutex<Config>,
    pub config_path: std::path::PathBuf,
    pub ws: Arc<WsClient>,
    pub actors: Arc<Mutex<ActorRegistry>>,
}

impl AppState {
    pub fn new(config: Config, config_path: std::path::PathBuf) -> Self {
        Self {
            config: tokio::sync::Mutex::new(config),
            config_path,
            ws: Arc::new(WsClient::new()),
            actors: Arc::new(Mutex::new(ActorRegistry::default())),
        }
    }
}
