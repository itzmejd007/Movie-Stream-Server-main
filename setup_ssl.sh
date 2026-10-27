#!/usr/bin/env bash
# ==============================================================================
# AnimeToon - Automated SSL Setup & Diagnostic Tool for VPS
# ==============================================================================
# Usage:
#   sudo ./setup_ssl.sh [backend_domain]
# ==============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}==================================================================${NC}"
echo -e "${BOLD}${CYAN}🔒 Automated SSL Setup & Diagnostic Tool for AnimeToon VPS${NC}"
echo -e "${CYAN}==================================================================${NC}"

# Detect root / sudo
if [ "$EUID" -ne 0 ]; then
  echo -e "${YELLOW}Please run with sudo: sudo ./setup_ssl.sh${NC}"
fi

DOMAIN="$1"
if [ -z "$DOMAIN" ]; then
    echo -e "${YELLOW}Enter your Backend API Subdomain (e.g. api.animetoon.xyz):${NC}"
    read -r -p "> " DOMAIN
fi

DOMAIN=$(echo "$DOMAIN" | sed -e 's|^https://||' -e 's|^http://||' -e 's|/$||' | tr -d ' ')

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Error: Domain cannot be empty.${NC}"
    exit 1
fi

echo -e "\n${BOLD}Target Subdomain:${NC} ${GREEN}$DOMAIN${NC}"

# Check Open Ports
echo -e "\n${GREEN}[1/3] Checking firewall & open ports (80, 443)...${NC}"
if command -v ufw &> /dev/null; then
    ufw allow 80/tcp 2>/dev/null || true
    ufw allow 443/tcp 2>/dev/null || true
    echo -e "✓ UFW firewall rules updated for port 80 and 443."
fi

# Detect Web Server (Caddy / Nginx)
echo -e "\n${GREEN}[2/3] Checking Web Server & Installing if needed...${NC}"

if command -v caddy &> /dev/null; then
    echo -e "✓ Caddy is already installed."
elif command -v nginx &> /dev/null; then
    echo -e "✓ Nginx is installed."
else
    echo -e "${YELLOW}No web server found. Installing Caddy for automated zero-config SSL...${NC}"
    apt update -y
    apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt update -y
    apt install -y caddy
    echo -e "✓ Caddy installed successfully!"
fi

# Configure & Request SSL
echo -e "\n${GREEN}[3/3] Requesting SSL Certificate for $DOMAIN...${NC}"

if command -v caddy &> /dev/null; then
    mkdir -p /etc/caddy
    cat <<EOF > /etc/caddy/Caddyfile
$DOMAIN {
    reverse_proxy localhost:8000
}
EOF
    systemctl restart caddy
    echo -e "✓ Caddy restarted. Requesting Let's Encrypt / ZeroSSL certificate..."
    sleep 3
elif command -v certbot &> /dev/null && command -v nginx &> /dev/null; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect || true
    systemctl reload nginx
fi

# SSL Verification Test
echo -e "\n${CYAN}==================================================================${NC}"
echo -e "${BOLD}🔍 Verifying SSL Connection to https://$DOMAIN...${NC}"
sleep 2

STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN/health" || curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN" || echo "000")

if [ "$STATUS_CODE" != "000" ]; then
    echo -e "${GREEN}✓ SSL is ACTIVE & WORKING! (HTTP Status: $STATUS_CODE)${NC}"
else
    echo -e "${YELLOW}⚠️ Cannot directly reach https://$DOMAIN yet.${NC}"
    echo -e "Possible reasons:"
    echo -e "1. DNS record for ${BOLD}$DOMAIN${NC} hasn't propagated yet in Cloudflare (wait 1-2 minutes)."
    echo -e "2. In Cloudflare SSL/TLS settings, set SSL mode to ${BOLD}Full${NC} or ${BOLD}Full (Strict)${NC}."
fi

echo -e "\n${GREEN}Setup script completed!${NC}"
echo -e "${CYAN}==================================================================${NC}\n"
