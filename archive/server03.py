import asyncio

HOST = "127.0.0.1"
PORT = 5555

clients = {}     # writer -> username
rooms = {}       # username -> room


async def broadcast(message, room=None, exclude=None):

    for writer, user in clients.items():

        if exclude and writer == exclude:
            continue

        if room and rooms.get(user) != room:
            continue

        writer.write((message + "\n").encode())
        await writer.drain()


async def private_message(sender, receiver, message):

    for writer, user in clients.items():

        if user == receiver:
            writer.write(f"[PRIVATE] {sender}: {message}\n".encode())
            await writer.drain()
            return True

    return False


async def send_user_list(writer):

    users = "\n".join(clients.values())

    writer.write(f"Online users:\n{users}\n".encode())
    await writer.drain()


async def send_help(writer):

    help_text = """
Commands:
/msg USER MESSAGE   send private message
/users              list users
/join ROOM          join or create room
/help               show this help
"""

    writer.write(help_text.encode())
    await writer.drain()


async def handle_command(writer, username, message):

    parts = message.split(" ", 2)
    command = parts[0]

    if command == "/msg":

        if len(parts) < 3:
            writer.write("Usage: /msg USER MESSAGE\n".encode())
            await writer.drain()
            return

        receiver = parts[1]
        msg = parts[2]

        sent = await private_message(username, receiver, msg)

        if sent:
            writer.write(f"[PRIVATE to {receiver}]: {msg}\n".encode())
        else:
            writer.write("User not found\n".encode())

        await writer.drain()

    elif command == "/users":

        await send_user_list(writer)

    elif command == "/join":

        if len(parts) < 2:
            writer.write("Usage: /join ROOM\n".encode())
            await writer.drain()
            return

        room = parts[1]

        rooms[username] = room

        writer.write(f"You joined room: {room}\n".encode())
        await writer.drain()

    elif command == "/help":

        await send_help(writer)

    else:

        writer.write("Unknown command. Type /help\n".encode())
        await writer.drain()


async def handle_client(reader, writer):

    writer.write("Enter nickname: ".encode())
    await writer.drain()

    username = (await reader.readline()).decode().strip()

    clients[writer] = username
    rooms[username] = "main"

    print(f"{username} connected")

    await broadcast(f"{username} joined the chat", room="main")

    try:

        while True:

            data = await reader.readline()

            if not data:
                break

            message = data.decode().strip()

            if message.startswith("/"):

                await handle_command(writer, username, message)

            else:

                room = rooms.get(username)

                await broadcast(
                    f"{username}: {message}",
                    room=room,
                    exclude=None
                )

    except:

        pass

    print(f"{username} disconnected")

    del clients[writer]
    del rooms[username]

    await broadcast(f"{username} left the chat")

    writer.close()
    await writer.wait_closed()


async def main():

    server = await asyncio.start_server(
        handle_client,
        HOST,
        PORT
    )
    print("main run")

    addr = server.sockets[0].getsockname()

    print(f"Server running on {addr}")

    async with server:
        await server.serve_forever()


asyncio.run(main())
