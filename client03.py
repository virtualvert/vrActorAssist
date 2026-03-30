import asyncio
import sys

async def receive(reader):
    while True:
        data = await reader.readline()
        if not data:
            break
        print(data.decode().strip())

async def send(writer):
    while True:
        message = await asyncio.to_thread(input, "")
        writer.write((message + "\n").encode())
        await writer.drain()

async def main():
    if len(sys.argv) == 3:
        HOST = sys.argv[1]
        PORT = sys.argv[2]
    else:
        print("Usage: " + sys.argv[0] + "(host) (port)")
        sys.exit()

    print("Connecting to " + HOST + ":" + str(PORT))

    reader, writer = await asyncio.open_connection(HOST, PORT)

    nickname = input("Choose nickname: ")

    writer.write((nickname + "\n").encode())
    await writer.drain()

    await asyncio.gather(
        receive(reader),
        send(writer)
    )


asyncio.run(main())