# vrActorAssist

A director/actor communication system for VRChat filmmaking. Director sends commands, actors receive and execute Soundpad sounds.

## Quick Start

### 1. Install Dependencies
```bash
# Server
pip install fastapi uvicorn websockets

# Clients
pip install websocket-client
```

### 2. Start the Server
```bash
python server_ws.py --port 5555 --secret your-secret-here
```

### 3. Run Director Client
```bash
python director_client_ws.py
```
- Enter server URL: `ws://host:5555/ws` or `wss://your-domain.com/ws`
- Enter secret (must match server)
- Approve pending actors

### 4. Run Actor Client
```bash
python actor_client_ws.py
```
- Enter server URL and your name
- Wait for director approval

## Deployment

| Scenario | Server URL |
|----------|------------|
| Local network | `ws://192.168.1.100:5555/ws` |
| Tailscale tailnet | `ws://100.104.39.106:5555/ws` |
| Public domain | `wss://actor.yourdomain.com/ws` |

### Public Domain Setup (Optional)
Use Caddy for auto-HTTPS:
```bash
# Caddyfile
actor.yourdomain.com {
    reverse_proxy localhost:5555
}
```

## Windows Executable

Actors don't need Python! Build a standalone `.exe`:

```powershell
pip install pyinstaller
python build_exe.py
# Output: dist/vrActorClient.exe
```

Just distribute `vrActorClient.exe` — no dependencies needed.

## Commands

Director can send:
| Command | Action |
|---------|--------|
| `*go` | Play selected sound in Soundpad |
| `*stop` | Stop playback |
| `*ready?` | Ask actors to confirm ready |
| `*play:5` | Play sound at index 5 |

## Releases

See [GitHub Releases](https://github.com/YOUR_USERNAME/vrActorAssist/releases) for downloadable builds.

| Version | Notes |
|---------|-------|
| v0.1.0 | Initial release — basic WebSocket client, Soundpad integration |
| v0.2.0 | (Planned) Selective triggering, file transfer, status indicators, VR-friendly buttons |

## Architecture

```
┌─────────────────────────────────────┐
│         Server (VPS)                │
│  - WebSocket endpoint: /ws          │
│  - Director auth via shared secret  │
│  - Actor approval system            │
└─────────────────────────────────────┘
                 │
     ┌───────────┼───────────┐
     ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│Director │ │ Actor 1 │ │ Actor 2 │
│(Linux)  │ │(Windows)│ │(Windows)│
│         │ │Soundpad │ │Soundpad │
└─────────┘ └─────────┘ └─────────┘
```

## Project Structure

```
vrActorAssist/
├── server_ws.py          # WebSocket server (FastAPI)
├── director_client_ws.py # Director GUI
├── actor_client_ws.py    # Actor GUI with Soundpad
├── shared.py             # Protocol utilities
├── soundpad.py           # Soundpad CLI integration
├── build_exe.py          # PyInstaller build script
├── vrActorClient.spec    # PyInstaller spec
├── requirements.txt      # Dependencies
├── ROADMAP.md            # Future features
│
├── legacy/               # TCP socket version (kept for reference)
│   ├── server.py
│   ├── director_client.py
│   └── actor_client.py
│
└── archive/              # Early prototypes (historical)
    └── *03.py, *04.py
```

## Protocol

Text-based, pipe-delimited messages:

| Message | Format |
|---------|--------|
| Chat | `MSG\|sender\|text` |
| Private | `PRIV\|sender\|target\|text` |
| Command | `CMD\|command` |
| Register | `REGISTER\|name\|machine_id\|role\|secret` |
| Approved | `APPROVED` |
| Denied | `DENIED\|reason` |
| Users | `USERS\|user1,user2,...` |
| Pending | `PENDING\|[{"machine_id":"...", "name":"..."}]` |

## Requirements

### Server (VPS)
- Python 3.8+
- fastapi, uvicorn, websockets

### Director (Linux/Windows/macOS)
- Python 3.8+
- websocket-client
- tkinter (usually built-in)

### Actor (Windows only)
- **Windows 10/11** (Soundpad requirement)
- Soundpad installed
- For Python: websocket-client, tkinter
- **OR** just use `vrActorClient.exe` (no Python needed)

## Future

See [ROADMAP.md](ROADMAP.md) for planned features:
- Selective actor triggering
- Ping compensation/delay
- File transfer to actors
- Actor status indicators
- Web dashboard for server admin