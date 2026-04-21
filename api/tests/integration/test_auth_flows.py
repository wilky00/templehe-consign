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
# Refresh / Logout (cookie-based)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_without_cookie_returns_401(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_invalid_cookie_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": "fakehex" * 10},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_without_auth_returns_401(client: AsyncClient):
    """Logout requires a bearer access token for audit hygiene."""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_sets_refresh_cookie(client: AsyncClient, db_session):
    """Successful login sets an HttpOnly refresh_token cookie."""
    login_resp = await _verify_and_login(client, db_session, email="cookie_login@example.com")
    assert login_resp.status_code == 200

    set_cookie = login_resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    # httpx stores the cookie in its jar
    assert "refresh_token" in login_resp.cookies


@pytest.mark.asyncio
async def test_refresh_cookie_full_cycle(client: AsyncClient, db_session):
    """login → cookie → refresh → new cookie → logout clears cookie."""
    login_resp = await _verify_and_login(client, db_session, email="cookie_cycle@example.com")
    assert login_resp.status_code == 200
    original_cookie = login_resp.cookies.get("refresh_token")
    assert original_cookie

    # Refresh: send the cookie, expect a new access token + a new refresh cookie.
    refresh_resp = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": original_cookie},
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()
    rotated_cookie = refresh_resp.cookies.get("refresh_token")
    assert rotated_cookie and rotated_cookie != original_cookie

    # Reusing the original (now-rotated-away) cookie must fail.
    replay_resp = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": original_cookie},
    )
    assert replay_resp.status_code == 401

    # Logout requires Bearer auth; carries the cookie to revoke.
    access_token = login_resp.json()["access_token"]
    logout_resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies={"refresh_token": rotated_cookie},
    )
    assert logout_resp.status_code == 200
    cleared = logout_resp.headers.get("set-cookie", "")
    assert 'refresh_token=""' in cleared or "refresh_token=;" in cleared

    # The rotated cookie no longer refreshes.
    post_logout = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": rotated_cookie},
    )
    assert post_logout.status_code == 401


