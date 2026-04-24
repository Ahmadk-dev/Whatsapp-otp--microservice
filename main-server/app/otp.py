import secrets
from datetime import datetime, timedelta

import bcrypt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OtpCode


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()


def verify_hash(code: str, code_hash: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode(), code_hash.encode())
    except ValueError:
        return False


class OtpError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CooldownError(Exception):
    def __init__(self, retry_after: int):
        super().__init__("cooldown")
        self.retry_after = retry_after


def create_otp(db: Session, phone: str) -> str:
    """Expire any live OTP for this phone, insert a new one, return plain code.

    Raises CooldownError if a code was sent within OTP_RESEND_COOLDOWN_SECONDS.
    """
    now = datetime.utcnow()

    recent = db.execute(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.verified_at.is_(None), OtpCode.expires_at > now)
        .order_by(OtpCode.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if recent is not None:
        age = int((now - recent.created_at).total_seconds())
        wait = settings.OTP_RESEND_COOLDOWN_SECONDS - age
        if wait > 0:
            raise CooldownError(retry_after=wait)

    db.execute(
        update(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.verified_at.is_(None), OtpCode.expires_at > now)
        .values(expires_at=now)
    )

    code = generate_code()
    db.add(OtpCode(
        phone=phone,
        code_hash=hash_code(code),
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
    ))
    db.commit()
    return code


def check_otp(db: Session, phone: str, code: str) -> None:
    """Raise OtpError on failure; return None on success."""
    now = datetime.utcnow()
    row = db.execute(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.verified_at.is_(None))
        .order_by(OtpCode.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        raise OtpError("invalid")
    if row.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OtpError("too_many_attempts")
    if row.expires_at <= now:
        raise OtpError("expired")

    row.attempts += 1
    if not verify_hash(code, row.code_hash):
        db.commit()
        raise OtpError("invalid")

    row.verified_at = now
    db.commit()
