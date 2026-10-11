#!/usr/bin/env bash
# =========================================================
# Movie Stream Backend - Start Script (Background Nohup)
# =========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Detect PORT from config.env (default 8000)
PORT=$(grep -E "^PORT" config.env 2>/dev/null | cut -d '=' -f2 | tr -d ' "' | tr -d "'" || echo "8000")
PORT=${PORT:-8000}

# Stop systemd service if running to prevent port conflicts
systemctl stop movie-stream 2>/dev/null || true

# Free ports and kill any lingering python processes
echo "Checking and freeing port $PORT..."
fuser -k -9 "${PORT}/tcp" 2>/dev/null || true
fuser -k -9 "8000/tcp" 2>/dev/null || true
fuser -k -9 "7860/tcp" 2>/dev/null || true
pkill -9 -f "python3 -m Backend" 2>/dev/null || true
pkill -9 -f "python -m Backend" 2>/dev/null || true
sleep 2

# Activate venv if exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../.venv" ]; then
    source ../.venv/bin/activate
fi

# Clear old log file
> log.txt

# Start in background using nohup
nohup python3 -m Backend > log.txt 2>&1 &
PID=$!

echo "=========================================="
echo "🚀 Backend started in background!"
echo "PID:  $PID"
echo "Port: $PORT"
echo "Log:  log.txt"
echo "=========================================="
echo "Commands:"
echo "• View live logs:  tail -f log.txt"
echo "• Stop server:     ./stop.sh"
echo "• Check status:    ./status.sh"
echo "=========================================="
