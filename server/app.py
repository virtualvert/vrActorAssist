"""The relay's FastAPI app: /v2/ws, /ws (v0.3 clients), / and /health."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from .relay import Relay
from .settings import Settings
from .timesync import Clock


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    relay = Relay(settings, clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        relay.start()
        yield
        await relay.stop()

    app = FastAPI(title="vrcActorSync Server", lifespan=lifespan)
    app.state.relay = relay

    @app.websocket("/ws")
    async def legacy_ws(websocket: WebSocket):
        """v0.3 clients: the pipe protocol (spec §11)."""
        if not relay.settings.legacy_enabled:
            await websocket.close(code=1008)
            return
        await relay.bridge.endpoint(websocket)

    @app.websocket("/v2/ws")
    async def v2_ws(websocket: WebSocket):
        await relay.router.endpoint(websocket)

    @app.get("/")
    async def root():
        """Health check (the v0.3 relay's, kept as is until the web app is hosted at /)."""
        return {"status": "ok", "clients": len(relay.registry), "approved": len(relay.approvals.entries)}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app
