# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A two-server OTP system. The user enters a phone number on a web page, a 6-digit OTP is generated and queued by the main server, then sent via WhatsApp Web (Playwright) by a standalone microservice running locally. The user then enters the OTP on a second page and the main server verifies it against the DB.

No Twilio. No Meta API. WhatsApp is automated via Playwright using a personal WhatsApp account.

---

## Architecture

```
Browser (Page 1 — phone input)
      ↓  POST /api/send-otp
Server 1 — main-server (FastAPI, runs on AWS EC2)
  - Generates 6-digit OTP, stores bcrypt hash in MySQL (otp_codes)
  - Inserts job in MySQL (otp_jobs) with status: pending
      ↓  POST /send-whatsapp
Server 2 — whatsapp-service (FastAPI + Playwright, runs locally)
  - Drives WhatsApp Web in a real Chromium window
  - Sends the OTP message via deep-link navigation
  - Returns { "ok": true }
      ↑  Server 1 marks job as sent/failed
Browser (Page 2 — OTP input)
      ↓  POST /api/verify-otp
Server 1 — verifies code, returns result
```

---

## Project Layout

```
.
├── main-server/                  # Server 1 — AWS EC2
│   ├── app/
│   │   ├── config.py             # pydantic-settings, all env vars
│   │   ├── db.py                 # SQLAlchemy engine, SessionLocal, get_db
│   │   ├── main.py               # FastAPI app, routes, static mount
│   │   ├── models.py             # OtpCode + OtpJob ORM models
│   │   ├── otp.py                # generate/hash/verify OTP, CooldownError, OtpError
│   │   ├── schemas.py            # Pydantic shapes, E.164 validator
│   │   └── whatsapp_client.py    # httpx client calling Server 2
│   ├── static/
│   │   ├── index.html / index.js # Page 1 — phone input
│   │   ├── verify.html / verify.js # Page 2 — OTP input + resend
│   │   └── style.css             # Dark WhatsApp theme
│   ├── .env.example
│   └── requirements.txt
│
└── whatsapp-service/             # Server 2 — runs locally
    ├── main.py                   # FastAPI app — /send-whatsapp, /setup, /health
    ├── whatsapp.py               # WhatsAppSender class (all Playwright logic)
    ├── test_send.py              # Standalone CLI test, no Server 1 needed
    ├── .env.example
    └── requirements.txt
```

---

## Running Locally

### Server 2 first (must be running before Server 1 can send OTPs)

```bash
cd whatsapp-service
python -m venv venv
venv\Scripts\pip install -r requirements.txt   # Windows
playwright install chromium
copy .env.example .env
venv\Scripts\uvicorn main:app --port 8001
```

On startup Server 2:
1. Wipes `./session/` (fresh login every run by design)
2. Opens a Chromium window showing WhatsApp Web
3. Opens `http://localhost:8001/setup` in your default browser automatically

On the setup page: enter your WhatsApp number (E.164) → Playwright clicks "Log in with phone number", fills it in, and displays the pairing code. Open WhatsApp on your phone → Settings → Linked Devices → Link a Device → enter the code. The setup page polls until login completes.

### Server 1

```bash
cd main-server
python -m venv venv
venv\Scripts\pip install -r requirements.txt
mysql -uroot -pahmad -e "CREATE DATABASE IF NOT EXISTS whatsappotp CHARACTER SET utf8mb4;"
copy .env.example .env
venv\Scripts\uvicorn app.main:app --port 8000 --reload
```

Open `http://127.0.0.1:8000/`

---

## Environment Variables

### main-server/.env

| Variable | Example | Notes |
|---|---|---|
| `MYSQL_HOST` | `127.0.0.1` | RDS endpoint on AWS |
| `MYSQL_PORT` | `3306` | |
| `MYSQL_USER` | `root` | Use a dedicated user in production |
| `MYSQL_PASSWORD` | `ahmad` | Replace in production |
| `MYSQL_DB` | `whatsappotp` | Must exist before first run |
| `OTP_TTL_SECONDS` | `300` | Code validity window |
| `OTP_MAX_ATTEMPTS` | `5` | Wrong attempts before invalidation |
| `WHATSAPP_SERVICE_URL` | `http://localhost:8001` | URL of Server 2 |
| `RESET_ON_STARTUP` | `false` | `true` wipes otp_codes/otp_jobs rows on boot |

### whatsapp-service/.env

