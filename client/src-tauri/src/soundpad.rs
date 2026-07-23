/// Attempts to locate Soundpad.exe in common Steam installation paths.
/// Returns `None` on non-Windows or if not found.
pub fn detect_soundpad() -> Option<String> {
    #[cfg(target_os = "windows")]
    {
        let candidates = [
            r"C:\Program Files (x86)\Steam\steamapps\common\Soundpad\Soundpad.exe",
            r"C:\Program Files\Steam\steamapps\common\Soundpad\Soundpad.exe",
            "Soundpad.exe",
        ];
        for path in &candidates {
            if std::path::Path::new(path).exists() {
                return Some(path.to_string());
            }
        }
        None
    }

    #[cfg(not(target_os = "windows"))]
    {
        None
    }
}

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
