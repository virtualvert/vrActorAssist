"""vrcActorSync desktop agent.

Serves the web UI (web/dist) on 127.0.0.1, shows it in a pywebview window (or the browser),
holds the connection to the relay, and does the local work: Soundpad and VRChat OSC for actors.
"""

import sys
from pathlib import Path

APP_NAME = "vrcActorSync"
APP_VERSION = "0.4.0-dev"

# vrcas_protocol (spec §5.8) lives in protocol/; a frozen build has it bundled instead.
_PROTOCOL = Path(__file__).resolve().parents[1] / "protocol"
if _PROTOCOL.is_dir() and str(_PROTOCOL) not in sys.path:
    sys.path.insert(0, str(_PROTOCOL))
