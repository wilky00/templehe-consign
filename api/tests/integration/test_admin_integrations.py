# ABOUTME: Phase 4 Sprint 7 — admin-side store/reveal/test for integration credentials.
# ABOUTME: Covers RBAC, step-up auth, rate-limiting, and the audit log entries.
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pyotp
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    IntegrationCredential,
    Role,
    User,
)
from services import credentials_vault
from services.auth_service import _encrypt_totp_secret

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    role_slug: str,
    *,
    enable_totp: bool = False,
) -> tuple[dict, str | None]:
    """Register, activate, assign role, log in, then optionally enable TOTP.

    TOTP is flipped on AFTER login so the login flow returns a normal
    access_token instead of partial_token + verify-roundtrip. The reveal
    step-up still verifies TOTP fresh against the user row, which is what
    the test wants to exercise.

    Returns (login_body, totp_secret). totp_secret is None when not enabled.
    """
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Int",
                "last_name": "Admin",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    await db.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    body = login.json()

    totp_secret: str | None = None
    if enable_totp:
        totp_secret = pyotp.random_base32()
        user.totp_secret_enc = _encrypt_totp_secret(totp_secret)
        user.totp_enabled = True
        await db.flush()
    return body, totp_secret


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _email() -> str:
    return f"int_{uuid.uuid4().hex[:8]}@example.com"


# --------------------------------------------------------------------------- #
# List + RBAC
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_returns_all_known_integrations_unconfigured(
    client: AsyncClient, db_session: AsyncSession
):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    resp = await client.get("/api/v1/admin/integrations", headers=_auth(admin["access_token"]))
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    names = {i["name"] for i in body["integrations"]}
    assert {"slack", "twilio", "sendgrid", "google_maps", "esign", "valuation"}.issubset(names)
    # Nothing saved yet → all is_set=False.
    for item in body["integrations"]:
        assert item["is_set"] is False


@pytest.mark.asyncio
async def test_non_admin_cannot_list(client: AsyncClient, db_session: AsyncSession):
    sales, _ = await _user_with_role(client, db_session, _email(), "sales")
    resp = await client.get("/api/v1/admin/integrations", headers=_auth(sales["access_token"]))
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_store_encrypts_and_audits(client: AsyncClient, db_session: AsyncSession):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    resp = await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["name"] == "slack"
    assert body["is_set"] is True

    # DB row uses encrypted bytes — never plaintext.
    row = (
        await db_session.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == "slack")
        )
    ).scalar_one()
    assert b"hooks.slack.com" not in row.encrypted_value
    assert (
        credentials_vault.decrypt(row.encrypted_value) == "https://hooks.slack.com/services/T/B/X"
    )

    # Audit log records the set without leaking plaintext.
    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "integration_credential_set")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].after_state == {"integration_name": "slack"}


@pytest.mark.asyncio
async def test_store_rejects_unknown_integration(client: AsyncClient, db_session: AsyncSession):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    resp = await client.put(
        "/api/v1/admin/integrations/myspace",
        json={"plaintext": "anything"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_store_rejects_empty_plaintext(client: AsyncClient, db_session: AsyncSession):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    resp = await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": ""},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_store_resets_test_status(client: AsyncClient, db_session: AsyncSession):
    """Saving a new value clears the prior tested-at + status — the previous
    test is no longer authoritative against fresh credentials."""
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    row = (
        await db_session.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == "slack")
        )
    ).scalar_one()
    row.last_tested_at = datetime.now(UTC)
    row.last_test_status = "success"
    await db_session.flush()

    resp = await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/Y"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.json()["last_tested_at"] is None
    assert resp.json()["last_test_status"] is None


