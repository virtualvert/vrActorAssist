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

/// True if running as a portable executable (no uninstall.exe sibling / no APPIMAGE env var),
/// false if running from an installed location.
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
