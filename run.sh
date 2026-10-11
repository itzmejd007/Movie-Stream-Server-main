#!/usr/bin/env bash
# =========================================================
# Movie Stream Backend - Start Script (Background Nohup)
# =========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Activate venv if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Stop previous running server if any
pkill -f "python3 -m Backend" 2>/dev/null || true
pkill -f "python -m Backend" 2>/dev/null || true
sleep 1

# Start in background using nohup
nohup python3 -m Backend > log.txt 2>&1 &
PID=$!

echo "=========================================="
echo "🚀 Backend started in background!"
echo "PID: $PID"
echo "Log file: log.txt"
echo "=========================================="
echo "Commands:"
echo "• View live logs:  tail -f log.txt"
echo "• Stop server:     ./stop.sh"
echo "• Check status:    ./status.sh"
echo "=========================================="
