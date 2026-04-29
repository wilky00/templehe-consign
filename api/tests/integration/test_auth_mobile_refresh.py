# ABOUTME: Phase 5 Sprint 1 — `X-Client: ios` body-mode refresh-token transport.
# ABOUTME: Mobile clients can't reliably persist HttpOnly cookies; iOS Keychain stores tokens.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User

_VALID_PASSWORD = "TestPassword1!"


async def _registered_user(client: AsyncClient, db: AsyncSession, email: str) -> None:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Mob",
                "last_name": "Ile",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    user.status = "active"
    db.add(user)
    await db.flush()


def _email(slug: str) -> str:
    import uuid

    return f"{slug}-{uuid.uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mobile_login_returns_refresh_in_body_no_cookie(
    client: AsyncClient, db_session: AsyncSession
):
    email = _email("mob")
    await _registered_user(client, db_session, email)

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/login",
            headers={"X-Client": "ios"},
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]  # body carries the refresh token
    # Set-Cookie must NOT carry a refresh_token cookie for mobile.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token" not in set_cookie


@pytest.mark.asyncio
async def test_web_login_unchanged(client: AsyncClient, db_session: AsyncSession):
    """Default (no X-Client header) → cookie + body access_token only.

    Backwards-compat check: existing web SPA path is byte-identical."""
    email = _email("web")
    await _registered_user(client, db_session, email)

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    # Web response does NOT carry the refresh token in the body. Pydantic
    # serializes the unset Optional field as `null` — the absence of a
    # real value (truthiness) is what matters.
    assert not body.get("refresh_token")
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mobile_refresh_from_body_rotates_token(
    client: AsyncClient, db_session: AsyncSession
):
    email = _email("mob")
    await _registered_user(client, db_session, email)

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            headers={"X-Client": "ios"},
            json={"email": email, "password": _VALID_PASSWORD},
        )
    refresh_1 = login.json()["refresh_token"]

    refresh_resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Client": "ios"},
        json={"refresh_token": refresh_1},
    )
    assert refresh_resp.status_code == 200
    refresh_2 = refresh_resp.json()["refresh_token"]
    assert refresh_2
    # Token is rotated — the new one is different.
    assert refresh_1 != refresh_2
    # No Set-Cookie on mobile.
    assert "refresh_token" not in refresh_resp.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_mobile_refresh_without_body_401(client: AsyncClient, db_session: AsyncSession):
    """Mobile must supply the body; missing or blank → 401."""
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Client": "ios"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mobile_logout_invalidates_body_token(client: AsyncClient, db_session: AsyncSession):
    """After mobile logout, the refresh token used in the body is gone
    from user_sessions — a follow-up /refresh with that same token 401s."""
    email = _email("mob")
    await _registered_user(client, db_session, email)

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            headers={"X-Client": "ios"},
            json={"email": email, "password": _VALID_PASSWORD},
        )
    body = login.json()
    access = body["access_token"]
    refresh = body["refresh_token"]

    logout_resp = await client.post(
        "/api/v1/auth/logout",
        headers={
            "X-Client": "ios",
            "Authorization": f"Bearer {access}",
        },
        json={"refresh_token": refresh},
    )
    assert logout_resp.status_code == 200

    # Re-using the revoked refresh now 401s.
    re_refresh = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Client": "ios"},
        json={"refresh_token": refresh},
    )
    assert re_refresh.status_code == 401


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mobile_2fa_verify_returns_refresh_in_body(
    client: AsyncClient, db_session: AsyncSession
):
    """2FA-enabled accounts: /2fa/verify with `X-Client: ios` returns
    the refresh token in the body and skips Set-Cookie."""
    import pyotp

    from services.auth_service import _encrypt_totp_secret

    email = _email("mfa")
    await _registered_user(client, db_session, email)

    user = (await db_session.execute(select(User).where(User.email == email.lower()))).scalar_one()
    secret = pyotp.random_base32()
    user.totp_secret_enc = _encrypt_totp_secret(secret)
    user.totp_enabled = True
    db_session.add(user)
    await db_session.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            headers={"X-Client": "ios"},
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert login.status_code == 200
    partial_token = login.json()["partial_token"]

    code = pyotp.TOTP(secret).now()
    verify = await client.post(
        "/api/v1/auth/2fa/verify",
        headers={"X-Client": "ios"},
        json={"partial_token": partial_token, "totp_code": code},
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert "refresh_token" not in verify.headers.get("set-cookie", "")
