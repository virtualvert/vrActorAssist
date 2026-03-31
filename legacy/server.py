# vrActorAssist Server
# Headless server with actor approval system
#
# Usage: python server.py [port] [--secret SHARED_SECRET]
#
# Approved actors are stored in approved_actors.json

import socket
import threading
import json
import os
import sys
import argparse
from datetime import datetime
from shared import parse_message, format_message

# Default settings
DEFAULT_PORT = 5555
DEFAULT_SECRET = "vractor-secret-change-me"

# Server state
clients = {}  # socket -> client_info
approved_actors = {}  # machine_id -> {name, approved_at, last_seen}
pending_actors = {}  # machine_id -> {name, socket}
server_secret = DEFAULT_SECRET

# Paths - same folder as server.py
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = SCRIPT_DIR
APPROVED_FILE = os.path.join(DATA_DIR, "approved_actors.json")
LOG_FILE = os.path.join(DATA_DIR, "server.log")


def log(message):
    """Log a message to console and file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"Warning: Could not write to log file: {e}")


def load_approved_actors():
    """Load approved actors from file."""
    global approved_actors
    if os.path.exists(APPROVED_FILE):
        try:
            with open(APPROVED_FILE, 'r') as f:
                data = json.load(f)
                approved_actors = data.get("approved_actors", {})
                log(f"Loaded {len(approved_actors)} approved actors")
        except Exception as e:
            log(f"Error loading approved actors: {e}")
            approved_actors = {}


def save_approved_actors():
    """Save approved actors to file."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(APPROVED_FILE, 'w') as f:
            json.dump({
                "approved_actors": approved_actors,
                "updated_at": datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        log(f"Error saving approved actors: {e}")


def broadcast(message, exclude=None):
    """Broadcast message to all connected approved clients."""
    for sock, info in clients.items():
        if sock != exclude and info.get("approved"):
            try:
                sock.send(message.encode() if isinstance(message, str) else message)
            except:
                pass


def send_to_directors(message, exclude=None):
    """Send message to all directors."""
    for sock, info in clients.items():
        if sock != exclude and info.get("role") == "director":
            try:
                sock.send(message.encode() if isinstance(message, str) else message)
            except:
                pass


def send_user_list():
    """Send updated user list to all clients."""
    users = [info.get("name", "Unknown") for sock, info in clients.items() 
             if info.get("approved")]
    msg = format_message("USERS", user_list=",".join(users))
    broadcast(msg.encode())


def send_pending_list():
    """Send pending actors list to directors."""
    pending = [{"machine_id": mid, "name": info["name"]} 
               for mid, info in pending_actors.items()]
    msg = format_message("PENDING", actors_json=json.dumps(pending))
    send_to_directors(msg.encode())


def handle_client(client_socket, addr):
    """Handle a connected client."""
    client_info = {
        "socket": client_socket,
        "addr": addr,
        "name": None,
        "machine_id": None,
        "role": None,
        "approved": False
    }
    
    log(f"New connection from {addr}")
    
    try:
        # First message should be REGISTER
        data = client_socket.recv(1024)
        if not data:
            client_socket.close()
            return
        
        msg_type, msg_data = parse_message(data)
        
        if msg_type != "REGISTER":
            log(f"Invalid registration from {addr}: {data}")
            client_socket.send(format_message("DENIED", reason="Must register first").encode())
            client_socket.close()
            return
        
        name = msg_data.get("name", "Unknown")
        machine_id = msg_data.get("machine_id", "unknown")
        role = msg_data.get("role", "actor")
        secret = msg_data.get("secret", "")
        
        client_info["name"] = name
        client_info["machine_id"] = machine_id
        client_info["role"] = role
        
        log(f"Registration: {name} ({role}) from {addr}, machine_id={machine_id[:8]}...")
        
        # Check if this is a director with correct secret
        if role == "director":
            if secret == server_secret:
                client_info["approved"] = True
                clients[client_socket] = client_info
                client_socket.send(format_message("APPROVED").encode())
                log(f"Director '{name}' authenticated")
                send_user_list()
                send_pending_list()
            else:
                client_socket.send(format_message("DENIED", reason="Invalid secret").encode())
                client_socket.close()
                log(f"Director '{name}' failed authentication - wrong secret")
                return
        
        # Check if actor is pre-approved
        elif machine_id in approved_actors:
            client_info["approved"] = True
            approved_actors[machine_id]["last_seen"] = datetime.now().isoformat()
            approved_actors[machine_id]["name"] = name  # Update name in case it changed
            save_approved_actors()
            clients[client_socket] = client_info
            client_socket.send(format_message("APPROVED").encode())
            log(f"Actor '{name}' auto-approved (known machine_id)")
            broadcast(format_message("MSG", sender="SERVER", text=f"{name} joined").encode())
            send_user_list()
        
        # Actor needs approval
        else:
            pending_actors[machine_id] = {
                "name": name,
                "socket": client_socket,
                "addr": addr
            }
            clients[client_socket] = client_info
            client_socket.send(format_message("DENIED", reason="Pending approval").encode())
            log(f"Actor '{name}' pending approval")
            send_pending_list()
        
        # Main message loop
        while True:
            data = client_socket.recv(4096)
            if not data:
                break
            
            msg_type, msg_data = parse_message(data)
            
            if msg_type == "MSG":
                # Broadcast chat message
                broadcast(data, exclude=client_socket)
            
            elif msg_type == "PRIV":
                # Private message
                target = msg_data.get("target")
                for sock, info in clients.items():
                    if info.get("name") == target:
                        sock.send(data)
                        break
            
            elif msg_type == "CMD":
                # Command from director
                if client_info.get("role") == "director":
                    broadcast(data)
                else:
                    client_socket.send(format_message("DENIED", reason="Only directors can send commands").encode())
            
            elif msg_type == "ACK":
                # Acknowledgment from actor
                send_to_directors(data)
            
            elif msg_type == "FILE":
                # File transfer
                forward_file(client_socket, msg_data)
            
            elif msg_type == "FORGET":
                # Remove actor from approved list (director only)
                if client_info.get("role") == "director":
                    forget_machine_id = msg_data.get("machine_id")
                    if forget_machine_id in approved_actors:
                        del approved_actors[forget_machine_id]
                        save_approved_actors()
                        log(f"Director removed actor: {forget_machine_id[:8]}...")
                        # Disconnect that actor if connected
                        for sock, info in list(clients.items()):
                            if info.get("machine_id") == forget_machine_id:
                                sock.send(format_message("DENIED", reason="Removed by director").encode())
                                sock.close()
                                del clients[sock]
                                break
                    send_user_list()
            
            elif msg_type == "APPROVE":
                # Director approves a pending actor
                if client_info.get("role") == "director":
                    approve_machine_id = msg_data.get("machine_id") if "machine_id" in msg_data else None
                    # Handle "APPROVE|machine_id" format
                    if not approve_machine_id and "|" in data.decode():
                        approve_machine_id = data.decode().split("|")[1]
                    
                    if approve_machine_id and approve_machine_id in pending_actors:
                        pending_info = pending_actors.pop(approve_machine_id)
                        approved_actors[approve_machine_id] = {
                            "name": pending_info["name"],
                            "approved_at": datetime.now().isoformat(),
                            "last_seen": datetime.now().isoformat()
                        }
                        save_approved_actors()
                        
                        # Update client and notify
                        actor_sock = pending_info.get("socket")
                        if actor_sock and actor_sock in clients:
                            clients[actor_sock]["approved"] = True
                            actor_sock.send(format_message("APPROVED").encode())
                        
                        log(f"Actor approved by director: {pending_info['name']}")
                        broadcast(format_message("MSG", sender="SERVER", 
                                    text=f"{pending_info['name']} joined").encode())
                        send_user_list()
                        send_pending_list()
            
            elif msg_type == "DENY":
                # Director denies a pending actor
                if client_info.get("role") == "director":
                    deny_machine_id = msg_data.get("machine_id") if "machine_id" in msg_data else None
                    # Handle "DENY|machine_id" format
                    if not deny_machine_id and "|" in data.decode():
                        deny_machine_id = data.decode().split("|")[1]
                    
                    if deny_machine_id and deny_machine_id in pending_actors:
                        pending_info = pending_actors.pop(deny_machine_id)
                        actor_sock = pending_info.get("socket")
                        if actor_sock:
                            actor_sock.send(format_message("DENIED", 
                                            reason="Denied by director").encode())
                            actor_sock.close()
                        if actor_sock in clients:
                            del clients[actor_sock]
                        log(f"Actor denied by director: {pending_info['name']}")
                        send_pending_list()
            
            elif msg_type == "FORGET_NAME":
                # Remove actor by name (director only)
                if client_info.get("role") == "director":
                    forget_name = msg_data.get("name") if "name" in msg_data else None
                    # Handle "FORGET_NAME|name" format
                    if not forget_name and "|" in data.decode():
                        forget_name = data.decode().split("|", 1)[1]
                    
                    if forget_name:
                        # Find machine_id by name
                        for mid, info in list(approved_actors.items()):
                            if info.get("name") == forget_name:
                                del approved_actors[mid]
                                save_approved_actors()
                                log(f"Director forgot actor: {forget_name}")
                                # Disconnect if connected
                                for sock, info in list(clients.items()):
                                    if info.get("name") == forget_name and info.get("role") == "actor":
                                        sock.send(format_message("DENIED", 
                                                    reason="Removed by director").encode())
                                        sock.close()
                                        del clients[sock]
                                        break
                                break
                        send_user_list()
            
            elif msg_type == "REFRESH":
                # Request user list refresh
                if client_info.get("role") == "director":
                    send_user_list()
                    send_pending_list()
    
    except Exception as e:
        log(f"Error handling client {addr}: {e}")
    
    finally:
        # Cleanup on disconnect
        machine_id = client_info.get("machine_id")
        if machine_id in pending_actors:
            del pending_actors[machine_id]
        
        if client_socket in clients:
            del clients[client_socket]
        
        if client_info.get("approved"):
            broadcast(format_message("MSG", sender="SERVER", text=f"{client_info.get('name', 'Unknown')} left").encode())
        
        send_user_list()
        send_pending_list()
        client_socket.close()
        log(f"Client disconnected: {client_info.get('name', 'Unknown')} ({addr})")


def forward_file(sender_socket, msg_data):
    """Forward file to all approved clients."""
    sender_name = "Unknown"
    for sock, info in clients.items():
        if sock == sender_socket:
            sender_name = info.get("name", "Unknown")
            break
    
    filename = msg_data.get("filename", "file")
    size = msg_data.get("size", 0)
    
    header = format_message("FILE", sender=sender_name, filename=filename, size=size)
    broadcast(header.encode(), exclude=sender_socket)
    
    remaining = size
    while remaining > 0:
        chunk = sender_socket.recv(min(4096, remaining))
        remaining -= len(chunk)
        for sock, info in clients.items():
            if sock != sender_socket and info.get("approved"):
                try:
                    sock.send(chunk)
                except:
                    pass


def approve_actor(machine_id):
    """Approve a pending actor."""
    global pending_actors
    
    if machine_id not in pending_actors:
        return False
    
    pending_info = pending_actors.pop(machine_id)
    
    approved_actors[machine_id] = {
        "name": pending_info["name"],
        "approved_at": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat()
    }
    save_approved_actors()
    
    # Update client info and notify
    sock = pending_info.get("socket")
    if sock and sock in clients:
        clients[sock]["approved"] = True
        sock.send(format_message("APPROVED").encode())
    
    log(f"Actor approved: {pending_info['name']} ({machine_id[:8]}...)")
    broadcast(format_message("MSG", sender="SERVER", text=f"{pending_info['name']} joined").encode())
    send_user_list()
    send_pending_list()
    
    return True


def main():
    global server_secret
    
    parser = argparse.ArgumentParser(description="vrActorAssist Server")
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--secret", default=DEFAULT_SECRET, help="Shared secret for director auth")
    args = parser.parse_args()
    
    server_secret = args.secret
    
    load_approved_actors()
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind(("0.0.0.0", args.port))
        server.listen(5)
        log(f"Server started on port {args.port}")
        log(f"Director secret: {server_secret[:4]}...{server_secret[-4:]}")
        
        while True:
            client_socket, addr = server.accept()
            thread = threading.Thread(target=handle_client, args=(client_socket, addr))
            thread.daemon = True
            thread.start()
    
    except KeyboardInterrupt:
        log("Server shutting down...")
    except Exception as e:
        log(f"Server error: {e}")
    finally:
        server.close()


if __name__ == "__main__":
    main()