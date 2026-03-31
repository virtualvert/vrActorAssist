# Shared utilities for vrActorAssist
# Protocol definitions, config handling, common functions

import json
import os
import uuid
import platform
from pathlib import Path

# Protocol message types
MSG_TYPES = {
    "MSG": "MSG|{sender}|{text}",           # Broadcast message
    "PRIV": "PRIV|{sender}|{target}|{text}", # Private message
    "USERS": "USERS|{user_list}",           # User list update
    "REGISTER": "REGISTER|{name}|{machine_id}|{role}|{secret}",  # Client registration (secret optional)
    "APPROVED": "APPROVED",                  # Actor approved
    "DENIED": "DENIED|{reason}",            # Actor denied
    "PENDING": "PENDING|{actors_json}",      # Pending actors list
    "CMD": "CMD|{command}",                 # Command (go, stop, etc.) - args optional
    "ACK": "ACK|{actor}|{command}|{status}", # Command acknowledgment
    "FILE": "FILE|{sender}|{filename}|{size}", # File transfer header
    "FORGET": "FORGET|{machine_id}",        # Remove actor from approved list
}


def get_machine_id():
    """Generate or retrieve a unique machine identifier."""
    # Use a combination of machine name + random UUID for uniqueness
    machine_name = platform.node()
    # Generate a UUID based on machine name for consistency
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, machine_name))


def load_config(config_path):
    """Load config from JSON file."""
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return None


def save_config(config_path, config):
    """Save config to JSON file."""
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


def get_default_config_path(filename="config.json"):
    """Get config path in the same directory as the executable."""
    # When running from PyInstaller, sys.executable is the .exe
    # When running normally, use the script's directory
    import sys
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        base_dir = os.path.dirname(sys.executable)
    else:
        # Running as script
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def format_message(msg_type, **kwargs):
    """Format a protocol message."""
    template = MSG_TYPES.get(msg_type)
    if template:
        # Handle optional args for CMD
        if msg_type == "CMD" and "args" not in kwargs:
            kwargs["args"] = ""
        return template.format(**kwargs)
    return None


def parse_message(data):
    """Parse a protocol message. Returns (type, data_dict) or (None, None)."""
    if isinstance(data, bytes):
        data = data.decode('utf-8', errors='replace')
    
    parts = data.split('|')
    if not parts:
        return None, None
    
    msg_type = parts[0]
    
    if msg_type == "MSG" and len(parts) >= 3:
        return msg_type, {"sender": parts[1], "text": "|".join(parts[2:])}
    
    elif msg_type == "PRIV" and len(parts) >= 4:
        return msg_type, {"sender": parts[1], "target": parts[2], "text": "|".join(parts[3:])}
    
    elif msg_type == "USERS" and len(parts) >= 2:
        users = parts[1].split(",") if parts[1] else []
        return msg_type, {"users": users}
    
    elif msg_type == "REGISTER" and len(parts) >= 4:
        # REGISTER|name|machine_id|role|secret (secret optional)
        return msg_type, {
            "name": parts[1],
            "machine_id": parts[2],
            "role": parts[3],
            "secret": parts[4] if len(parts) >= 5 else ""
        }
    
    elif msg_type == "APPROVED":
        return msg_type, {}
    
    elif msg_type == "DENIED" and len(parts) >= 2:
        return msg_type, {"reason": "|".join(parts[1:])}
    
    elif msg_type == "PENDING" and len(parts) >= 2:
        import json as json_mod
        try:
            actors = json_mod.loads(parts[1])
        except:
            actors = []
        return msg_type, {"actors": actors}
    
    elif msg_type == "CMD" and len(parts) >= 2:
        return msg_type, {"command": parts[1], "args": "|".join(parts[2:]) if len(parts) > 2 else ""}
    
    elif msg_type == "ACK" and len(parts) >= 4:
        return msg_type, {"actor": parts[1], "command": parts[2], "status": parts[3]}
    
    elif msg_type == "FILE" and len(parts) >= 4:
        return msg_type, {"sender": parts[1], "filename": parts[2], "size": int(parts[3])}
    
    elif msg_type == "FORGET" and len(parts) >= 2:
        return msg_type, {"machine_id": parts[1]}
    
    elif msg_type == "APPROVE":
        # APPROVE|machine_id
        if len(parts) >= 2:
            return msg_type, {"machine_id": parts[1]}
        return msg_type, {}
    
    elif msg_type == "DENY":
        # DENY|machine_id
        if len(parts) >= 2:
            return msg_type, {"machine_id": parts[1]}
        return msg_type, {}
    
    elif msg_type == "FORGET_NAME" and len(parts) >= 2:
        return msg_type, {"name": parts[1]}
    
    elif msg_type == "REFRESH":
        return msg_type, {}
    
    return msg_type, {"raw": data}