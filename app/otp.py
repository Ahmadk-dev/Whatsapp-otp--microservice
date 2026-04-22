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
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_hash(code: str, code_hash: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))
    except ValueError:
        return False


class CooldownError(Exception):
    def __init__(self, retry_after: int):
        super().__init__("cooldown")
        self.retry_after = retry_after  # seconds until resend is allowed


def create_otp(db: Session, phone: str) -> str:
    """Invalidate any prior unverified codes for this phone, insert a new one, return the plain code.

    Raises CooldownError if a code was sent less than OTP_RESEND_COOLDOWN_SECONDS ago.
    """
    now = datetime.utcnow()

    recent = db.execute(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.verified_at.is_(None), OtpCode.expires_at > now)
        .order_by(OtpCode.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if recent is not None:
        age = (now - recent.created_at).total_seconds()
        wait = settings.OTP_RESEND_COOLDOWN_SECONDS - int(age)
        if wait > 0:
            raise CooldownError(retry_after=wait)

    db.execute(
        update(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.verified_at.is_(None), OtpCode.expires_at > now)
        .values(expires_at=now)
    )
    code = generate_code()
    row = OtpCode(
        phone=phone,
        code_hash=hash_code(code),
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    db.add(row)
    db.commit()
    return code


class OtpError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def check_otp(db: Session, phone: str, code: str) -> None:
    """Raise OtpError('invalid'|'expired'|'too_many_attempts') on failure. Returns None on success."""
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
