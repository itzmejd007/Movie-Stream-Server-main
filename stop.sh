#!/usr/bin/env bash
# =========================================================
# Movie Stream Backend - Stop Script
# =========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

PORT=$(grep -E "^PORT" config.env 2>/dev/null | cut -d '=' -f2 | tr -d ' "' | tr -d "'" || echo "8000")
PORT=${PORT:-8000}

echo "Stopping Movie Stream Server and freeing port $PORT..."
systemctl stop movie-stream 2>/dev/null || true
fuser -k -9 "${PORT}/tcp" 2>/dev/null || true
fuser -k -9 "8000/tcp" 2>/dev/null || true
fuser -k -9 "7860/tcp" 2>/dev/null || true
pkill -9 -f "python3 -m Backend" 2>/dev/null || true
pkill -9 -f "python -m Backend" 2>/dev/null || true
sleep 1

echo "✓ Backend stopped and Ports ($PORT, 8000, 7860) freed successfully!"