@pytest.mark.asyncio
async def test_email_change_revokes_sessions(client: AsyncClient, db_session):
    """Confirming an email change must invalidate all active sessions for that
    account so existing refresh cookies (which were issued under the old
    identity) can't continue working."""
    import re

    from sqlalchemy import select

    from database.models import User

    login_resp = await _verify_and_login(client, db_session, email="changing@example.com")
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    old_refresh_cookie = login_resp.cookies.get("refresh_token")
    assert old_refresh_cookie

    # Capture the confirmation URL emitted to the *new* address.
    captured_urls: list[str] = []

    async def _capture(to: str, subject: str, html: str) -> None:
        match = re.search(r'href="([^"]+change-email[^"]+)"', html)
        if match:
            captured_urls.append(match.group(1))

    with patch("services.email_service.send_email", side_effect=_capture):
        init_resp = await client.post(
            "/api/v1/auth/change-email",
            headers=auth_headers,
            json={
                "new_email": "changed@example.com",
                "current_password": _VALID_PASSWORD,
            },
        )
    assert init_resp.status_code == 200
    assert captured_urls, "email change confirmation URL not captured"
    token = captured_urls[0].split("token=")[-1]

    confirm_resp = await client.get(f"/api/v1/auth/change-email/confirm?token={token}")
    assert confirm_resp.status_code == 200

    # User's email actually changed in the DB.
    updated = (
        await db_session.execute(select(User).where(User.email == "changed@example.com"))
    ).scalar_one_or_none()
    assert updated is not None

    # The cookie issued before the email change must no longer refresh.
    replay = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": old_refresh_cookie},
    )
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_login_produces_exactly_one_active_session(client: AsyncClient, db_session):
    """Regression: the refresh-token-dropped bug created orphan sessions per login."""
    from sqlalchemy import select

    from database.models import User, UserSession

    await _verify_and_login(client, db_session, email="one_session@example.com")

    user = (
        await db_session.execute(select(User).where(User.email == "one_session@example.com"))
    ).scalar_one_or_none()
    assert user is not None

    active = (
        (
            await db_session.execute(
                select(UserSession).where(
                    UserSession.user_id == user.id,
                    UserSession.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(active) == 1


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


@pytest.mark.asyncio
async def test_recovery_endpoint_rate_limits_by_ip(client: AsyncClient):
    """/2fa/recovery allows 5 attempts/hour per IP; the 6th from same IP returns 429.

    Vary the partial_token on every request so the per-token limiter (3/5min) does
    NOT trip — we want to exercise the IP-scoped counter in isolation.
    """
    headers = {"CF-Connecting-IP": "203.0.113.42"}

    for attempt in range(5):
        resp = await client.post(
            "/api/v1/auth/2fa/recovery",
            headers=headers,
            json={
                "partial_token": f"token-per-request-{attempt}",
                "recovery_code": "AAAAAAAAAAAAAAAA",
            },
        )
        assert resp.status_code != 429, f"limiter tripped too early on attempt {attempt + 1}"

    # 6th from the same CF-IP must trip the IP limiter.
    resp = await client.post(
        "/api/v1/auth/2fa/recovery",
        headers=headers,
        json={"partial_token": "token-per-request-5", "recovery_code": "AAAAAAAAAAAAAAAA"},
    )
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") is not None


@pytest.mark.asyncio
async def test_register_succeeds_when_email_send_fails(client: AsyncClient):
    """Registration must not 500 when the email backend is down — the email
    is scheduled via BackgroundTasks and its failure is logged, not raised."""

    async def _always_fails(*args, **kwargs):
        raise RuntimeError("simulated SendGrid outage")

    with patch("services.email_service.send_email", side_effect=_always_fails):
        resp = await _register(client, email="email_fail@example.com")

    # The user row is created even if the confirmation email fails.
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 2FA — re-auth required on enable / disable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_2fa_confirm_requires_password(client: AsyncClient, db_session):
    """Enabling 2FA without a password reprompt lets a stolen access token
    bind the account to an attacker's authenticator. Confirm must require
    the current password in addition to a valid TOTP code.
    """
    import pyotp

    login_resp = await _verify_and_login(client, db_session, email="twofa_enable@example.com")
    access_token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    setup_resp = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers)
    assert setup_resp.status_code == 200
    secret = setup_resp.json()["secret"]
    totp = pyotp.TOTP(secret)

    # Missing password → 422 (schema validation).
    missing = await client.post(
        "/api/v1/auth/2fa/confirm",
        headers=auth_headers,
        json={"totp_code": totp.now()},
    )
    assert missing.status_code == 422

    # Wrong password → 401; emit user.2fa_reauth_failed audit event.
    wrong = await client.post(
        "/api/v1/auth/2fa/confirm",
        headers=auth_headers,
        json={"totp_code": totp.now(), "password": "WrongPassword1!"},
    )
    assert wrong.status_code == 401

    from sqlalchemy import select

    from database.models import AuditLog

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event_type == "user.2fa_reauth_failed")
        )
    ).scalar_one_or_none()
    assert audit_row is not None

    # Correct password + valid TOTP → 200 with recovery codes.
    ok = await client.post(
        "/api/v1/auth/2fa/confirm",
        headers=auth_headers,
        json={"totp_code": totp.now(), "password": _VALID_PASSWORD},
    )
    assert ok.status_code == 200
    assert len(ok.json()["recovery_codes"]) == 10


