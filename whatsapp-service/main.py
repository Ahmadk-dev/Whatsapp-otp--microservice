import asyncio
import re
import sys
from contextlib import asynccontextmanager

# Playwright requires ProactorEventLoop on Windows to spawn subprocesses.
# This must be set before uvicorn starts the event loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from whatsapp import WhatsAppError, WhatsAppSender


E164 = re.compile(r"^\+[1-9]\d{6,14}$")


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


@app.post("/send-whatsapp")
async def send_whatsapp(body: SendRequest, request: Request):
    sender: WhatsAppSender = request.app.state.sender
    message = f"Your verification code is {body.code}. It expires in 5 minutes."
    try:
        await sender.send(body.phone, message)
    except WhatsAppError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}
