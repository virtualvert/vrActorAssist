# vrActorAssist
This utility simplifies VR filming by coordinating common tasks for distributed multi-actor productions (e.g. synchronized audio playback)

The architecture for this system is as follows:
   * A headless server runs in a location accessible to all participants.
   * The director connects via the "director" client (which has the capability to instruct other client types).
   * The actors connect via the "actor" client.

Messages are sent in plaintext, and depending on version may allow standard chat messages (group or private), 
as well as special commands which are designated by some "escape code" format such as *____. It would be a
smart idea to convert all messages (including groupchat) into this format as well, to avoid inadvertant commands.

Presently the goal is to just get it to work with on-demand push commands (when message is received, go), but
another concept is to send a timestamp at a point a few seconds in the future, which - if NTP is used -
should enable synchronization within tens of milliseconds.

By "go" I mean execute a command along the lines of:
  subprocess.run(["soundpad -rc DoPlaySelectedSound()"]) 

This will initiate playback of the highlighted item. It also is possible to use a more sophisticated
wrapper for the soundpad API, but the command-line based approach is more straightforward and does
not require users to install supplemental python libraries.

Initial files in this repo include:
actor03.py, director03.py, server03.py - as described above, for "03" style architecture (asyncio)
client03.py - a version of the 03-style architecture client for raw use, which can be used for debugging
actor04.py, server04.py - headless server and GUI client for "04" style architecture - not yet broken into role-specific clients

Future ideas:
* Foremost, see source code comments for some ideas and TODOs specific to each program.
* Architecturally, there may be a "camera" client to enable remote start/stop/status for OBS, and possibly
  scene/shot/take metadata.

