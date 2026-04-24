# WhatsApp OTP — Project Reference

## What this is

A two-server OTP system. The user enters a phone number on a web page, a 6-digit OTP is generated and queued by the main server, then picked up and sent via WhatsApp Web (Playwright) by a standalone microservice running locally. The user then enters the OTP on a second page and the main server verifies it against the DB.

No Twilio. No Meta API. WhatsApp is automated via Playwright using a personal WhatsApp account.

---

## Architecture Overview

```
Browser (Page 1 — phone input)
      ↓  POST /api/send-otp
Server 1 — Main Server (FastAPI, runs on AWS EC2)
  - Generates 6-digit OTP
  - Stores bcrypt hash in MySQL (otp_codes table)
  - Inserts a job into MySQL (otp_jobs table) with status: pending
      ↓  POST /send-whatsapp (HTTP call)
Server 2 — WhatsApp Microservice (FastAPI + Playwright, runs locally)
  - Receives phone + OTP
  - Opens WhatsApp Web via Playwright
  - Starts a new chat with the phone number
  - Sends the OTP message
  - Returns { "ok": true } to Server 1
      ↑  Server 1 marks job as sent in DB
Browser (Page 2 — OTP input)
      ↓  POST /api/verify-otp
Server 1
  - Checks OTP matches phone, not expired, not used
  - Returns verified or error
```

---

## Project Layout

```
.
├── main-server/                  # Server 1 — runs on AWS EC2
│   ├── app/
│   │   ├── config.py             # pydantic-settings — reads all env vars
│   │   ├── db.py                 # SQLAlchemy engine, SessionLocal, get_db
│   │   ├── main.py               # FastAPI app, API routes, static mount
│   │   ├── models.py             # OtpCode + OtpJob ORM models
│   │   ├── otp.py                # generate / hash / verify OTP, DB read-write
│   │   ├── schemas.py            # Pydantic request/response shapes, E.164 validation
│   │   └── whatsapp_client.py    # HTTP client that calls Server 2
│   ├── static/
│   │   ├── index.html            # Page 1 — phone number input + "Receive OTP" button
│   │   ├── verify.html           # Page 2 — OTP code input + verify button
│   │   ├── app.js                # Vanilla JS, fetch calls, page state
│   │   └── style.css             # Dark WhatsApp-style theme
│   ├── .env                      # NOT committed — see variables below
│   ├── .env.example
│   ├── requirements.txt
│   └── CLAUDE.md                 # This file
│
└── whatsapp-service/             # Server 2 — runs locally on dev machine
    ├── main.py                   # FastAPI app — POST /send-whatsapp endpoint
    ├── whatsapp.py               # Playwright logic — open WA Web, send message
    ├── session/                  # Saved Playwright browser session (gitignored)
    ├── test_send.py              # Standalone test script — no Server 1 needed
    ├── .env
    ├── .env.example
    └── requirements.txt
```

---

## Environment Variables

### main-server/.env

| Variable | Example | Notes |
|---|---|---|
| `MYSQL_HOST` | `127.0.0.1` | Change to RDS endpoint on AWS |
| `MYSQL_PORT` | `3306` | |
| `MYSQL_USER` | `root` | **Use a dedicated user in production** |
| `MYSQL_PASSWORD` | `ahmad` | **Replace with strong password in production** |
| `MYSQL_DB` | `whatsappotp` | Database must exist before first run |
| `OTP_TTL_SECONDS` | `300` | How long a code is valid (default 5 min) |
| `OTP_MAX_ATTEMPTS` | `5` | Wrong-code attempts before code is invalidated |
| `WHATSAPP_SERVICE_URL` | `http://localhost:8001` | URL of Server 2 |
| `RESET_ON_STARTUP` | `false` | Set to `true` in local dev to wipe DB on restart |

### whatsapp-service/.env

| Variable | Example | Notes |
|---|---|---|
| `PORT` | `8001` | Port Server 2 listens on |
| `SESSION_DIR` | `./session` | Where Playwright saves the WhatsApp login session |
| `MAIN_SERVER_URL` | `http://localhost:8000` | URL of Server 1 (for callbacks if needed) |

---

## Database

- Engine: **MySQL** (SQLAlchemy + PyMySQL driver)
- DB name: `whatsappotp`
- Local connection: root / ahmad (dev only — replace in production)
- Tables auto-created by SQLAlchemy on startup via `Base.metadata.create_all()`

### Table: `otp_codes`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | auto-increment |
| `phone` | VARCHAR(32) | E.164, indexed |
| `code_hash` | VARCHAR(128) | bcrypt hash — plain code never stored |
| `expires_at` | DATETIME | UTC |
| `attempts` | INT | incremented on each wrong guess |
| `verified_at` | DATETIME NULL | set on successful verify |
| `created_at` | DATETIME | server default NOW() |

### Table: `otp_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | auto-increment |
| `phone` | VARCHAR(32) | recipient phone number |
| `code` | VARCHAR(6) | plain OTP (sent to WA service, not stored long-term) |
| `status` | ENUM | `pending` / `sent` / `failed` |
| `created_at` | DATETIME | server default NOW() |
| `updated_at` | DATETIME | updated when status changes |

