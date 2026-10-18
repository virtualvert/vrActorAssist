import sys
from pathlib import Path

# Make the top-level modules (server_ws, shared, soundpad) importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
