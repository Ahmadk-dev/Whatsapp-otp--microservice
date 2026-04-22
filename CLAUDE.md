# WhatsApp OTP — Project Reference

## What this is

A minimal FastAPI web app that sends a 6-digit OTP to a phone number via WhatsApp (Twilio WhatsApp sandbox) and verifies the code the user types back. No user accounts, no sessions — purely stateless OTP send/verify.

---

## Project layout

```
.
├── app/
│   ├── config.py      # pydantic-settings — reads all env vars
│   ├── db.py          # SQLAlchemy engine, SessionLocal, get_db dependency
│   ├── main.py        # FastAPI app, two API routes, static file mount
│   ├── models.py      # OtpCode ORM model (single table)
│   ├── otp.py         # generate / hash / verify OTP, DB read-write
│   ├── schemas.py     # Pydantic request/response shapes, E.164 validation
│   └── whatsapp.py    # Twilio HTTP client (httpx, no Twilio SDK)
├── static/
│   ├── index.html     # Single-page UI — three states: phone / code / verified
│   ├── app.js         # Vanilla JS, fetch calls, state toggling
│   └── style.css      # Dark WhatsApp-style theme
├── .env               # NOT committed — see variables below
├── .env.example       # Committed template
├── requirements.txt
└── CLAUDE.md          # This file
```

---

## Environment variables

All settings live in `.env` (loaded by pydantic-settings at startup). `.env` is gitignored — create it on the server from the values below.

| Variable | Example | Notes |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | `ACb50c4d...` | From Twilio Console |
| `TWILIO_AUTH_TOKEN` | `61c707...` | From Twilio Console — treat as a secret |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` | Twilio sandbox number (include `whatsapp:` prefix) |
| `MYSQL_HOST` | `127.0.0.1` | Change to RDS endpoint on AWS |
| `MYSQL_PORT` | `3306` | |
| `MYSQL_USER` | `root` | **Use a dedicated least-privilege user in production** |
| `MYSQL_PASSWORD` | `ahmad` | **Replace with a strong password in production** |
| `MYSQL_DB` | `whatsappotp` | Database must exist before first run |
| `OTP_TTL_SECONDS` | `300` | How long a code is valid (default 5 min) |
| `OTP_MAX_ATTEMPTS` | `5` | Wrong-code attempts before code is invalidated |

---

## Database

- Engine: **MySQL** (SQLAlchemy + PyMySQL driver).
- Single table: `otp_codes` — auto-created by SQLAlchemy on startup via `Base.metadata.create_all()`.
- **On every startup, all rows are deleted** (`OtpCode.__table__.delete()` in the lifespan hook). This is intentional for development — remove or gate that line behind an env flag for production if persistence across restarts is needed.

Schema:

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | auto-increment |
| `phone` | VARCHAR(32) | E.164, indexed |
| `code_hash` | VARCHAR(128) | bcrypt hash — plain code is never stored |
| `expires_at` | DATETIME | UTC |
| `attempts` | INT | incremented on each wrong guess |
| `verified_at` | DATETIME NULL | set on successful verify |
| `created_at` | DATETIME | server default NOW() |

---

## API endpoints

### `POST /api/send-otp`
```json
{ "phone": "+96181926481" }
```
- Invalidates any live OTP for that phone, generates a new 6-digit code.
- Stores bcrypt hash in DB, sends plain code to user via Twilio WhatsApp.
- Returns `{ "ok": true, "expires_in": 300 }` or HTTP 502 on Twilio error.

### `POST /api/verify-otp`
```json
{ "phone": "+96181926481", "code": "057529" }
```
- Looks up the latest unverified, non-expired row.
- Returns `{ "verified": true }` or HTTP 400 with `detail` = `"invalid"` / `"expired"` / `"too_many_attempts"`.

### `GET /`
Serves `static/index.html`.

---

## Running locally

```bash
# 1. Create virtualenv and install deps
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # Windows
# source venv/bin/activate && pip install -r requirements.txt  # Linux/Mac

# 2. Create the database (table is auto-created by the app)
mysql -uroot -pahmad -e "CREATE DATABASE IF NOT EXISTS whatsappotp CHARACTER SET utf8mb4;"

# 3. Copy and fill env
cp .env.example .env
# edit .env with real Twilio credentials

