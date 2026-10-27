# 🚀 Movie Stream Backend - Production VPS Deployment Guide

This guide explains how to easily deploy the **Movie-Stream-Server** backend on any Linux VPS (Ubuntu 22.04 / 24.04, Debian 11/12) and connect it with your Vercel-hosted frontend.

---

## 📋 Prerequisites
- A VPS with Ubuntu 20.04/22.04/24.04 or Debian (Recommended: 1GB+ RAM, e.g. DigitalOcean, Hetzner, AWS EC2, Contabo, Linode)
- Open Ports: `22` (SSH), `80` (HTTP), `443` (HTTPS)
- Your domain or subdomain (e.g., `api.yourdomain.com`) pointing to your VPS IP address in DNS (A Record).

---

## ⚡ Option 1: Docker Compose (Recommended - Quickest & Isolated)

If you have Docker & Docker Compose installed on your VPS, this is the easiest method.

### 1. Clone repository to VPS
```bash
git clone <your-repo-url> /opt/movie-stream
cd /opt/movie-stream
```

### 2. Configure credentials
Ensure your `config.env` exists with your Telegram and MongoDB credentials:
```bash
nano config.env
```

### 3. Start the container in background
```bash
docker compose up -d --build
```

### 4. Useful Docker Commands
```bash
# View real-time logs
docker compose logs -f

# Check container status
docker compose ps

# Restart backend
docker compose restart

# Stop backend
docker compose down
```

---

## 🛠 Option 2: Automated 1-Script VPS Deployment

We have created an automated setup script `deploy_vps.sh` that installs all system packages (Python, venv, ffmpeg, git), sets up the virtual environment, installs dependencies, and configures an auto-restarting `systemd` service.

### 1. Run the script on your VPS
```bash
cd /path/to/Movie-Stream-Server-main-main
chmod +x deploy_vps.sh
sudo bash deploy_vps.sh
```

The script will automatically configure `movie-stream.service` and start the server!

### Useful Systemd Commands:
```bash
# View live logs
journalctl -u movie-stream.service -f

# Restart service
sudo systemctl restart movie-stream.service

# Stop service
sudo systemctl stop movie-stream.service

# Check status
sudo systemctl status movie-stream.service
```

---

## 📦 Option 3: Manual Systemd Setup (Native Python)

If you prefer setting up manually without Docker:

### 1. Install system dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git ffmpeg curl
```

### 2. Setup Virtual Environment & Install Requirements
```bash
cd /var/www/Movie-Stream-Server-main-main
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Test running directly
```bash
python3 -m Backend
```
Press `Ctrl+C` once verified.

### 4. Enable Background Service
Copy the provided unit file:
```bash
sudo cp movie-stream.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable movie-stream.service
sudo systemctl start movie-stream.service
```

---

## 🌐 Setting Up Domain & Free SSL (Caddy Reverse Proxy)

Caddy is the simplest web server with **automatic SSL certificate issuance and renewals**.

### 1. Install Caddy
```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy -y
```

### 2. Configure Caddyfile
```bash
sudo nano /etc/caddy/Caddyfile
```
Add:
```caddy
api.yourdomain.com {
    reverse_proxy localhost:8000
}
```
*(Replace `api.yourdomain.com` with your actual subdomain pointing to this VPS IP, and `8000` with your `PORT` if different).*

### 3. Restart Caddy
```bash
sudo systemctl restart caddy
```
Caddy will automatically generate a free HTTPS SSL certificate from Let's Encrypt!

---

## 🔗 Connecting Frontend on Vercel

In your Vercel Dashboard for the frontend (`Client-main`):
1. Navigate to **Project Settings** → **Environment Variables**.
2. Set or update `VITE_BASE_URL`:
   ```env
   VITE_BASE_URL=https://api.yourdomain.com
   ```
3. Click **Redeploy** on Vercel.

---

## 🛡 Automatic Maintenance Mode Behavior

Your frontend now includes automatic backend health detection:
- **Server Online:** The frontend functions normally without interruption.
- **Server Offline / Maintenance:** If the VPS server is restarting, undergoing updates, or unreachable, the frontend automatically displays a clean **Under Maintenance** screen with an auto-reconnect timer and "Retry Now" button.
- As soon as the VPS backend is back online, the frontend automatically reconnects seamlessly!

---

## 🔄 1-Click Domain Migration & Automatic SSL (DMCA / Copyright Protection)

When buying a new domain (e.g. `animetoon.xyz`) and migrating from `animetoon.in`:

### 1. On your VPS (1-Command Automatic Domain & SSL Change)
```bash
chmod +x change_domain.sh setup_ssl.sh
sudo ./change_domain.sh animetoon.xyz api.animetoon.xyz
```
This automatically:
- Updates `FRONTEND_LINK` in `config.env`.
- Updates Caddy / Nginx reverse proxy with the new domain.
- Obtains and installs free Let's Encrypt / ZeroSSL HTTPS certificate automatically.
- Restarts the backend service seamlessly.

### 2. On Cloudflare (Old Domain Redirection Rule)
To redirect **all traffic from old domain (`animetoon.in`) to new domain (`animetoon.xyz`)** without breaking links:
1. Open Cloudflare dashboard for `animetoon.in`.
2. Go to: **Rules** → **Redirect Rules** → **Create Rule**.
3. Name: `Redirect to New Domain`.
4. Matching incoming requests: **All incoming requests**.
5. Target URL:
   - Type: **Dynamic**
   - Expression: `concat("https://animetoon.xyz", http.request.uri.path)`
   - Status code: `301 (Moved Permanently)`
   - Check: **Preserve query string**.
6. Click **Deploy**.

### 3. On Vercel
1. Project Settings → **Domains** → Add `animetoon.xyz` and `www.animetoon.xyz`.
2. Environment Variables → Update `VITE_BASE_URL` to `https://api.animetoon.xyz`.
3. Click **Redeploy**.

