# vrActorAssist WebSocket Server
# FastAPI + WebSocket server for director/actor communication
#
# Usage: uvicorn server_ws:app --host 0.0.0.0 --port 5555
#        python server_ws.py (runs directly)

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
import uvicorn

from shared import parse_message, format_message

# Configuration
DEFAULT_PORT = 5555
DEFAULT_SECRET = "vractor-secret-change-me"

# Get secret from env or arg
SERVER_SECRET = os.environ.get("VR_ACTOR_SECRET", DEFAULT_SECRET)

# File paths (same directory as script)
BASE_DIR = Path(__file__).parent
APPROVED_FILE = BASE_DIR / "approved_actors.json"
LOG_FILE = BASE_DIR / "server.log"


def log(message: str):
    """Log message with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    print(entry)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except:
        pass


def load_approved() -> Dict[str, dict]:
    """Load approved actors from file."""
    if APPROVED_FILE.exists():
        try:
            return json.loads(APPROVED_FILE.read_text())
        except:
            pass
    return {}


def save_approved(approved: Dict[str, dict]):
    """Save approved actors to file."""
    try:
        APPROVED_FILE.write_text(json.dumps(approved, indent=2))
    except Exception as e:
        log(f"Error saving approved: {e}")


# Server state
approved_actors: Dict[str, dict] = load_approved()
pending_actors: Dict[str, dict] = {}  # machine_id -> info


@dataclass
class Client:
    """Connected client info."""
    websocket: WebSocket
    name: str = "Unknown"
    machine_id: str = ""
    role: str = "actor"
    approved: bool = False
    last_ping_sent: float = 0.0
    last_ping_received: float = 0.0
    latency_ms: int = 0  # Rolling average latency


# Active connections
clients: Dict[WebSocket, Client] = {}

# Pending file transfers: filename -> {director_ws, actor_ws}
pending_transfers: Dict[str, dict] = {}


app = FastAPI(title="vrActorAssist Server")

@app.on_event("startup")
async def startup_event():
    """Start background tasks on server startup."""
    asyncio.create_task(status_broadcast_loop())


def get_directors() -> list:
    """Get list of connected directors."""
    return [c for ws, c in clients.items() if c.role == "director" and c.approved]


def get_approved_actors() -> list:
    """Get list of connected approved actors."""
    return [c for ws, c in clients.items() if c.role == "actor" and c.approved]


async def broadcast(message: str, exclude: Optional[WebSocket] = None):
    """Broadcast message to all approved clients."""
    disconnected = []
    for ws, client in clients.items():
        if ws == exclude:
            continue
        if not client.approved:
            continue
        try:
            await ws.send_text(message)
        except:
            disconnected.append(ws)
    
    for ws in disconnected:
        clients.pop(ws, None)


async def send_to_directors(message: str):
    """Send message to all directors."""
    for ws, client in clients.items():
        if client.role == "director" and client.approved:
            try:
                await ws.send_text(message)
            except:
                pass


async def send_user_list():
    """Send updated user list to all clients."""
    users = [c.name for c in get_approved_actors()]
    msg = format_message("USERS", user_list=",".join(users))
    await broadcast(msg)


async def send_pending_list():
    """Send pending actors list to directors."""
    pending = [{"machine_id": mid, "name": info["name"]} 
                for mid, info in pending_actors.items()]
    msg = format_message("PENDING", actors_json=json.dumps(pending))
    await send_to_directors(msg)


async def send_actor_status():
    """Send actor latency status to directors."""
    actors = []
    for c in get_approved_actors():
        actors.append({
            "name": c.name,
            "latency_ms": c.latency_ms,
            "last_seen": c.last_ping_received
        })
    msg = format_message("STATUS", actors_json=json.dumps(actors))
    await send_to_directors(msg)


async def ping_actors():
    """Send PING to all actors and track latency."""
    current_time = time.time()
    for ws, client in clients.items():
        if client.role == "actor" and client.approved:
            client.last_ping_sent = current_time
            try:
                await ws.send_text("PING")
            except:
                pass


async def status_broadcast_loop():
    """Periodically broadcast actor status to directors and ping actors."""
    while True:
        await asyncio.sleep(10)  # Every 10 seconds
        
        # Ping actors for latency tracking
        await ping_actors()
        
        # Give them 2 seconds to respond
        await asyncio.sleep(2)
        
        # Check for timeout (gray indicators)
        current_time = time.time()
        for ws, client in list(clients.items()):
            if client.role == "actor" and client.approved:
                # If no pong received in 60s, mark as timed out
                if client.last_ping_received > 0 and (current_time - client.last_ping_received) > 60:
                    client.latency_ms = -1  # -1 means timed out
        
        # Send status to directors
        await send_actor_status()


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    secret: str = Query(default=""),
):
    """WebSocket endpoint for clients."""
    await websocket.accept()
    
    client = Client(websocket=websocket)
    clients[websocket] = client
    
    log(f"Client connected from {websocket.client}")
    
    try:
        while True:
            data = await websocket.receive_text()
            msg_type, msg_data = parse_message(data)
            
            if not msg_type:
                continue
            
            # Handle registration
            if msg_type == "REGISTER":
                name = msg_data.get("name", "Unknown")
                machine_id = msg_data.get("machine_id", "")
                role = msg_data.get("role", "actor")
                provided_secret = msg_data.get("secret", "")
                
                client.name = name
                client.machine_id = machine_id
                client.role = role
                
                log(f"Registration: {name} ({role}), machine_id={machine_id[:8]}...")
                
                # Director authentication
                if role == "director":
                    if provided_secret == SERVER_SECRET:
                        client.approved = True
                        log(f"Director '{name}' authenticated")
                        await websocket.send_text(format_message("APPROVED"))
                        
                        # Handle multi-director warnings
                        existing_directors = [c for c in get_directors() if c.websocket != websocket]
                        if existing_directors:
                            # Warn new director about existing ones
                            existing_names = [d.name for d in existing_directors]
                            await websocket.send_text(format_message("MSG", sender="SERVER",
                                text=f"⚠ Warning: {', '.join(existing_names)} is already connected"))
                            log(f"Director '{name}' warned about existing directors")
                            
                            # Warn existing directors about new one
                            for d in existing_directors:
                                try:
                                    await d.websocket.send_text(format_message("MSG", sender="SERVER",
                                        text=f"⚠ Warning: {name} has connected as another director"))
                                except:
                                    pass
                        
                        await send_user_list()
                        await send_pending_list()
                    else:
                        log(f"Director '{name}' failed auth")
                        await websocket.send_text(format_message("DENIED", reason="Invalid secret"))
                        await websocket.close()
                        return
                    continue
                
                # Actor registration
                if machine_id in approved_actors:
                    # Known actor - auto-approve
                    client.approved = True
                    client.name = approved_actors[machine_id].get("name", name)
                    log(f"Actor '{client.name}' auto-approved (known machine_id)")
                    await websocket.send_text(format_message("APPROVED"))
                    await broadcast(format_message("MSG", sender="SERVER", text=f"{client.name} joined"))
                    await send_user_list()
                elif machine_id in pending_actors:
                    # Already pending
                    await websocket.send_text(format_message("DENIED", reason="Pending approval"))
                else:
                    # New actor - needs approval
                    pending_actors[machine_id] = {
                        "name": name,
                        "websocket": websocket,
                    }
                    await websocket.send_text(format_message("DENIED", reason="Pending approval"))
                    log(f"Actor '{name}' pending approval")
                    await send_pending_list()
                continue
            
            # Require approval for all other messages
            if not client.approved:
                await websocket.send_text(format_message("DENIED", reason="Not approved"))
                continue
            
            # Handle PONG response (latency tracking)
            if msg_type == "PONG" or data == "PONG":
                current_time = time.time()
                client.last_ping_received = current_time
                
                # Calculate latency if we have a ping sent time
                if client.last_ping_sent > 0:
                    latency = int((current_time - client.last_ping_sent) * 1000)  # Convert to ms
                    # Rolling average (smooth out fluctuations)
                    if client.latency_ms > 0:
                        client.latency_ms = int((client.latency_ms + latency) / 2)
                    else:
                        client.latency_ms = latency
                continue
            
            # Handle messages
            if msg_type == "MSG":
                sender = msg_data.get("sender", "Unknown")
                text = msg_data.get("text", "")
                # Broadcast to all
                await broadcast(format_message("MSG", sender=sender, text=text))
            
            elif msg_type == "PRIV":
                sender = msg_data.get("sender", "Unknown")
                target = msg_data.get("target", "")
                text = msg_data.get("text", "")
                # Send to specific target
                found = False
                for ws, c in clients.items():
                    if c.name == target and c.approved:
                        try:
                            await ws.send_text(format_message("PRIV", sender=sender, target=target, text=text))
                            found = True
                        except:
                            pass
                if not found and client.role == "director":
                    await websocket.send_text(format_message("MSG", sender="SERVER", text=f"Actor '{target}' not found"))
            
            elif msg_type == "CMD":
                command = msg_data.get("command", "")
                # Broadcast command to all actors
                await broadcast(format_message("CMD", command=command))
            
            # File transfer messages - route to target
            elif msg_type in ("FILEREQ", "FILEACK", "FILEDENY", "FILESTART", "FILECHUNK", "FILEEND", "FILEOK", "FILEERR"):
                filename = msg_data.get("filename", "")
                
                if msg_type == "FILEREQ":
                    # Director requesting to send to actor
                    target = msg_data.get("target", "")
                    sender_ws = websocket
                    
                    # Find target actor
                    for ws, c in clients.items():
                        if c.name == target and c.approved and c.role == "actor":
                            # Store the transfer mapping
                            pending_transfers[filename] = {
                                "director_ws": websocket,
                                "actor_ws": ws
                            }
                            try:
                                await ws.send_text(data)
                            except:
                                pass
                            break
                
                elif filename in pending_transfers:
                    transfer = pending_transfers[filename]
                    
                    if msg_type in ("FILEACK", "FILEDENY", "FILEOK", "FILEERR"):
                        # Actor -> Director
                        try:
                            await transfer["director_ws"].send_text(data)
                        except:
                            pass
                        
                        if msg_type in ("FILEOK", "FILEERR", "FILEDENY"):
                            # Transfer complete, cleanup
                            del pending_transfers[filename]
                    
                    elif msg_type in ("FILESTART", "FILECHUNK", "FILEEND"):
                        # Director -> Actor
                        try:
                            await transfer["actor_ws"].send_text(data)
                        except:
                            pass
                        
                        if msg_type == "FILEEND":
                            # Will be cleaned up after FILEOK/FILEERR
                            pass
            
            elif msg_type == "APPROVE":
                # Director approves pending actor
                if client.role != "director":
                    continue
                approve_machine_id = msg_data.get("machine_id")
                if not approve_machine_id:
                    continue
                
                if approve_machine_id in pending_actors:
                    pending_info = pending_actors.pop(approve_machine_id)
                    
                    # Add to approved
                    approved_actors[approve_machine_id] = {
                        "name": pending_info["name"],
                        "approved_at": datetime.now().isoformat(),
                    }
                    save_approved(approved_actors)
                    
                    # Notify the pending actor
                    pending_ws = pending_info.get("websocket")
                    if pending_ws:
                        for ws, c in clients.items():
                            if ws == pending_ws:
                                c.approved = True
                                try:
                                    await ws.send_text(format_message("APPROVED"))
                                except:
                                    pass
                                break
                    
                    log(f"Actor approved by director: {pending_info['name']}")
                    await broadcast(format_message("MSG", sender="SERVER", text=f"{pending_info['name']} joined"))
                    await send_user_list()
                    await send_pending_list()
            
            elif msg_type == "DENY":
                # Director denies pending actor
                if client.role != "director":
                    continue
                deny_machine_id = msg_data.get("machine_id")
                if not deny_machine_id:
                    continue
                
                if deny_machine_id in pending_actors:
                    denied = pending_actors.pop(deny_machine_id)
                    log(f"Actor denied by director: {denied['name']}")
                    # Notify the denied actor
                    pending_ws = denied.get("websocket")
                    if pending_ws:
                        try:
                            await pending_ws.send_text(format_message("DENIED", reason="Denied by director"))
                            await pending_ws.close()
                        except:
                            pass
                    await send_pending_list()
            
            elif msg_type == "FORGET":
                # Remove actor from approved list
                if client.role != "director":
                    continue
                forget_machine_id = msg_data.get("machine_id")
                if forget_machine_id and forget_machine_id in approved_actors:
                    name = approved_actors[forget_machine_id].get("name", "Unknown")
                    del approved_actors[forget_machine_id]
                    save_approved(approved_actors)
                    log(f"Actor forgotten: {name}")
                    await send_user_list()
            
            elif msg_type == "FORGET_NAME":
                # Remove actor by name
                if client.role != "director":
                    continue
                forget_name = msg_data.get("name", "")
                to_remove = None
                for mid, info in approved_actors.items():
                    if info.get("name") == forget_name:
                        to_remove = mid
                        break
                if to_remove:
                    del approved_actors[to_remove]
                    save_approved(approved_actors)
                    log(f"Actor forgotten by name: {forget_name}")
                    await send_user_list()
            
            elif msg_type == "REFRESH":
                await send_user_list()
                if client.role == "director":
                    await send_pending_list()
    
    except WebSocketDisconnect:
        log(f"Client disconnected: {client.name}")
    except Exception as e:
        log(f"Error: {e}")
    finally:
        # Cleanup
        if websocket in clients:
            del clients[websocket]
        
        # Remove from pending if applicable
        for mid, info in list(pending_actors.items()):
            if info.get("websocket") == websocket:
                del pending_actors[mid]
        
        if client.approved and client.role == "actor":
            asyncio.create_task(send_user_list())
            if client.name:
                asyncio.create_task(broadcast(format_message("MSG", sender="SERVER", text=f"{client.name} left")))


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "clients": len(clients), "approved": len(approved_actors)}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="vrActorAssist WebSocket Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--secret", default=SERVER_SECRET, help="Director secret")
    args = parser.parse_args()
    
    # Update secret from arg
    SERVER_SECRET = args.secret
    
    log(f"Starting WebSocket server on {args.host}:{args.port}")
    log(f"Director secret: {SERVER_SECRET[:4]}...")
    
    # Run with websocket ping enabled
    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port, 
        log_level="info",
        ws_ping_interval=30.0,  # Send ping every 30 seconds
        ws_ping_timeout=10.0,  # Wait 10 seconds for pong
    )