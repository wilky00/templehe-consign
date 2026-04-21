# ABOUTME: Pydantic request/response schemas for all auth endpoints.
# ABOUTME: Password complexity is validated here so it never reaches the service layer unchecked.
from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, EmailStr, field_validator

_PASSWORD_RE = re.compile(
    r"^(?=.*[A-Z])(?=.*[0-9])(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{12,}$"
)


def _validate_password(value: str) -> str:
    if not _PASSWORD_RE.match(value):
        raise ValueError(
            "Password must be at least 12 characters and include an uppercase letter, "
            "a number, and a special character."
        )
    return value


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("first_name", "last_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field is required.")
        return v


class RegisterResponse(BaseModel):
    id: uuid.UUID
    email: str
    message: str


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class MessageResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Partial2FAResponse(BaseModel):
    requires_2fa: bool = True
    partial_token: str


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


class PasswordResetRequestBody(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return _validate_password(v)


# ---------------------------------------------------------------------------
# Email change
# ---------------------------------------------------------------------------


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    current_password: str


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------


class TwoFASetupResponse(BaseModel):
    secret: str
    qr_uri: str
    message: str


class TwoFAConfirmRequest(BaseModel):
    totp_code: str


class TwoFAConfirmResponse(BaseModel):
    recovery_codes: list[str]
    message: str


class TwoFAVerifyRequest(BaseModel):
    partial_token: str
    totp_code: str


class TwoFARecoveryRequest(BaseModel):
    partial_token: str
    recovery_code: str


class TwoFADisableRequest(BaseModel):
    totp_code: str


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------


class CurrentUser(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    first_name: str
    last_name: str
    totp_enabled: bool
