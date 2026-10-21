"""Local UI server: the web build, a tiny API and the /ui/ws socket.

Only this machine may talk to it, and only pages the app opened: requests must use the
loopback Host (blocks DNS rebinding), sockets and POSTs must come from our own origin, and
data needs a session cookie traded for the one-time `?t=` token in the URL the app opens.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, APP_VERSION
from .core import CallError
from .folders import MAX_WRITE_BYTES, FolderError, pick_folder

if TYPE_CHECKING:
    from .core import Agent

log = logging.getLogger("vrcas")

COOKIE = "vrcas_session"
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>vrcActorSync</title>
<body style="font-family:system-ui;background:#0b0d12;color:#e8ebf2;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:32rem"><h1>The web UI isn't built yet</h1>
<p>From the repository root run:</p><pre style="background:#171b24;padding:1rem;border-radius:.5rem">bun --cwd=web install
bun --cwd=web run build</pre><p>then restart the app.</p></div></body>"""


class Security:
    def __init__(self, port: int, dev: bool = False):
        self.port = port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if dev:
            self.origins.update(DEV_ORIGINS)
        self._open_tokens: set[str] = set()
        self._sessions: set[str] = set()

    def new_open_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self._open_tokens.add(token)
        return token

    def exchange(self, token: str) -> str | None:
        """Trade a one-time open token for a session id (each token works once)."""
        if token not in self._open_tokens:
            return None
        self._open_tokens.discard(token)
        session = secrets.token_urlsafe(32)
        self._sessions.add(session)
        return session

    def host_ok(self, host: str | None) -> bool:
        return host in self.hosts

    def origin_ok(self, origin: str | None) -> bool:
        return origin in self.origins

    def session_ok(self, session: str | None) -> bool:
        return bool(session) and session in self._sessions


class HostGuard:
    """Pure ASGI middleware so HTTP and WebSocket requests are both checked."""

    def __init__(self, app, security: Security):
        self.app = app
        self.security = security

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
            if not self.security.host_ok(host):
                log.warning("Rejected request for host %r", host)
                if scope["type"] == "http":
                    response = JSONResponse({"error": "forbidden host"}, status_code=403)
                    await response(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


def create_app(agent: "Agent", security: Security, static_dir: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await agent.start()
        yield
        await agent.shutdown()

    app = FastAPI(title=f"{APP_NAME} agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/ping")
    async def ping():
        return {"app": APP_NAME, "version": APP_VERSION}

    @app.post("/api/session")
    async def session(request: Request):
        if not security.origin_ok(request.headers.get("origin")):
            return JSONResponse({"error": "forbidden origin"}, status_code=403)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        session_id = security.exchange(str(body.get("token", "")))
        if session_id is None:
            return JSONResponse({"error": "invalid or used token"}, status_code=401)
        response = JSONResponse({"ok": True})
        response.set_cookie(COOKIE, session_id, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/state")
    async def state(request: Request):
        if not security.session_ok(request.cookies.get(COOKIE)):
            return JSONResponse({"error": "no session"}, status_code=401)
        return agent.snapshot()

    # Normalize folder (spec §8.4.2) and Send files: the page does the audio work; these only move bytes.
    folders = agent.folders

    def denied(request: Request) -> JSONResponse | None:
        if not security.origin_ok(request.headers.get("origin")):
            return JSONResponse({"error": "forbidden origin"}, status_code=403)
        if not security.session_ok(request.cookies.get(COOKIE)):
            return JSONResponse({"error": "no session"}, status_code=401)
        return None

    async def json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    def refused(exc: FolderError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/folders/pick")
    async def folders_pick(request: Request):
        if (response := denied(request)) is not None:
            return response
        try:
            return {"path": await pick_folder()}
        except FolderError as exc:
            return refused(exc)

    @app.post("/api/folders/open")
    async def folders_open(request: Request):
        if (response := denied(request)) is not None:
            return response
        body = await json_body(request)
        try:
            kind = "all" if body.get("kind") == "all" else "audio"
            return await asyncio.to_thread(folders.open, str(body.get("folder", "")), kind)
        except FolderError as exc:
            return refused(exc)

    @app.post("/api/folders/read")
    async def folders_read(request: Request):
        if (response := denied(request)) is not None:
            return response
        body = await json_body(request)
        try:
            path = folders.source(str(body.get("folder", "")), str(body.get("path", "")))
        except FolderError as exc:
            return refused(exc)
        return FileResponse(path, media_type="application/octet-stream")

    @app.post("/api/folders/write")
    async def folders_write(request: Request, folder: str = "", path: str = ""):
        if (response := denied(request)) is not None:
            return response
        if int(request.headers.get("content-length") or 0) > MAX_WRITE_BYTES:
            return JSONResponse({"error": "That copy is too large"}, status_code=413)
        data = await request.body()
        try:
            target = await asyncio.to_thread(folders.write, folder, path, data)
        except FolderError as exc:
            return refused(exc)
        return {"path": str(target)}

    @app.websocket("/ui/ws")
    async def ui_socket(ws: WebSocket):
        if not security.origin_ok(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept()
        if not security.session_ok(ws.cookies.get(COOKIE)):
            await ws.close(code=4401)
            return
        await agent.hub.add(ws)
        try:
            while True:
                try:
                    message = json.loads(await ws.receive_text())
                except (json.JSONDecodeError, ValueError):
                    continue
                call_id = message.get("id")
                try:
                    await agent.handle_call(str(message.get("call", "")), message.get("args") or {})
                    result = {"type": "result", "id": call_id, "ok": True}
                except CallError as exc:
                    result = {"type": "result", "id": call_id, "ok": False, "error": str(exc)}
                except Exception as exc:  # keep the socket alive; report the bug
                    log.exception("UI call %s failed", message.get("call"))
                    result = {"type": "result", "id": call_id, "ok": False, "error": f"Internal error: {exc}"}
                await ws.send_text(json.dumps(result))
        except WebSocketDisconnect:
            pass
        finally:
            agent.hub.remove(ws)

    if (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    else:

        @app.get("/")
        async def not_built():
            return HTMLResponse(NOT_BUILT)

    return HostGuard(app, security)  # type: ignore[return-value]
