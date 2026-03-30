# This file contains an "actor client" for soundpad control.
# Intended usage is:
#    1. Actor will execute this program using agreed IP address and port
#    2. Actor provides username (Todo: Specify role)
#    3. Actor opens soundpad and SELECTS the designated track
#       (Actor may send "RDY" when ready or "NOGO" if not ready)
#    4. Director issues one of:
#           "*go" (all start immediately) - "soundpad -rc DoPlaySelectedSound()"
#           "*goat" (go at) to start all at a predetermined time, e.g. cron
#               (in this case NTP must be configured)
#           May also say "only (actor)" or "hush (actor)" to specific users
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

#async def async_upper(text):


async def receive(reader):
    while True:
        data = await reader.readline()      # data is "raw"
        if not data:
            break
        msgin = data.decode().strip()       # msgin exists only when there's a new message
        idx = msgin.find(": *")             # in which case look for a command (msgs are "user: text")
        if idx != -1:                       # if it's ": *" that means it's a command; parse it
            print ("Command received")      # (todo: sloppy; should parse for ": " then get next char)
            print (msgin[idx+3:idx+6])
            #msgin=msgin.upper
            match msgin[idx+3:idx+6]:
                case "RUN":
                    print("running")
                    #subprocess.run(["soundpad -rc DoPlaySelectedSound()"])
                case "STO":
                    print("stopping")
                    #subprocess.run(["soundpad -rc DoStopSound()"])
                case _:
                    print("unknown cmd")
        else:
            print(msgin)

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

    print("Connecting as ACTOR to " + HOST + ":" + str(PORT))
    reader, writer = await asyncio.open_connection(HOST, PORT)

    # Todo: Could, for example use invisible first letter of name for role, e.g.
    # (D)irector, (A)ctor, (C)amera, etc.

    myname = input("Enter your name: ")

    writer.write((myname + "\n").encode())
    await writer.drain()

    await asyncio.gather(
        receive(reader),
        send(writer)
    )

asyncio.run(main())