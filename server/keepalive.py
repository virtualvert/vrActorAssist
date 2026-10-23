"""WebSocket keepalive on the relay: uvicorn's ping settings, and keepalive timeouts the app can see.

uvicorn pings every client every WS_PING_INTERVAL_S and drops one that hasn't answered within
WS_PING_TIMEOUT_S. Its WebSocket protocol then tells the app 1005 (no close frame), the same as
for a connection that simply went away; `protocol_class()` reports 1011 "keepalive ping timeout"
instead and marks the connection's scope, so server.log can tell the two apart.
"""

from __future__ import annotations

# 30 s rather than 10 s: a 10–20 s stall on the Tailscale Funnel path (2026-10-22 23:24) dropped
# actors whose connections were otherwise fine. The cost: a dead connection is noticed up to
# interval + timeout (60 s) after it died, instead of 40 s.
WS_PING_INTERVAL_S = 30.0
WS_PING_TIMEOUT_S = 30.0
# In the ASGI scope of a connection the relay dropped because its keepalive ping got no pong
TIMED_OUT = "vrcas.keepalive_timeout"


def protocol_class():
    """For uvicorn.run(ws=...): uvicorn's websockets (sans-I/O) protocol, reporting keepalive
    timeouts to the app. "auto" (uvicorn's own choice) if this uvicorn doesn't have it."""
    try:
        from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
    except ImportError:
        return "auto"
    if not callable(getattr(WebSocketsSansIOProtocol, "keepalive_timeout", None)):
        return "auto"

    class Protocol(WebSocketsSansIOProtocol):
        def keepalive_timeout(self) -> None:
            try:
                if not (self.close_sent or self.transport.is_closing()):
                    self.scope[TIMED_OUT] = True
                    # Ahead of the 1005 that connection_lost() queues once the socket is closed
                    self.queue.put_nowait({"type": "websocket.disconnect", "code": 1011, "reason": "keepalive ping timeout"})
            except Exception:  # noqa: BLE001 - a uvicorn that differs inside still drops the connection
                pass
            super().keepalive_timeout()

    return Protocol
