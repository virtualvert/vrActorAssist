# This file contains an "director client" for soundpad control.
# Intended usage is:
#    1. Director will execute this program using agreed IP address and port
#    2. Director provides username (Todo: Specify role)
#    3. Todo: Wait for "RDY"/"NOGO" and display status
#    4. Director issues one of:
#           "*go" (all start immediately) - "soundpad -rc DoPlaySelectedSound()"
#           "*goat" (go at) to start all at a predetermined time, e.g. cron
#               (in this case NTP must be configured)
#           May also say "only (actor)" or "hush (actor)" to specific users
#                * Note that right now this can be done by DM'ing
#    5. During playback, director may send "*stop" -> "soundpad -rc DoStopSound()"
#       name as an optional parameter
#
# Todo: offset start time, perhaps discovered by ping (both here and OSC)
# Todo: Might trigger OSC event to flash/beep/slate on set in VR (cam op role?)
# Todo: Implement /quit (rather than ctrl-brk or ctrl-c)
# Todo: Implement Director cmd "wrap" which ends the session for all
# Todo: Possibly use TCP and/or ack messages
# Todo: Possibly timecode messages (probably no reason to store it, but could help debug)
# Todo: Add "role" to /who (e.g. director, actor, camera, none)

import asyncio                      # Supposedly more efficient than sockets
import sys                          # So we can get command line parameters
import subprocess                   # So we can launch the remote control for soundpad

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
    if len(sys.argv) == 3:                  # Todo: better input checking
        HOST = sys.argv[1]
        PORT = sys.argv[2]
    else:
        print("Usage: " + sys.argv[0] + "(host) (port)")
        sys.exit()

    print("Connecting as DIRECTOR to " + HOST + ":" + str(PORT))
    reader, writer = await asyncio.open_connection(HOST, PORT)

    myname = input("Enter your name: ")

    writer.write((myname + "\n").encode())
    await writer.drain()

    await asyncio.gather(
        receive(reader),
        send(writer)
    )

asyncio.run(main())