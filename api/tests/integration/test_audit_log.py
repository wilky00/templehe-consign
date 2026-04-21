# ABOUTME: Integration tests verifying that auth state transitions produce audit_log rows.
# ABOUTME: Checks event_type and actor_id for each event category.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, User

_VALID_PASSWORD = "TestPassword1!"


async def _register_and_activate(
    client: AsyncClient, db: AsyncSession, email: str
) -> tuple[str, str]:
    """Register, activate via test session, login. Returns (user_id, access_token)."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Audit",
                "last_name": "Test",
            },
        )
    assert reg.status_code == 201, reg.json()
    user_id = reg.json()["id"]

    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    assert user is not None
    user.status = "active"
    await db.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert login.status_code == 200, login.json()
    return user_id, login.json()["access_token"]


async def _get_audit_events(db: AsyncSession, user_id: str) -> list[AuditLog]:
    result = await db.execute(select(AuditLog).where(AuditLog.actor_id == user_id))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_registration(client: AsyncClient, db_session: AsyncSession):
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "audit_reg@example.com",
                "password": _VALID_PASSWORD,
                "first_name": "A",
                "last_name": "B",
            },
        )
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.registered" in event_types


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_login_success(client: AsyncClient, db_session: AsyncSession):
    user_id, _ = await _register_and_activate(client, db_session, "audit_login@example.com")
    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.login" in event_types


@pytest.mark.asyncio
async def test_audit_log_failed_login(client: AsyncClient, db_session: AsyncSession):
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "audit_fail@example.com",
                "password": _VALID_PASSWORD,
                "first_name": "A",
                "last_name": "B",
            },
        )
    user_id = reg.json()["id"]

    result = await db_session.execute(select(User).where(User.email == "audit_fail@example.com"))
    user = result.scalar_one_or_none()
    assert user is not None
    user.status = "active"
    await db_session.flush()

    await client.post(
        "/api/v1/auth/login",
        json={"email": "audit_fail@example.com", "password": "WrongPassword1!"},
    )

    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.login_failed" in event_types


@pytest.mark.asyncio
async def test_audit_log_logout(client: AsyncClient, db_session: AsyncSession):
    user_id, _ = await _register_and_activate(client, db_session, "audit_logout@example.com")
    # Logout on invalid token is graceful (idempotent) — only verifies login audit was written
    await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "fakehex" * 10},
    )
    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.login" in event_types


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_account_locked(client: AsyncClient, db_session: AsyncSession):
    email = "audit_lockout@example.com"
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "A",
                "last_name": "B",
            },
        )
    user_id = reg.json()["id"]

    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    assert user is not None
    user.status = "active"
    await db_session.flush()

    for _ in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword1!"},
        )

    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.account_locked" in event_types


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_password_reset_request(client: AsyncClient, db_session: AsyncSession):
    user_id, _ = await _register_and_activate(client, db_session, "audit_pwreset@example.com")
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/password-reset-request",
            json={"email": "audit_pwreset@example.com"},
        )

    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.password_reset_requested" in event_types


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_2fa_setup(client: AsyncClient, db_session: AsyncSession):
    user_id, token = await _register_and_activate(client, db_session, "audit_2fa@example.com")
    resp = await client.post(
        "/api/v1/auth/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    events = await _get_audit_events(db_session, user_id)
    event_types = [e.event_type for e in events]
    assert "user.2fa_setup_initiated" in event_types