| Variable | Example | Notes |
|---|---|---|
| `PORT` | `8001` | |
| `SESSION_DIR` | `./session` | Wiped on every startup |
| `HEADLESS` | `false` | Keep false — WA Web is unreliable headless |
| `LOGIN_TIMEOUT_SECONDS` | `180` | |
| `SEND_TIMEOUT_SECONDS` | `45` | |

---

## API Endpoints

### Server 1 — port 8000

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/send-otp` | `{"phone"}` → generates OTP, calls Server 2, returns `{"ok", "expires_in"}` or 429/502 |
| `POST` | `/api/verify-otp` | `{"phone","code"}` → returns `{"verified":true}` or 400 `invalid`/`expired`/`too_many_attempts` |
| `GET` | `/` | Serves Page 1 (phone input) |
| `GET` | `/verify` | Serves Page 2 (OTP input) |

### Server 2 — port 8001

| Method | Path | Description |
|---|---|---|
| `POST` | `/send-whatsapp` | `{"phone","code"}` → sends OTP via WA Web. Returns 503 if not logged in |
| `GET` | `/setup` | Setup UI — collects phone number for WA login |
| `POST` | `/setup/start` | `{"phone"}` → drives phone-number login in Playwright, returns `{"pairing_code"}` |
| `GET` | `/setup/status` | Returns `{"logged_in": bool, "setup_needed": bool}` |
| `GET` | `/health` | Returns `{"status":"ok","logged_in":bool}` |

---

## Database

- Engine: MySQL via SQLAlchemy + PyMySQL. Tables auto-created on startup.
- `otp_codes`: phone, code_hash (bcrypt), expires_at, attempts, verified_at
- `otp_jobs`: phone, code (plain, short-lived), status enum(pending/sent/failed)

---

## Key Design Decisions

- **`launch_persistent_context`** (not `storage_state`) — WhatsApp Web stores encryption keys in IndexedDB; only persistent context captures that.
- **Session wiped on every startup** — forces re-login via `/setup` each time, so the WhatsApp account phone number is never stored in any file.
- **Phone-number login, not QR** — user enters their number in the `/setup` UI; Playwright clicks "Log in with phone number" and fills it automatically. The pairing code is shown in the setup page (or in the Chromium window as fallback).
- **asyncio.Lock in WhatsAppSender** — serializes all Playwright navigations; only one send/login at a time.
- **WindowsProactorEventLoopPolicy** set at the top of `whatsapp-service/main.py` — required on Windows for Playwright to spawn subprocesses under uvicorn.
- **Deep-link send**: `https://web.whatsapp.com/send?phone={digits}&text={encoded}` — avoids searching for contacts.
- **CooldownError** in `otp.py` — prevents rapid resends; frontend shows a countdown timer.

---

## Deploying on AWS (Server 1 only)

Server 2 stays local — Playwright requires a real display.

```bash
# EC2: Amazon Linux 2023 / Ubuntu 22.04, t2.micro
sudo dnf install python3.10 python3.10-pip git nginx mysql-server -y
sudo systemctl enable --now mysqld
sudo mysql -e "CREATE DATABASE whatsappotp CHARACTER SET utf8mb4;"
sudo mysql -e "CREATE USER 'otpapp'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';"
sudo mysql -e "GRANT SELECT,INSERT,UPDATE,DELETE ON whatsappotp.* TO 'otpapp'@'localhost'; FLUSH PRIVILEGES;"

git clone <repo-url> /opt/whatsappotp
cd /opt/whatsappotp/main-server
python3.10 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env  # set MYSQL_*, WHATSAPP_SERVICE_URL=http://<your-local-ip>:8001
```

Systemd unit (`/etc/systemd/system/whatsappotp.service`):
```ini
[Unit]
Description=WhatsApp OTP Main Server
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/opt/whatsappotp/main-server
EnvironmentFile=/opt/whatsappotp/main-server/.env
ExecStart=/opt/whatsappotp/main-server/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Nginx (`/etc/nginx/conf.d/whatsappotp.conf`):
```nginx
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

EC2 ↔ Local: Server 1 calls Server 2 over HTTP. Port 8001 on your local machine must be reachable from EC2 — use ngrok or router port-forwarding.

---

## Known Constraints

- **WhatsApp DOM changes** — selectors in `whatsapp.py` (`SEL_*` constants at the top) may break when WhatsApp updates its web client. Check those first if Playwright steps fail.
- **Personal account only** — do not use at scale; WhatsApp may flag automated usage.
- **No rate limiting** — add `slowapi` to `/api/send-otp` before public exposure.
- **Plain HTTP** — add Certbot/Let's Encrypt behind Nginx before production.
