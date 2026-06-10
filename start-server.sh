#!/bin/bash
# Start/stop script for vrActorAssist server + Caddy reverse proxy
# Usage: ./start-server.sh start|stop|restart|status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
SERVER_PID="$SCRIPT_DIR/server.pid"
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
CADDYFILE="/etc/caddy/Caddyfile"
DOMAIN="relay.dannygreyproductions.com"
SERVER_PORT="5555"

# Core server dependencies (actor clients have their own)
REQUIRED_PACKAGES=("fastapi" "uvicorn" "websockets")

# Ask for sudo upfront so we don't hang mid-start
ensure_sudo() {
    if ! sudo -n true 2>/dev/null; then
        echo "Caddy config requires sudo — entering password now so it doesn't interrupt later."
        sudo -v || { echo "✗ sudo required to configure Caddy"; exit 1; }
    fi
}

# --- Virtual environment management ---

setup_venv() {
    echo "Checking virtual environment..."

    # Create venv if it doesn't exist
    if [ ! -d "$VENV_DIR" ] || [ ! -f "$PYTHON" ]; then
        echo "  Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
        if [ $? -ne 0 ]; then
            echo "✗ Failed to create venv — is python3-venv installed?"
            exit 1
        fi
        echo "  ✓ venv created at $VENV_DIR"
    fi

    # Check if required packages are installed
    MISSING=()
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        if ! "$PYTHON" -c "import $pkg" 2>/dev/null; then
            MISSING+=("$pkg")
        fi
    done

    if [ ${#MISSING[@]} -gt 0 ]; then
        echo "  Installing missing packages: ${MISSING[*]}..."
        "$PIP" install --quiet "${MISSING[@]}"
        if [ $? -ne 0 ]; then
            echo "✗ Failed to install packages"
            exit 1
        fi
        echo "  ✓ Installed: ${MISSING[*]}"
    else
        echo "  ✓ All dependencies satisfied"
    fi
}

# --- Caddy management ---

ensure_caddy_running() {
    echo "Checking Caddy..."
    if ! systemctl is-active --quiet caddy 2>/dev/null; then
        echo "  Caddy is not running — starting..."
        sudo systemctl start caddy
        sleep 1
    fi
    if systemctl is-active --quiet caddy 2>/dev/null; then
        echo "  ✓ Caddy is running"
    else
        echo "  ✗ Caddy failed to start — is it installed? (apt install caddy)"
        exit 1
    fi
}

ensure_caddy_config() {
    echo "Checking Caddy reverse proxy config..."

    # Build the expected config block
    local target_block
    target_block=$(cat <<EOF
$DOMAIN {
    reverse_proxy localhost:$SERVER_PORT
}
EOF
)

    # If Caddyfile doesn't exist, create it
    if [ ! -f "$CADDYFILE" ]; then
        echo "  Creating Caddyfile..."
        sudo mkdir -p "$(dirname "$CADDYFILE")"
        echo "$target_block" | sudo tee "$CADDYFILE" > /dev/null
        reload_caddy
        return
    fi

    # Check if the domain is already configured
    if grep -q "^$DOMAIN\b" "$CADDYFILE" 2>/dev/null; then
        echo "  ✓ $DOMAIN already in Caddyfile"
        return
    fi

    # Append the block
    echo "  Adding $DOMAIN reverse proxy block..."
    echo "" | sudo tee -a "$CADDYFILE" > /dev/null
    echo "$target_block" | sudo tee -a "$CADDYFILE" > /dev/null
    reload_caddy
}

reload_caddy() {
    echo "  Reloading Caddy..."
    sudo systemctl reload caddy 2>/dev/null
    sleep 1
    echo "  ✓ Caddy reloaded"
}

# --- Server management ---

# Kill any existing server processes
stop_existing() {
    echo "Checking for existing server processes..."

    # Kill server via PID file
    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        echo "  Stopping existing server (PID $(cat "$SERVER_PID"))..."
        kill "$(cat "$SERVER_PID")" 2>/dev/null
        sleep 1
        if kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
            kill -9 "$(cat "$SERVER_PID")" 2>/dev/null
        fi
        rm -f "$SERVER_PID"
        echo "  ✓ Server stopped"
    else
        rm -f "$SERVER_PID" 2>/dev/null
    fi

    # Kill any orphaned server_ws.py processes
    ORPHANS=$(pgrep -f "server_ws.py" 2>/dev/null)
    if [ -n "$ORPHANS" ]; then
        echo "  Killing orphaned server processes: $ORPHANS"
        echo "$ORPHANS" | xargs kill 2>/dev/null
        sleep 1
        echo "$ORPHANS" | xargs kill -9 2>/dev/null
    fi

    echo "  All clear"
}

start() {
    # Always clean up existing processes first
    stop_existing

    # Ensure virtual environment is ready
    setup_venv

    # Prompt for server secret
    read -s -p "Enter server secret: " SECRET
    echo
    if [ -z "$SECRET" ]; then
        echo "Error: Secret cannot be empty"
        exit 1
    fi

    # Get sudo access upfront for Caddy config
    ensure_sudo

    # Create log directory if needed
    mkdir -p "$LOG_DIR"

    # Start Python server (as current user, not root)
    echo "Starting server..."
    "$PYTHON" "$SCRIPT_DIR/server_ws.py" --secret "$SECRET" >> "$LOG_DIR/server.log" 2>&1 &
    echo $! > "$SERVER_PID"

    # Give server a moment to bind
    sleep 1

    # Verify server started
    if ! kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        echo "✗ Server failed to start — check $LOG_DIR/server.log"
        rm -f "$SERVER_PID"
        exit 1
    fi
    echo "✓ Server running (PID $(cat "$SERVER_PID")) on localhost:$SERVER_PORT"

    # Ensure Caddy is running and configured
    ensure_caddy_running
    ensure_caddy_config

    echo ""
    echo "────────────────────────────────────────"
    echo "🔗 Connection URL (share with clients):"
    echo "   wss://$DOMAIN/ws"
    echo "────────────────────────────────────────"
    echo "  Logs: $LOG_DIR/"
}

stop() {
    echo "Stopping server..."

    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        kill "$(cat "$SERVER_PID")" 2>/dev/null
        rm -f "$SERVER_PID"
        echo "✓ Server stopped"
    else
        rm -f "$SERVER_PID" 2>/dev/null
        echo "Server: not running"
    fi

    # Also kill orphans
    ORPHANS=$(pgrep -f "server_ws.py" 2>/dev/null)
    if [ -n "$ORPHANS" ]; then
        echo "  Killing orphaned server processes: $ORPHANS"
        echo "$ORPHANS" | xargs kill 2>/dev/null
    fi
}

status() {
    echo "────────────────────────────────────"
    echo "  vrActorAssist — relay.dgp.lol"
    echo "────────────────────────────────────"
    echo ""

    # Server status
    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        echo "Server:  ✓ running (PID $(cat "$SERVER_PID"))"
    else
        echo "Server:  ✗ not running"
    fi

    # Caddy status
    if systemctl is-active --quiet caddy 2>/dev/null; then
        echo "Caddy:   ✓ running"
    else
        echo "Caddy:   ✗ not running"
    fi

    # Domain config
    if grep -q "^$DOMAIN\b" "$CADDYFILE" 2>/dev/null; then
        echo "Domain:  ✓ $DOMAIN configured"
    else
        echo "Domain:  ✗ $DOMAIN not in Caddyfile"
    fi

    # Connection URL if both server and caddy are up
    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null && \
       systemctl is-active --quiet caddy 2>/dev/null && \
       grep -q "^$DOMAIN\b" "$CADDYFILE" 2>/dev/null; then
        echo ""
        echo "────────────────────────────────────────"
        echo "🔗 Connection URL:"
        echo "   wss://$DOMAIN/ws"
        echo "────────────────────────────────────────"
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        echo ""
        start
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
