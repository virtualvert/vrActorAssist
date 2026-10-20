# Golden transcripts (spec §11.5): v0.3 clients on /ws must see exactly what the v0.3.3 relay
# sent them. tests/golden/legacy_session.txt was recorded from tests/legacy_relay/server_ws_v033.py.

from legacy_client import GOLDEN, RelayThread, golden_session, load_v033_relay, prepare_data_dir


def test_frozen_v033_relay_reproduces_golden(tmp_path):
    """The harness itself is deterministic against the relay the golden came from."""
    module = load_v033_relay(prepare_data_dir(tmp_path))
    with RelayThread(module.app) as relay:
        transcript = golden_session(relay.url)
    assert transcript == GOLDEN.read_text(encoding="utf-8")
