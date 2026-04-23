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
from pathlib import Path

from shared import parse_message, format_message, get_machine_id, load_config, save_config, get_default_config_path, APP_VERSION
from soundpad import execute_command, set_soundpad_path

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
        
        self.setup_ui()
        self.display(f"vrActorAssist Actor Client v{APP_VERSION}", "info")
        
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
        dialog.geometry("450x350")
        dialog.minsize(450, 350)
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
        
        def save_and_close():
            self.config = {
                "server_url": server_entry.get().strip(),
                "actor_name": name_entry.get().strip() or "Actor",
                "receive_dir": dir_entry.get().strip(),
                "auto_accept_files": auto_accept_var.get()
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
        dialog.geometry("450x350")
        dialog.minsize(450, 350)
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
        
        def save_changes():
            self.config["server_url"] = server_entry.get().strip()
            self.config["actor_name"] = name_entry.get().strip() or "Actor"
            self.config["receive_dir"] = dir_entry.get().strip()
            self.config["auto_accept_files"] = auto_accept_var.get()
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
                version=APP_VERSION
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
            
            # Execute as command (same as CMD)
            success, error_msg = execute_command(text, "")
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
            
            # Execute Soundpad command
            success, error_msg = execute_command(command, args)
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