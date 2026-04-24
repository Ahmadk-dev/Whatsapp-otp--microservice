from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_db
from app.models import OtpCode, OtpJob
from app.otp import CooldownError, OtpError, check_otp, create_otp
from app.schemas import SendOtpRequest, SendOtpResponse, VerifyOtpRequest, VerifyOtpResponse
from app.whatsapp_client import WhatsAppServiceError, send_otp as wa_send

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app import models  # noqa: F401 — register models before create_all
    Base.metadata.create_all(bind=engine)
    if settings.RESET_ON_STARTUP:
        with engine.begin() as conn:
            conn.execute(OtpJob.__table__.delete())
            conn.execute(OtpCode.__table__.delete())
    yield


app = FastAPI(title="WhatsApp OTP", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/verify", include_in_schema=False)
async def verify_page():
    return FileResponse(STATIC_DIR / "verify.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.post("/api/send-otp", response_model=SendOtpResponse)
async def send_otp_endpoint(body: SendOtpRequest, db: Session = Depends(get_db)):
    try:
        code = create_otp(db, body.phone)
    except CooldownError as e:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {e.retry_after} seconds before requesting a new code.",
        )

    job = OtpJob(phone=body.phone, code=code, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        await wa_send(body.phone, code)
        job.status = "sent"
    except WhatsAppServiceError as e:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))

    db.commit()
    return SendOtpResponse(ok=True, expires_in=settings.OTP_TTL_SECONDS)


@app.post("/api/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp_endpoint(body: VerifyOtpRequest, db: Session = Depends(get_db)):
    try:
        check_otp(db, body.phone, body.code)
    except OtpError as e:
        raise HTTPException(status_code=400, detail=e.reason)
    return VerifyOtpResponse(verified=True)
