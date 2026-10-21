"""vrcActorSync relay: protocol v2 on /v2/ws and the v0.3 pipe protocol on /ws (spec §6, §11).

Run it with `python server_ws.py --port 5555 --secret ...` (server_ws.py is the entry point).
"""

import sys
from pathlib import Path

SERVER_VERSION = "0.4.0-dev"

# vrcas_protocol lives in protocol/ (spec §5.8); make it importable from a source checkout.
_PROTOCOL = Path(__file__).resolve().parents[1] / "protocol"
if _PROTOCOL.is_dir() and str(_PROTOCOL) not in sys.path:
    sys.path.insert(0, str(_PROTOCOL))
