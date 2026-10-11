#!/usr/bin/env bash
# ==============================================================================
# Automated VPS Deployment Script for Movie Stream Server (Ubuntu/Debian)
# ==============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}🚀 Starting VPS Setup for Movie Stream Backend Server${NC}"
echo -e "${CYAN}======================================================${NC}"

# 1. Check Root / Sudo
if [ "$EUID" -ne 0 ]; then
  echo -e "${YELLOW}Notice: It is recommended to run this script as root or with sudo.${NC}"
fi

# 2. Update System Packages
echo -e "\n${GREEN}[1/5] Updating system packages & installing dependencies...${NC}"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git ffmpeg curl

# 3. Check config.env
echo -e "\n${GREEN}[2/5] Checking configuration file...${NC}"
CURRENT_DIR=$(pwd)

if [ ! -f "$CURRENT_DIR/config.env" ]; then
    if [ -f "$CURRENT_DIR/config.env.example" ]; then
        echo -e "${YELLOW}config.env not found! Copying from config.env.example...${NC}"
        cp "$CURRENT_DIR/config.env.example" "$CURRENT_DIR/config.env"
        echo -e "${YELLOW}⚠️ Please make sure to fill in your credentials in $CURRENT_DIR/config.env!${NC}"
    else
        echo -e "${RED}Error: config.env is missing! Please create it before starting the server.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Found existing config.env${NC}"
fi

# 4. Setup Python Virtual Environment
echo -e "\n${GREEN}[3/5] Setting up Python virtual environment...${NC}"
if [ ! -d "$CURRENT_DIR/venv" ]; then
    python3 -m venv "$CURRENT_DIR/venv"
    echo -e "${GREEN}✓ Created venv${NC}"
fi

source "$CURRENT_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$CURRENT_DIR/requirements.txt"
echo -e "${GREEN}✓ Python packages installed successfully${NC}"

# 5. Setup Systemd Service
echo -e "\n${GREEN}[4/5] Setting up systemd background service (movie-stream.service)...${NC}"
SERVICE_FILE="/etc/systemd/system/movie-stream.service"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Movie Stream Backend FastAPI and Telegram Bot Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python3 -m Backend
Restart=always
RestartSec=5
KillMode=process
StandardOutput=journal
StandardError=journal
EnvironmentFile=$CURRENT_DIR/config.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable movie-stream.service
systemctl restart movie-stream.service

echo -e "\n${GREEN}[5/5] Checking server status...${NC}"
sleep 3

if systemctl is-active --quiet movie-stream.service; then
    echo -e "${GREEN}======================================================${NC}"
    echo -e "${GREEN}🎉 Movie Stream Backend is RUNNING SUCCESSFULLY!${NC}"
    echo -e "${GREEN}======================================================${NC}"
    echo -e "• Check logs:     ${CYAN}journalctl -u movie-stream.service -f${NC}"
    echo -e "• Restart server: ${CYAN}systemctl restart movie-stream.service${NC}"
    echo -e "• Stop server:    ${CYAN}systemctl stop movie-stream.service${NC}"
    echo -e "• Health check:   ${CYAN}curl http://localhost:8000/health${NC}"
else
    echo -e "${YELLOW}⚠️ Service started. Check logs to ensure Telegram Bot connected:${NC}"
    echo -e "journalctl -u movie-stream.service -n 50 --no-pager"
fi
