import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

# Make the top-level modules (server_ws, shared, soundpad) importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def stack():
    with ExitStack() as s:
        yield s
