# vrActorAssist Director Client (WebSocket)
# GUI client for directors with approval system
#
# Usage: python director_client_ws.py

import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
import threading
import json
import websocket
import time
import hashlib
import base64
import os
import urllib.request
import tempfile
import subprocess
import sys
from pathlib import Path

from shared import parse_message, format_message, get_machine_id, load_config, save_config, get_default_config_path, APP_VERSION, get_platform_id

# Defaults
DEFAULT_SERVER = "ws://localhost:5555/ws"
DEFAULT_SECRET = "vractor-secret-change-me"
RECONNECT_DELAY = 5


class DirectorClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Director Client v{APP_VERSION}")
        self.root.geometry("850x700")
        self.root.minsize(800, 650)
        
        self.config_path = get_default_config_path("director_config.json")
        self.config = load_config(self.config_path)
        self.machine_id = get_machine_id()
        
        self.ws = None
        self.connected = False
        self.approved = False
        self.should_reconnect = True
        
        self.pending_actors = []  # List of {machine_id, name}
        self.approved_actors = []  # List of names
        self.actor_status = {}  # name -> {"latency_ms": int}
        self.actor_enabled = {}  # name -> bool (checkbox state)
        
        # Countdown state
        self.countdown_active = False
        self.countdown_id = None
        
        # Batch file transfer state
        self.pending_files = {}  # filename -> {path, target, checksum, accepted, batch_id}
        self.active_batches = {}  # batch_id -> {target, file_count, files_done, files_ok, files_err, cancelled}
        self.batch_counter = 0   # Incrementing batch ID
        self.char_actor_map = {}  # character_name -> actor_name (session memory)
        
        self.setup_ui()
        self.display(f"vrActorAssist Director Client v{APP_VERSION}", "info")
        self._cleanup_old_updates()
        
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
        
        # Bigger buttons for VR
        btn_style = {'height': 2, 'width': 10, 'font': ('Arial', 11, 'bold')}
        tk.Button(pending_btn_frame, text="✓ Approve", command=self.approve_selected, **btn_style).pack(side=tk.LEFT, padx=2, pady=2)
        
        # Active actors
        tk.Label(left_frame, text="Active:").pack(anchor='w', padx=5, pady=(10, 0))
        
        # Frame for actor list with checkboxes and indicators
        self.actors_frame = tk.Frame(left_frame)
        self.actors_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Canvas + Scrollbar for scrollable actor list
        self.actors_canvas = tk.Canvas(self.actors_frame, highlightthickness=0)
        self.actors_scrollbar = tk.Scrollbar(self.actors_frame, orient="vertical", command=self.actors_canvas.yview)
        self.actors_inner_frame = tk.Frame(self.actors_canvas)
        
        self.actors_canvas.configure(yscrollcommand=self.actors_scrollbar.set)
        
        self.actors_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.actors_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.actors_canvas_window = self.actors_canvas.create_window((0, 0), window=self.actors_inner_frame, anchor="nw")
        self.actors_inner_frame.bind("<Configure>", lambda e: self.actors_canvas.configure(scrollregion=self.actors_canvas.bbox("all")))
        self.actors_canvas.bind("<Configure>", lambda e: self.actors_canvas.itemconfig(self.actors_canvas_window, width=e.width))
        
        # Store actor row widgets
        self.actor_rows = {}  # name -> {"frame": Frame, "indicator": Label, "checkbox": Checkbutton}
        
        tk.Button(left_frame, text="Forget Actor", command=self.forget_actor, height=2, width=15, font=('Arial', 11, 'bold')).pack(pady=5)
        
        # Toggle all buttons
        toggle_frame = tk.Frame(left_frame)
        toggle_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Button(toggle_frame, text="All On", command=self.enable_all_actors, height=2, width=8, font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=2)
        tk.Button(toggle_frame, text="All Off", command=self.disable_all_actors, height=2, width=8, font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=2)
        
        # Send file button (multi-file with character routing)
        tk.Button(left_frame, text="📁 Send Files...", command=self.send_file_dialog, height=2, width=15, font=('Arial', 11, 'bold')).pack(pady=5)
        
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
        
        # Input area
        input_frame = tk.Frame(right_frame)
        input_frame.pack(fill=tk.X, pady=5)
        
        self.entry = tk.Entry(input_frame, font=('Arial', 11))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry.bind("<Return>", lambda e: self.send_msg())
        
        # Bigger button for VR
        self.send_btn = tk.Button(input_frame, text="Send", command=self.send_msg,
                                   height=2, width=10, font=('Arial', 11, 'bold'))
        self.send_btn.pack(side=tk.RIGHT)
        
        # Command buttons (bigger for VR)
        cmd_frame = tk.Frame(right_frame)
        cmd_frame.pack(fill=tk.X, pady=10)
        
        # Bigger button style for VR
        cmd_btn_style = {'height': 3, 'width': 12, 'font': ('Arial', 14, 'bold')}
        
        tk.Button(cmd_frame, text="▶ GO", command=self.send_go, **cmd_btn_style).pack(side=tk.LEFT, padx=5)
        
        # Play in 3s button (countdown)
        self.play_3s_btn = tk.Button(cmd_frame, text="⏱ Play in 3s", command=self.start_countdown, 
                                      height=3, width=14, font=('Arial', 14, 'bold'))
        self.play_3s_btn.pack(side=tk.LEFT, padx=5)
        
        tk.Button(cmd_frame, text="■ Stop", command=self.send_stop, **cmd_btn_style).pack(side=tk.LEFT, padx=5)
        
        # Window close handler
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
    
    def display(self, message: str, msg_type: str = "normal"):
        """Display a message in the chat area.
        
        Args:
            message: The message to display
            msg_type: One of "success", "error", "warning", "info", "normal"
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "success": "#008800",  # Green
            "error": "#CC0000",    # Red
            "warning": "#CC9900",  # Yellow/Orange
            "info": "#0066CC",     # Blue
            "normal": None         # Default
        }
        
        self.chat_area.config(state=tk.NORMAL)
        color = colors.get(msg_type)
        if color:
            tag_name = f"color_{msg_type}"
            self.chat_area.tag_configure(tag_name, foreground=color)
            self.chat_area.insert(tk.END, f"[{timestamp}] {message}\n", tag_name)
        else:
            self.chat_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)
    
    def prompt_config(self):
        """Prompt for initial configuration."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Director Setup")
        dialog.geometry("400x200")
        dialog.minsize(400, 200)
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
            self.display(f"Config saved to {self.config_path}", "success")
            dialog.destroy()
            self.connect()
        
        # Bigger button for VR
        tk.Button(dialog, text="Connect", command=save_and_close, height=2, width=15, font=('Arial', 11, 'bold')).pack(pady=20)
        
        self.root.wait_window(dialog)
    
    def edit_config(self):
        """Open config editor."""
        if not self.config:
            self.prompt_config()
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Config")
        dialog.geometry("400x180")
        dialog.minsize(400, 180)
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
            self.display("Config updated. Reconnect to apply changes.", "success")
            dialog.destroy()
        
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)
        # Bigger buttons for VR
        tk.Button(btn_frame, text="Save", command=save_changes, height=2, width=10, font=('Arial', 11, 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, height=2, width=10, font=('Arial', 11, 'bold')).pack(side=tk.LEFT)
    
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
            self.display("Connected! Authenticating...", "info")
            
            # Send registration with secret
            secret = self.config.get("secret", DEFAULT_SECRET) if self.config else DEFAULT_SECRET
            register_msg = format_message(
                "REGISTER",
                name="Director",
                machine_id=self.machine_id,
                role="director",
                secret=secret,
                version=APP_VERSION,
                platform=get_platform_id()
            )
            ws.send(register_msg)
        
        def on_message(ws, message):
            self.handle_message(message)
        
        def on_error(ws, error):
            self.display(f"Error: {error}", "error")
        
        def on_close(ws, close_status_code, close_msg):
            self.connected = False
            self.approved = False
            self.root.after(0, lambda: self.status_var.set("Disconnected"))
            if self.should_reconnect:
                self.display(f"Disconnected. Reconnecting in {RECONNECT_DELAY}s...", "warning")
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
                self.display(f"Connection error: {e}", "error")
                if self.should_reconnect:
                    self.display(f"Retrying in {RECONNECT_DELAY}s...", "info")
                    time.sleep(RECONNECT_DELAY)
                else:
                    break
        
        self.root.after(0, lambda: self.connect_btn.config(text="Connect"))
    
    def handle_message(self, data: str):
        """Handle a message from the server."""
        msg_type, msg_data = parse_message(data)
        
        if msg_type == "APPROVED":
            self.approved = True
            self.root.after(0, lambda: self.display("✓ Authenticated as Director", "success"))
            self.root.after(0, lambda: self.status_var.set("Connected (Director)"))
        
        elif msg_type == "VERSION":
            status = msg_data.get("status", "")
            server_ver = msg_data.get("server_version", "")
            message = msg_data.get("message", "")
            if status == "ok":
                self.root.after(0, lambda: self.display(f"✓ Server version: v{server_ver}", "info"))
            elif status == "warning":
                self.root.after(0, lambda: self.display(f"⚠ {message}", "warning"))
            elif status == "unsupported":
                self.root.after(0, lambda: self.display(f"✗ {message}", "error"))
        
        elif msg_type == "UPDATE":
            latest = msg_data.get("latest_version", "")
            url = msg_data.get("download_url", "")
            sha256 = msg_data.get("sha256", "")
            notes = msg_data.get("release_notes", "")
            if latest and url:
                self.root.after(0, lambda: self._show_update_dialog(latest, url, sha256, notes))
        
        elif msg_type == "DENIED":
            reason = msg_data.get("reason", "Unknown reason")
            self.root.after(0, lambda: self.display(f"✗ Denied: {reason}", "error"))
            self.approved = False
        
        elif msg_type == "MSG":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            # Check if it's a warning (from SERVER with ⚠)
            is_warning = sender == "SERVER" and text.startswith("⚠")
            # Don't show our own messages (we already displayed them locally)
            if sender != "Director":
                self.root.after(0, lambda: self.display(f"{sender}: {text}", msg_type="warning" if is_warning else "normal"))
        
        elif msg_type == "PRIV":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            self.root.after(0, lambda: self.display(f"[Private] {sender}: {text}"))
        
        elif msg_type == "ACK":
            actor = msg_data.get("actor", "Unknown")
            command = msg_data.get("command", "")
            status = msg_data.get("status", "")
            self.root.after(0, lambda: self.display(f"✓ {actor}: {command} ({status})", "success"))
        
        elif msg_type == "USERS":
            users = msg_data.get("users", [])
            self.approved_actors = users
            # Initialize enabled state for new actors
            for user in users:
                if user not in self.actor_enabled:
                    self.actor_enabled[user] = True
            self.root.after(0, self.update_approved_list)
            self.root.after(0, lambda: self.display(f"Actors: {', '.join(users)}", "info"))
        
        elif msg_type == "STATUS":
            actors = msg_data.get("actors", [])
            # Update status dict
            self.actor_status = {}
            for actor in actors:
                self.actor_status[actor["name"]] = actor
            self.root.after(0, self.update_actor_indicators)
        
        elif msg_type == "PENDING":
            actors = msg_data.get("actors", [])
            self.pending_actors = actors
            self.root.after(0, self.update_pending_list)
            if actors:
                self.root.after(0, lambda: self.display(f"Pending: {len(actors)} actor(s) waiting", "info"))
        
        elif msg_type == "FILEACK":
            filename = msg_data.get("filename", "")
            accepted = msg_data.get("accept", False)
            if accepted:
                self.root.after(0, lambda: self.display(f"Actor accepted {filename}", "success"))
                self.root.after(0, lambda fn=filename: self.send_file_chunks(fn))
            else:
                self.root.after(0, lambda: self.display(f"Actor declined {filename}", "warning"))
                # If part of a batch, mark as failed and advance queue
                if filename in self.pending_files:
                    batch_id = self.pending_files[filename].get("batch_id")
                    self.pending_files.pop(filename, None)
                    if batch_id and batch_id in self.active_batches:
                        self.active_batches[batch_id]["files_err"] += 1
                        self.active_batches[batch_id]["files_done"] += 1
                        self.active_batches[batch_id]["current"] = None
                        if not self._check_batch_complete(batch_id):
                            self._send_next_in_batch(batch_id)
        
        elif msg_type == "FILEDENY":
            filename = msg_data.get("filename", "")
            reason = msg_data.get("reason", "Unknown")
            self.root.after(0, lambda: self.display(f"File transfer denied: {reason}", "warning"))
            # If part of a batch, mark as failed and advance queue
            if filename in self.pending_files:
                batch_id = self.pending_files[filename].get("batch_id")
                self.pending_files.pop(filename, None)
                if batch_id and batch_id in self.active_batches:
                    self.active_batches[batch_id]["files_err"] += 1
                    self.active_batches[batch_id]["files_done"] += 1
                    self.active_batches[batch_id]["current"] = None
                    if not self._check_batch_complete(batch_id):
                        self._send_next_in_batch(batch_id)
        
        elif msg_type == "FILEOK":
            filename = msg_data.get("filename", "")
            saved_path = msg_data.get("saved_path", "")
            self.root.after(0, lambda: self.display(f"✓ File saved: {saved_path}", "success"))
            # Track batch progress and advance queue
            if filename in self.pending_files:
                batch_id = self.pending_files[filename].get("batch_id")
                self.pending_files.pop(filename, None)
                if batch_id and batch_id in self.active_batches:
                    self.active_batches[batch_id]["files_ok"] += 1
                    self.active_batches[batch_id]["files_done"] += 1
                    self.active_batches[batch_id]["current"] = None
                    if not self._check_batch_complete(batch_id):
                        self._send_next_in_batch(batch_id)
        
        elif msg_type == "FILEERR":
            filename = msg_data.get("filename", "")
            error = msg_data.get("error", "Unknown error")
            self.root.after(0, lambda: self.display(f"✗ File error: {error}", "error"))
            # Track batch progress and advance queue
            if filename in self.pending_files:
                batch_id = self.pending_files[filename].get("batch_id")
                self.pending_files.pop(filename, None)
                if batch_id and batch_id in self.active_batches:
                    self.active_batches[batch_id]["files_err"] += 1
                    self.active_batches[batch_id]["files_done"] += 1
                    self.active_batches[batch_id]["current"] = None
                    if not self._check_batch_complete(batch_id):
                        self._send_next_in_batch(batch_id)
    
    def update_pending_list(self):
        """Update the pending actors listbox."""
        self.pending_list.delete(0, tk.END)
        for actor in self.pending_actors:
            self.pending_list.insert(tk.END, actor["name"])
    
    def update_approved_list(self):
        """Update the approved actors list with indicators and checkboxes."""
        # Clear existing rows
        for widget in self.actors_inner_frame.winfo_children():
            widget.destroy()
        self.actor_rows = {}
        
        # Create rows for each actor
        for name in self.approved_actors:
            self._create_actor_row(name)
    
    def _create_actor_row(self, name: str):
        """Create a row for an actor with indicator and checkbox."""
        row_frame = tk.Frame(self.actors_inner_frame)
        row_frame.pack(fill=tk.X, pady=1)
        
        # Status indicator (colored dot)
        indicator = tk.Label(row_frame, text="⚪", font=('Arial', 12), width=2)
        indicator.pack(side=tk.LEFT)
        
        # Actor name
        name_label = tk.Label(row_frame, text=name, font=('Arial', 11), anchor='w')
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Mic checkbox (enabled/disabled)
        enabled_var = tk.BooleanVar(value=self.actor_enabled.get(name, True))
        is_enabled = enabled_var.get()
        checkbox = tk.Checkbutton(row_frame, text="🔊" if is_enabled else "🔈", variable=enabled_var, 
                                   font=('Arial', 14), indicatoron=False,
                                   command=lambda n=name: self._toggle_actor(n))
        checkbox.pack(side=tk.RIGHT)
        
        self.actor_rows[name] = {
            "frame": row_frame,
            "indicator": indicator,
            "name_label": name_label,
            "checkbox": checkbox,
            "enabled_var": enabled_var
        }
        
        # Update indicator based on status
        self._update_actor_indicator(name)
    
    def _toggle_actor(self, name: str):
        """Toggle actor enabled state."""
        if name in self.actor_rows:
            enabled = self.actor_rows[name]["enabled_var"].get()
            self.actor_enabled[name] = enabled
            # Update checkbox text
            self.actor_rows[name]["checkbox"].config(text="🔊" if enabled else "🔈")
    
    def enable_all_actors(self):
        """Enable all actors."""
        for name in self.approved_actors:
            self.actor_enabled[name] = True
            if name in self.actor_rows:
                self.actor_rows[name]["enabled_var"].set(True)
                self.actor_rows[name]["checkbox"].config(text="🔊")
    
    def disable_all_actors(self):
        """Disable all actors."""
        for name in self.approved_actors:
            self.actor_enabled[name] = False
            if name in self.actor_rows:
                self.actor_rows[name]["enabled_var"].set(False)
                self.actor_rows[name]["checkbox"].config(text="🔈")
    
    def update_actor_indicators(self):
        """Update all actor indicators based on status."""
        for name in self.approved_actors:
            self._update_actor_indicator(name)
    
    def _update_actor_indicator(self, name: str):
        """Update indicator for a single actor."""
        if name not in self.actor_rows:
            # Create row if it doesn't exist
            self._create_actor_row(name)
            return
        
        indicator = self.actor_rows[name]["indicator"]
        name_label = self.actor_rows[name]["name_label"]
        
        if name not in self.actor_status:
            indicator.config(text="⚪")
            name_label.config(text=name)
            return
        
        status = self.actor_status[name]
        latency = status.get("latency_ms", 0)
        
        # Determine color based on latency
        if latency < 0:
            # Timed out
            indicator.config(text="⚪", fg="gray")
            tooltip = "Timed out"
        elif latency < 100:
            indicator.config(text="🟢", fg="green")
            tooltip = f"{latency}ms"
        elif latency < 300:
            indicator.config(text="🟡", fg="#CC9900")
            tooltip = f"{latency}ms"
        else:
            indicator.config(text="🔴", fg="red")
            tooltip = f"{latency}ms"
        
        # Show latency in name label on hover
        name_label.config(text=f"{name}")
        
        # Bind hover events
        def enter(event, t=tooltip):
            name_label.config(text=f"{name} ({t})")
        def leave(event, n=name):
            name_label.config(text=n)
        
        name_label.bind("<Enter>", enter)
        name_label.bind("<Leave>", leave)
    
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
    
    def forget_actor(self):
        """Remove an actor from the approved list."""
        if not self.approved_actors:
            messagebox.showwarning("No Actors", "No actors connected")
            return
        
        # Actor selection dialog (same pattern as send_file_dialog)
        dialog = tk.Toplevel(self.root)
        dialog.title("Forget Actor")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Select actor to forget:", font=('Arial', 12)).pack(pady=10)
        
        # Actor listbox with selection
        listbox_frame = tk.Frame(dialog)
        listbox_frame.pack(fill=tk.X, padx=20)
        
        listbox = tk.Listbox(listbox_frame, height=6, selectmode=tk.SINGLE)
        scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)
        
        for name in self.approved_actors:
            listbox.insert(tk.END, name)
        
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Select first actor by default
        if self.approved_actors:
            listbox.selection_set(0)
            listbox.activate(0)
        
        def do_forget():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("No Selection", "Please select an actor")
                return
            
            actor_name = listbox.get(sel[0])
            if messagebox.askyesno("Confirm", f"Forget {actor_name}?"):
                self.display(f"Forgetting: {actor_name}...", "info")
                if self.ws and self.connected:
                    self.ws.send(f"FORGET_NAME|{actor_name}")
            dialog.destroy()
        
        tk.Button(dialog, text="Forget", command=do_forget, height=2, width=10, font=('Arial', 11, 'bold')).pack(pady=10)
    
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
    
    def send_command(self, command: str):
        """Send a command to enabled actors only."""
        if not self.ws or not self.connected:
            self.display("Not connected")
            return
        
        # Get list of enabled actors
        enabled_actors = [name for name in self.approved_actors if self.actor_enabled.get(name, True)]
        
        if not enabled_actors:
            self.display("No actors enabled")
            return
        
        # Send to each enabled actor via PRIV
        for actor in enabled_actors:
            msg = format_message("PRIV", sender="Director", target=actor, text=command)
            try:
                self.ws.send(msg)
            except Exception as e:
                self.display(f"Send error to {actor}: {e}")
        
        # Log what was sent
        if len(enabled_actors) == len(self.approved_actors):
            self.display(f">> {command} (to all)")
        else:
            self.display(f">> {command} (to: {', '.join(enabled_actors)})")
    
    def send_go(self):
        self.send_command("*go")
    
    def start_countdown(self):
        """Start the 3-second countdown for Play in 3s button."""
        if self.countdown_active:
            return
        
        self.countdown_active = True
        self.play_3s_btn.config(state=tk.DISABLED)
        self._countdown_tick(3)
    
    def _countdown_tick(self, seconds):
        """Countdown tick."""
        if not self.countdown_active:
            # Cancelled
            self.play_3s_btn.config(text="⏱ Play in 3s", state=tk.NORMAL)
            return
        
        if seconds > 0:
            self.play_3s_btn.config(text=f"   {seconds}...   ")
            self.countdown_id = self.root.after(1000, lambda: self._countdown_tick(seconds - 1))
        else:
            # Countdown complete, send command
            self.countdown_active = False
            self.play_3s_btn.config(text="⏱ Play in 3s", state=tk.NORMAL)
            self.send_command("*go")
    
    def cancel_countdown(self):
        """Cancel the countdown."""
        if self.countdown_active:
            self.countdown_active = False
            if self.countdown_id:
                self.root.after_cancel(self.countdown_id)
                self.countdown_id = None
            self.play_3s_btn.config(text="⏱ Play in 3s", state=tk.NORMAL)
            self.display("Countdown cancelled")
    
    def send_stop(self):
        # If countdown is active, cancel it instead of sending stop
        if self.countdown_active:
            self.cancel_countdown()
        else:
            self.send_command("*stop")
    
    # --- Character name parsing ---
    
    @staticmethod
    def parse_character_name(filename: str):
        """Extract character name from filename using ' - ' pattern.
        
        Pattern: 'Scene 4 - Diego.mp3' -> 'Diego'
        Last ' - ' wins: 'EP3 - Scene 4.2 - Diego.wav' -> 'Diego'
        Returns None if no pattern match.
        """
        if ' - ' in filename:
            # Extract after last ' - ', strip extension
            character = filename.rsplit(' - ', 1)[-1].rsplit('.', 1)[0].strip()
            return character if character else None
        return None
    
    # --- Multi-file send dialog ---
    
    def send_file_dialog(self):
        """Open multi-file picker, parse character names, show mapping dialog."""
        if not self.approved_actors:
            messagebox.showwarning("No Actors", "No actors connected")
            return
        
        # Multi-select file picker
        filepaths = filedialog.askopenfilenames(
            title="Select files to send"
        )
        
        if not filepaths:
            return
        
        # Parse filenames for character names
        # Group: {character: [filepath, ...]} or None for ungrouped
        char_groups = {}   # character_name -> [filepath, ...]
        ungrouped = []     # files without character pattern
        
        for fp in filepaths:
            filename = os.path.basename(fp)
            character = self.parse_character_name(filename)
            if character:
                if character not in char_groups:
                    char_groups[character] = []
                char_groups[character].append(fp)
            else:
                ungrouped.append(fp)
        
        # If only one file and no character pattern, use simple single-file flow
        if len(filepaths) == 1 and not char_groups:
            self._send_single_file_dialog(filepaths[0])
            return
        
        # Show character/actor mapping dialog
        self._show_mapping_dialog(char_groups, ungrouped)
    
    def _send_single_file_dialog(self, filepath: str):
        """Original single-file send flow (for backward compat with 1 file, no pattern)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Send File")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Send file to:", font=('Arial', 12)).pack(pady=10)
        
        listbox_frame = tk.Frame(dialog)
        listbox_frame.pack(fill=tk.X, padx=20)
        
        listbox = tk.Listbox(listbox_frame, height=6, selectmode=tk.SINGLE)
        scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)
        
        for name in self.approved_actors:
            listbox.insert(tk.END, name)
        
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        if self.approved_actors:
            listbox.selection_set(0)
            listbox.activate(0)
        
        def do_send():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("No Selection", "Please select an actor")
                return
            actor_name = listbox.get(sel[0])
            dialog.destroy()
            self.send_file_to_actor(filepath, actor_name)
        
        tk.Button(dialog, text="Send", command=do_send, height=2, width=10, font=('Arial', 11, 'bold')).pack(pady=10)
    
    def _show_mapping_dialog(self, char_groups: dict, ungrouped: list):
        """Show character-to-actor mapping dialog for multi-file send."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Map Characters to Actors")
        dialog.geometry("500x450")
        dialog.minsize(450, 350)
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Map files to actors:", font=('Arial', 12, 'bold')).pack(pady=10)
        
        # Scrollable mapping area
        canvas = tk.Canvas(dialog, highlightthickness=0)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        mappings = {}  # Display key -> (character_or_filename, actor_var, is_char_group)
        
        # Character groups
        for char_name, file_list in char_groups.items():
            row = tk.Frame(scroll_frame)
            row.pack(fill=tk.X, pady=2, padx=5)
            
            file_count = len(file_list)
            label_text = f"{char_name}  ({file_count} file{'s' if file_count > 1 else ''})"
            tk.Label(row, text=label_text, font=('Arial', 11), anchor='w', width=25).pack(side=tk.LEFT)
            
            # Auto-fill from session memory
            default_actor = self.char_actor_map.get(char_name, "")
            actor_var = tk.StringVar(value=default_actor)
            
            # Dropdown with actor names + "Skip" option
            options = [""] + self.approved_actors + ["<Skip>"]
            combo = tk.OptionMenu(row, actor_var, *options)
            combo.config(font=('Arial', 10), width=15)
            combo.pack(side=tk.LEFT, padx=5)
            
            mappings[char_name] = (char_name, actor_var, True, file_list)
        
        # Ungrouped files
        for fp in ungrouped:
            filename = os.path.basename(fp)
            row = tk.Frame(scroll_frame)
            row.pack(fill=tk.X, pady=2, padx=5)
            
            # Truncate long filenames
            display_name = filename if len(filename) <= 30 else filename[:27] + "..."
            tk.Label(row, text=display_name, font=('Arial', 10), anchor='w', width=25).pack(side=tk.LEFT)
            
            actor_var = tk.StringVar(value="")
            options = [""] + self.approved_actors + ["<Skip>"]
            combo = tk.OptionMenu(row, actor_var, *options)
            combo.config(font=('Arial', 10), width=15)
            combo.pack(side=tk.LEFT, padx=5)
            
            mappings[filename] = (filename, actor_var, False, [fp])
        
        # "Remember for this session" checkbox
        remember_var = tk.BooleanVar(value=True)
        tk.Checkbutton(scroll_frame, text="Remember character→actor mappings for this session",
                       variable=remember_var, font=('Arial', 10)).pack(pady=10, padx=5, anchor='w')
        
        # Buttons
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def do_send_all():
            # Build per-actor file lists
            actor_files = {}  # actor_name -> [filepath, ...]
            skipped_chars = []
            
            for key, (name, actor_var, is_char, file_list) in mappings.items():
                actor = actor_var.get()
                if actor == "<Skip>" or actor == "":
                    if is_char:
                        skipped_chars.append(name)
                    continue
                if actor not in actor_files:
                    actor_files[actor] = []
                actor_files[actor].extend(file_list)
                
                # Save session memory
                if is_char and remember_var.get():
                    self.char_actor_map[name] = actor
            
            if not actor_files:
                messagebox.showinfo("Nothing to Send", "All files were skipped. Select actors to send files to.")
                return
            
            dialog.destroy()
            
            # Send batches to each actor
            for actor_name, files in actor_files.items():
                self.send_batch_to_actor(files, actor_name)
            
            if skipped_chars:
                self.display(f"Skipped: {', '.join(skipped_chars)} (no actor assigned)", "warning")
        
        tk.Button(btn_frame, text="Send All", command=do_send_all,
                  height=2, width=12, font=('Arial', 11, 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  height=2, width=12, font=('Arial', 11)).pack(side=tk.RIGHT, padx=5)
    
    # --- Batch file transfer ---
    
    def send_batch_to_actor(self, filepaths: list, actor_name: str):
        """Send multiple files to an actor using batch protocol."""
        if not self.ws or not self.connected:
            messagebox.showerror("Error", "Not connected")
            return
        
        # Calculate total size
        total_bytes = 0
        for fp in filepaths:
            total_bytes += os.path.getsize(fp)
        
        file_count = len(filepaths)
        self.batch_counter += 1
        batch_id = self.batch_counter
        
        # Send BATCH_START
        start_msg = format_message("BATCH_START",
            target=actor_name,
            file_count=file_count,
            total_bytes=total_bytes
        )
        self.ws.send(start_msg)
        
        # Track batch
        self.active_batches[batch_id] = {
            "target": actor_name,
            "file_count": file_count,
            "files_done": 0,
            "files_ok": 0,
            "files_err": 0,
            "cancelled": False,
            "queue": filepaths,  # Remaining files to send
            "current": None      # File waiting for FILEACK
        }
        
        self.display(f"📦 Sending batch of {file_count} file{'s' if file_count > 1 else ''} to {actor_name} ({total_bytes/1024:.1f} KB)")
        
        # Send first FILEREQ only — subsequent ones sent after FILEACK
        self._send_next_in_batch(batch_id)
    
    def _send_next_in_batch(self, batch_id: int):
        """Send FILEREQ for the next file in a batch after previous FILEACK received."""
        if batch_id not in self.active_batches:
            return
        
        batch = self.active_batches[batch_id]
        
        if batch["cancelled"]:
            return
        
        if batch["current"] is not None:
            # A file is already pending — skip (shouldn't happen, but guard)
            return
        
        if not batch["queue"]:
            # No more files to queue — batch completion handled by FILEOK/FILEERR
            return
        
        filepath = batch["queue"].pop(0)
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        
        # Calculate MD5 checksum
        md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5.update(chunk)
        checksum = md5.hexdigest()
        
        # Send FILEREQ
        req_msg = format_message("FILEREQ",
            sender="Director",
            target=batch["target"],
            filename=filename,
            size=filesize,
            checksum=checksum
        )
        self.ws.send(req_msg)
        
        # Store in pending with batch_id
        self.pending_files[filename] = {
            "path": filepath,
            "target": batch["target"],
            "checksum": checksum,
            "accepted": False,
            "batch_id": batch_id
        }
        batch["current"] = filename
    
    def _check_batch_complete(self, batch_id: int) -> bool:
        """Check if a batch is complete and send BATCH_END if so.
        
        Returns True if batch is complete (and was cleaned up), False otherwise.
        """
        if batch_id not in self.active_batches:
            return True  # Already cleaned up
        
        batch = self.active_batches[batch_id]
        if batch["files_done"] >= batch["file_count"] or batch["cancelled"]:
            # Batch complete
            target = batch["target"]
            ok = batch["files_ok"]
            err = batch["files_err"]
            
            end_msg = format_message("BATCH_END",
                target=target,
                success_count=ok,
                fail_count=err
            )
            if self.ws and self.connected:
                self.ws.send(end_msg)
            
            status = "✓" if err == 0 else "⚠"
            self.display(f"{status} Batch to {target} complete: {ok} ok, {err} failed", 
                        "success" if err == 0 else "warning")
            
            del self.active_batches[batch_id]
            return True
        return False
    
    def cancel_batch(self, batch_id: int):
        """Cancel an in-progress batch transfer."""
        if batch_id not in self.active_batches:
            return
        
        batch = self.active_batches[batch_id]
        batch["cancelled"] = True
        target = batch["target"]
        
        cancel_msg = format_message("BATCH_CANCEL",
            target=target,
            reason="Cancelled by director"
        )
        if self.ws and self.connected:
            self.ws.send(cancel_msg)
        
        self.display(f"⚠ Batch to {target} cancelled", "warning")
        
        # Cleanup remaining pending files for this batch
        to_remove = [fn for fn, info in self.pending_files.items() 
                     if info.get("batch_id") == batch_id]
        for fn in to_remove:
            del self.pending_files[fn]
        
        del self.active_batches[batch_id]
    
    # --- Backwards-compatible single file send ---
    
    def send_file_to_actor(self, filepath: str, actor_name: str):
        """Send a single file to specific actor (non-batch, backward compatible)."""
        if not self.ws or not self.connected:
            messagebox.showerror("Error", "Not connected")
            return
        
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        
        # Calculate MD5 checksum
        md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5.update(chunk)
        checksum = md5.hexdigest()
        
        # Send file request
        self.display(f"Sending {filename} ({filesize/1024:.1f} KB) to {actor_name}...")
        
        req_msg = format_message("FILEREQ",
            sender="Director",
            target=actor_name,
            filename=filename,
            size=filesize,
            checksum=checksum
        )
        self.ws.send(req_msg)
        
        # Store pending file transfer (no batch_id)
        self.pending_files[filename] = {
            "path": filepath,
            "target": actor_name,
            "checksum": checksum,
            "accepted": False,
            "batch_id": None
        }
    
    def send_file_chunks(self, filename: str):
        """Send file in chunks after accepted."""
        if filename not in self.pending_files:
            return
        
        pending = self.pending_files[filename]
        filepath = pending["path"]
        filesize = os.path.getsize(filepath)
        checksum = pending["checksum"]
        
        # Read file and send in chunks
        chunk_size = 64 * 1024  # 64KB chunks
        total_chunks = (filesize + chunk_size - 1) // chunk_size
        
        # Send FILESTART
        start_msg = format_message("FILESTART",
            filename=filename,
            total_chunks=total_chunks,
            chunk_size=chunk_size
        )
        self.ws.send(start_msg)
        
        # Send chunks
        with open(filepath, 'rb') as f:
            for chunk_num in range(total_chunks):
                chunk_data = f.read(chunk_size)
                b64_data = base64.b64encode(chunk_data).decode('utf-8')
                
                chunk_msg = format_message("FILECHUNK",
                    filename=filename,
                    chunk_num=chunk_num,
                    data=b64_data
                )
                self.ws.send(chunk_msg)
                
                # Progress update every 10 chunks
                if chunk_num % 10 == 0:
                    progress = (chunk_num + 1) / total_chunks * 100
                    self.display(f"  {filename}: {progress:.0f}%")
        
        # Send FILEEND
        end_msg = format_message("FILEEND",
            filename=filename,
            checksum=checksum
        )
        self.ws.send(end_msg)
        
        self.display(f"✓ Sent {filename}", "success")
        # Note: pending_files cleanup happens in FILEOK/FILEERR/FILEDENY handlers
    
    def _show_update_dialog(self, latest_version, download_url, sha256, release_notes):
        """Show update available dialog."""
        notes_text = f"\n\n{release_notes}" if release_notes else ""
        result = messagebox.askyesno(
            "Update Available",
            f"A new version is available: v{latest_version}\n"
            f"You are currently running v{APP_VERSION}\n"
            f"{notes_text}\n\n"
            f"Download and install update?",
            parent=self.root
        )
        if result:
            self._download_update(latest_version, download_url, sha256)
    
    def _download_update(self, version, url, expected_sha256):
        """Download update in a background thread."""
        self.display(f"⬇ Downloading v{version}...", "info")
        
        def download():
            try:
                # Determine temp file path next to current executable
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                else:
                    exe_path = os.path.abspath(__file__)
                
                ext = os.path.splitext(exe_path)[1]
                # Windows: .exe, Linux: .AppImage or no extension
                is_windows = sys.platform == "win32"
                
                if is_windows:
                    suffix = ".exe.tmp"
                else:
                    suffix = ".AppImage.tmp"
                
                temp_path = os.path.join(os.path.dirname(exe_path), f"vrDirectorClient-v{version}{suffix}")
                
                # Download
                self.root.after(0, lambda: self.display(f"⬇ Downloading from {url}...", "info"))
                urllib.request.urlretrieve(url, temp_path)
                
                # Verify SHA256
                if expected_sha256:
                    self.root.after(0, lambda: self.display("Verifying download...", "info"))
                    sha256_hash = hashlib.sha256()
                    with open(temp_path, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha256_hash.update(chunk)
                    actual_sha256 = sha256_hash.hexdigest()
                    
                    if actual_sha256.lower() != expected_sha256.lower():
                        os.remove(temp_path)
                        self.root.after(0, lambda: self.display("✗ Update failed: SHA256 checksum mismatch", "error"))
                        return
                
                # Make executable on Linux
                if not is_windows:
                    os.chmod(temp_path, 0o755)
                
                self.root.after(0, lambda: self.display("✓ Download complete. Will update on restart.", "success"))
                
                # Create and launch updater script
                self._create_updater(exe_path, temp_path, is_windows)
                
            except Exception as e:
                self.root.after(0, lambda: self.display(f"✗ Update failed: {e}", "error"))
        
        threading.Thread(target=download, daemon=True).start()
    
    def _create_updater(self, current_path, new_path, is_windows):
        """Create and launch the updater script, then exit."""
        if is_windows:
            updater_path = os.path.join(os.path.dirname(current_path), "_updater.bat")
            with open(updater_path, "w") as f:
                f.write("@echo off\n")
                f.write("echo Updating vrDirectorClient...\n")
                f.write(f":wait\n")
                f.write(f'tasklist | find "{os.path.basename(current_path)}" >nul 2>&1\n')
                f.write("if %errorlevel%==0 timeout /t 1 >nul & goto wait\n")
                f.write(f'move /y "{new_path}" "{current_path}"\n')
                f.write(f'start "" "{current_path}"\n')
                f.write("del \"%~f0\"\n")
        else:
            updater_path = os.path.join(os.path.dirname(current_path), "_updater.sh")
            with open(updater_path, "w") as f:
                f.write("#!/bin/sh\n")
                f.write("echo 'Updating vrDirectorClient...'\n")
                f.write(f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 1; done\n")
                f.write(f"cp -f '{new_path}' '{current_path}'\n")
                f.write(f"chmod +x '{current_path}'\n")
                f.write(f"exec '{current_path}'\n")
            os.chmod(updater_path, 0o755)
        
        # Launch updater and exit
        if is_windows:
            subprocess.Popen([updater_path], shell=True)
        else:
            subprocess.Popen([updater_path])
        
        self.quit()
    
    def _cleanup_old_updates(self):
        """Clean up temp files and updater scripts from previous updates."""
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            for filename in os.listdir(base_dir):
                filepath = os.path.join(base_dir, filename)
                if filename.endswith('.tmp'):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                elif filename in ('_updater.bat', '_updater.sh'):
                    try:
                        os.remove(filepath)
                    except:
                        pass
        except:
            pass
    
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