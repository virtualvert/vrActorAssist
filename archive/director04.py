# Director client with GUI for vrActorAssist
# Based on actor04.py architecture using regular sockets
#
# Director-specific features:
#   - Send commands: *go, *stop, *goat (go at time)
#   - Send to specific actors via private message
#   - See connected actors list
#   - Ready/NOGO status tracking (future)
#
# Message format:
#   MSG|sender|text          - broadcast to all
#   PRIV|sender|target|text  - private to target
#   CMD|sender|command       - system command (future)

import socket
import threading
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import datetime

HOST = "127.0.0.1"
PORT = 5555


class DirectorClient:

    def __init__(self):

        self.root = tk.Tk()
        self.root.title("vrActorAssist - Director")
        self.root.geometry("800x600")

        self.build_gui()

        self.myname = simpledialog.askstring("Name", "Enter your name (Director):", initialvalue="Director")

        self.connect()

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_gui(self):

        # Main container
        main = tk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left side - Chat and controls
        left = tk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Chat area
        chat_frame = tk.Frame(left)
        chat_frame.pack(fill=tk.BOTH, expand=True)

        self.chat = tk.Text(chat_frame, height=20, state=tk.DISABLED)
        self.chat.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(chat_frame, command=self.chat.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat.config(yscrollcommand=scrollbar.set)

        # Message input
        input_frame = tk.Frame(left)
        input_frame.pack(fill=tk.X, pady=5)

        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.send_msg())

        tk.Button(input_frame, text="Send", command=self.send_msg).pack(side=tk.LEFT, padx=5)

        # Command buttons frame
        cmd_frame = tk.LabelFrame(left, text="Sound Commands", padx=5, pady=5)
        cmd_frame.pack(fill=tk.X, pady=5)

        # Row 1: Main commands
        cmd_row1 = tk.Frame(cmd_frame)
        cmd_row1.pack(fill=tk.X, pady=2)

        self.go_btn = tk.Button(cmd_row1, text="▶ GO (Play)", command=self.send_go,
                                bg="#4CAF50", fg="white", width=12)
        self.go_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(cmd_row1, text="⏹ STOP", command=self.send_stop,
                                  bg="#f44336", fg="white", width=12)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.ready_btn = tk.Button(cmd_row1, text="✓ Ready Check", command=self.send_ready_check,
                                   bg="#2196F3", fg="white", width=12)
        self.ready_btn.pack(side=tk.LEFT, padx=5)

        # Row 2: Go-at-time
        cmd_row2 = tk.Frame(cmd_frame)
        cmd_row2.pack(fill=tk.X, pady=2)

        tk.Label(cmd_row2, text="Go at (seconds):").pack(side=tk.LEFT, padx=5)
        self.goat_entry = tk.Entry(cmd_row2, width=8)
        self.goat_entry.pack(side=tk.LEFT, padx=5)
        self.goat_entry.insert(0, "5")

        tk.Button(cmd_row2, text="⏱ GO AT", command=self.send_goat,
                  bg="#FF9800", fg="white", width=10).pack(side=tk.LEFT, padx=5)

        # Row 3: Per-actor commands
        cmd_row3 = tk.Frame(cmd_frame)
        cmd_row3.pack(fill=tk.X, pady=2)

        tk.Label(cmd_row3, text="Target actor:").pack(side=tk.LEFT, padx=5)
        self.target_var = tk.StringVar()
        self.target_combo = ttk.Combobox(cmd_row3, textvariable=self.target_var, width=15)
        self.target_combo['values'] = ['(All)']
        self.target_combo.current(0)
        self.target_combo.pack(side=tk.LEFT, padx=5)

        tk.Button(cmd_row3, text="Play (target)", command=self.send_targeted_go,
                  bg="#81C784", width=12).pack(side=tk.LEFT, padx=5)

        tk.Button(cmd_row3, text="Stop (target)", command=self.send_targeted_stop,
                  bg="#E57373", width=12).pack(side=tk.LEFT, padx=5)

        # Right side - Users list
        right = tk.Frame(main, width=200)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        right.pack_propagate(False)

        tk.Label(right, text="Connected Actors", font=('Arial', 10, 'bold')).pack(pady=5)

        self.user_list = tk.Listbox(right, width=25)
        self.user_list.pack(fill=tk.BOTH, expand=True)

        # Status label
        self.status_var = tk.StringVar(value="Not connected")
        tk.Label(right, textvariable=self.status_var, fg="gray").pack(pady=5)

    def connect(self):

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((HOST, PORT))
            self.sock.send((self.myname + "\n").encode())
            self.status_var.set(f"Connected to {HOST}:{PORT}")
            threading.Thread(target=self.receive, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Connection Failed", f"Could not connect to server: {e}")
            self.root.destroy()

    def timestamp(self):
        return datetime.datetime.now().strftime("%H:%M:%S")

    def display(self, text, tag=None):
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"[{self.timestamp()}] {text}\n")
        self.chat.yview(tk.END)
        self.chat.config(state=tk.DISABLED)

    def receive(self):

        while True:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break

                if data.startswith(b"MSG|"):
                    _, sender, text = data.decode().split("|", 2)
                    self.display(f"{sender}: {text}")

                elif data.startswith(b"PRIV|"):
                    _, sender, target, text = data.decode().split("|", 3)
                    self.display(f"[PRIVATE] {sender}: {text}")

                elif data.startswith(b"USERS|"):
                    users = data.decode().split("|")[1].split(",")
                    self.user_list.delete(0, tk.END)
                    for u in users:
                        if u and u != self.myname:
                            self.user_list.insert(tk.END, u)
                    # Update target combo
                    actor_list = ['(All)'] + [u for u in users if u and u != self.myname]
                    self.target_combo['values'] = actor_list
                    self.display(f"Actors online: {', '.join(actor_list[1:]) or 'None'}")

                elif data.startswith(b"FILE|"):
                    # Directors probably don't receive files, but handle it
                    header = data.decode()
                    _, sender, filename, size = header.split("|")
                    self.display(f"[FILE] {sender} sent: {filename} ({size} bytes)")

            except Exception as e:
                self.display(f"[ERROR] Connection lost: {e}")
                break

        self.status_var.set("Disconnected")

    def send_msg(self):
        msg = self.entry.get().strip()
        if not msg:
            return
        self.entry.delete(0, tk.END)
        try:
            self.sock.send(f"MSG|{self.myname}|{msg}".encode())
        except Exception as e:
            self.display(f"[ERROR] Failed to send: {e}")

    def send_command(self, command, target=None):
        """Send a command. If target specified, send as private message."""
        if target and target != "(All)":
            # Send as private message to specific actor
            msg = f"PRIV|{self.myname}|{target}|{command}"
        else:
            # Broadcast to all
            msg = f"MSG|{self.myname}|{command}"
        try:
            self.sock.send(msg.encode())
            self.display(f">> {command}" + (f" (to {target})" if target and target != "(All)" else ""))
        except Exception as e:
            self.display(f"[ERROR] Failed to send command: {e}")

    def send_go(self):
        self.send_command("*go")

    def send_stop(self):
        self.send_command("*stop")

    def send_ready_check(self):
        self.send_command("*ready?")

    def send_goat(self):
        try:
            seconds = self.goat_entry.get()
            if seconds.isdigit():
                self.send_command(f"*goat {seconds}")
            else:
                messagebox.showwarning("Invalid Input", "Please enter a number of seconds")
        except Exception as e:
            self.display(f"[ERROR] {e}")

    def send_targeted_go(self):
        target = self.target_var.get()
        if target == "(All)":
            self.send_command("*go")
        else:
            self.send_command("*go", target)

    def send_targeted_stop(self):
        target = self.target_var.get()
        if target == "(All)":
            self.send_command("*stop")
        else:
            self.send_command("*stop", target)

    def close(self):
        try:
            self.sock.close()
        except:
            pass
        self.root.destroy()


if __name__ == "__main__":
    DirectorClient().root.mainloop()