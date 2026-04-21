# ABOUTME: Integration tests for all auth endpoints — real DB, real JWT, real bcrypt.
# ABOUTME: Each test function gets a fresh DB transaction that rolls back on completion.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PASSWORD = "TestPassword1!"
_VALID_EMAIL = "testuser@example.com"


async def _register(client: AsyncClient, email: str = _VALID_EMAIL) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": _VALID_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    return resp


async def _verify_and_login(client: AsyncClient, db_session, email: str = _VALID_EMAIL) -> dict:
    """Register, activate via test session, then login."""
    from sqlalchemy import select

    from database.models import User

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await _register(client, email)
        assert reg.status_code == 201

    result = await db_session.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user:
        user.status = "active"
        await db_session.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return login_resp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == _VALID_EMAIL
    assert "id" in data
    assert "message" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await _register(client)
        resp = await _register(client)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_invalid_password(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "weak", "first_name": "A", "last_name": "B"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "not-an-email",
            "password": _VALID_PASSWORD,
            "first_name": "A",
            "last_name": "B",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_email_invalid_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/verify-email?token=badtoken")
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_verify_email_success(client: AsyncClient):
    """Full round-trip: register → capture token → verify."""
    captured_url: list[str] = []

    async def _capture_email(to: str, subject: str, html: str) -> None:
        if "verify" in subject.lower():
            import re

            match = re.search(r'href="([^"]+verify[^"]+)"', html)
            if match:
                captured_url.append(match.group(1))

    with patch("services.email_service.send_email", side_effect=_capture_email):
        resp = await _register(client)
    assert resp.status_code == 201

    assert captured_url, "Verification URL was not captured from email"
    # Extract token from URL
    token = captured_url[0].split("token=")[-1]
    verify_resp = await client.get(f"/api/v1/auth/verify-email?token={token}")
    assert verify_resp.status_code == 200
    assert "verified" in verify_resp.json()["message"].lower()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_unverified_account(client: AsyncClient):
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await _register(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _VALID_EMAIL, "password": _VALID_PASSWORD},
    )
    assert resp.status_code == 403
    assert "verify" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await _register(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _VALID_EMAIL, "password": "WrongPassword1!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": _VALID_PASSWORD},
    )
    assert resp.status_code == 401
    # Same message as wrong password — no enumeration
    assert "Incorrect email or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_account_lockout(client: AsyncClient, db_session):
    """Five wrong-password attempts should lock the account."""
    from sqlalchemy import select

    from database.models import User

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await _register(client)

    result = await db_session.execute(select(User).where(User.email == _VALID_EMAIL))
    user = result.scalar_one_or_none()
    assert user is not None
    user.status = "active"
    await db_session.flush()

    for _ in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": _VALID_EMAIL, "password": "WrongPassword1!"},
        )

    locked_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _VALID_EMAIL, "password": _VALID_PASSWORD},
    )
    assert locked_resp.status_code == 423
    assert "locked" in locked_resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Refresh / Logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "fakehex" * 10})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_invalid_token(client: AsyncClient):
    # Should succeed gracefully (idempotent)
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "fakehex" * 10})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_reset_request_always_200(client: AsyncClient):
    """Should return 200 even for non-existent emails."""
    resp = await client.post(
        "/api/v1/auth/password-reset-request",
        json={"email": "nobody@example.com"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_confirm_invalid_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/password-reset-confirm",
        json={"token": "badtoken", "new_password": _VALID_PASSWORD},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_password_reset_confirm_weak_password(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/password-reset-confirm",
        json={"token": "anything", "new_password": "weak"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Protected route — authentication required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protected_route_without_token(client: AsyncClient):
    """The /2fa/setup endpoint requires auth — should return 401 without a token."""
    resp = await client.post("/api/v1/auth/2fa/setup")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_with_invalid_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/2fa/setup",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Health check still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_still_works(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
