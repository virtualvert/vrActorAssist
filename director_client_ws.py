# vrActorAssist Director Client (WebSocket)
# GUI client for directors with approval system
#
# Usage: python director_client_ws.py

import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog, ttk
import threading
import json
import websocket
import time
from pathlib import Path

from shared import parse_message, format_message, get_machine_id, load_config, save_config, get_default_config_path

# Defaults
DEFAULT_SERVER = "ws://localhost:5555/ws"
DEFAULT_SECRET = "vractor-secret-change-me"
RECONNECT_DELAY = 5


class DirectorClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Director Client")
        self.root.geometry("700x550")
        
        self.config_path = get_default_config_path("director_config.json")
        self.config = load_config(self.config_path)
        self.machine_id = get_machine_id()
        
        self.ws = None
        self.connected = False
        self.approved = False
        self.should_reconnect = True
        
        self.pending_actors = []  # List of {machine_id, name}
        self.approved_actors = []  # List of names
        
        self.setup_ui()
        
        # Auto-connect if config exists
        if self.config:
            self.root.after(500, self.connect)
        else:
            self.root.after(500, self.prompt_config)
    
    def setup_ui(self):
        """Setup the GUI."""
        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Edit Config", command=self.edit_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        
        # Main frame
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - Actors
        left_frame = tk.LabelFrame(main_frame, text="Actors", width=200)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_frame.pack_propagate(False)
        
        # Pending actors
        tk.Label(left_frame, text="Pending:").pack(anchor='w', padx=5)
        
        pending_frame = tk.Frame(left_frame)
        pending_frame.pack(fill=tk.X, padx=5)
        
        self.pending_list = tk.Listbox(pending_frame, height=5, width=20)
        self.pending_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        pending_scroll = tk.Scrollbar(pending_frame, command=self.pending_list.yview)
        pending_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.pending_list.config(yscrollcommand=pending_scroll.set)
        
        pending_btn_frame = tk.Frame(left_frame)
        pending_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(pending_btn_frame, text="✓ Approve", command=self.approve_selected, width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(pending_btn_frame, text="✗ Deny", command=self.deny_selected, width=8).pack(side=tk.LEFT, padx=2)
        
        # Approved actors
        tk.Label(left_frame, text="Approved:").pack(anchor='w', padx=5, pady=(10, 0))
        
        approved_frame = tk.Frame(left_frame)
        approved_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.approved_list = tk.Listbox(approved_frame, height=10)
        self.approved_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        approved_scroll = tk.Scrollbar(approved_frame, command=self.approved_list.yview)
        approved_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.approved_list.config(yscrollcommand=approved_scroll.set)
        
        tk.Button(left_frame, text="Forget Actor", command=self.forget_actor).pack(pady=5)
        
        # Right panel - Chat and controls
        right_frame = tk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Status bar
        self.status_var = tk.StringVar(value="Disconnected")
        status_frame = tk.Frame(right_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        tk.Label(status_frame, textvariable=self.status_var, fg="blue").pack(side=tk.LEFT, padx=5)
        
        # Connection button
        self.connect_btn = tk.Button(status_frame, text="Connect", command=self.toggle_connection)
        self.connect_btn.pack(side=tk.RIGHT)
        
        # Chat area
        self.chat_area = scrolledtext.ScrolledText(right_frame, height=15)
        self.chat_area.pack(fill=tk.BOTH, expand=True)
        
        # Target selector
        target_frame = tk.Frame(right_frame)
        target_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(target_frame, text="Target:").pack(side=tk.LEFT)
        self.target_var = tk.StringVar(value="(All)")
        self.target_combo = ttk.Combobox(target_frame, textvariable=self.target_var, width=20, state="readonly")
        self.target_combo['values'] = ["(All)"]
        self.target_combo.pack(side=tk.LEFT, padx=5)
        
        tk.Button(target_frame, text="Refresh", command=self.refresh_users).pack(side=tk.LEFT)
        
        # Input area
        input_frame = tk.Frame(right_frame)
        input_frame.pack(fill=tk.X, pady=5)
        
        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry.bind("<Return>", lambda e: self.send_msg())
        
        self.send_btn = tk.Button(input_frame, text="Send", command=self.send_msg)
        self.send_btn.pack(side=tk.RIGHT)
        
        # Command buttons
        cmd_frame = tk.Frame(right_frame)
        cmd_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(cmd_frame, text="▶ GO", command=self.send_go, width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(cmd_frame, text="⏹ Stop", command=self.send_stop, width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(cmd_frame, text="? Ready?", command=self.send_ready_check, width=8).pack(side=tk.LEFT, padx=2)
        
        tk.Button(cmd_frame, text="▶ Target GO", command=self.send_targeted_go, width=10).pack(side=tk.LEFT, padx=2)
        tk.Button(cmd_frame, text="⏹ Target Stop", command=self.send_targeted_stop, width=10).pack(side=tk.LEFT, padx=2)
        
        # Window close handler
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
    
    def display(self, message: str):
        """Display a message in the chat area."""
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, message + "\n")
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)
    
    def prompt_config(self):
        """Prompt for initial configuration."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Director Setup")
        dialog.geometry("400x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(frame, text="Server URL:").pack(anchor='w')
        server_entry = tk.Entry(frame, width=45)
        server_entry.insert(0, DEFAULT_SERVER)
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Director Secret:").pack(anchor='w')
        secret_entry = tk.Entry(frame, width=45, show="*")
        secret_entry.insert(0, self.config.get("secret", "") if self.config else "")
        secret_entry.pack(fill=tk.X)
        
        def save_and_close():
            self.config = {
                "server_url": server_entry.get().strip(),
                "secret": secret_entry.get().strip()
            }
            save_config(self.config_path, self.config)
            self.display(f"Config saved to {self.config_path}")
            dialog.destroy()
            self.connect()
        
        tk.Button(dialog, text="Connect", command=save_and_close).pack(pady=20)
        
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
    
    def get_ws_url(self, server_url: str) -> str:
        """Convert HTTP URL to WebSocket URL with secret."""
        # Get secret
        secret = self.config.get("secret", DEFAULT_SECRET) if self.config else DEFAULT_SECRET
        
        # Handle various URL formats
        if server_url.startswith("https://"):
            base = server_url[8:].rstrip("/")
            return f"wss://{base}/ws?secret={secret}"
        elif server_url.startswith("http://"):
            base = server_url[7:].rstrip("/")
            return f"ws://{base}/ws?secret={secret}"
        elif server_url.startswith("wss://") or server_url.startswith("ws://"):
            base = server_url.rstrip("/")
            if "?" in base:
                return f"{base}&secret={secret}"
            return f"{base}?secret={secret}"
        else:
            return f"ws://{server_url}/ws?secret={secret}"
    
    def toggle_connection(self):
        """Toggle connection state."""
        if self.connected:
            self.disconnect()
        else:
            self.connect()
    
    def connect(self):
        """Connect to server."""
        if not self.config:
            self.display("No config - cannot connect")
            return
        
        self.should_reconnect = True
        self.connect_btn.config(text="Disconnect")
        threading.Thread(target=self._connect_thread, daemon=True).start()
    
    def disconnect(self):
        """Disconnect from server."""
        self.should_reconnect = False
        if self.ws:
            try:
                # WebSocketApp.close() doesn't take args
                self.ws.close()
            except:
                pass
        self.connected = False
        self.approved = False
        self.connect_btn.config(text="Connect")
        self.status_var.set("Disconnected")
        self.display("Disconnected")
    
    def _connect_thread(self):
        """Connection thread."""
        server_url = self.config.get("server_url", DEFAULT_SERVER)
        ws_url = self.get_ws_url(server_url)
        
        self.display(f"Connecting to {ws_url.split('?')[0]}...")
        
        def on_open(ws):
            self.connected = True
            self.display("Connected! Authenticating...")
            
            # Send registration with secret
            secret = self.config.get("secret", DEFAULT_SECRET) if self.config else DEFAULT_SECRET
            register_msg = format_message(
                "REGISTER",
                name="Director",
                machine_id=self.machine_id,
                role="director",
                secret=secret
            )
            ws.send(register_msg)
        
        def on_message(ws, message):
            self.handle_message(message)
        
        def on_error(ws, error):
            self.display(f"Error: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            self.connected = False
            self.approved = False
            self.root.after(0, lambda: self.status_var.set("Disconnected"))
            if self.should_reconnect:
                self.display(f"Disconnected. Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)
                if self.should_reconnect:
                    self._connect_thread()
        
        while self.should_reconnect:
            try:
                # Use WebSocketApp for automatic ping handling
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                
                # Run with ping enabled
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
                
                if not self.should_reconnect:
                    break
                    
            except Exception as e:
                self.display(f"Connection error: {e}")
                if self.should_reconnect:
                    self.display(f"Retrying in {RECONNECT_DELAY}s...")
                    time.sleep(RECONNECT_DELAY)
                else:
                    break
        
        self.root.after(0, lambda: self.connect_btn.config(text="Connect"))
    
    def handle_message(self, data: str):
        """Handle a message from the server."""
        msg_type, msg_data = parse_message(data)
        
        if msg_type == "APPROVED":
            self.approved = True
            self.root.after(0, lambda: self.display("✓ Authenticated as Director"))
            self.root.after(0, lambda: self.status_var.set("Connected (Director)"))
        
        elif msg_type == "DENIED":
            reason = msg_data.get("reason", "Unknown reason")
            self.root.after(0, lambda: self.display(f"✗ Denied: {reason}"))
            self.approved = False
        
        elif msg_type == "MSG":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            self.root.after(0, lambda: self.display(f"{sender}: {text}"))
        
        elif msg_type == "PRIV":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            self.root.after(0, lambda: self.display(f"[Private] {sender}: {text}"))
        
        elif msg_type == "ACK":
            actor = msg_data.get("actor", "Unknown")
            command = msg_data.get("command", "")
            status = msg_data.get("status", "")
            self.root.after(0, lambda: self.display(f"✓ {actor}: {command} ({status})"))
        
        elif msg_type == "USERS":
            users = msg_data.get("users", [])
            self.approved_actors = users
            self.root.after(0, self.update_approved_list)
            self.root.after(0, lambda: self.display(f"Actors: {', '.join(users)}"))
        
        elif msg_type == "PENDING":
            actors = msg_data.get("actors", [])
            self.pending_actors = actors
            self.root.after(0, self.update_pending_list)
            if actors:
                self.root.after(0, lambda: self.display(f"Pending: {len(actors)} actor(s) waiting"))
    
    def update_pending_list(self):
        """Update the pending actors listbox."""
        self.pending_list.delete(0, tk.END)
        for actor in self.pending_actors:
            self.pending_list.insert(tk.END, actor["name"])
    
    def update_approved_list(self):
        """Update the approved actors listbox."""
        self.approved_list.delete(0, tk.END)
        for name in self.approved_actors:
            self.approved_list.insert(tk.END, name)
        
        # Update target combo
        targets = ["(All)"] + self.approved_actors
        self.target_combo['values'] = targets
    
    def approve_selected(self):
        """Approve selected pending actor."""
        selection = self.pending_list.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select an actor to approve")
            return
        
        idx = selection[0]
        if idx < len(self.pending_actors):
            actor = self.pending_actors[idx]
            self.display(f"Approving: {actor['name']}...")
            
            if self.ws and self.connected:
                # Use pipe-delimited format: APPROVE|machine_id
                self.ws.send(f"APPROVE|{actor['machine_id']}")
    
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
                
                if self.ws and self.connected:
                    # Use pipe-delimited format: DENY|machine_id
                    self.ws.send(f"DENY|{actor['machine_id']}")
    
    def forget_actor(self):
        """Remove an actor from the approved list."""
        selection = self.approved_list.curselection()
        if not selection:
            target = self.target_var.get()
            if target and target != "(All)":
                if messagebox.askyesno("Confirm Forget", f"Forget {target}?"):
                    self.display(f"Forgetting: {target}...")
                    if self.ws and self.connected:
                        self.ws.send(f"FORGET_NAME|{target}")
                return
            
            messagebox.showwarning("No Selection", "Please select an actor from the list or choose a target")
            return
        
        idx = selection[0]
        name = self.approved_list.get(idx)
        
        if messagebox.askyesno("Confirm Forget", f"Forget {name}?"):
            self.display(f"Forgetting: {name}...")
            if self.ws and self.connected:
                self.ws.send(f"FORGET_NAME|{name}")
    
    def refresh_users(self):
        """Request user list refresh."""
        if self.ws and self.connected:
            self.ws.send("REFRESH")
    
    def send_msg(self):
        """Send a chat message."""
        msg = self.entry.get().strip()
        if not msg or not self.ws or not self.connected:
            return
        
        self.entry.delete(0, tk.END)
        # Display own message locally
        self.display(f"Director: {msg}")
        
        try:
            self.ws.send(format_message("MSG", sender="Director", text=msg))
        except Exception as e:
            self.display(f"Send error: {e}")
    
    def send_command(self, command: str, target: str = None):
        """Send a command to actors."""
        if not self.ws or not self.connected:
            self.display("Not connected")
            return
        
        if target and target != "(All)":
            msg = format_message("PRIV", sender="Director", target=target, text=command)
        else:
            msg = format_message("CMD", command=command)
        
        try:
            self.ws.send(msg)
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
    
    def quit(self):
        """Quit the application."""
        self.should_reconnect = False
        self.disconnect()
        self.root.destroy()
    
    def run(self):
        """Run the application."""
        self.root.mainloop()


if __name__ == "__main__":
    client = DirectorClient()
    client.run()