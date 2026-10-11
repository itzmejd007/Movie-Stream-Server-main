#!/usr/bin/env bash
# =========================================================
# Movie Stream Backend - Stop Script
# =========================================================

echo "Stopping Movie Stream Server and freeing port 8000..."
fuser -k 8000/tcp 2>/dev/null || true
pkill -f "python3 -m Backend" 2>/dev/null || true
pkill -f "python -m Backend" 2>/dev/null || true
sleep 1

if pgrep -f "Backend" > /dev/null; then
    pkill -9 -f "Backend" 2>/dev/null || true
fi

echo "✓ Backend stopped and Port 8000 freed successfully!"
