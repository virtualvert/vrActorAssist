"""Start the vrcActorSync app: python -m agent [--role actor] [--headless] ...

The UI server runs on 127.0.0.1. With a desktop window (pywebview, Windows) the server runs
in a background thread and the window owns the main thread; otherwise the server runs in the
main thread and the UI opens in the default browser.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from . import APP_NAME, APP_VERSION
from .config import ROLES, ConfigStore, data_dir, exe_dir, is_portable
from .core import Agent
from .shell import open_browser, run_window, window_reason
from .web import Security, create_app

DEFAULT_PORT = 47800


def find_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"No free port between {preferred} and {preferred + 19}")


def static_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", exe_dir())) / "web"
    return exe_dir() / "web" / "dist"


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("vrcas")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(folder / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(console)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="vrcActorSync", description=f"{APP_NAME} {APP_VERSION}")
    p.add_argument("--role", choices=ROLES, help="open in this role (saved for next time)")
    p.add_argument("--name", help="your display name (saved)")
    p.add_argument("--server", help="relay address, e.g. wss://relay.example.com/ws (saved)")
    p.add_argument("--headless", action="store_true", help="no desktop window; use the browser")
    p.add_argument("--window", action="store_true", help="force a pywebview window (Linux)")
    p.add_argument("--no-open", action="store_true", help="don't open any window or browser; just print the URL")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"local UI port (default {DEFAULT_PORT})")
    p.add_argument("--data-dir", type=Path, help="where config and logs live")
    p.add_argument("--portable", action="store_true", help="keep config next to the program")
    p.add_argument("--dev", action="store_true", help="also accept the Vite dev server (localhost:5173)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    folder = args.data_dir or data_dir(True if args.portable else None)
    setup_logging(folder / "logs")
    log = logging.getLogger("vrcas")

    store = ConfigStore(folder, legacy_folder=exe_dir())
    cfg = store.config
    if args.role:
        cfg.role = args.role
    if args.name:
        cfg.name = args.name
    if args.server:
        cfg.server_url = args.server
    if args.role or args.name or args.server:
        store.save()

    port = find_port(args.port)
    security = Security(port, dev=args.dev)
    agent = Agent(store)

    def ui_url() -> str:
        return f"http://127.0.0.1:{port}/?t={security.new_open_token()}"

    agent.ui_url = ui_url
    app = create_app(agent, security, static_dir())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    reason = None if args.window else window_reason()
    use_window = not args.headless and not args.no_open and reason is None
    log.info("%s %s · data in %s%s", APP_NAME, APP_VERSION, folder, " (portable)" if is_portable() or args.portable else "")

    if use_window:
        thread = threading.Thread(target=lambda: asyncio.run(server.serve()), name="ui-server", daemon=True)
        thread.start()
        while not server.started and thread.is_alive():
            thread.join(0.05)
        if not server.started:
            log.error("The UI server didn't start")
            return 1

        def closed() -> None:
            server.should_exit = True

        run_window(ui_url(), str(folder / "webview"), closed)
        thread.join(5)
        return 0

    if reason and not args.headless and not args.no_open:
        log.info("Opening the browser: %s", reason)

    async def serve() -> None:
        task = asyncio.create_task(server.serve())
        while not server.started and not task.done():
            await asyncio.sleep(0.05)
        url = ui_url()
        if args.no_open:
            # Console only: the link carries a one-time token, so keep it out of the log file.
            print(f"UI: {url}", flush=True)
        else:
            log.info("Opening %s", url.split("?")[0])
            await asyncio.to_thread(open_browser, url)
        await task

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