---

## API Endpoints

### Server 1 (main-server) — port 8000

#### `POST /api/send-otp`
```json
{ "phone": "+96181926481" }
```
- Invalidates any live OTP for that phone
- Generates a new 6-digit OTP, stores bcrypt hash in `otp_codes`
- Inserts a job in `otp_jobs` with status `pending`
- Calls Server 2 `POST /send-whatsapp` with phone + plain OTP
- Marks job as `sent` or `failed` based on Server 2 response
- Returns `{ "ok": true, "expires_in": 300 }` or HTTP 502 on failure

#### `POST /api/verify-otp`
```json
{ "phone": "+96181926481", "code": "057529" }
```
- Looks up latest unverified, non-expired row in `otp_codes`
- Returns `{ "verified": true }` or HTTP 400 with `detail` = `"invalid"` / `"expired"` / `"too_many_attempts"`

#### `GET /`
Serves `static/index.html` (Page 1 — phone input)

#### `GET /verify`
Serves `static/verify.html` (Page 2 — OTP input)

---

### Server 2 (whatsapp-service) — port 8001

#### `POST /send-whatsapp`
```json
{ "phone": "+96181926481", "code": "057529" }
```
- Opens WhatsApp Web via Playwright using saved session
- Navigates to a new chat with the given phone number
- Sends the OTP message
- Returns `{ "ok": true }` or HTTP 500 on failure

#### `GET /health`
Returns `{ "status": "ok" }` — used by Server 1 to check if Server 2 is reachable

---

## Running Locally

### Server 2 first (WhatsApp microservice)
```bash
cd whatsapp-service
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # Windows
# source venv/bin/activate && pip install -r requirements.txt  # Linux/Mac

playwright install chromium

cp .env.example .env
venv/Scripts/uvicorn main:app --port 8001 --reload
```
- First run: a browser window opens with WhatsApp Web — scan the QR code once
- Session is saved to `./session` — QR not needed again after that
- Test independently using `python test_send.py` before connecting to Server 1

### Server 1 (main server)
```bash
cd main-server
python -m venv venv
venv/Scripts/pip install -r requirements.txt

mysql -uroot -pahmad -e "CREATE DATABASE IF NOT EXISTS whatsappotp CHARACTER SET utf8mb4;"

cp .env.example .env
venv/Scripts/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/

---

## Deploying on AWS

Server 1 runs on EC2. Server 2 runs locally (Playwright requires a display/browser — not suited for headless EC2 on free tier without extra setup).

### EC2 Setup (Server 1 only)

- **Instance**: Amazon Linux 2023 or Ubuntu 22.04, t2.micro (free tier)
- **Ports open**: 22 (SSH), 80 (HTTP), 443 (HTTPS optional)
- **MySQL**: Install on EC2 or use RDS free tier (db.t3.micro)

```bash
sudo dnf update -y
sudo dnf install python3.10 python3.10-pip git nginx -y

# MySQL on same instance (skip if using RDS)
sudo dnf install mysql-server -y
sudo systemctl enable --now mysqld
sudo mysql -e "CREATE DATABASE whatsappotp CHARACTER SET utf8mb4;"
sudo mysql -e "CREATE USER 'otpapp'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';"
sudo mysql -e "GRANT SELECT,INSERT,UPDATE,DELETE ON whatsappotp.* TO 'otpapp'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"
```

### Deploy Server 1
```bash
git clone <repo-url> /opt/whatsappotp
cd /opt/whatsappotp/main-server
python3.10 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env   # fill in DB credentials + WHATSAPP_SERVICE_URL (your local machine's IP)
```

`.env` on EC2:
- `MYSQL_USER` / `MYSQL_PASSWORD` = dedicated DB user (NOT root)
- `WHATSAPP_SERVICE_URL` = `http://<YOUR_LOCAL_IP>:8001` (your machine running Server 2)
- `RESET_ON_STARTUP` = `false`

### Systemd Service
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

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now whatsappotp
```

### Nginx Reverse Proxy
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

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Known Constraints / Gotchas

- **WhatsApp Web automation**: Playwright controls a real browser session tied to your personal WhatsApp account. WhatsApp may occasionally show a "linked devices" warning — this is normal. Do not use at scale.
- **Server 2 is local**: Playwright needs a real browser with a display. Running it on a headless EC2 free tier requires Xvfb (virtual display) — avoid for now, keep it local.
- **Session persistence**: The Playwright session is saved in `whatsapp-service/session/`. If WhatsApp logs out, delete the session folder and re-scan the QR code.
- **OTP table wipe on startup**: Controlled by `RESET_ON_STARTUP` env var. `true` in local dev, `false` in production.
- **No rate limiting**: Add `slowapi` to `/api/send-otp` before exposing to public internet.
- **Plain HTTP**: Add Certbot/Let's Encrypt behind Nginx for HTTPS before going to production.
- **EC2 ↔ Local communication**: Server 1 (EC2) calls Server 2 (your machine) over HTTP. Make sure your local machine's port 8001 is reachable from EC2 — either via port forwarding on your router or a tunneling tool like ngrok.