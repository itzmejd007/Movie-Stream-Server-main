## Easily Deploy to Heroku

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/1s86kjrlOsdTos0M0BStvKmUiOovHoVjK)



# 🚀 PRODUCTION VPS / AWS DEPLOYMENT GUIDE

(For FastAPI + Domain + SSL + Cloudflare optional)

---

# 📦 1. Server Requirements

* Ubuntu 22.04 LTS
* Python 3.10+
* 1 GB RAM minimum
* Ports: 22, 80, 443 open

---

# 🛠 2. Initial Server Setup

### Update system

```bash
sudo apt update && sudo apt upgrade -y
```

### Install required tools

```bash
sudo apt install python3 python3-venv python3-pip git -y
```

---

# 📁 3. Deploy Your App (VPS / AWS)

Clone your project:

```bash
git clone https://github.com/yourrepo.git
cd yourrepo
```

Create virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# 🌐 4. Domain Setup (VPS / AWS)

In your DNS (Hostinger / etc.):

Create:

| Type | Name | Value          |
| ---- | ---- | -------------- |
| A    | api  | YOUR_SERVER_IP |

TTL: `300`

---

# 🔐 5. Install Caddy (Best Reverse Proxy + Auto SSL)

Install:

```bash
sudo apt install caddy -y
```

Edit config:

```bash
sudo nano /etc/caddy/Caddyfile
```

Add:

```
api.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Restart:

```bash
sudo systemctl restart caddy
```

Check:

```bash
sudo systemctl status caddy
```

---

# 🏗 6. Run/Stop FastAPI in Production

To Run:

```bash
nohup python -m Backend

```

To Stop:

```bash
sudo pkill -f python
# or
ps -ef | grep python # Now kill the process using PID
kill <PID> # eg: kill 64182
```

---


# 🌍 7. AWS Specific Steps

## Open Security Group Ports

Go to:

```
EC2 → Security Groups
```

Add inbound rules:

| Port | Type  |
| ---- | ----- |
| 22   | SSH   |
| 80   | HTTP  |
| 443  | HTTPS |

---

# ☁ 8. If Using Cloudflare

DNS → Orange Cloud (Proxied)

SSL Mode → **Full**

Never use Flexible once Caddy is installed.

---

# 🧠 Final Architecture

```
User
  ↓
Cloudflare (optional)
  ↓
Caddy (SSL + Reverse Proxy)
  ↓
Gunicorn (8000)
  ↓
FastAPI App
```

---

# 📊 Monitoring Commands

Check FastAPI:

```bash
sudo systemctl status fastapi
```

Check Caddy:

```bash
sudo systemctl status caddy
```

Check logs:

```bash
journalctl -u fastapi -f
journalctl -u caddy -f
```

---

# 🛡 Production Improvements (Recommended) (Optional)

### Enable Firewall

```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

---

### Enable Swap (For 1GB servers) (Optional)

```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

# 🔥 Common Errors & Fixes

| Error                        | Cause                | Fix                     |
| ---------------------------- | -------------------- | ----------------------- |
| 522                          | Port 80 blocked      | Open security group     |
| SSL loop                     | Cloudflare Flexible  | Change to Full          |
| Port 80 in use               | nginx/apache running | Stop them               |
| SSL_ERROR_RX_RECORD_TOO_LONG | Using https on 8000  | Use domain without port |

---

# 🎯 Final Result

Your site runs on:

```
https://api.yourdomain.com
```

* Auto HTTPS
* Auto restart
* Production ready
* No manual SSL renewals

---

