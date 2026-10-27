# vrcActorSync relay server - entry point
# The relay itself lives in server/ (protocol v2 on /v2/ws, v0.3 clients on /ws).
#
# Usage: python server_ws.py --port 5555 --secret <director secret> [--host 0.0.0.0]
#        uvicorn server_ws:app --host 0.0.0.0 --port 5555   (secret from VR_ACTOR_SECRET)

import os
from pathlib import Path

import uvicorn

from server import SERVER_VERSION
from server.app import create_app
from server.keepalive import WS_PING_INTERVAL_S, WS_PING_TIMEOUT_S, protocol_class
from server.settings import DEFAULT_DATA_DIR, DEFAULT_PORT, DEFAULT_SECRET, Settings
from server.updates import find_update  # noqa: F401 (tests use server_ws.find_update)
from shared import APP_VERSION

# Get secret from env or arg
SERVER_SECRET = os.environ.get("VR_ACTOR_SECRET", DEFAULT_SECRET)

app = create_app(Settings(secret=SERVER_SECRET))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="vrcActorSync relay server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--secret", default=SERVER_SECRET, help="Director secret")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="Folder for approved_actors.json, server.log and update_manifest.json (default: next to this script)")
    parser.add_argument("--no-legacy", action="store_true", help="Refuse v0.3 clients on /ws")
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(secret=args.secret, data_dir=args.data_dir, legacy_enabled=not args.no_legacy)
    app = create_app(settings)
    relay = app.state.relay
    relay.log(f"Starting vrcActorSync relay v{SERVER_VERSION} on {args.host}:{args.port} "
              f"(v2 on /v2/ws; v0.3 clients on /ws{' disabled' if args.no_legacy else f', as v{APP_VERSION}'})")
    relay.log(f"Director secret: {settings.secret[:4]}...")
    if settings.data_dir != DEFAULT_DATA_DIR:
        relay.log(f"Data folder: {settings.data_dir}")

    # WebSocket keepalive: a ping every 30 s, a client that hasn't answered in 30 s is dropped
    # (server/keepalive.py; the drop shows in server.log as 1011 keepalive ping timeout)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        ws=protocol_class(),
        ws_ping_interval=WS_PING_INTERVAL_S,
        ws_ping_timeout=WS_PING_TIMEOUT_S,
    )
