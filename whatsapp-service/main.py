import asyncio
import re
import sys
from contextlib import asynccontextmanager

# Playwright requires ProactorEventLoop on Windows to spawn subprocesses.
# This must be set before uvicorn starts the event loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from whatsapp import WhatsAppError, WhatsAppSender


E164 = re.compile(r"^\+[1-9]\d{6,14}$")

SETUP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WhatsApp Setup</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,sans-serif;background:#111b21;color:#e9edef;
         display:flex;align-items:center;justify-content:center;min-height:100vh}
    .card{background:#202c33;border-radius:12px;padding:2rem;width:100%;max-width:440px}
    h1{font-size:1.4rem;margin-bottom:.4rem}
    .sub{color:#8696a0;font-size:.9rem;margin-bottom:1.5rem}
    label{display:block;font-size:.85rem;color:#8696a0;margin-bottom:.4rem}
    input{width:100%;padding:.7rem 1rem;border-radius:8px;border:1px solid #2a3942;
          background:#2a3942;color:#e9edef;font-size:1rem;margin-bottom:1rem}
    input:focus{outline:2px solid #00a884;border-color:transparent}
    .btn{width:100%;padding:.75rem;border:none;border-radius:8px;background:#00a884;
         color:#fff;font-size:1rem;cursor:pointer}
    .btn:disabled{opacity:.5;cursor:not-allowed}
    .status{margin-top:1rem;font-size:.9rem;min-height:1.2rem}
    .ok{color:#00a884}.err{color:#f15c6d}
    .code-box{margin-top:1.2rem;background:#2a3942;border-radius:8px;padding:1.2rem;text-align:center}
    .code-label{font-size:.8rem;color:#8696a0;margin-bottom:.5rem}
    .code{font-size:2.2rem;font-weight:700;letter-spacing:.25rem;color:#00a884}
    .code-hint{font-size:.8rem;color:#8696a0;margin-top:.6rem;line-height:1.4}
    .success{text-align:center}
    .check{font-size:3.5rem;color:#00a884;margin-bottom:.8rem}
    .already{text-align:center;color:#00a884;font-size:1.1rem}
  </style>
</head>
<body>
<div class="card">
  <h1>WhatsApp Setup</h1>
  <p class="sub">Link your WhatsApp account to this service.</p>

  <div id="already-section" hidden>
    <div class="already">&#10003;&nbsp; Already linked — service is ready.</div>
  </div>

  <div id="setup-section">
    <label for="phone">Your WhatsApp number (E.164)</label>
    <input id="phone" type="tel" placeholder="+15551234567" autocomplete="tel" />
    <button id="start-btn" class="btn" type="button">Link Account</button>
    <p id="status" class="status"></p>
    <div id="code-box" class="code-box" hidden>
      <div class="code-label">Pairing code</div>
      <div id="code" class="code"></div>
      <div class="code-hint">
        Open <strong>WhatsApp</strong> on your phone &rarr;
        <strong>Settings &rarr; Linked Devices &rarr; Link a Device</strong>,
        then enter this code.
      </div>
    </div>
    <div id="browser-hint" class="code-box" hidden>
      <div class="code-label">Pairing code</div>
      <div class="code-hint">
        The code is visible in the <strong>browser window</strong> that opened.<br/>
        Open <strong>WhatsApp &rarr; Settings &rarr; Linked Devices &rarr; Link a Device</strong>
        and enter the code shown there.
      </div>
    </div>
  </div>

  <div id="success-section" class="success" hidden>
    <div class="check">&#10003;</div>
    <p>WhatsApp account linked successfully.</p>
    <p style="color:#8696a0;font-size:.85rem;margin-top:.6rem">
      You can close this window. The service is now ready.
    </p>
  </div>
</div>

<script>
const phoneEl     = document.getElementById('phone');
const startBtn    = document.getElementById('start-btn');
const statusEl    = document.getElementById('status');
const codeBox     = document.getElementById('code-box');
const browserHint = document.getElementById('browser-hint');
const codeEl      = document.getElementById('code');
const setupSec    = document.getElementById('setup-section');
const successSec  = document.getElementById('success-section');
const alreadySec  = document.getElementById('already-section');

function setStatus(msg, ok=false, err=false) {
  statusEl.textContent = msg;
  statusEl.className = 'status' + (ok?' ok':err?' err':'');
}

function showSuccess() {
  setupSec.hidden = true;
  successSec.hidden = false;
}

async function checkStatus() {
  const res = await fetch('/setup/status');
  const d = await res.json();
  return d.logged_in;
}

function startPolling() {
  const iv = setInterval(async () => {
    if (await checkStatus()) {
      clearInterval(iv);
      showSuccess();
    }
  }, 3000);
}

// On load — if already logged in, show "already linked"
checkStatus().then(loggedIn => {
  if (loggedIn) {
    setupSec.hidden = true;
    alreadySec.hidden = false;
  }
});

startBtn.addEventListener('click', async () => {
  const phone = phoneEl.value.trim();
  if (!phone) { setStatus('Enter your phone number.', false, true); return; }

  startBtn.disabled = true;
  setStatus('Opening WhatsApp Web…');

  try {
    const res = await fetch('/setup/start', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({phone}),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      setStatus(data.detail || 'Failed — check the terminal for details.', false, true);
      startBtn.disabled = false;
      return;
    }

    if (data.pairing_code) {
      codeEl.textContent = data.pairing_code;
      codeBox.hidden = false;
      setStatus('Enter the code above in your WhatsApp app, then wait…');
    } else {
      browserHint.hidden = false;
      setStatus('Enter the code from the browser window in your WhatsApp app, then wait…');
    }

    startPolling();
  } catch (e) {
    setStatus('Network error — is the service running?', false, true);
    startBtn.disabled = false;
  }
});
</script>
</body>
</html>"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PORT: int = 8001
    SESSION_DIR: str = "./session"
    MAIN_SERVER_URL: str = "http://localhost:8000"
    HEADLESS: bool = False
    LOGIN_TIMEOUT_SECONDS: int = 180
    SEND_TIMEOUT_SECONDS: int = 45


settings = Settings()


class SendRequest(BaseModel):
    phone: str = Field(..., description="E.164 phone number, e.g. +15551234567")
    code: str = Field(..., min_length=4, max_length=10)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip().replace(" ", "")
        if not E164.match(v):
            raise ValueError("phone must be in E.164 format, e.g. +15551234567")
        return v

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("code must be numeric")
        return v


class SetupRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip().replace(" ", "")
        if not E164.match(v):
            raise ValueError("phone must be in E.164 format, e.g. +15551234567")
        return v


@asynccontextmanager
async def lifespan(app: FastAPI):
    sender = WhatsAppSender(
        session_dir=settings.SESSION_DIR,
        headless=settings.HEADLESS,
        login_timeout_seconds=settings.LOGIN_TIMEOUT_SECONDS,
        send_timeout_seconds=settings.SEND_TIMEOUT_SECONDS,
    )
    await sender.start()
    app.state.sender = sender
    try:
        yield
    finally:
        await sender.stop()


app = FastAPI(title="WhatsApp Microservice", lifespan=lifespan)


@app.get("/health")
async def health(request: Request):
    sender: WhatsAppSender = request.app.state.sender
    return await sender.health()


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return SETUP_HTML


@app.get("/setup/status")
async def setup_status(request: Request):
    sender: WhatsAppSender = request.app.state.sender
    logged_in = await sender.is_logged_in()
    return {"logged_in": logged_in, "setup_needed": not logged_in}


@app.post("/setup/start")
async def setup_start(body: SetupRequest, request: Request):
    sender: WhatsAppSender = request.app.state.sender
    try:
        pairing_code = await sender.begin_phone_login(body.phone)
    except WhatsAppError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "pairing_code": pairing_code}


@app.post("/send-whatsapp")
async def send_whatsapp(body: SendRequest, request: Request):
    sender: WhatsAppSender = request.app.state.sender
    if not await sender.is_logged_in():
        raise HTTPException(
            status_code=503,
            detail="WhatsApp not linked. Open http://localhost:8001/setup to complete setup.",
        )
    message = f"Your verification code is {body.code}. It expires in 5 minutes."
    try:
        await sender.send(body.phone, message)
    except WhatsAppError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}
