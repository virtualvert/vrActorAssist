# Soundpad integration for Windows
# Uses command-line interface to control Soundpad playback

import subprocess
import platform
import os
import glob


def is_windows():
    """Check if we're running on Windows."""
    return platform.system() == "Windows"


def find_soundpad_exe():
    """Find Soundpad.exe installation path.
    
    Checks common locations:
    1. Environment variable SOUNDPAD_PATH (if set)
    2. Program Files (standard install)
    3. Steam installation
    4. User's Steam library folders
    """
    if not is_windows():
        return None
    
    # Check environment variable first
    env_path = os.environ.get("SOUNDPAD_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    
    # Common installation paths
    common_paths = [
        # Standard installer location
        r"C:\Program Files\Soundpad\Soundpad.exe",
        r"C:\Program Files (x86)\Soundpad\Soundpad.exe",
        
        # Steam default location
        r"C:\Program Files (x86)\Steam\steamapps\common\Soundpad\Soundpad.exe",
        r"C:\Program Files\Steam\steamapps\common\Soundpad\Soundpad.exe",
        
        # Steam in Program Files
        r"C:\Program Files\Steam\steamapps\common\Soundpad\Soundpad.exe",
    ]
    
    for path in common_paths:
        if os.path.isfile(path):
            return path
    
    # Try to find Steam library folders and search there
    # Steam stores library folders in libraryfolders.vdf
    steam_config_paths = [
        r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf",
        r"C:\Program Files\Steam\steamapps\libraryfolders.vdf",
        os.path.expanduser(r"~\Steam\steamapps\libraryfolders.vdf"),
    ]
    
    for config_path in steam_config_paths:
        if os.path.isfile(config_path):
            try:
                with open(config_path, 'r') as f:
                    content = f.read()
                    # Parse library paths from VDF (simple regex-free parsing)
                    # Look for "path" values
                    import re
                    paths = re.findall(r'"path"\s+"([^"]+)"', content)
                    for lib_path in paths:
                        soundpad_path = os.path.join(lib_path, "steamapps", "common", "Soundpad", "Soundpad.exe")
                        if os.path.isfile(soundpad_path):
                            return soundpad_path
            except:
                pass
    
    # Last resort: search common drive letters
    for drive in ["C", "D", "E", "F"]:
        for pattern in [
            f"{drive}:\\SteamLibrary\\steamapps\\common\\Soundpad\\Soundpad.exe",
            f"{drive}:\\Games\\Steam\\steamapps\\common\\Soundpad\\Soundpad.exe",
        ]:
            if os.path.isfile(pattern):
                return pattern
    
    # Try glob search in Program Files as last resort
    for base in [r"C:\Program Files", r"C:\Program Files (x86)"]:
        matches = glob.glob(os.path.join(base, "**", "Soundpad.exe"), recursive=True)
        if matches:
            return matches[0]
    
    return None


# Cache the Soundpad path
_SOUNDPAD_PATH = None
_CONFIG_SOUNDPAD_PATH = None  # Set by actor client from config


def set_soundpad_path(path):
    """Set Soundpad path from config."""
    global _CONFIG_SOUNDPAD_PATH
    _CONFIG_SOUNDPAD_PATH = path


def get_soundpad_path():
    """Get cached Soundpad path or find it."""
    global _SOUNDPAD_PATH
    # Check config path first (set by actor client)
    if _CONFIG_SOUNDPAD_PATH and os.path.isfile(_CONFIG_SOUNDPAD_PATH):
        return _CONFIG_SOUNDPAD_PATH
    if _SOUNDPAD_PATH is None:
        _SOUNDPAD_PATH = find_soundpad_exe()
    return _SOUNDPAD_PATH


def run_soundpad_command(command):
    """Run a Soundpad remote control command.
    
    Returns:
        tuple: (success: bool, message: str or None)
    """
    if not is_windows():
        print(f"[Soundpad] Not on Windows - simulating: {command}")
        return (True, None)
    
    soundpad_exe = get_soundpad_path()
    if not soundpad_exe:
        print("[Soundpad] Soundpad.exe not found!")
        print("[Soundpad] Install Soundpad or set SOUNDPAD_PATH environment variable")
        print("[Soundpad] Example: set SOUNDPAD_PATH=C:\\Program Files\\Soundpad\\Soundpad.exe")
        return (False, "Soundpad not found. Please install Soundpad or set SOUNDPAD_PATH environment variable.")
    
    try:
        result = subprocess.run(
            [soundpad_exe, "-rc", command],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            print(f"[Soundpad] Command failed (code {result.returncode}): {command}")
            if result.stderr:
                print(f"[Soundpad] Error: {result.stderr}")
            return (False, f"Soundpad command failed (code {result.returncode}). Is Soundpad running?")
        return (True, None)
    except FileNotFoundError:
        print(f"[Soundpad] Could not execute: {soundpad_exe}")
        return (False, "Could not execute Soundpad. Is it installed?")
    except subprocess.TimeoutExpired:
        print("[Soundpad] Command timed out")
        return (False, "Soundpad command timed out. Is Soundpad running?")
    except Exception as e:
        print(f"[Soundpad] Error: {e}")
        return (False, f"Soundpad error: {e}")


def play_selected():
    """Play the currently selected sound in Soundpad."""
    return run_soundpad_command("DoPlaySelectedSound()")


def play_by_index(index):
    """Play a sound by its index number in Soundpad."""
    return run_soundpad_command(f"DoPlaySound({index})")


def stop():
    """Stop current sound playback."""
    return run_soundpad_command("DoStopSound()")


def set_volume(volume):
    """Set Soundpad volume (0.0 to 1.0)."""
    if volume < 0.0 or volume > 1.0:
        print("[Soundpad] Volume must be between 0.0 and 1.0")
        return (False, "Volume must be between 0.0 and 1.0")
    return run_soundpad_command(f"SetVolume({volume})")


def execute_command(command, args=""):
    """Execute a Soundpad command based on protocol command.
    
    Returns:
        tuple: (success: bool, message: str or None)
    """
    command = command.lower().strip()
    
    if command == "go" or command == "*go":
        return play_selected()
    
    elif command == "stop" or command == "*stop":
        return stop()
    
    elif command.startswith("play:") or command.startswith("*play:"):
        # Format: play:5 or *play:5 (play sound at index 5)
        try:
            index = int(command.split(":")[1])
            return play_by_index(index)
        except (ValueError, IndexError):
            print(f"[Soundpad] Invalid play command: {command}")
            return (False, f"Invalid play command: {command}")
    
    elif command == "volume" and args:
        # Format: volume 0.5
        try:
            vol = float(args.split()[0])
            return set_volume(vol)
        except (ValueError, IndexError):
            print(f"[Soundpad] Invalid volume: {args}")
            return (False, f"Invalid volume: {args}")
    
    else:
        print(f"[Soundpad] Unknown command: {command}")
        return (False, f"Unknown command: {command}")


# Debug: print found path on import
if __name__ == "__main__":
    path = get_soundpad_path()
    if path:
        print(f"Found Soundpad at: {path}")
    else:
        print("Soundpad.exe not found!")
        print("Set SOUNDPAD_PATH environment variable to your Soundpad.exe location")