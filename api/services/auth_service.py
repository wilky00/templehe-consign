# ABOUTME: Core authentication service — registration, login, 2FA, password management.
# ABOUTME: All business logic lives here; route handlers are thin wrappers that call these.
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt as _bcrypt
import jwt
import pyotp
import structlog
from cryptography.fernet import Fernet
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import AuditLog, KnownDevice, Role, TotpRecoveryCode, User
from services import email_service, legal_service, session_service

logger = structlog.get_logger(__name__)


async def _send_or_await(background_tasks: BackgroundTasks | None, func, *args) -> None:
    """Schedule email via BackgroundTasks when called from an HTTP route,
    or await inline otherwise (tests, scripts). Either way, failures in
    email_service are already logged and swallowed there."""
    if background_tasks is not None:
        background_tasks.add_task(func, *args)
    else:
        await func(*args)


_BCRYPT_ROUNDS = 12

_TYPE_ACCESS = "access"
_TYPE_PARTIAL = "partial"
_TYPE_VERIFY_EMAIL = "verify_email"
_TYPE_RESET_PASSWORD = "reset_password"
_TYPE_CHANGE_EMAIL = "change_email"


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, email: str, role: str) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "email": email, "role": role, "type": _TYPE_ACCESS, "exp": exp},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_partial_token(user_id: uuid.UUID) -> str:
    """Short-lived token issued when password is correct but 2FA is still pending."""
    exp = datetime.now(UTC) + timedelta(minutes=5)
    return jwt.encode(
        {"sub": str(user_id), "type": _TYPE_PARTIAL, "exp": exp},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _create_signed_token(payload: dict, expiry: timedelta) -> str:
    payload["exp"] = datetime.now(UTC) + expiry
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise jwt.InvalidTokenError("invalid token") from exc
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# ---------------------------------------------------------------------------
# TOTP / Fernet helpers
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    return Fernet(settings.totp_encryption_key.encode())


def _encrypt_totp_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def _decrypt_totp_secret(enc: str) -> str:
    return _fernet().decrypt(enc.encode()).decode()


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Audit log helper
# ---------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    event_type: str,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    target_id: uuid.UUID | None = None,
    target_type: str | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.add(
        AuditLog(
            event_type=event_type,
            actor_id=actor_id,
            actor_role=actor_role,
            target_id=target_id,
            target_type=target_type,
            after_state=after_state,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Device fingerprinting
# ---------------------------------------------------------------------------


def _device_fingerprint(user_agent: str | None, ip_address: str | None) -> str:
    ua_family = (user_agent or "unknown")[:50]
    ip_prefix = ".".join((ip_address or "0.0.0.0").split(".")[:3])
    return hashlib.sha256(f"{ua_family}:{ip_prefix}".encode()).hexdigest()


async def _check_new_device(
    user: User,
    ip_address: str | None,
    user_agent: str | None,
    db: AsyncSession,
) -> bool:
    """Record the device atomically and return whether it was newly seen.

    Uses INSERT ... ON CONFLICT DO NOTHING on the (user_id, device_fingerprint)
    unique constraint to avoid a SELECT-then-INSERT race: two concurrent first
    logins from the same browser would otherwise both pass the SELECT and the
    second INSERT would 500 the request.
    """
    fp = _device_fingerprint(user_agent, ip_address)
    stmt = (
        pg_insert(KnownDevice)
        .values(user_id=user.id, device_fingerprint=fp)
        .on_conflict_do_nothing(index_elements=["user_id", "device_fingerprint"])
        .returning(KnownDevice.id)
    )
    result = await db.execute(stmt)
    inserted = result.scalar_one_or_none()
    return inserted is not None


async def _get_role_slug(user: User, db: AsyncSession) -> str:
    result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = result.scalar_one_or_none()
    return role.slug if role else "customer"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def register_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    tos_version: str,
    privacy_version: str,
    db: AsyncSession,
    base_url: str = "",
    background_tasks: BackgroundTasks | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    existing = await db.execute(select(User).where(User.email == email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    # Reject sign-ups against stale versions so the version bump → re-accept
    # flow actually protects new account creation too. The client must read
    # the current versions (GET /legal/tos, /legal/privacy or app_config via
    # the sign-up page) and echo them back.
    current_tos, current_privacy = await legal_service.get_current_versions(db)
    if tos_version != current_tos or privacy_version != current_privacy:
        raise HTTPException(
            status_code=409,
            detail="Terms have been updated. Please refresh and review the latest versions.",
        )

    role_result = await db.execute(select(Role).where(Role.slug == "customer"))
    role = role_result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=500, detail="Role configuration error. Contact support.")

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role_id=role.id,
        status="pending_verification",
    )
    db.add(user)
    await db.flush()

    await legal_service.record_acceptance(
        db=db,
        user=user,
        tos_version=current_tos,
        privacy_version=current_privacy,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    token = _create_signed_token(
        {"sub": str(user.id), "type": _TYPE_VERIFY_EMAIL},
        timedelta(hours=24),
    )
    await _send_or_await(
        background_tasks,
        email_service.send_verification_email,
        user.email,
        f"{base_url}/auth/verify-email?token={token}",
    )
    await _audit(db, "user.registered", actor_id=user.id, target_id=user.id, target_type="user")
    return user


async def verify_email(token: str, db: AsyncSession) -> User:
    try:
        payload = _decode_token(token, _TYPE_VERIFY_EMAIL)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=400, detail="Verification link is invalid or has expired."
        ) from exc

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status != "pending_verification":
        raise HTTPException(status_code=400, detail="Verification link is invalid or has expired.")

    user.status = "active"
    db.add(user)
    await _audit(db, "user.email_verified", actor_id=user.id, target_id=user.id, target_type="user")
    return user


async def resend_verification(
    email: str,
    db: AsyncSession,
    base_url: str = "",
    background_tasks: BackgroundTasks | None = None,
) -> None:
    """Always returns without error — never reveals whether an account exists."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or user.status != "pending_verification":
        return
    token = _create_signed_token(
        {"sub": str(user.id), "type": _TYPE_VERIFY_EMAIL},
        timedelta(hours=24),
    )
    await _send_or_await(
        background_tasks,
        email_service.send_verification_email,
        user.email,
        f"{base_url}/auth/verify-email?token={token}",
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def login(
    email: str,
    password: str,
    db: AsyncSession,
    ip_address: str | None = None,
    user_agent: str | None = None,
    base_url: str = "",
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    """
    Returns one of:
      {"access_token": ..., "refresh_token": ...}  — full session
      {"requires_2fa": True, "partial_token": ...}  — 2FA pending
    """
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    now = datetime.now(UTC)

    async def _record_failed_attempt() -> None:
        if user is None:
            return
        user.failed_login_count = (user.failed_login_count or 0) + 1
        await _audit(
            db,
            "user.login_failed",
            actor_id=user.id,
            target_id=user.id,
            target_type="user",
            ip_address=ip_address,
        )
        if user.failed_login_count >= 5:
            user.locked_until = now + timedelta(minutes=30)
            user.failed_login_count = 0
            await _audit(
                db,
                "user.account_locked",
                actor_id=user.id,
                target_id=user.id,
                target_type="user",
                ip_address=ip_address,
            )
        db.add(user)
        await db.flush()

    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    if user.locked_until and user.locked_until > now:
        raise HTTPException(
            status_code=423,
            detail=(
                "This account has been temporarily locked due to repeated failed login attempts. "
                "Try again in 30 minutes or reset your password."
            ),
        )

    # Short-circuit on non-active status BEFORE touching the failed-login counter,
    # so a pending-verification account cannot be brute-forced into the 5-strike
    # lockout state and left unrecoverable.
    if user.status == "pending_verification":
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before logging in.",
        )
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Your account is not active. Contact support.")

    if not user.password_hash or not verify_password(password, user.password_hash):
        await _record_failed_attempt()
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    user.failed_login_count = 0
    user.locked_until = None
    db.add(user)

    role_slug = await _get_role_slug(user, db)

    is_new_device = await _check_new_device(user, ip_address, user_agent, db)
    if is_new_device:
        await _send_or_await(
            background_tasks,
            email_service.send_new_device_email,
            user.email,
            ip_address or "unknown location",
            (user_agent or "unknown device")[:80],
        )

    await _audit(
        db,
        "user.login",
        actor_id=user.id,
        actor_role=role_slug,
        target_id=user.id,
        target_type="user",
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if user.totp_enabled:
        return {"requires_2fa": True, "partial_token": create_partial_token(user.id)}

    access_token = create_access_token(user.id, user.email, role_slug)
    refresh_token = await session_service.issue_refresh_token(
        user.id, db, ip_address=ip_address, user_agent=user_agent
    )
    return {"access_token": access_token, "refresh_token": refresh_token}


# ---------------------------------------------------------------------------
# Token refresh / logout
# ---------------------------------------------------------------------------


async def refresh_access_token(
    raw_refresh_token: str,
    db: AsyncSession,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    result = await session_service.validate_and_rotate(
        raw_refresh_token, db, ip_address=ip_address, user_agent=user_agent
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired.")

    user_id, new_refresh_token = result
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Session is no longer valid.")

    role_slug = await _get_role_slug(user, db)
    access_token = create_access_token(user.id, user.email, role_slug)
    return {"access_token": access_token, "refresh_token": new_refresh_token}


async def logout(raw_refresh_token: str, db: AsyncSession) -> None:
    await session_service.revoke_token(raw_refresh_token, db)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


async def request_password_reset(
    email: str,
    db: AsyncSession,
    base_url: str = "",
    background_tasks: BackgroundTasks | None = None,
) -> None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    # Allow pending-verification accounts to reset so a user who lost the
    # verification email can still recover via password reset (the token
    # proves email ownership; confirm_password_reset transitions them to
    # active below).
    if user is None or user.status not in ("active", "locked", "pending_verification"):
        return
    token = _create_signed_token(
        {"sub": str(user.id), "type": _TYPE_RESET_PASSWORD},
        timedelta(minutes=30),
    )
    await _send_or_await(
        background_tasks,
        email_service.send_password_reset_email,
        user.email,
        f"{base_url}/auth/reset-password?token={token}",
    )
    await _audit(
        db,
        "user.password_reset_requested",
        actor_id=user.id,
        target_id=user.id,
        target_type="user",
    )


async def confirm_password_reset(
    token: str,
    new_password: str,
    db: AsyncSession,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    try:
        payload = _decode_token(token, _TYPE_RESET_PASSWORD)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=400, detail="Password reset link is invalid or has expired."
        ) from exc

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=400, detail="Password reset link is invalid or has expired."
        )

    user.password_hash = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    # Successful token confirmation proves email ownership — transition
    # both locked and pending_verification accounts to active.
    if user.status in ("locked", "pending_verification"):
        user.status = "active"
    db.add(user)

    await session_service.revoke_all_for_user(user.id, db)
    await _send_or_await(
        background_tasks,
        email_service.send_password_changed_email,
        user.email,
    )
    await _audit(
        db,
        "user.password_reset_confirmed",
        actor_id=user.id,
        target_id=user.id,
        target_type="user",
    )


# ---------------------------------------------------------------------------
# Email change
# ---------------------------------------------------------------------------


async def initiate_email_change(
    user_id: uuid.UUID,
    new_email: str,
    current_password: str,
    db: AsyncSession,
    base_url: str = "",
    background_tasks: BackgroundTasks | None = None,
) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if not user.password_hash or not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")

    existing = await db.execute(select(User).where(User.email == new_email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="This email address is already in use.")

    token = _create_signed_token(
        {"sub": str(user_id), "new_email": new_email.lower(), "type": _TYPE_CHANGE_EMAIL},
        timedelta(hours=1),
    )
    confirm_url = f"{base_url}/auth/change-email/confirm?token={token}"
    await _send_or_await(
        background_tasks,
        email_service.send_email_change_verification,
        new_email,
        confirm_url,
    )
    await _send_or_await(
        background_tasks,
        email_service.send_email_change_notification,
        user.email,
        new_email,
    )
    await _audit(
        db,
        "user.email_change_requested",
        actor_id=user_id,
        target_id=user_id,
        target_type="user",
    )


async def confirm_email_change(token: str, db: AsyncSession) -> None:
    try:
        payload = _decode_token(token, _TYPE_CHANGE_EMAIL)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=400, detail="Email change link is invalid or has expired."
        ) from exc

    user_id = uuid.UUID(payload["sub"])
    new_email: str = payload.get("new_email", "")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not new_email:
        raise HTTPException(status_code=400, detail="Email change link is invalid or has expired.")

    taken = await db.execute(select(User).where(User.email == new_email))
    if taken.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="This email address is already in use.")

    user.email = new_email
    db.add(user)
    # Changing the email on an account is an identity shift — all outstanding
    # sessions (browsers, mobile) must be invalidated so they re-authenticate
    # under the new identity.
    await session_service.revoke_all_for_user(user_id, db)
    await _audit(
        db,
        "user.email_changed",
        actor_id=user_id,
        target_id=user_id,
        target_type="user",
        after_state={"new_email": new_email},
    )


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------


async def setup_2fa(user_id: uuid.UUID, db: AsyncSession) -> dict:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="Two-factor authentication is already enabled.")

    secret = pyotp.random_base32()
    qr_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="TempleHE")
    user.totp_secret_enc = _encrypt_totp_secret(secret)
    db.add(user)
    await db.flush()
    await _audit(
        db, "user.2fa_setup_initiated", actor_id=user_id, target_id=user_id, target_type="user"
    )
    return {"secret": secret, "qr_uri": qr_uri}


async def confirm_2fa(
    user_id: uuid.UUID, totp_code: str, password: str, db: AsyncSession
) -> list[str]:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.totp_secret_enc:
        raise HTTPException(status_code=400, detail="2FA setup has not been initiated.")

    if not user.password_hash or not verify_password(password, user.password_hash):
        await _audit(
            db,
            "user.2fa_reauth_failed",
            actor_id=user_id,
            target_id=user_id,
            target_type="user",
        )
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    secret = _decrypt_totp_secret(user.totp_secret_enc)
    if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    user.totp_enabled = True
    db.add(user)

    raw_codes = [secrets.token_hex(8).upper() for _ in range(10)]
    await db.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id))
    for code in raw_codes:
        db.add(TotpRecoveryCode(user_id=user_id, code_hash=_hash_recovery_code(code)))

    await _audit(db, "user.2fa_enabled", actor_id=user_id, target_id=user_id, target_type="user")
    return raw_codes


async def verify_2fa(partial_token: str, totp_code: str, db: AsyncSession) -> dict:
    try:
        payload = _decode_token(partial_token, _TYPE_PARTIAL)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401, detail="Session expired. Please log in again."
        ) from exc

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.totp_enabled or not user.totp_secret_enc:
        raise HTTPException(status_code=401, detail="Invalid 2FA state.")

    secret = _decrypt_totp_secret(user.totp_secret_enc)
    if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    return await _complete_2fa_login(user, db)


async def recover_2fa(
    partial_token: str,
    recovery_code: str,
    db: AsyncSession,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    try:
        payload = _decode_token(partial_token, _TYPE_PARTIAL)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401, detail="Session expired. Please log in again."
        ) from exc

    user_id = uuid.UUID(payload["sub"])
    code_hash = _hash_recovery_code(recovery_code.strip().upper())
    result = await db.execute(
        select(TotpRecoveryCode).where(
            TotpRecoveryCode.user_id == user_id,
            TotpRecoveryCode.code_hash == code_hash,
            TotpRecoveryCode.used_at.is_(None),
        )
    )
    recovery = result.scalar_one_or_none()
    if recovery is None:
        raise HTTPException(status_code=400, detail="Invalid or already-used recovery code.")

    recovery.used_at = datetime.now(UTC)
    db.add(recovery)

    remaining_result = await db.execute(
        select(TotpRecoveryCode).where(
            TotpRecoveryCode.user_id == user_id,
            TotpRecoveryCode.used_at.is_(None),
        )
    )
    remaining = len(remaining_result.scalars().all())
    if remaining <= 3:
        user_result = await db.execute(select(User).where(User.id == user_id))
        u = user_result.scalar_one_or_none()
        if u:
            await _send_or_await(
                background_tasks,
                email_service.send_2fa_warning_email,
                u.email,
                remaining,
            )

    await _audit(
        db,
        "user.2fa_recovery_used",
        actor_id=user_id,
        target_id=user_id,
        target_type="user",
    )
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found.")
    return await _complete_2fa_login(user, db)


async def _complete_2fa_login(user: User, db: AsyncSession) -> dict:
    role_slug = await _get_role_slug(user, db)
    access_token = create_access_token(user.id, user.email, role_slug)
    refresh_token = await session_service.issue_refresh_token(user.id, db)
    return {"access_token": access_token, "refresh_token": refresh_token}


async def disable_2fa(user_id: uuid.UUID, totp_code: str, password: str, db: AsyncSession) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.totp_enabled or not user.totp_secret_enc:
        raise HTTPException(status_code=400, detail="Two-factor authentication is not enabled.")

    if not user.password_hash or not verify_password(password, user.password_hash):
        await _audit(
            db,
            "user.2fa_reauth_failed",
            actor_id=user_id,
            target_id=user_id,
            target_type="user",
        )
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    secret = _decrypt_totp_secret(user.totp_secret_enc)
    if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    user.totp_enabled = False
    user.totp_secret_enc = None
    db.add(user)
    await db.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id))
    await _audit(
        db,
        "user.2fa_disabled",
        actor_id=user_id,
        target_id=user_id,
        target_type="user",
    )
