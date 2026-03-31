# vrActorAssist Actor Client
# Connects to server, receives commands, triggers Soundpad
#
# Features:
#   - Config file (same folder as executable)
#   - Auto-connect on launch
#   - Reconnection with exponential backoff
#   - Soundpad command execution
#   - Connection status indicator

import socket
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox
import datetime
import time
import json
import os
import sys
import platform

from shared import (
    parse_message, format_message, 
    get_machine_id, load_config, save_config, get_default_config_path
)
from soundpad import execute_command, is_windows

# Connection settings
DEFAULT_SERVER = "127.0.0.1:5555"
RECONNECT_BASE_DELAY = 2  # seconds
RECONNECT_MAX_DELAY = 60  # seconds


class ActorClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("vrActorAssist - Actor Client")
        self.root.geometry("500x400")
        
        self.config_path = get_default_config_path("actor_config.json")
        self.config = None
        
        self.sock = None
        self.connected = False
        self.approved = False
        self.reconnect_delay = RECONNECT_BASE_DELAY
        self.should_reconnect = True
        
        self.machine_id = get_machine_id()
        
        self.build_gui()
        self.load_or_prompt_config()
        
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        
        # Start connection
        if self.config:
            self.connect()
    
    def build_gui(self):
        # Main container
        main = tk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Status bar
        status_frame = tk.Frame(main)
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.status_var = tk.StringVar(value="Not connected")
        self.status_label = tk.Label(status_frame, textvariable=self.status_var, 
                                      font=('Arial', 10, 'bold'))
        self.status_label.pack(side=tk.LEFT)
        
        self.status_indicator = tk.Label(status_frame, text="●", 
                                           font=('Arial', 16), fg="red")
        self.status_indicator.pack(side=tk.RIGHT)
        
        # Actor name display
        name_frame = tk.Frame(main)
        name_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(name_frame, text="Name:", font=('Arial', 10)).pack(side=tk.LEFT)
        self.name_var = tk.StringVar(value="Not set")
        tk.Label(name_frame, textvariable=self.name_var, 
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=(5, 0))
        
        # Chat area
        chat_frame = tk.Frame(main)
        chat_frame.pack(fill=tk.BOTH, expand=True)
        
        self.chat = tk.Text(chat_frame, height=15, state=tk.DISABLED)
        self.chat.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = tk.Scrollbar(chat_frame, command=self.chat.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat.config(yscrollcommand=scrollbar.set)
        
        # Input area
        input_frame = tk.Frame(main)
        input_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.send_msg())
        self.entry.config(state=tk.DISABLED)
        
        self.send_btn = tk.Button(input_frame, text="Send", command=self.send_msg)
        self.send_btn.pack(side=tk.LEFT, padx=(5, 0))
        self.send_btn.config(state=tk.DISABLED)
        
        # Bottom buttons
        btn_frame = tk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.reconnect_btn = tk.Button(btn_frame, text="Reconnect", 
                                         command=self.manual_reconnect)
        self.reconnect_btn.pack(side=tk.LEFT)
        
        tk.Button(btn_frame, text="Edit Config", 
                  command=self.edit_config).pack(side=tk.LEFT, padx=(5, 0))
        
        # Soundpad status
        if is_windows():
            tk.Label(btn_frame, text="Soundpad: Ready", 
                     fg="green").pack(side=tk.RIGHT)
        else:
            tk.Label(btn_frame, text="Soundpad: Simulation (not Windows)", 
                     fg="orange").pack(side=tk.RIGHT)
    
    def load_or_prompt_config(self):
        """Load config or prompt for first-time setup."""
        self.config = load_config(self.config_path)
        
        if self.config:
            self.name_var.set(self.config.get("actor_name", "Unknown"))
            self.display(f"Loaded config: {self.config.get('server_url', 'unknown')}")
        else:
            self.prompt_config()
    
    def prompt_config(self):
        """Prompt user for server URL and actor name."""
        dialog = tk.Toplevel(self.root)
        dialog.title("First Time Setup")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center on parent
        dialog.geometry(f"+{self.root.winfo_x() + 50}+{self.root.winfo_y() + 50}")
        
        tk.Label(dialog, text="Enter connection details:", 
                 font=('Arial', 12, 'bold')).pack(pady=10)
        
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(frame, text="Server URL:").pack(anchor='w')
        server_entry = tk.Entry(frame, width=40)
        server_entry.insert(0, DEFAULT_SERVER)
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Your Name:").pack(anchor='w')
        name_entry = tk.Entry(frame, width=40)
        name_entry.pack(fill=tk.X)
        
        def save_and_close():
            server_url = server_entry.get().strip()
            actor_name = name_entry.get().strip()
            
            if not server_url or not actor_name:
                messagebox.showwarning("Required", "Please fill in all fields")
                return
            
            self.config = {
                "server_url": server_url,
                "actor_name": actor_name,
                "machine_id": self.machine_id
            }
            save_config(self.config_path, self.config)
            self.name_var.set(actor_name)
            self.display(f"Config saved to {self.config_path}")
            dialog.destroy()
            self.connect()
        
        tk.Button(dialog, text="Connect", command=save_and_close).pack(pady=20)
        
        # Wait for dialog
        self.root.wait_window(dialog)
    
    def edit_config(self):
        """Open config editor."""
        if not self.config:
            self.prompt_config()
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Config")
        dialog.geometry("400x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(frame, text="Server URL:").pack(anchor='w')
        server_entry = tk.Entry(frame, width=40)
        server_entry.insert(0, self.config.get("server_url", DEFAULT_SERVER))
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Your Name:").pack(anchor='w')
        name_entry = tk.Entry(frame, width=40)
        name_entry.insert(0, self.config.get("actor_name", ""))
        name_entry.pack(fill=tk.X)
        
        def save_changes():
            self.config["server_url"] = server_entry.get().strip()
            self.config["actor_name"] = name_entry.get().strip()
            save_config(self.config_path, self.config)
            self.name_var.set(self.config["actor_name"])
            self.display("Config updated. Reconnect to apply changes.")
            dialog.destroy()
        
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Save", command=save_changes).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)
    
    def parse_server_url(self, url):
        """Parse server URL into host and port.
        
        Handles:
        - https://hostname.tailXXX.ts.net/ (Tailscale Funnel)
        - http://hostname:port/
        - hostname:port
        - hostname (default port 5555)
        """
        from urllib.parse import urlparse
        
        # Add scheme if missing for urlparse
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        
        parsed = urlparse(url)
        host = parsed.hostname or parsed.netloc.split(':')[0]
        
        # Get port from URL or use default
        if parsed.port:
            port = parsed.port
        elif parsed.scheme == 'https':
            port = 443
        elif parsed.scheme == 'http':
            # Check if there's a port in the original string
            if ':' in parsed.netloc and parsed.netloc.count(':') == 1:
                try:
                    port = int(parsed.netloc.split(':')[1])
                except:
                    port = 80
            else:
                port = 80
        else:
            port = 5555
        
        return host, port
    
    def connect(self):
        """Connect to server in a background thread."""
        if not self.config:
            self.display("No config - cannot connect")
            return
        
        threading.Thread(target=self._connect_thread, daemon=True).start()
    
    def _connect_thread(self):
        """Connection thread with retry logic."""
        server_url = self.config.get("server_url", DEFAULT_SERVER)
        host, port = self.parse_server_url(server_url)
        
        self.display(f"Connecting to {host}:{port}...")
        
        while self.should_reconnect:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((host, port))
                
                self.sock = sock
                self.connected = True
                self.reconnect_delay = RECONNECT_BASE_DELAY
                
                # Send registration (no secret for actors)
                register_msg = format_message(
                    "REGISTER",
                    name=self.config.get("actor_name", "Unknown"),
                    machine_id=self.machine_id,
                    role="actor",
                    secret=""  # Empty secret for actors
                )
                sock.send(register_msg.encode())
                
                # Start receive loop
                self.receive_loop()
                
            except socket.timeout:
                self.display(f"Connection timeout")
            except ConnectionRefusedError:
                self.display(f"Connection refused")
            except Exception as e:
                self.display(f"Connection error: {e}")
            
            self.connected = False
            self.update_status()
            
            if self.should_reconnect:
                self.display(f"Reconnecting in {self.reconnect_delay}s...")
                time.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, RECONNECT_MAX_DELAY)
    
    def receive_loop(self):
        """Main receive loop."""
        self.update_status()
        
        while self.connected and self.sock:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                
                msg_type, msg_data = parse_message(data)
                
                if msg_type == "APPROVED":
                    self.approved = True
                    self.display("✓ Approved by director!")
                    self.enable_input(True)
                    self.update_status()
                
                elif msg_type == "DENIED":
                    reason = msg_data.get("reason", "Unknown reason")
                    self.display(f"✗ Denied: {reason}")
                    self.approved = False
                    self.enable_input(False)
                    if "Pending" in reason:
                        self.display("Waiting for director approval...")
                
                elif msg_type == "MSG":
                    sender = msg_data.get("sender", "Unknown")
                    text = msg_data.get("text", "")
                    self.display(f"{sender}: {text}")
                
                elif msg_type == "PRIV":
                    sender = msg_data.get("sender", "Unknown")
                    text = msg_data.get("text", "")
                    self.display(f"[Private] {sender}: {text}")
                
                elif msg_type == "CMD":
                    command = msg_data.get("command", "")
                    args = msg_data.get("args", "")
                    self.display(f">> Command: {command}")
                    
                    # Execute Soundpad command
                    success = execute_command(command, args)
                    if success:
                        # Send ACK back
                        ack_msg = format_message("ACK", 
                            actor=self.config.get("actor_name", "Unknown"),
                            command=command,
                            status="OK"
                        )
                        self.sock.send(ack_msg.encode())
                        self.display(f"✓ Executed: {command}")
                    else:
                        self.display(f"✗ Failed: {command}")
                
                elif msg_type == "USERS":
                    users = msg_data.get("users", [])
                    self.display(f"Users: {', '.join(users)}")
                
                elif msg_type == "FILE":
                    self.receive_file(msg_data)
                
            except socket.timeout:
                continue
            except Exception as e:
                self.display(f"Receive error: {e}")
                break
        
        self.connected = False
        self.approved = False
        self.enable_input(False)
        self.update_status()
    
    def receive_file(self, msg_data):
        """Receive a file transfer."""
        sender = msg_data.get("sender", "Unknown")
        filename = msg_data.get("filename", "file")
        size = msg_data.get("size", 0)
        
        self.display(f"Receiving file: {filename} ({size} bytes) from {sender}")
        
        # Ask where to save
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(initialfile=filename)
        if not path:
            self.display("File transfer cancelled")
            return
        
        remaining = size
        with open(path, "wb") as f:
            while remaining > 0:
                chunk = self.sock.recv(min(4096, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        
        self.display(f"File saved: {path}")
    
    def send_msg(self):
        """Send a chat message."""
        msg = self.entry.get().strip()
        if not msg or not self.sock or not self.approved:
            return
        
        self.entry.delete(0, tk.END)
        # Display own message locally
        self.display(f"You: {msg}")
        try:
            self.sock.send(format_message("MSG", 
                sender=self.config.get("actor_name", "Unknown"),
                text=msg
            ).encode())
        except Exception as e:
            self.display(f"Send error: {e}")
    
    def enable_input(self, enabled):
        """Enable or disable input controls."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.root.after(0, lambda: self.entry.config(state=state))
        self.root.after(0, lambda: self.send_btn.config(state=state))
    
    def update_status(self):
        """Update status display."""
        def _update():
            if self.connected and self.approved:
                self.status_var.set("Connected & Approved")
                self.status_indicator.config(fg="green")
            elif self.connected:
                self.status_var.set("Connected - Pending Approval")
                self.status_indicator.config(fg="orange")
            else:
                self.status_var.set("Disconnected")
                self.status_indicator.config(fg="red")
        self.root.after(0, _update)
    
    def display(self, text):
        """Display a message in the chat area."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        def _display():
            self.chat.config(state=tk.NORMAL)
            self.chat.insert(tk.END, f"[{timestamp}] {text}\n")
            self.chat.yview(tk.END)
            self.chat.config(state=tk.DISABLED)
        self.root.after(0, _display)
    
    def manual_reconnect(self):
        """Manually trigger reconnection."""
        self.should_reconnect = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        time.sleep(0.5)
        self.should_reconnect = True
        self.reconnect_delay = RECONNECT_BASE_DELAY
        self.connect()
    
    def close(self):
        """Clean shutdown."""
        self.should_reconnect = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.root.destroy()


if __name__ == "__main__":
    client = ActorClient()
    client.root.mainloop()