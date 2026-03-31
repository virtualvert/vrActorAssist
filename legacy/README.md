# Legacy (TCP Socket Version)

These files use raw TCP sockets. Kept for reference.

| File | Description |
|------|-------------|
| `server.py` | TCP socket server |
| `director_client.py` | Director GUI (TCP) |
| `actor_client.py` | Actor GUI with Soundpad (TCP) |

## Why Legacy?

The TCP version works on local networks and Tailscale, but doesn't support:
- Public internet access (requires WebSocket + reverse proxy)
- Tailscale Funnel (HTTP-only)
- Cloudflare Tunnel (HTTP-only)

Use the WebSocket version (`*_ws.py` files) instead.