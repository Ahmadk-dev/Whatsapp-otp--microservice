import re

from pydantic import BaseModel, Field, field_validator

E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def _validate_phone(v: str) -> str:
    v = v.strip().replace(" ", "")
    if not E164.match(v):
        raise ValueError("phone must be in E.164 format, e.g. +15551234567")
    return v


class SendOtpRequest(BaseModel):
    phone: str = Field(..., description="E.164 phone number")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone(v)


class SendOtpResponse(BaseModel):
    ok: bool
    expires_in: int


class VerifyOtpRequest(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=10)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("code must be numeric")
        return v


class VerifyOtpResponse(BaseModel):
    verified: bool
