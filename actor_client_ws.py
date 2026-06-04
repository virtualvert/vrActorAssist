# vrActorAssist Actor Client (WebSocket)
# GUI client for actors with Soundpad integration
#
# Usage: python actor_client_ws.py

import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
import threading
import json
import websocket
import time
import base64
import hashlib
import os
import urllib.request
import tempfile
import subprocess
import sys
from pathlib import Path

from shared import parse_message, format_message, get_machine_id, load_config, save_config, get_default_config_path, APP_VERSION, get_platform_id
from soundpad import execute_command, set_soundpad_path

# OSC configuration defaults
OSC_DEFAULT_HOST = "127.0.0.1"
OSC_DEFAULT_PORT = 9000

# Defaults
DEFAULT_SERVER = "ws://localhost:5555/ws"
RECONNECT_DELAY = 5


class ActorClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Actor Client v{APP_VERSION}")
        self.root.geometry("550x500")
        self.root.minsize(500, 450)
        
        self.config_path = get_default_config_path("actor_config.json")
        self.config = load_config(self.config_path)
        
        # Migrate config to add new fields if missing
        if self.config:
            changed = False
            if "receive_dir" not in self.config:
                self.config["receive_dir"] = str(Path.home() / "Downloads")
                changed = True
            if "auto_accept_files" not in self.config:
                self.config["auto_accept_files"] = False
                changed = True
            if "soundpad_enabled" not in self.config:
                self.config["soundpad_enabled"] = True
                changed = True
            # OSC config migration
            if "osc_enabled" not in self.config:
                self.config["osc_enabled"] = True
                changed = True
            if "vrchat_osc_host" not in self.config:
                self.config["vrchat_osc_host"] = OSC_DEFAULT_HOST
                changed = True
            if "vrchat_osc_port" not in self.config:
                self.config["vrchat_osc_port"] = OSC_DEFAULT_PORT
                changed = True
            if changed:
                save_config(self.config_path, self.config)
                self.display("Config updated with new fields", "info")
            
            # Set Soundpad path from config if available
            if "soundpad_path" in self.config:
                set_soundpad_path(self.config["soundpad_path"])
        
        self.machine_id = get_machine_id()
        
        self.ws = None
        self.connected = False
        self.approved = False
        self.should_reconnect = True
        
        # Incoming file transfer state
        self.incoming_file = None
        self.file_chunks = {}
        
        # Batch transfer state
        self.active_batch = None  # {file_count, total_bytes, files_received, files_ok, files_err}
        
        # OSC state
        self.osc_client = None  # python-osc UDP client
        self.osc_pending_timers = []  # Active threading.Timer objects for scheduled cues
        
        self.setup_ui()
        self.display(f"vrActorAssist Actor Client v{APP_VERSION}", "info")
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
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)
        
        # Status bar with connection button
        self.status_var = tk.StringVar(value="Disconnected")
        status_frame = tk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        tk.Label(status_frame, textvariable=self.status_var, fg="blue").pack(side=tk.LEFT, padx=5)
        
        # Bigger button for VR
        self.connect_btn = tk.Button(status_frame, text="Connect", command=self.toggle_connection,
                                      height=2, width=12, font=('Arial', 11, 'bold'))
        self.connect_btn.pack(side=tk.RIGHT)
        
        # Chat area
        self.chat_area = scrolledtext.ScrolledText(self.root, state=tk.DISABLED)
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Input area
        input_frame = tk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.entry = tk.Entry(input_frame, font=('Arial', 11))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry.bind("<Return>", lambda e: self.send_msg())
        self.entry.config(state=tk.DISABLED)
        
        # Bigger button for VR
        self.send_btn = tk.Button(input_frame, text="Send", command=self.send_msg, state=tk.DISABLED,
                                   height=2, width=10, font=('Arial', 11, 'bold'))
        self.send_btn.pack(side=tk.RIGHT)
        
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
        dialog.title("Actor Setup")
        dialog.geometry("450x420")
        dialog.minsize(450, 420)
        dialog.transient(self.root)
        dialog.grab_set()
        
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(frame, text="Server URL:").pack(anchor='w')
        server_entry = tk.Entry(frame, width=40)
        server_entry.insert(0, DEFAULT_SERVER)
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Your Name:").pack(anchor='w')
        name_entry = tk.Entry(frame, width=40)
        name_entry.pack(fill=tk.X, pady=(0, 10))
        
        # File receive directory
        tk.Label(frame, text="File Receive Directory:").pack(anchor='w')
        dir_frame = tk.Frame(frame)
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        
        dir_entry = tk.Entry(dir_frame, width=30)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        dir_entry.insert(0, str(Path.home() / "Downloads"))
        
        def browse_dir():
            path = filedialog.askdirectory(title="Select directory for received files")
            if path:
                dir_entry.delete(0, tk.END)
                dir_entry.insert(0, path)
        
        tk.Button(dir_frame, text="Browse", command=browse_dir).pack(side=tk.LEFT, padx=5)
        
        # Soundpad path (optional)
        tk.Label(frame, text="Soundpad Path (optional):").pack(anchor='w')
        sp_frame = tk.Frame(frame)
        sp_frame.pack(fill=tk.X, pady=(0, 10))
        
        sp_entry = tk.Entry(sp_frame, width=30)
        sp_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sp_entry.insert(0, "")
        
        def browse_sp():
            path = filedialog.askopenfilename(
                title="Select Soundpad.exe",
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
            )
            if path:
                sp_entry.delete(0, tk.END)
                sp_entry.insert(0, path)
        
        tk.Button(sp_frame, text="Browse", command=browse_sp).pack(side=tk.LEFT, padx=5)
        
        # Auto-accept toggle
        auto_accept_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Auto-accept incoming files", variable=auto_accept_var).pack(anchor='w')
        
        # Soundpad enable toggle
        soundpad_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Enable Soundpad commands (disable if you don't own Soundpad)",
                       variable=soundpad_enabled_var).pack(anchor='w')
        
        # OSC settings
        osc_frame = tk.LabelFrame(frame, text="VRChat OSC")
        osc_frame.pack(fill=tk.X, pady=(10, 5))
        
        osc_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(osc_frame, text="Enable OSC triggers", variable=osc_enabled_var).pack(anchor='w', padx=5)
        
        host_frame = tk.Frame(osc_frame)
        host_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(host_frame, text="Host:").pack(side=tk.LEFT)
        osc_host_entry = tk.Entry(host_frame, width=20)
        osc_host_entry.insert(0, OSC_DEFAULT_HOST)
        osc_host_entry.pack(side=tk.LEFT, padx=5)
        
        tk.Label(host_frame, text="Port:").pack(side=tk.LEFT)
        osc_port_entry = tk.Entry(host_frame, width=8)
        osc_port_entry.insert(0, str(OSC_DEFAULT_PORT))
        osc_port_entry.pack(side=tk.LEFT, padx=5)
        
        def save_and_close():
            self.config = {
                "server_url": server_entry.get().strip(),
                "actor_name": name_entry.get().strip() or "Actor",
                "receive_dir": dir_entry.get().strip(),
                "auto_accept_files": auto_accept_var.get(),
                "soundpad_enabled": soundpad_enabled_var.get(),
                "osc_enabled": osc_enabled_var.get(),
                "vrchat_osc_host": osc_host_entry.get().strip() or OSC_DEFAULT_HOST,
                "vrchat_osc_port": int(osc_port_entry.get().strip() or str(OSC_DEFAULT_PORT))
            }
            # Save Soundpad path if provided
            sp_path = sp_entry.get().strip()
            if sp_path:
                self.config["soundpad_path"] = sp_path
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
        dialog.geometry("450x420")
        dialog.minsize(450, 420)
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
        name_entry.pack(fill=tk.X, pady=(0, 10))
        
        # File receive directory
        tk.Label(frame, text="File Receive Directory:").pack(anchor='w')
        dir_frame = tk.Frame(frame)
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        
        dir_entry = tk.Entry(dir_frame, width=30)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        dir_entry.insert(0, self.config.get("receive_dir", str(Path.home() / "Downloads")))
        
        def browse_dir():
            path = filedialog.askdirectory(title="Select directory for received files")
            if path:
                dir_entry.delete(0, tk.END)
                dir_entry.insert(0, path)
        
        tk.Button(dir_frame, text="Browse", command=browse_dir).pack(side=tk.LEFT, padx=5)
        
        # Soundpad path (optional)
        tk.Label(frame, text="Soundpad Path (optional):").pack(anchor='w')
        sp_frame = tk.Frame(frame)
        sp_frame.pack(fill=tk.X, pady=(0, 10))
        
        sp_entry = tk.Entry(sp_frame, width=30)
        sp_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sp_entry.insert(0, self.config.get("soundpad_path", ""))
        
        def browse_sp():
            path = filedialog.askopenfilename(
                title="Select Soundpad.exe",
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
            )
            if path:
                sp_entry.delete(0, tk.END)
                sp_entry.insert(0, path)
        
        tk.Button(sp_frame, text="Browse", command=browse_sp).pack(side=tk.LEFT, padx=5)
        
        # Auto-accept toggle
        auto_accept_var = tk.BooleanVar(value=self.config.get("auto_accept_files", False))
        tk.Checkbutton(frame, text="Auto-accept incoming files", variable=auto_accept_var).pack(anchor='w')
        
        # Soundpad enable toggle
        soundpad_enabled_var = tk.BooleanVar(value=self.config.get("soundpad_enabled", True))
        tk.Checkbutton(frame, text="Enable Soundpad commands", variable=soundpad_enabled_var).pack(anchor='w')
        
        # OSC settings
        osc_frame = tk.LabelFrame(frame, text="VRChat OSC")
        osc_frame.pack(fill=tk.X, pady=(10, 5))
        
        osc_enabled_var = tk.BooleanVar(value=self.config.get("osc_enabled", True))
        tk.Checkbutton(osc_frame, text="Enable OSC triggers", variable=osc_enabled_var).pack(anchor='w', padx=5)
        
        host_frame = tk.Frame(osc_frame)
        host_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(host_frame, text="Host:").pack(side=tk.LEFT)
        osc_host_entry = tk.Entry(host_frame, width=20)
        osc_host_entry.insert(0, self.config.get("vrchat_osc_host", OSC_DEFAULT_HOST))
        osc_host_entry.pack(side=tk.LEFT, padx=5)
        
        tk.Label(host_frame, text="Port:").pack(side=tk.LEFT)
        osc_port_entry = tk.Entry(host_frame, width=8)
        osc_port_entry.insert(0, str(self.config.get("vrchat_osc_port", OSC_DEFAULT_PORT)))
        osc_port_entry.pack(side=tk.LEFT, padx=5)
        
        def save_changes():
            self.config["server_url"] = server_entry.get().strip()
            self.config["actor_name"] = name_entry.get().strip() or "Actor"
            self.config["receive_dir"] = dir_entry.get().strip()
            self.config["auto_accept_files"] = auto_accept_var.get()
            self.config["soundpad_enabled"] = soundpad_enabled_var.get()
            self.config["osc_enabled"] = osc_enabled_var.get()
            self.config["vrchat_osc_host"] = osc_host_entry.get().strip() or OSC_DEFAULT_HOST
            try:
                self.config["vrchat_osc_port"] = int(osc_port_entry.get().strip())
            except ValueError:
                self.config["vrchat_osc_port"] = OSC_DEFAULT_PORT
            sp_path = sp_entry.get().strip()
            if sp_path:
                self.config["soundpad_path"] = sp_path
            elif "soundpad_path" in self.config:
                del self.config["soundpad_path"]
            save_config(self.config_path, self.config)
            self.display("Config updated. Reconnect to apply changes.", "success")
            dialog.destroy()
        
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)
        # Bigger buttons for VR
        tk.Button(btn_frame, text="Save", command=save_changes, height=2, width=10, font=('Arial', 11, 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, height=2, width=10, font=('Arial', 11, 'bold')).pack(side=tk.LEFT)
    
    def get_ws_url(self, server_url: str) -> str:
        """Convert HTTP URL to WebSocket URL."""
        # Handle various URL formats
        if server_url.startswith("https://"):
            return "wss://" + server_url[8:].rstrip("/") + "/ws"
        elif server_url.startswith("http://"):
            return "ws://" + server_url[7:].rstrip("/") + "/ws"
        elif server_url.startswith("wss://") or server_url.startswith("ws://"):
            # Already websocket URL
            if "/ws" in server_url:
                return server_url
            return server_url.rstrip("/") + "/ws"
        else:
            # Assume plain host:port
            return f"ws://{server_url}/ws"
    
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
        self.enable_input(False)
        self.display("Disconnected", "error")
    
    def handle_forgotten(self):
        """Handle being forgotten by director - disconnect locally."""
        self.should_reconnect = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        self.connected = False
        self.approved = False
        self.connect_btn.config(text="Connect")
        self.status_var.set("Forgotten - click Connect to rejoin")
        self.enable_input(False)
    
    def _connect_thread(self):
        """Connection thread using WebSocketApp for proper ping handling."""
        server_url = self.config.get("server_url", DEFAULT_SERVER)
        ws_url = self.get_ws_url(server_url)
        
        self.display(f"Connecting to {ws_url}...")
        
        def on_open(ws):
            self.connected = True
            self.display("Connected! Registering...", "info")
            
            # Send registration
            register_msg = format_message(
                "REGISTER",
                name=self.config.get("actor_name", "Unknown"),
                machine_id=self.machine_id,
                role="actor",
                secret="",
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
            self.root.after(0, lambda: self.enable_input(False))
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
                
                # Run with ping enabled (sends ping every 30s, expects pong within 10s)
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
        # Handle raw PING (latency check)
        if data == "PING":
            if self.ws and self.connected:
                try:
                    self.ws.send("PONG")
                except:
                    pass
            return
        
        msg_type, msg_data = parse_message(data)
        
        if msg_type == "APPROVED":
            self.approved = True
            actor_name = self.config.get("actor_name", "Unknown")
            self.root.after(0, lambda: self.display("✓ Approved by director!", "success"))
            self.root.after(0, lambda: self.status_var.set(f"Connected (as {actor_name})"))
            self.root.after(0, lambda: self.enable_input(True))
            # Initialize OSC client for receiving cues
            self._init_osc_client()
        
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
            self.root.after(0, lambda: self.display(f"✗ {reason}", "error"))
            self.approved = False
            self.root.after(0, lambda: self.enable_input(False))
            if "Pending" in reason:
                self.root.after(0, lambda: self.display("Waiting for director approval...", "info"))
        
        elif msg_type == "MSG":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            # Check for forgotten message
            if "forgotten" in text.lower() and sender == "SERVER":
                self.root.after(0, lambda: self.display("You have been forgotten. Click Connect to request approval.", "warning"))
                self.root.after(0, self.handle_forgotten)
            elif sender != self.config.get("actor_name", "Unknown"):
                self.root.after(0, lambda: self.display(f"{sender}: {text}"))
        
        elif msg_type == "PRIV":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            self.root.after(0, lambda: self.display(f"[Private] {sender}: {text}"))
            
            # Execute as command (same as CMD) — skip if Soundpad disabled
            soundpad_ok = self.config.get("soundpad_enabled", True) if self.config else True
            if soundpad_ok and text.startswith("*"):
                success, error_msg = execute_command(text, "")
            else:
                success, error_msg = True, None
            if success:
                ack_msg = format_message("ACK", 
                    actor=self.config.get("actor_name", "Unknown"),
                    command=text,
                    status="OK"
                )
                self.ws.send(ack_msg)
                self.root.after(0, lambda: self.display(f"✓ Executed: {text}", "success"))
            else:
                self.root.after(0, lambda: self.display(f"✗ Failed: {text}", "error"))
                if error_msg:
                    self.root.after(0, lambda msg=error_msg: self.display(f"   {msg}", "error"))
        
        elif msg_type == "CMD":
            command = msg_data.get("command", "")
            args = msg_data.get("args", "")
            self.root.after(0, lambda: self.display(f">> Command: {command}"))
            
            # Cancel OSC timers on stop
            if command in ("stop", "*stop"):
                self._cancel_osc_timers()
            
            # Execute Soundpad command (unless disabled)
            soundpad_ok = self.config.get("soundpad_enabled", True) if self.config else True
            if soundpad_ok:
                success, error_msg = execute_command(command, args)
            else:
                success, error_msg = True, None  # Silently skip, still ACK
            if success:
                ack_msg = format_message("ACK", 
                    actor=self.config.get("actor_name", "Unknown"),
                    command=command,
                    status="OK"
                )
                self.ws.send(ack_msg)
                self.root.after(0, lambda: self.display(f"✓ Executed: {command}", "success"))
            else:
                self.root.after(0, lambda: self.display(f"✗ Failed: {command}", "error"))
                if error_msg:
                    self.root.after(0, lambda msg=error_msg: self.display(f"   {msg}", "error"))
        
        elif msg_type == "USERS":
            users = msg_data.get("users", [])
            self.root.after(0, lambda: self.display(f"Actors: {', '.join(users)}"))
        
        elif msg_type == "FILEREQ":
            sender = msg_data.get("sender", "Unknown")
            filename = msg_data.get("filename", "")
            size = msg_data.get("size", 0)
            checksum = msg_data.get("checksum", "")
            
            # Store pending file info
            self.incoming_file = {
                "sender": sender,
                "filename": filename,
                "size": size,
                "checksum": checksum
            }
            
            # Ask user to accept
            self.root.after(0, lambda: self.show_file_request(filename, size))
        
        elif msg_type == "FILESTART":
            filename = msg_data.get("filename", "")
            total_chunks = msg_data.get("total_chunks", 0)
            chunk_size = msg_data.get("chunk_size", 0)
            
            self.file_chunks[filename] = {
                "data": b"",
                "total": total_chunks,
                "received": 0,
                "chunk_size": chunk_size
            }
            self.root.after(0, lambda: self.display(f"Receiving {filename}..."))
        
        elif msg_type == "FILECHUNK":
            filename = msg_data.get("filename", "")
            chunk_num = msg_data.get("chunk_num", 0)
            b64_data = msg_data.get("data", "")
            
            if filename in self.file_chunks:
                # Decode and append
                chunk_data = base64.b64decode(b64_data)
                self.file_chunks[filename]["data"] += chunk_data
                self.file_chunks[filename]["received"] += 1
                
                # Progress update every 10 chunks
                total = self.file_chunks[filename]["total"]
                if self.file_chunks[filename]["received"] % 10 == 0:
                    progress = self.file_chunks[filename]["received"] / total * 100
                    self.root.after(0, lambda p=progress, fn=filename: self.display(f"  {fn}: {p:.0f}%"))
        
        elif msg_type == "FILEEND":
            filename = msg_data.get("filename", "")
            checksum = msg_data.get("checksum", "")
            
            if filename in self.file_chunks:
                # Verify checksum
                received_checksum = hashlib.md5(self.file_chunks[filename]["data"]).hexdigest()
                
                if received_checksum == checksum:
                    # Save file
                    save_dir = self.config.get("receive_dir", "")
                    if not save_dir:
                        # Prompt for directory
                        save_dir = filedialog.askdirectory(title="Save file to...")
                        if not save_dir:
                            self.root.after(0, lambda: self.display("✗ File save cancelled", "error"))
                            return
                        # Save to config
                        self.config["receive_dir"] = save_dir
                        save_config(self.config_path, self.config)
                    
                    save_path = os.path.join(save_dir, filename)
                    
                    # Overwrite handling
                    file_saved = False
                    if os.path.exists(save_path):
                        auto_accept = self.config.get("auto_accept_files", False)
                        if auto_accept:
                            # Silent overwrite
                            with open(save_path, 'wb') as f:
                                f.write(self.file_chunks[filename]["data"])
                            self.root.after(0, lambda sp=save_path: self.display(f"⚠ Saved (replaced existing): {sp}", "warning"))
                            file_saved = True
                        else:
                            # Write to temp file first to avoid holding bytes in lambda
                            import tempfile
                            temp_fd, temp_path = tempfile.mkstemp(prefix="vra_", suffix=os.path.splitext(filename)[1])
                            try:
                                with os.fdopen(temp_fd, 'wb') as tmp_f:
                                    tmp_f.write(self.file_chunks[filename]["data"])
                            except:
                                os.close(temp_fd)
                                raise
                            # Prompt for overwrite — dialog handles FILEOK/FILEDENY
                            self.root.after(0, lambda fn=filename, sd=save_dir, tp=temp_path: 
                                self._show_overwrite_dialog(fn, sd, tp))
                            # Cleanup chunks but DON'T send FILEOK yet — dialog handles that
                            del self.file_chunks[filename]
                            return
                    else:
                        with open(save_path, 'wb') as f:
                            f.write(self.file_chunks[filename]["data"])
                        self.root.after(0, lambda sp=save_path: self.display(f"✓ Saved: {sp}", "success"))
                        file_saved = True
                    
                    if file_saved:
                        # Send confirmation
                        ok_msg = format_message("FILEOK", filename=filename, saved_path=save_path)
                        self.ws.send(ok_msg)
                        
                        # Track batch progress
                        self._on_file_received(ok=True)
                else:
                    self.root.after(0, lambda: self.display("✗ Checksum mismatch", "error"))
                    err_msg = format_message("FILEERR", filename=filename, error="Checksum mismatch")
                    self.ws.send(err_msg)
                    self._on_file_received(ok=False)
                
                # Cleanup
                del self.file_chunks[filename]
        
        # Batch file transfer messages
        elif msg_type == "BATCH_START":
            file_count = msg_data.get("file_count", 0)
            total_bytes = msg_data.get("total_bytes", 0)
            size_str = f"{total_bytes/1024:.1f} KB" if total_bytes < 1024*1024 else f"{total_bytes/1024/1024:.1f} MB"
            self.active_batch = {
                "file_count": file_count,
                "total_bytes": total_bytes,
                "files_received": 0,
                "files_ok": 0,
                "files_err": 0
            }
            self.root.after(0, lambda fc=file_count, ss=size_str: 
                self.display(f"📦 Receiving batch of {fc} file{'s' if fc > 1 else ''} ({ss})", "info"))
        
        elif msg_type == "BATCH_END":
            if self.active_batch:
                ok = self.active_batch["files_ok"]
                err = self.active_batch["files_err"]
                total = self.active_batch["file_count"]
                status = "✓" if err == 0 else "⚠"
                msg_type_str = "success" if err == 0 else "warning"
                self.root.after(0, lambda: self.display(
                    f"{status} Batch complete: {ok}/{total} saved" + (f", {err} failed" if err > 0 else ""),
                    msg_type_str))
                self.active_batch = None
        
        elif msg_type == "BATCH_CANCEL":
            reason = msg_data.get("reason", "")
            self.root.after(0, lambda: self.display(f"⚠ Batch cancelled by director{': ' + reason if reason else ''}", "warning"))
            self.active_batch = None
        
        # OSC cue trigger — fire parameter immediately (no delay for MVP)
        elif msg_type == "OSC_CUE":
            parameter = msg_data.get("parameter", "")
            value = msg_data.get("value", "")
            # Fire on the main thread to avoid tkinter thread issues
            self.root.after(0, lambda p=parameter, v=value: self._send_osc_parameter(p, v))
    
    def show_file_request(self, filename: str, size: int):
        """Show file request dialog."""
        size_kb = size / 1024
        save_dir = self.config.get("receive_dir", "")
        auto_accept = self.config.get("auto_accept_files", False)
        
        # Auto-accept if enabled
        if auto_accept and save_dir:
            ack_msg = format_message("FILEACK",
                filename=filename,
                accept="1",
                save_dir=save_dir
            )
            self.ws.send(ack_msg)
            self.display(f"Auto-accepted {filename} ({size_kb:.1f} KB)", "success")
            self.display(f"Save location: {save_dir}", "info")
            return
        
        # Prompt for directory if not set
        if not save_dir:
            save_dir = filedialog.askdirectory(title="Select directory for received files")
            if save_dir:
                self.config["receive_dir"] = save_dir
                save_config(self.config_path, self.config)
            else:
                # Cancelled
                deny_msg = format_message("FILEDENY", filename=filename, reason="No save directory")
                self.ws.send(deny_msg)
                self.display(f"Declined {filename} (no save directory)")
                return
        
        result = messagebox.askyesno(
            "Incoming File",
            f"{self.incoming_file['sender']} wants to send:\n\n"
            f"  {filename}\n"
            f"  ({size_kb:.1f} KB)\n\n"
            f"Save to: {save_dir}\n\n"
            f"Accept?"
        )
        
        if result:
            # Send accept
            ack_msg = format_message("FILEACK",
                filename=filename,
                accept="1",
                save_dir=save_dir
            )
            self.ws.send(ack_msg)
            self.display(f"Accepted {filename} ({size_kb:.1f} KB)", "success")
            self.display(f"Save location: {save_dir}", "info")
        else:
            # Send deny
            deny_msg = format_message("FILEDENY", filename=filename, reason="Declined")
            self.ws.send(deny_msg)
            self.display(f"Declined {filename}", "warning")
    
    def _on_file_received(self, ok: bool):
        """Track batch progress when a file transfer completes."""
        if self.active_batch:
            self.active_batch["files_received"] += 1
            if ok:
                self.active_batch["files_ok"] += 1
                received = self.active_batch["files_received"]
                total = self.active_batch["file_count"]
                if total > 1:
                    self.root.after(0, lambda r=received, t=total: 
                        self.display(f"  Batch progress: {r}/{t} files", "info"))
            else:
                self.active_batch["files_err"] += 1
    
    def _show_overwrite_dialog(self, filename: str, save_dir: str, temp_path: str):
        """Show overwrite confirmation dialog when file already exists.
        
        Args:
            filename: Name of the file
            save_dir: Directory to save in
            temp_path: Path to temp file containing the data (not raw bytes)
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("File Already Exists")
        dialog.geometry("400x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="This will overwrite:", font=('Arial', 11)).pack(pady=(15, 5))
        tk.Label(dialog, text=filename, font=('Arial', 11, 'bold')).pack(pady=5)
        
        auto_accept_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dialog, text="Auto-accept future files", 
                       variable=auto_accept_var, font=('Arial', 10)).pack(pady=5)
        
        def do_accept():
            if auto_accept_var.get():
                self.config["auto_accept_files"] = True
                save_config(self.config_path, self.config)
            dialog.destroy()
            save_path = os.path.join(save_dir, filename)
            import shutil
            shutil.move(temp_path, save_path)
            self.display(f"⚠ Saved (replaced existing): {save_path}", "warning")
            ok_msg = format_message("FILEOK", filename=filename, saved_path=save_path)
            self.ws.send(ok_msg)
            self._on_file_received(ok=True)
        
        def do_decline():
            dialog.destroy()
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass
            deny_msg = format_message("FILEDENY", filename=filename, reason="Declined overwrite")
            self.ws.send(deny_msg)
            self.display(f"Declined overwrite for {filename}", "warning")
            self._on_file_received(ok=False)
        
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Accept (Overwrite)", command=do_accept,
                  height=2, width=16, font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Decline", command=do_decline,
                  height=2, width=10, font=('Arial', 10)).pack(side=tk.RIGHT, padx=5)
    
    def _init_osc_client(self):
        """Initialize the python-osc UDP client for VRChat OSC."""
        if not self.config.get("osc_enabled", True):
            self.osc_client = None
            return
        try:
            from pythonosc import udp_client
            host = self.config.get("vrchat_osc_host", OSC_DEFAULT_HOST)
            port = self.config.get("vrchat_osc_port", OSC_DEFAULT_PORT)
            self.osc_client = udp_client.SimpleUDPClient(host, port)
            self.display(f"OSC client ready → {host}:{port}", "info")
        except ImportError:
            self.osc_client = None
            self.display("python-osc not installed. OSC cues disabled.", "warning")
        except Exception as e:
            self.osc_client = None
            self.display(f"OSC init failed: {e}", "warning")

    def _ensure_osc_address(self, parameter: str) -> str:
        """Ensure parameter has full /avatar/parameters/ path."""
        param = parameter.strip()
        if param.startswith("/"):
            return param
        return f"/avatar/parameters/{param}"

    def _send_osc_parameter(self, parameter: str, value: str):
        """Send an OSC parameter to VRChat immediately."""
        if not self.osc_client:
            self.display(f"[OSC] Skipped {parameter}={value} — OSC not initialized", "warning")
            return False
        try:
            addr = self._ensure_osc_address(parameter)
            if value.lower() in ("true", "false"):
                self.osc_client.send_message(addr, value.lower() == "true")
            else:
                # Future: float/int parsing
                self.osc_client.send_message(addr, value)
            self.display(f"[OSC] {addr} ← {value}", "success")
            return True
        except Exception as e:
            self.display(f"[OSC] Failed: {parameter}={value} — {e}", "error")
            return False

    def _cancel_osc_timers(self):
        """Cancel all pending OSC cue timers."""
        for timer in self.osc_pending_timers:
            try:
                timer.cancel()
            except:
                pass
        self.osc_pending_timers.clear()

    def send_msg(self):
        """Send a chat message."""
        msg = self.entry.get().strip()
        if not msg or not self.ws or not self.approved:
            return
        
        self.entry.delete(0, tk.END)
        # Display own message locally
        self.display(f"You: {msg}")
        
        try:
            self.ws.send(format_message("MSG", 
                sender=self.config.get("actor_name", "Unknown"),
                text=msg
            ))
        except Exception as e:
            self.display(f"Send error: {e}")
    
    def enable_input(self, enabled: bool):
        """Enable or disable input controls."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.entry.config(state=state)
        self.send_btn.config(state=state)
    
    def _show_about(self):
        """Show About dialog."""
        messagebox.showinfo(
            "About vrActorAssist",
            f"Danny Grey Productions\n\n"
            f"vrActorAssist Actor Client\n"
            f"Version {APP_VERSION}\n\n"
            f"VRChat filmmaking assistant\n"
            f"for directors and actors.\n\n"
            f"https://github.com/virtualvert/vrActorAssist",
            parent=self.root
        )
    
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
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                else:
                    exe_path = os.path.abspath(__file__)
                
                is_windows = sys.platform == "win32"
                
                if is_windows:
                    suffix = ".exe.tmp"
                else:
                    suffix = ".AppImage.tmp"
                
                temp_path = os.path.join(os.path.dirname(exe_path), f"vrActorClient-v{version}{suffix}")
                
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
                
                self.root.after(0, lambda: self.display("✓ Download complete. Verifying...", "success"))
                
                # Schedule update prompt on main thread
                self.root.after(0, lambda: self._apply_update(exe_path, temp_path, is_windows))
                
            except Exception as e:
                self.root.after(0, lambda: self.display(f"✗ Update failed: {e}", "error"))
        
        threading.Thread(target=download, daemon=True).start()
    
    def _apply_update(self, current_path, new_path, is_windows):
        """Prompt user to restart, then swap the update into place after exit.
        
        Flow:
        1. Ask user "Update ready. Restart to apply?"
        2. If yes: write a swap script, launch it, then quit the app
        3. Swap script waits for this process to die, then renames files
        4. User reopens the app manually (no auto-restart)
        """
        result = messagebox.askyesno(
            "Update Ready",
            "A new version has been downloaded and verified.\n\n"
            "The app needs to close to apply the update.\n\n"
            "Close and apply update now?",
            parent=self.root
        )
        if not result:
            self.display("Update downloaded but not applied. Restart to apply.", "info")
            return
        
        # Write the swap script
        exe_dir = os.path.dirname(current_path)
        current_pid = os.getpid()
        
        if is_windows:
            updater_path = os.path.join(exe_dir, "_updater.bat")
            with open(updater_path, "w") as f:
                f.write("@echo off\n")
                f.write("echo Applying update...\n")
                f.write(f":wait\n")
                f.write(f'tasklist /FI "PID eq {current_pid}" | find "{current_pid}" >nul 2>&1\n')
                f.write("if %errorlevel%==0 timeout /t 1 >nul & goto wait\n")
                f.write("timeout /t 2 /nointerrupt >nul\n")
                f.write(f'move /y "{new_path}" "{current_path}"\n')
                f.write("echo Update applied. You can now reopen vrActorAssist.\n")
                f.write("pause\n")
                f.write('del "%~f0"\n')
        else:
            updater_path = os.path.join(exe_dir, "_updater.sh")
            with open(updater_path, "w") as f:
                f.write("#!/bin/sh\n")
                f.write("echo 'Applying update...'\n")
                f.write(f"while kill -0 {current_pid} 2>/dev/null; do sleep 1; done\n")
                f.write("sleep 1\n")
                f.write(f"mv -f '{new_path}' '{current_path}'\n")
                f.write(f"chmod +x '{current_path}'\n")
                f.write("echo 'Update applied. You can now reopen vrActorAssist.'\n")
            os.chmod(updater_path, 0o755)
        
        # Launch the swap script and quit
        if is_windows:
            subprocess.Popen([updater_path], shell=True)
        else:
            subprocess.Popen([updater_path])
        
        self.quit()
    
    def _cleanup_old_updates(self):
        """Clean up temp files, updater scripts, and .old files from previous updates."""
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            for filename in os.listdir(base_dir):
                filepath = os.path.join(base_dir, filename)
                # Clean up versioned .tmp download files
                if (filename.startswith("vrActorClient-v") or filename.startswith("vrDirectorClient-v")) and filename.endswith(".tmp"):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                # Clean up .old files from self-update swaps
                elif (filename.startswith("vrActorClient.") or filename.startswith("vrDirectorClient.")) and filename.endswith(".old"):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                # Clean up updater scripts
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
    client = ActorClient()
    client.run()