# --------------------------------------------------------------------------- #
# Reveal step-up
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reveal_requires_password_and_totp(client: AsyncClient, db_session: AsyncSession):
    admin, totp = await _user_with_role(client, db_session, _email(), "admin", enable_totp=True)
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    code = pyotp.TOTP(totp).now()
    resp = await client.post(
        "/api/v1/admin/integrations/slack/reveal",
        json={"password": _VALID_PASSWORD, "totp_code": code},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["plaintext"] == "https://hooks.slack.com/services/T/B/X"

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "integration_credential_revealed")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_reveal_wrong_password_fails_without_leaking_which_factor(
    client: AsyncClient, db_session: AsyncSession
):
    admin, totp = await _user_with_role(client, db_session, _email(), "admin", enable_totp=True)
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    resp = await client.post(
        "/api/v1/admin/integrations/slack/reveal",
        json={"password": "WrongPass1!", "totp_code": pyotp.TOTP(totp).now()},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 401
    assert "Wrong password or TOTP" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reveal_wrong_totp_fails(client: AsyncClient, db_session: AsyncSession):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin", enable_totp=True)
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    resp = await client.post(
        "/api/v1/admin/integrations/slack/reveal",
        json={"password": _VALID_PASSWORD, "totp_code": "000000"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reveal_blocked_when_admin_has_no_totp(client: AsyncClient, db_session: AsyncSession):
    """Step-up requires 2FA on the actor. An admin without TOTP enabled
    can't reveal — the audit log captures the blocked attempt."""
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    resp = await client.post(
        "/api/v1/admin/integrations/slack/reveal",
        json={"password": _VALID_PASSWORD, "totp_code": "123456"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 401

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.event_type == "integration_credential_reveal_blocked"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_reveal_not_set_returns_404(client: AsyncClient, db_session: AsyncSession):
    admin, totp = await _user_with_role(client, db_session, _email(), "admin", enable_totp=True)
    resp = await client.post(
        "/api/v1/admin/integrations/twilio/reveal",
        json={"password": _VALID_PASSWORD, "totp_code": pyotp.TOTP(totp).now()},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reveal_rate_limited_at_10_per_hour(client: AsyncClient, db_session: AsyncSession):
    admin, totp = await _user_with_role(client, db_session, _email(), "admin", enable_totp=True)
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    # 10 successful reveals.
    for _ in range(10):
        code = pyotp.TOTP(totp).now()
        resp = await client.post(
            "/api/v1/admin/integrations/slack/reveal",
            json={"password": _VALID_PASSWORD, "totp_code": code},
            headers=_auth(admin["access_token"]),
        )
        assert resp.status_code == 200, resp.json()
    # 11th — rate limit.
    resp = await client.post(
        "/api/v1/admin/integrations/slack/reveal",
        json={"password": _VALID_PASSWORD, "totp_code": pyotp.TOTP(totp).now()},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 429


# --------------------------------------------------------------------------- #
# Test endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_test_button_runs_tester_and_persists_status(
    client: AsyncClient, db_session: AsyncSession
):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(admin["access_token"]),
    )
    respx.post("https://hooks.slack.com/services/T/B/X").respond(status_code=200, text="ok")
    resp = await client.post(
        "/api/v1/admin/integrations/slack/test",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["success"] is True
    assert body["status"] == "success"

    # Persisted to the DB row.
    row = (
        await db_session.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == "slack")
        )
    ).scalar_one()
    assert row.last_test_status == "success"
    assert row.last_tested_at is not None


@pytest.mark.asyncio
async def test_test_unset_credential_returns_404(client: AsyncClient, db_session: AsyncSession):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    resp = await client.post(
        "/api/v1/admin/integrations/twilio/test",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_test_twilio_with_to_number_passes_extra_args(
    client: AsyncClient, db_session: AsyncSession
):
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    payload = json.dumps({"account_sid": "ACxxxx", "auth_token": "tok", "from_number": "+15551234"})
    await client.put(
        "/api/v1/admin/integrations/twilio",
        json={"plaintext": payload},
        headers=_auth(admin["access_token"]),
    )
    respx.get("https://api.twilio.com/2010-04-01/Accounts/ACxxxx.json").respond(
        status_code=200, json={"sid": "ACxxxx"}
    )
    sms_route = respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACxxxx/Messages.json"
    ).respond(status_code=201, json={"sid": "MSGxxx", "status": "queued"})

    resp = await client.post(
        "/api/v1/admin/integrations/twilio/test",
        json={"extra_args": {"to_number": "+15559999999"}},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    assert sms_route.called


@pytest.mark.asyncio
@respx.mock
async def test_test_sendgrid_with_to_email_passes_extra_args(
    client: AsyncClient, db_session: AsyncSession
):
    """Phase 5 Sprint 0 — admin can opt into a real test email via the
    `to_email` extra_arg. Mirrors the Twilio + `to_number` pattern. The
    SPA surfaces this as the "Test email to" input on AdminIntegrations."""
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    await client.put(
        "/api/v1/admin/integrations/sendgrid",
        json={"plaintext": "SG.test-key"},
        headers=_auth(admin["access_token"]),
    )
    respx.get("https://api.sendgrid.com/v3/scopes").respond(
        status_code=200, json={"scopes": ["mail.send"]}
    )
    send_route = respx.post("https://api.sendgrid.com/v3/mail/send").respond(
        status_code=202, text=""
    )

    resp = await client.post(
        "/api/v1/admin/integrations/sendgrid/test",
        json={"extra_args": {"to_email": "ops@example.com"}},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["success"] is True
    assert "ops@example.com" in body["detail"]
    assert send_route.called

    # Verify the outgoing payload addressed the supplied email.
    payload = json.loads(send_route.calls[0].request.content)
    assert payload["personalizations"][0]["to"][0]["email"] == "ops@example.com"


@pytest.mark.asyncio
@respx.mock
async def test_test_sendgrid_without_to_email_does_not_send(
    client: AsyncClient, db_session: AsyncSession
):
    """Without `to_email`, the test endpoint hits /v3/scopes only —
    no real email goes out. Default behavior unchanged from Phase 4."""
    admin, _ = await _user_with_role(client, db_session, _email(), "admin")
    await client.put(
        "/api/v1/admin/integrations/sendgrid",
        json={"plaintext": "SG.test-key"},
        headers=_auth(admin["access_token"]),
    )
    respx.get("https://api.sendgrid.com/v3/scopes").respond(
        status_code=200, json={"scopes": ["mail.send"]}
    )
    send_route = respx.post("https://api.sendgrid.com/v3/mail/send").respond(
        status_code=202, text=""
    )

    resp = await client.post(
        "/api/v1/admin/integrations/sendgrid/test",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["success"] is True
    assert not send_route.called


@pytest.mark.asyncio
async def test_non_admin_cannot_store(client: AsyncClient, db_session: AsyncSession):
    sales, _ = await _user_with_role(client, db_session, _email(), "sales")
    resp = await client.put(
        "/api/v1/admin/integrations/slack",
        json={"plaintext": "https://hooks.slack.com/services/T/B/X"},
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403
