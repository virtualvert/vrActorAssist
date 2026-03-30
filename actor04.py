# This version uses regular sockets instead of asyncio, and adds file transfers
#
# Messages are in the form:
#   TYPE|Username|(payload)
# 
# Where "TYPE" is one of MSG (standard chat), PRIV (private), USERS (list?), or
# "FILE" (note extra fields: FILE|username|filename|size).
#
# Wouldn't hurt to add a "CMD" type to avoid the ability for people to inject messages



import socket
import threading
import tkinter as tk
from tkinter import simpledialog, filedialog
import datetime

HOST = "127.0.0.1"
PORT = 5555


class ChatClient:

    def __init__(self):

        self.root = tk.Tk()
        self.root.title("AudioTrigger (Actor)")

        self.build_gui()

        self.myname = simpledialog.askstring("Name", "Enter name")

        self.connect()

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_gui(self):

        main = tk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        # Chat area
        center = tk.Frame(main)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat = tk.Text(center)
        self.chat.pack(fill=tk.BOTH, expand=True)

        bottom = tk.Frame(center)
        bottom.pack(fill=tk.X)

        self.entry = tk.Entry(bottom)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Button(bottom, text="Send", command=self.send_msg).pack(side=tk.LEFT)

        tk.Button(bottom, text="Send File", command=self.send_file).pack(side=tk.LEFT)

        # Sidebar
        sidebar = tk.Frame(main)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)

        tk.Label(sidebar, text="Users").pack()

        self.user_list = tk.Listbox(sidebar, width=20)
        self.user_list.pack(fill=tk.Y)

    def connect(self):

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((HOST, PORT))

        self.sock.send((self.myname + "\n").encode())

        threading.Thread(target=self.receive, daemon=True).start()

    def timestamp(self):

        return datetime.datetime.now().strftime("%H:%M:%S")

    def display(self, text):

        self.chat.insert(tk.END, f"[{self.timestamp()}] {text}\n")
        self.chat.yview(tk.END)

    def receive(self):

        while True:

            try:

                data = self.sock.recv(4096)

                if not data:
                    break

                if data.startswith(b"MSG|"):                        # Standard msg
                    _, sender, text = data.decode().split("|", 2)
                    self.display(f"{sender}: {text}")

                elif data.startswith(b"PRIV|"):                     # Private msg
                    _, sender, target, text = data.decode().split("|", 3)
                    self.display(f"[PRIVATE] {sender}: {text}")

                elif data.startswith(b"USERS|"):                    # Users (TODO: refactor?)
                    users = data.decode().split("|")[1].split(",")
                    self.user_list.delete(0, tk.END)
                    for u in users:
                        self.user_list.insert(tk.END, u)

                elif data.startswith(b"FILE|"):
                    header = data.decode()
                    _, sender, filename, size = header.split("|")
                    size = int(size)

                    path = filedialog.asksaveasfilename(initialfile=filename)

                    remaining = size

                    with open(path, "wb") as f:         # TODO: Progress bar/etc?
                        while remaining > 0:
                            chunk = self.sock.recv(min(4096, remaining))
                            remaining -= len(chunk)
                            f.write(chunk)

                    self.display(f"{sender} sent file: {filename}")

            except:                     # TODO: Cleaner fault handling?
                break

    def send_msg(self):
        msg = self.entry.get()
        self.entry.delete(0, tk.END)
        self.sock.send(f"MSG|{self.myname}|{msg}".encode())

    def send_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return

        filename = path.split("/")[-1]

        size = open(path, "rb").seek(0, 2)
        size = open(path, "rb").tell()

        header = f"FILE|{self.myname}|{filename}|{size}"
        self.sock.send(header.encode())

        with open(path, "rb") as f:
            while True:
                chunk = f.read(4096)        # get 4K chunk and send it until EOF
                if not chunk:
                    break
                self.sock.send(chunk)

        self.display(f"Sent file: {filename}")

    def close(self):
        try:
            self.sock.close()
        except:
            pass
        self.root.destroy()


ChatClient().root.mainloop()
