use crate::config::Config;
use crate::director::ActorRegistry;
use crate::file_transfer::FileReceiveBuffer;
use crate::ws_client::WsClient;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::sync::Mutex as TokioMutex;

pub struct AppState {
    pub config: TokioMutex<Config>,
    pub config_path: std::path::PathBuf,
    pub ws: Arc<WsClient>,
    pub actors: Arc<Mutex<ActorRegistry>>,
    pub receive_buffers: Arc<TokioMutex<HashMap<String, FileReceiveBuffer>>>,
}

impl AppState {
    pub fn new(config: Config, config_path: std::path::PathBuf) -> Self {
        Self {
            config: TokioMutex::new(config),
            config_path,
            ws: Arc::new(WsClient::new()),
            actors: Arc::new(Mutex::new(ActorRegistry::default())),
            receive_buffers: Arc::new(TokioMutex::new(HashMap::new())),
        }
    }
}
