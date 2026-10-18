import sys
from pathlib import Path

# Tests import `agent`, `shared`, `soundpad` and `server_ws` from the repository root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