@pytest.mark.asyncio
async def test_2fa_disable_requires_password(client: AsyncClient, db_session):
    """Disabling 2FA removes a security layer, so require the current
    password in addition to the TOTP code."""
    import pyotp

    login_resp = await _verify_and_login(client, db_session, email="twofa_disable@example.com")
    access_token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    # Enable 2FA first.
    setup_resp = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers)
    secret = setup_resp.json()["secret"]
    totp = pyotp.TOTP(secret)
    await client.post(
        "/api/v1/auth/2fa/confirm",
        headers=auth_headers,
        json={"totp_code": totp.now(), "password": _VALID_PASSWORD},
    )

    # Missing password → 422.
    missing = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers,
        json={"totp_code": totp.now()},
    )
    assert missing.status_code == 422

    # Wrong password → 401.
    wrong = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers,
        json={"totp_code": totp.now(), "password": "WrongPassword1!"},
    )
    assert wrong.status_code == 401

    # Correct password + valid TOTP → 200.
    ok = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers,
        json={"totp_code": totp.now(), "password": _VALID_PASSWORD},
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_recovery_endpoint_rate_limits_per_partial_token_across_ips(client: AsyncClient):
    """Same partial_token hitting 3+ distinct IPs still trips the token-scoped limit."""
    payload = {"partial_token": "stolen-token-reused", "recovery_code": "AAAAAAAAAAAAAAAA"}

    # 3 attempts across 3 different IPs — each attempt should not yet be 429.
    for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        resp = await client.post(
            "/api/v1/auth/2fa/recovery",
            headers={"CF-Connecting-IP": ip},
            json=payload,
        )
        assert resp.status_code != 429

    # 4th attempt on yet another IP — token-scoped counter trips regardless of IP.
    resp = await client.post(
        "/api/v1/auth/2fa/recovery",
        headers={"CF-Connecting-IP": "10.0.0.4"},
        json=payload,
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Refresh token — success path (service-layer test; HTTP layer omits token in body)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_access_token_success(db_session):
    """Valid refresh token returns new access + refresh tokens."""
    from sqlalchemy import select

    import services.auth_service as auth_svc
    import services.session_service as session_svc
    from database.models import Role, User

    role_result = await db_session.execute(select(Role).where(Role.slug == "customer"))
    role = role_result.scalar_one_or_none()

    user = User(
        email="refresh_svc_test@example.com",
        password_hash=auth_svc.hash_password("TestPassword1!"),
        first_name="Refresh",
        last_name="Svc",
        role_id=role.id,
        status="active",
    )
    db_session.add(user)
    await db_session.flush()

    raw_token = await session_svc.issue_refresh_token(user.id, db_session)
    result = await auth_svc.refresh_access_token(raw_token, db_session)
    assert "access_token" in result
    assert "refresh_token" in result
    assert result["refresh_token"] != raw_token


# ---------------------------------------------------------------------------
# Password reset — full success flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_reset_full_flow(client: AsyncClient, db_session):
    """Request reset for active user, capture token, confirm with new password."""
    email = "reset_flow@example.com"
    new_password = "NewPassword2@"

    await _verify_and_login(client, db_session, email=email)

    captured_url: list[str] = []

    async def _capture(to: str, subject: str, html: str) -> None:
        import re

        match = re.search(r'href="([^"]+reset[^"]+)"', html)
        if match:
            captured_url.append(match.group(1))

    with patch("services.email_service.send_email", side_effect=_capture):
        reset_req = await client.post("/api/v1/auth/password-reset-request", json={"email": email})
    assert reset_req.status_code == 200
    assert captured_url, "Password reset URL was not captured from email"

    token = captured_url[0].split("token=")[-1]
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        confirm_resp = await client.post(
            "/api/v1/auth/password-reset-confirm",
            json={"token": token, "new_password": new_password},
        )
    assert confirm_resp.status_code == 200


# ---------------------------------------------------------------------------
# Resend verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resend_verification_sends_email_for_pending_user(client: AsyncClient):
    """Pending-verification users should receive a new verification email on resend."""
    email = "pending_resend@example.com"
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await _register(client, email)

    with patch("services.email_service.send_email", new_callable=AsyncMock) as mock_resend:
        resp = await client.post("/api/v1/auth/resend-verification", json={"email": email})
    assert resp.status_code == 200
    mock_resend.assert_called_once()


@pytest.mark.asyncio
async def test_resend_verification_silent_for_unknown_email(client: AsyncClient):
    """Non-existent email should return 200 without sending — no enumeration."""
    resp = await client.post(
        "/api/v1/auth/resend-verification", json={"email": "ghost@example.com"}
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health check still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_still_works(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
