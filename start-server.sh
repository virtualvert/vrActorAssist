#!/bin/bash
# Start/stop script for vrActorAssist server + Tailscale funnel
# Usage: ./start-server.sh start|stop|restart|status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
SERVER_PID="$SCRIPT_DIR/server.pid"
FUNNEL_PID="$SCRIPT_DIR/funnel.pid"

# Ask for sudo upfront so we don't hang mid-start
ensure_sudo() {
    if ! sudo -n true 2>/dev/null; then
        echo "Funnel requires sudo — entering password now so it doesn't interrupt later."
        sudo -v || { echo "✗ sudo required for Tailscale funnel"; exit 1; }
    fi
}

# Kill any existing server or funnel processes
stop_existing() {
    echo "Checking for existing processes..."
    
    # Kill server via PID file
    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        echo "  Stopping existing server (PID $(cat "$SERVER_PID"))..."
        kill "$(cat "$SERVER_PID")" 2>/dev/null
        sleep 1
        # Force kill if still running
        if kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
            kill -9 "$(cat "$SERVER_PID")" 2>/dev/null
        fi
        rm -f "$SERVER_PID"
        echo "  ✓ Server stopped"
    else
        rm -f "$SERVER_PID" 2>/dev/null
    fi
    
    # Kill funnel via PID file
    if [ -f "$FUNNEL_PID" ] && kill -0 "$(cat "$FUNNEL_PID")" 2>/dev/null; then
        echo "  Stopping existing funnel (PID $(cat "$FUNNEL_PID"))..."
        sudo kill "$(cat "$FUNNEL_PID")" 2>/dev/null
        sleep 1
        if kill -0 "$(cat "$FUNNEL_PID")" 2>/dev/null; then
            sudo kill -9 "$(cat "$FUNNEL_PID")" 2>/dev/null
        fi
        rm -f "$FUNNEL_PID"
        echo "  ✓ Funnel stopped"
    else
        rm -f "$FUNNEL_PID" 2>/dev/null
    fi
    
    # Kill any orphaned server_ws.py processes
    ORPHANS=$(pgrep -f "python3.*server_ws.py" 2>/dev/null)
    if [ -n "$ORPHANS" ]; then
        echo "  Killing orphaned server processes: $ORPHANS"
        echo "$ORPHANS" | xargs kill 2>/dev/null
        sleep 1
        echo "$ORPHANS" | xargs kill -9 2>/dev/null
    fi
    
    # Kill any orphaned tailscale funnel processes
    FUNNEL_ORPHANS=$(pgrep -f "tailscale funnel" 2>/dev/null)
    if [ -n "$FUNNEL_ORPHANS" ]; then
        echo "  Killing orphaned funnel processes: $FUNNEL_ORPHANS"
        echo "$FUNNEL_ORPHANS" | xargs sudo kill 2>/dev/null
        sleep 1
        echo "$FUNNEL_ORPHANS" | xargs sudo kill -9 2>/dev/null
    fi
    
    # Also turn off the funnel serving (tailscale funnel off)
    sudo tailscale funnel off 2>/dev/null
    
    echo "  All clear"
}

start() {
    # Always clean up existing processes first
    stop_existing
    
    # Prompt for server secret
    read -s -p "Enter server secret: " SECRET
    echo
    if [ -z "$SECRET" ]; then
        echo "Error: Secret cannot be empty"
        exit 1
    fi
    
    # Get sudo access upfront for funnel
    ensure_sudo
    
    # Create log directory if needed
    mkdir -p "$LOG_DIR"
    
    # Start Python server (as current user, not root)
    echo "Starting server..."
    python3 "$SCRIPT_DIR/server_ws.py" --secret "$SECRET" >> "$LOG_DIR/server.log" 2>&1 &
    echo $! > "$SERVER_PID"
    
    # Give server a moment to bind
    sleep 1
    
    # Verify server started
    if ! kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        echo "✗ Server failed to start — check $LOG_DIR/server.log"
        rm -f "$SERVER_PID"
        exit 1
    fi
    
    # Start Tailscale funnel (sudo already cached)
    echo "Starting Tailscale funnel on port 5555..."
    sudo tailscale funnel 5555 >> "$LOG_DIR/funnel.log" 2>&1 &
    echo $! > "$FUNNEL_PID"
    
    # Get Tailscale DNS name for funnel URL
    TS_DNS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('Self',{}).get('DNSName',''))" 2>/dev/null | sed 's/\.$//')
    
    # Wait for funnel to initialize
    sleep 2
    
    echo ""
    echo "✓ Server running (PID $(cat "$SERVER_PID"))"
    echo "✓ Funnel running (PID $(cat "$FUNNEL_PID"))"
    echo "  Logs: $LOG_DIR/"
    echo ""
    if [ -n "$TS_DNS" ]; then
        echo "────────────────────────────────────────"
        echo "🔗 Funnel URL (share with clients):"
        echo "   wss://$TS_DNS/ws"
        echo "────────────────────────────────────────"
    fi
}

stop() {
    echo "Stopping server and funnel..."
    
    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        kill "$(cat "$SERVER_PID")" 2>/dev/null
        rm -f "$SERVER_PID"
        echo "✓ Server stopped"
    else
        rm -f "$SERVER_PID" 2>/dev/null
        echo "Server: not running"
    fi
    
    if [ -f "$FUNNEL_PID" ] && kill -0 "$(cat "$FUNNEL_PID")" 2>/dev/null; then
        sudo kill "$(cat "$FUNNEL_PID")" 2>/dev/null
        rm -f "$FUNNEL_PID"
        echo "✓ Funnel stopped"
    else
        rm -f "$FUNNEL_PID" 2>/dev/null
        echo "Funnel: not running"
    fi
    
    # Turn off funnel serving
    sudo tailscale funnel off 2>/dev/null
}

status() {
    if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
        echo "Server: running (PID $(cat "$SERVER_PID"))"
    else
        echo "Server: not running"
    fi
    
    if [ -f "$FUNNEL_PID" ] && kill -0 "$(cat "$FUNNEL_PID")" 2>/dev/null; then
        echo "Funnel: running (PID $(cat "$FUNNEL_PID"))"
        
        # Show funnel URL if server is also running
        if [ -f "$SERVER_PID" ] && kill -0 "$(cat "$SERVER_PID")" 2>/dev/null; then
            TS_DNS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('Self',{}).get('DNSName',''))" 2>/dev/null | sed 's/\.$//')
            if [ -n "$TS_DNS" ]; then
                echo ""
                echo "────────────────────────────────────────"
                echo "🔗 Funnel URL (share with clients):"
                echo "   wss://$TS_DNS/ws"
                echo "────────────────────────────────────────"
            fi
        fi
    else
        echo "Funnel: not running"
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