# 4. Start
venv/Scripts/uvicorn app.main:app --reload        # Windows
# uvicorn app.main:app --reload --host 0.0.0.0    # expose on network
```

Open http://127.0.0.1:8000/

---

## Deploying on AWS — task for the deployment agent

The goal is to run this app on an **EC2 instance** with a **MySQL backend** (either on the same instance or RDS). Below is the full checklist.

### 1. Infrastructure to provision

- **EC2**: Amazon Linux 2023 or Ubuntu 22.04, at minimum `t3.micro`. Open inbound ports: **22** (SSH), **80** (HTTP), **443** (HTTPS if SSL is added).
- **MySQL**: Either install MySQL 8 on the EC2 instance, or use **RDS MySQL 8** (recommended for production). The DB name must be `whatsappotp`.
- **Security group**: EC2 must be able to reach the MySQL host on port 3306. If using RDS, the RDS security group must allow inbound 3306 from the EC2 security group.

### 2. Server setup (EC2)

```bash
# Update system
sudo dnf update -y   # Amazon Linux 2023
# or: sudo apt update && sudo apt upgrade -y   # Ubuntu

# Install Python 3.10+
sudo dnf install python3.10 python3.10-pip git -y

# If MySQL is on this instance (skip if using RDS)
sudo dnf install mysql-server -y
sudo systemctl enable --now mysqld
sudo mysql -e "CREATE DATABASE whatsappotp CHARACTER SET utf8mb4;"
sudo mysql -e "CREATE USER 'otpapp'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';"
sudo mysql -e "GRANT SELECT,INSERT,UPDATE,DELETE ON whatsappotp.* TO 'otpapp'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"
```

### 3. Deploy the app

```bash
# Clone or copy files to the server (no venv/, no .env)
git clone <repo-url> /opt/whatsappotp
cd /opt/whatsappotp

python3.10 -m venv venv
venv/bin/pip install -r requirements.txt

# Create .env — fill in real values
cp .env.example .env
nano .env
```

`.env` on EC2 must have:
- `MYSQL_HOST` = RDS endpoint or `127.0.0.1` if local
- `MYSQL_USER` / `MYSQL_PASSWORD` = dedicated DB user (NOT root)
- Real Twilio credentials

> ⚠️ Set `RESET_ON_STARTUP=false` in `.env` on the server. The default is `false` — rows are only wiped on startup when explicitly set to `true` (used in local dev).

### 4. Run as a systemd service

Create `/etc/systemd/system/whatsappotp.service`:

```ini
[Unit]
Description=WhatsApp OTP FastAPI app
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/opt/whatsappotp
EnvironmentFile=/opt/whatsappotp/.env
ExecStart=/opt/whatsappotp/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now whatsappotp
sudo systemctl status whatsappotp
```

### 5. Expose on port 80 (Nginx reverse proxy)

```bash
sudo dnf install nginx -y   # or apt install nginx
sudo systemctl enable --now nginx
```

`/etc/nginx/conf.d/whatsappotp.conf`:

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

### 6. Verify deployment

```bash
# From the EC2 instance
curl -s -X POST http://localhost:8000/api/send-otp \
  -H "Content-Type: application/json" \
  -d '{"phone": "+96181926481"}' | python3 -m json.tool

# From outside — replace with your EC2 public IP or domain
curl -s -X POST http://<EC2_PUBLIC_IP>/api/send-otp \
  -H "Content-Type: application/json" \
  -d '{"phone": "+96181926481"}' | python3 -m json.tool
```

Expected response: `{ "ok": true, "expires_in": 300 }`

---

## Known constraints / gotchas

- **Twilio sandbox**: Recipients must send a join code to the Twilio sandbox number before they can receive messages. This restriction is lifted when you upgrade to a paid Twilio WhatsApp number.
- **OTP table wipe on startup**: Controlled by `RESET_ON_STARTUP` env var. Set to `true` in local dev, `false` (default) in production.
- **No rate limiting**: The `/api/send-otp` endpoint has no per-IP or per-phone rate limit. Add `slowapi` if needed before exposing to the public internet.
- **Plain HTTP**: No TLS is configured. Add Certbot/Let's Encrypt behind Nginx for HTTPS before going to production.
- **Single-instance only**: OTP state is in MySQL, so multiple uvicorn workers or EC2 instances share state correctly — but the `table.delete()` on startup would wipe data if multiple instances restart at different times. Remove it for multi-instance setups.
