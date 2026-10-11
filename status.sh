#!/usr/bin/env bash
# =========================================================
# Movie Stream Backend - Status Script
# =========================================================

if pgrep -f "Backend" > /dev/null; then
    echo "🟢 Movie Stream Server is RUNNING"
    echo "Process Details:"
    pgrep -a -f "Backend"
else
    echo "🔴 Movie Stream Server is STOPPED"
fi
