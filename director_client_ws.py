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
        
        # Send file button
        tk.Button(left_frame, text="📁 Send File...", command=self.send_file_dialog, height=2, width=15, font=('Arial', 11, 'bold')).pack(pady=5)
        
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
                secret=secret
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
        
        elif msg_type == "FILEDENY":
            filename = msg_data.get("filename", "")
            reason = msg_data.get("reason", "Unknown")
            self.root.after(0, lambda: self.display(f"File transfer denied: {reason}", "warning"))
        
        elif msg_type == "FILEOK":
            filename = msg_data.get("filename", "")
            saved_path = msg_data.get("saved_path", "")
            self.root.after(0, lambda: self.display(f"✓ File saved: {saved_path}", "success"))
        
        elif msg_type == "FILEERR":
            filename = msg_data.get("filename", "")
            error = msg_data.get("error", "Unknown error")
            self.root.after(0, lambda: self.display(f"✗ File error: {error}", "error"))
    
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
    
    def send_file_dialog(self):
        """Open file picker and send file to selected actor."""
        if not self.approved_actors:
            messagebox.showwarning("No Actors", "No actors connected")
            return
        
        # Actor selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Send File")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Send file to:", font=('Arial', 12)).pack(pady=10)
        
        # Actor listbox with explicit selection mode
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
        
        def do_send():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("No Selection", "Please select an actor")
                return
            
            actor_name = listbox.get(sel[0])
            dialog.destroy()
            
            # Open file picker
            filepath = filedialog.askopenfilename(
                title=f"Send file to {actor_name}",
            )
            
            if filepath:
                self.send_file_to_actor(filepath, actor_name)
        
        tk.Button(dialog, text="Send", command=do_send, height=2, width=10, font=('Arial', 11, 'bold')).pack(pady=10)
    
    def send_file_to_actor(self, filepath: str, actor_name: str):
        """Send file to specific actor."""
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
        
        # Store pending file transfer
        if not hasattr(self, 'pending_files'):
            self.pending_files = {}
        self.pending_files[filename] = {
            "path": filepath,
            "target": actor_name,
            "checksum": checksum,
            "accepted": False
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
        del self.pending_files[filename]
    
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