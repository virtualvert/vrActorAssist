# vrActorAssist Director Client
# Cross-platform GUI for directing VR actor sessions
#
# Features:
#   - Approve/deny pending actors
#   - Forget approved actors (remove from server)
#   - Send sound commands (*go, *stop, etc.)
#   - Target specific actors
#   - File transfer
#   - Connection status

import socket
import threading
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog
import datetime
import time
import json
import os

from shared import (
    parse_message, format_message,
    get_machine_id, load_config, save_config, get_default_config_path
)

# Connection settings
DEFAULT_SERVER = "127.0.0.1:5555"
DEFAULT_SECRET = "vractor-secret-change-me"
RECONNECT_BASE_DELAY = 2
RECONNECT_MAX_DELAY = 60


class DirectorClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("vrActorAssist - Director")
        self.root.geometry("900x650")
        
        self.config_path = get_default_config_path("director_config.json")
        self.config = None
        
        self.sock = None
        self.connected = False
        self.reconnect_delay = RECONNECT_BASE_DELAY
        self.should_reconnect = True
        
        self.machine_id = get_machine_id()
        self.pending_actors = []  # List of {machine_id, name}
        self.approved_actors = []  # List of names
        
        self.build_gui()
        self.load_or_prompt_config()
        
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        
        if self.config:
            self.connect()
    
    def build_gui(self):
        # Main container with paned window for resizable sections
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left side - Chat and controls
        left_frame = tk.Frame(main_pane)
        main_pane.add(left_frame)
        
        # Status bar
        status_frame = tk.Frame(left_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.status_var = tk.StringVar(value="Not connected")
        tk.Label(status_frame, textvariable=self.status_var, 
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        self.status_indicator = tk.Label(status_frame, text="●", 
                                          font=('Arial', 16), fg="red")
        self.status_indicator.pack(side=tk.RIGHT)
        
        # Chat area
        chat_frame = tk.Frame(left_frame)
        chat_frame.pack(fill=tk.BOTH, expand=True)
        
        self.chat = tk.Text(chat_frame, height=20, state=tk.DISABLED)
        self.chat.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = tk.Scrollbar(chat_frame, command=self.chat.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat.config(yscrollcommand=scrollbar.set)
        
        # Input area
        input_frame = tk.Frame(left_frame)
        input_frame.pack(fill=tk.X, pady=5)
        
        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.send_msg())
        self.entry.config(state=tk.DISABLED)
        
        self.send_btn = tk.Button(input_frame, text="Send", command=self.send_msg)
        self.send_btn.pack(side=tk.LEFT, padx=(5, 0))
        self.send_btn.config(state=tk.DISABLED)
        
        # Command buttons frame
        cmd_frame = tk.LabelFrame(left_frame, text="Sound Commands", padx=5, pady=5)
        cmd_frame.pack(fill=tk.X, pady=5)
        
        # Row 1: Main commands
        cmd_row1 = tk.Frame(cmd_frame)
        cmd_row1.pack(fill=tk.X, pady=2)
        
        tk.Button(cmd_row1, text="▶ GO (Play All)", command=self.send_go,
                  bg="#4CAF50", fg="white", width=14).pack(side=tk.LEFT, padx=2)
        
        tk.Button(cmd_row1, text="⏹ STOP All", command=self.send_stop,
                  bg="#f44336", fg="white", width=14).pack(side=tk.LEFT, padx=2)
        
        tk.Button(cmd_row1, text="📋 Ready Check", command=self.send_ready_check,
                  bg="#2196F3", fg="white", width=14).pack(side=tk.LEFT, padx=2)
        
        # Row 2: Targeted commands
        cmd_row2 = tk.Frame(cmd_frame)
        cmd_row2.pack(fill=tk.X, pady=2)
        
        tk.Label(cmd_row2, text="Target:").pack(side=tk.LEFT, padx=5)
        self.target_var = tk.StringVar()
        self.target_combo = ttk.Combobox(cmd_row2, textvariable=self.target_var, width=18)
        self.target_combo['values'] = ['(All)']
        self.target_combo.current(0)
        self.target_combo.pack(side=tk.LEFT, padx=5)
        
        tk.Button(cmd_row2, text="Play", command=self.send_targeted_go,
                  bg="#81C784", width=8).pack(side=tk.LEFT, padx=2)
        
        tk.Button(cmd_row2, text="Stop", command=self.send_targeted_stop,
                  bg="#E57373", width=8).pack(side=tk.LEFT, padx=2)
        
        # File transfer button
        tk.Button(cmd_row2, text="📁 Send File", 
                  command=self.send_file).pack(side=tk.LEFT, padx=10)
        
        # Right side - Actors panel
        right_frame = tk.Frame(main_pane, width=280)
        main_pane.add(right_frame)
        
        # Pending actors section
        pending_frame = tk.LabelFrame(right_frame, text="Pending Approval", padx=5, pady=5)
        pending_frame.pack(fill=tk.X, pady=5)
        
        self.pending_list = tk.Listbox(pending_frame, height=5, width=30)
        self.pending_list.pack(fill=tk.X, pady=2)
        self.pending_list.bind('<<ListboxSelect>>', self.on_pending_select)
        
        pending_btn_frame = tk.Frame(pending_frame)
        pending_btn_frame.pack(fill=tk.X)
        
        tk.Button(pending_btn_frame, text="✓ Approve", command=self.approve_selected,
                  bg="#4CAF50", fg="white", width=10).pack(side=tk.LEFT, padx=2)
        
        tk.Button(pending_btn_frame, text="✗ Deny", command=self.deny_selected,
                  bg="#f44336", fg="white", width=10).pack(side=tk.LEFT, padx=2)
        
        # Approved actors section
        approved_frame = tk.LabelFrame(right_frame, text="Connected Actors", padx=5, pady=5)
        approved_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.approved_list = tk.Listbox(approved_frame, height=10, width=30)
        self.approved_list.pack(fill=tk.BOTH, expand=True)
        
        approved_btn_frame = tk.Frame(approved_frame)
        approved_btn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(approved_btn_frame, text="🔄 Refresh", 
                  command=self.refresh_users).pack(side=tk.LEFT, padx=2)
        
        tk.Button(approved_btn_frame, text="🗑 Forget", 
                  command=self.forget_actor,
                  bg="#FF9800", fg="white").pack(side=tk.LEFT, padx=2)
        
        # Connection buttons
        conn_frame = tk.Frame(right_frame)
        conn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(conn_frame, text="Reconnect", 
                  command=self.manual_reconnect).pack(side=tk.LEFT, padx=2)
        
        tk.Button(conn_frame, text="Edit Config", 
                  command=self.edit_config).pack(side=tk.LEFT, padx=2)
    
    def load_or_prompt_config(self):
        """Load config or prompt for first-time setup."""
        self.config = load_config(self.config_path)
        
        if self.config:
            self.display(f"Loaded config: {self.config.get('server_url', 'unknown')}")
        else:
            self.prompt_config()
    
    def prompt_config(self):
        """Prompt for server URL and secret."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Director Setup")
        dialog.geometry("450x220")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Enter connection details:", 
                 font=('Arial', 12, 'bold')).pack(pady=10)
        
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(frame, text="Server URL:").pack(anchor='w')
        server_entry = tk.Entry(frame, width=45)
        server_entry.insert(0, DEFAULT_SERVER)
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Director Secret:").pack(anchor='w')
        secret_entry = tk.Entry(frame, width=45, show="*")
        secret_entry.insert(0, DEFAULT_SECRET)
        secret_entry.pack(fill=tk.X)
        
        tk.Label(frame, text="(Secret is set on server startup)", 
                 font=('Arial', 8), fg='gray').pack(anchor='w')
        
        def save_and_connect():
            server_url = server_entry.get().strip()
            secret = secret_entry.get().strip()
            
            if not server_url or not secret:
                messagebox.showwarning("Required", "Please fill in all fields")
                return
            
            self.config = {
                "server_url": server_url,
                "secret": secret,
                "machine_id": self.machine_id
            }
            save_config(self.config_path, self.config)
            self.display(f"Config saved to {self.config_path}")
            dialog.destroy()
            self.connect()
        
        tk.Button(dialog, text="Connect", command=save_and_connect).pack(pady=20)
        
        self.root.wait_window(dialog)
    
    def edit_config(self):
        """Open config editor."""
        if not self.config:
            self.prompt_config()
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Config")
        dialog.geometry("400x150")
        dialog.transient(self.root)
        dialog.grab_set()
        
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(frame, text="Server URL:").pack(anchor='w')
        server_entry = tk.Entry(frame, width=45)
        server_entry.insert(0, self.config.get("server_url", DEFAULT_SERVER))
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Director Secret:").pack(anchor='w')
        secret_entry = tk.Entry(frame, width=45, show="*")
        secret_entry.insert(0, self.config.get("secret", ""))
        secret_entry.pack(fill=tk.X)
        
        def save_changes():
            self.config["server_url"] = server_entry.get().strip()
            self.config["secret"] = secret_entry.get().strip()
            save_config(self.config_path, self.config)
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
        """Connect to server."""
        if not self.config:
            self.display("No config - cannot connect")
            return
        
        threading.Thread(target=self._connect_thread, daemon=True).start()
    
    def _connect_thread(self):
        """Connection thread with retry logic."""
        server_url = self.config.get("server_url", DEFAULT_SERVER)
        host, port = self.parse_server_url(server_url)
        secret = self.config.get("secret", DEFAULT_SECRET)
        
        self.display(f"Connecting to {host}:{port}...")
        
        while self.should_reconnect:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((host, port))
                
                self.sock = sock
                self.connected = True
                self.reconnect_delay = RECONNECT_BASE_DELAY
                
                # Send registration with secret
                register_msg = format_message(
                    "REGISTER",
                    name="Director",
                    machine_id=self.machine_id,
                    role="director",
                    secret=secret
                )
                sock.send(register_msg.encode())
                
                self.receive_loop()
                
            except socket.timeout:
                self.display("Connection timeout")
            except ConnectionRefusedError:
                self.display("Connection refused")
            except Exception as e:
                self.display(f"Connection error: {e}")
            
            self.connected = False
            self.update_status()
            self.enable_input(False)
            
            if self.should_reconnect:
                self.display(f"Reconnecting in {self.reconnect_delay}s...")
                time.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, RECONNECT_MAX_DELAY)
    
    def receive_loop(self):
        """Main receive loop."""
        self.update_status()
        self.enable_input(True)
        self.display("✓ Connected as Director")
        
        while self.connected and self.sock:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                
                msg_type, msg_data = parse_message(data)
                
                if msg_type == "APPROVED":
                    self.display("✓ Authenticated successfully")
                
                elif msg_type == "DENIED":
                    reason = msg_data.get("reason", "Unknown reason")
                    self.display(f"✗ Authentication failed: {reason}")
                    self.should_reconnect = False
                
                elif msg_type == "MSG":
                    sender = msg_data.get("sender", "Unknown")
                    text = msg_data.get("text", "")
                    self.display(f"{sender}: {text}")
                
                elif msg_type == "PRIV":
                    sender = msg_data.get("sender", "Unknown")
                    text = msg_data.get("text", "")
                    self.display(f"[Private] {sender}: {text}")
                
                elif msg_type == "USERS":
                    users = msg_data.get("users", [])
                    self.approved_actors = users
                    self.root.after(0, self.update_approved_list)
                    self.display(f"Actors: {', '.join(users) or 'None'}")
                
                elif msg_type == "PENDING":
                    actors = msg_data.get("actors", [])
                    self.pending_actors = actors
                    self.root.after(0, self.update_pending_list)
                    self.display(f"Pending: {len(actors)} actor(s) waiting")
                
                elif msg_type == "ACK":
                    actor = msg_data.get("actor", "Unknown")
                    command = msg_data.get("command", "")
                    status = msg_data.get("status", "")
                    self.display(f"✓ {actor}: {command} {status}")
                
                elif msg_type == "FILE":
                    # Directors shouldn't normally receive files, but handle it
                    self.receive_file(msg_data)
                
            except socket.timeout:
                continue
            except Exception as e:
                self.display(f"Receive error: {e}")
                break
        
        self.connected = False
        self.update_status()
        self.enable_input(False)
    
    def update_pending_list(self):
        """Update the pending actors listbox."""
        self.pending_list.delete(0, tk.END)
        for actor in self.pending_actors:
            display_name = f"{actor['name']} ({actor['machine_id'][:8]}...)"
            self.pending_list.insert(tk.END, display_name)
    
    def update_approved_list(self):
        """Update the approved actors listbox."""
        self.approved_list.delete(0, tk.END)
        for name in self.approved_actors:
            self.approved_list.insert(tk.END, name)
        
        # Update target combo
        actor_list = ['(All)'] + [name for name in self.approved_actors if name != "Director"]
        self.target_combo['values'] = actor_list
    
    def on_pending_select(self, event):
        """Handle pending actor selection."""
        pass  # Selection is read from listbox when approve/deny is clicked
    
    def approve_selected(self):
        """Approve selected pending actor."""
        selection = self.pending_list.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select an actor to approve")
            return
        
        idx = selection[0]
        if idx < len(self.pending_actors):
            actor = self.pending_actors[idx]
            # Send approve command (server handles this internally)
            # For now, we'll send a special message
            self.display(f"Approving: {actor['name']}...")
            # The server's approval is handled via the pending_actors update
            # We need to signal the server somehow - let's use a command
            # Actually, the server needs an approve API - let's add a direct socket message
            self.sock.send(f"APPROVE|{actor['machine_id']}".encode())
    
    def deny_selected(self):
        """Deny selected pending actor."""
        selection = self.pending_list.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select an actor to deny")
            return
        
        idx = selection[0]
        if idx < len(self.pending_actors):
            actor = self.pending_actors[idx]
            if messagebox.askyesno("Confirm Deny", f"Deny {actor['name']}?"):
                self.display(f"Denying: {actor['name']}...")
                self.sock.send(f"DENY|{actor['machine_id']}".encode())
    
    def forget_actor(self):
        """Remove an actor from the approved list."""
        selection = self.approved_list.curselection()
        if not selection:
            # Also check if we have the actor by name in target combo
            target = self.target_var.get()
            if target and target != "(All)":
                if messagebox.askyesno("Confirm Forget", 
                    f"Forget {target}?\nThey will need to re-approve next time."):
                    self.display(f"Forgetting: {target}...")
                    # Find machine_id from approved list
                    # We need to track this - for now, use name-based forget
                    self.sock.send(f"FORGET_NAME|{target}".encode())
                return
            
            messagebox.showwarning("No Selection", 
                "Please select an actor from the list or choose a target")
            return
        
        idx = selection[0]
        name = self.approved_list.get(idx)
        
        if messagebox.askyesno("Confirm Forget", 
            f"Forget {name}?\nThey will need to re-approve next time."):
            self.display(f"Forgetting: {name}...")
            self.sock.send(f"FORGET_NAME|{name}".encode())
    
    def refresh_users(self):
        """Request user list refresh."""
        if self.sock and self.connected:
            self.sock.send("REFRESH".encode())
    
    def send_msg(self):
        """Send a chat message."""
        msg = self.entry.get().strip()
        if not msg or not self.sock or not self.connected:
            return
        
        self.entry.delete(0, tk.END)
        # Display own message locally
        self.display(f"Director: {msg}")
        try:
            self.sock.send(format_message("MSG", sender="Director", text=msg).encode())
        except Exception as e:
            self.display(f"Send error: {e}")
    
    def send_command(self, command, target=None):
        """Send a command to actors."""
        if not self.sock or not self.connected:
            self.display("Not connected")
            return
        
        if target and target != "(All)":
            msg = format_message("PRIV", sender="Director", target=target, text=command)
        else:
            msg = format_message("CMD", command=command)
        
        try:
            self.sock.send(msg.encode())
            self.display(f">> {command}" + (f" (to {target})" if target and target != "(All)" else ""))
        except Exception as e:
            self.display(f"Send error: {e}")
    
    def send_go(self):
        self.send_command("*go")
    
    def send_stop(self):
        self.send_command("*stop")
    
    def send_ready_check(self):
        self.send_command("*ready?")
    
    def send_targeted_go(self):
        target = self.target_var.get()
        self.send_command("*go", target if target != "(All)" else None)
    
    def send_targeted_stop(self):
        target = self.target_var.get()
        self.send_command("*stop", target if target != "(All)" else None)
    
    def send_file(self):
        """Send a file to all actors."""
        path = filedialog.askopenfilename()
        if not path:
            return
        
        if not self.sock or not self.connected:
            self.display("Not connected")
            return
        
        filename = os.path.basename(path)
        size = os.path.getsize(path)
        
        # Send header
        header = format_message("FILE", sender="Director", filename=filename, size=size)
        self.sock.send(header.encode())
        
        # Send file data
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                self.sock.send(chunk)
        
        self.display(f"Sent file: {filename} ({size} bytes)")
    
    def receive_file(self, msg_data):
        """Receive a file transfer."""
        sender = msg_data.get("sender", "Unknown")
        filename = msg_data.get("filename", "file")
        size = msg_data.get("size", 0)
        
        self.display(f"Receiving file: {filename} from {sender}")
        
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
    
    def enable_input(self, enabled):
        """Enable or disable input controls."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.root.after(0, lambda: self.entry.config(state=state))
        self.root.after(0, lambda: self.send_btn.config(state=state))
    
    def update_status(self):
        """Update status display."""
        def _update():
            if self.connected:
                self.status_var.set("Connected")
                self.status_indicator.config(fg="green")
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
    client = DirectorClient()
    client.root.mainloop()