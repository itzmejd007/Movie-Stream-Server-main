#!/usr/bin/env bash
# Execute optional upstream update safely, then run the Backend server
python3 update.py || true
exec python3 -m Backend
