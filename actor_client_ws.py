# vrActorAssist Actor Client (WebSocket)
# GUI client for actors with Soundpad integration
#
# Usage: python actor_client_ws.py

import tkinter as tk
from tkinter import messagebox, scrolledtext
import threading
import json
import websocket
import time
from pathlib import Path

from shared import parse_message, format_message, get_machine_id, load_config, save_config, get_default_config_path
from soundpad import execute_command

# Defaults
DEFAULT_SERVER = "ws://localhost:5555/ws"
RECONNECT_DELAY = 5


class ActorClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Actor Client")
        self.root.geometry("550x500")
        self.root.minsize(500, 450)
        
        self.config_path = get_default_config_path("actor_config.json")
        self.config = load_config(self.config_path)
        self.machine_id = get_machine_id()
        
        self.ws = None
        self.connected = False
        self.approved = False
        self.should_reconnect = True
        
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
    
    def display(self, message: str, error: bool = False):
        """Display a message in the chat area.
        
        Args:
            message: The message to display
            error: If True, display in red text
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        self.chat_area.config(state=tk.NORMAL)
        if error:
            self.chat_area.tag_configure("error", foreground="red")
            self.chat_area.insert(tk.END, f"[{timestamp}] {message}\n", "error")
        else:
            self.chat_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)
    
    def prompt_config(self):
        """Prompt for initial configuration."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Actor Setup")
        dialog.geometry("400x200")
        dialog.minsize(400, 200)
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
        name_entry.pack(fill=tk.X)
        
        def save_and_close():
            self.config = {
                "server_url": server_entry.get().strip(),
                "actor_name": name_entry.get().strip() or "Actor"
            }
            save_config(self.config_path, self.config)
            self.display(f"Config saved to {self.config_path}")
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
        server_entry = tk.Entry(frame, width=40)
        server_entry.insert(0, self.config.get("server_url", DEFAULT_SERVER))
        server_entry.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame, text="Your Name:").pack(anchor='w')
        name_entry = tk.Entry(frame, width=40)
        name_entry.insert(0, self.config.get("actor_name", ""))
        name_entry.pack(fill=tk.X)
        
        def save_changes():
            self.config["server_url"] = server_entry.get().strip()
            self.config["actor_name"] = name_entry.get().strip() or "Actor"
            save_config(self.config_path, self.config)
            self.display("Config updated. Reconnect to apply changes.")
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
        self.display("Disconnected")
    
    def _connect_thread(self):
        """Connection thread using WebSocketApp for proper ping handling."""
        server_url = self.config.get("server_url", DEFAULT_SERVER)
        ws_url = self.get_ws_url(server_url)
        
        self.display(f"Connecting to {ws_url}...")
        
        def on_open(ws):
            self.connected = True
            self.display("Connected! Registering...")
            
            # Send registration
            register_msg = format_message(
                "REGISTER",
                name=self.config.get("actor_name", "Unknown"),
                machine_id=self.machine_id,
                role="actor",
                secret=""
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
            self.root.after(0, lambda: self.enable_input(False))
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
        msg_type, msg_data = parse_message(data)
        
        if msg_type == "APPROVED":
            self.approved = True
            actor_name = self.config.get("actor_name", "Unknown")
            self.root.after(0, lambda: self.display("✓ Approved by director!"))
            self.root.after(0, lambda: self.status_var.set(f"Connected (as {actor_name})"))
            self.root.after(0, lambda: self.enable_input(True))
        
        elif msg_type == "DENIED":
            reason = msg_data.get("reason", "Unknown reason")
            self.root.after(0, lambda: self.display(f"✗ {reason}"))
            self.approved = False
            self.root.after(0, lambda: self.enable_input(False))
            if "Pending" in reason:
                self.root.after(0, lambda: self.display("Waiting for director approval..."))
        
        elif msg_type == "MSG":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            # Don't show our own messages (we already displayed them locally)
            if sender != self.config.get("actor_name", "Unknown"):
                self.root.after(0, lambda: self.display(f"{sender}: {text}"))
        
        elif msg_type == "PRIV":
            sender = msg_data.get("sender", "Unknown")
            text = msg_data.get("text", "")
            self.root.after(0, lambda: self.display(f"[Private] {sender}: {text}"))
        
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
                self.root.after(0, lambda: self.display(f"✓ Executed: {command}"))
            else:
                self.root.after(0, lambda: self.display(f"✗ Failed: {command}", error=True))
                if error_msg:
                    self.root.after(0, lambda msg=error_msg: self.display(f"   {msg}", error=True))
        
        elif msg_type == "USERS":
            users = msg_data.get("users", [])
            self.root.after(0, lambda: self.display(f"Actors: {', '.join(users)}"))
    
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