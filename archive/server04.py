# This version uses regular sockets instead of asyncio and can transfer files

import socket
import threading

HOST = "127.0.0.1"
PORT = 5555

clients = {}
usernames = {}


def broadcast(message, exclude=None):
    for c in clients:
        if c != exclude:
            try:
                c.send(message)
            except:
                pass


def send_user_list():
    users = ",".join(usernames.values())
    msg = f"USERS|{users}".encode()

    for c in clients:
        c.send(msg)


def forward_file(sender, filename, size, sender_socket):

    header = f"FILE|{sender}|{filename}|{size}".encode()
    broadcast(header, sender_socket)

    remaining = size

    while remaining > 0:
        chunk = sender_socket.recv(min(4096, remaining))
        remaining -= len(chunk)

        for c in clients:
            if c != sender_socket:
                c.send(chunk)


def handle_client(client):

    username = client.recv(1024).decode().strip()

    clients[client] = username
    usernames[client] = username

    broadcast(f"MSG|SERVER|{username} joined".encode())
    send_user_list()

    while True:
        try:
            data = client.recv(1024)
            if not data:
                break

            msg = data.decode()
            if msg.startswith("MSG|"):
                broadcast(data, client)

            elif msg.startswith("PRIV|"):
                _, sender, target, text = msg.split("|", 3)
                for c, name in usernames.items():
                    if name == target:
                        c.send(data)

            elif msg.startswith("FILE|"):
                _, sender, filename, size = msg.split("|")
                forward_file(sender, filename, int(size), client)

        except:
            break

    username = usernames.get(client)

    del clients[client]
    del usernames[client]

    broadcast(f"MSG|SERVER|{username} left".encode())
    send_user_list()

    client.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print("Server running...")

    while True:                         # As long as we're alive, keep spawning
        client, _ = server.accept()     # new server threads if someone joins
        thread = threading.Thread(target=handle_client, args=(client,))
        thread.start()

main()