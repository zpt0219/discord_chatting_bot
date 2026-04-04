# Deployment Guide

## Remote Server Setup (adna.world)

### 1. Upload the code
```bash
# From your local PC
scp -r ./* user@adna.world:~/discord_bot/
# Or use git: push to repo and clone on server
```

### 2. Install dependencies
```bash
ssh user@adna.world
cd ~/discord_bot
pip install -r requirements.txt
```

### 3. Configure .env
Make sure `.env` on the server has all the same keys. Change `TUNNEL_SECRET` to your own secret (must match on both sides).

### 4. Start the services
You need TWO processes running on the server:

**Terminal 1 - Tunnel Server (start first):**
```bash
python tunnel/tunnel_server.py
```

**Terminal 2 - Discord Bot:**
```bash
python bot.py
```

Or use `screen`/`tmux` to run both in the background:
```bash
# Start tunnel server in background
screen -dmS tunnel python tunnel/tunnel_server.py

# Start bot in background  
screen -dmS bot python bot.py

# View logs
screen -r tunnel   # Ctrl+A, D to detach
screen -r bot
```

Or use systemd (create `/etc/systemd/system/discord-bot.service`):
```ini
[Unit]
Description=Discord Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/your_user/discord_bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Local PC Setup

### 1. Make sure your local Llama server is running
```bash
# Your Llama.cpp server should be on http://127.0.0.1:8888
```

### 2. Start the tunnel client
```bash
cd d:\python_server\take_home_task
python tunnel/tunnel_client.py
```

You should see:
```
============================================================
  TUNNEL CLIENT - Run this on your LOCAL PC
  Server:  ws://adna.world:9999/ws
  Llama:   http://127.0.0.1:8888
============================================================
[TUNNEL CLIENT] Connecting to ws://adna.world:9999/ws...
[TUNNEL CLIENT] Connected and authenticated!
[TUNNEL CLIENT] Forwarding requests to http://127.0.0.1:8888
```

### 3. That's it!
- When the tunnel is connected: Bot uses your local Llama model (free, fast)
- When you close the tunnel client: Bot automatically falls back to Claude → OpenAI
- The tunnel client auto-reconnects if the connection drops

---

## How the Fallback Chain Works

```
Bot receives message
    ↓
Router: "Is this simple?"
    ↓ Yes
Try Local Llama (via tunnel)
    ↓ Tunnel down? 503 error
Fall back to Claude
    ↓ Claude fails?
Fall back to OpenAI
```

The bot NEVER goes offline. It just gracefully degrades when your local model isn't available.

---

## Security Notes

- Change `TUNNEL_SECRET` in `.env` to a strong random string
- The WebSocket port (9999) should ideally be firewalled to allow only your local IP
- The HTTP proxy (8888) only listens on `127.0.0.1` (not exposed to the internet)
