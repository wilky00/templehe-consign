# ABOUTME: Phase 2 Sprint 1 integration tests — consent capture, profile CRUD, re-accept flow.
# ABOUTME: Exercises /auth/register consent archive + /legal/* + /me/profile + /me/email-prefs.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AppConfig, User, UserConsentVersion

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str, tos: str = "1", privacy: str = "1") -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Phase2",
        "last_name": "Customer",
        "tos_version": tos,
        "privacy_version": privacy,
    }


async def _register_activate_login(client: AsyncClient, db: AsyncSession, email: str) -> str:
    """Returns the access_token for an active customer."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post("/api/v1/auth/register", json=_register_payload(email))
    assert reg.status_code == 201, reg.json()

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
    return login.json()["access_token"]


# ---------------------------------------------------------------------------
# Registration records consent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_writes_consent_archive(client: AsyncClient, db_session: AsyncSession):
    email = "sprint1_consent@example.com"
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post("/api/v1/auth/register", json=_register_payload(email))
    assert resp.status_code == 201

    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.tos_version == "1"
    assert user.privacy_version == "1"
    assert user.tos_accepted_at is not None
    assert user.privacy_accepted_at is not None

    archive = await db_session.execute(
        select(UserConsentVersion).where(UserConsentVersion.user_id == user.id)
    )
    rows = list(archive.scalars().all())
    kinds = sorted((r.consent_type, r.version) for r in rows)
    assert kinds == [("privacy", "1"), ("tos", "1")]


@pytest.mark.asyncio
async def test_registration_rejects_stale_tos_version(
    client: AsyncClient, db_session: AsyncSession
):
    """A client posting an old tos_version must 409 instead of silently
    recording consent to whatever the server thinks is current."""
    payload = _register_payload("sprint1_stale@example.com", tos="0")
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409
    assert "updated" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_registration_missing_consent_fields_is_422(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "sprint1_noconsent@example.com",
            "password": _VALID_PASSWORD,
            "first_name": "A",
            "last_name": "B",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /auth/me requires_terms_reaccept flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_requires_reaccept_after_version_bump(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _register_activate_login(client, db_session, "sprint1_bump@example.com")
    # Initially, current versions match — no re-accept required.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["requires_terms_reaccept"] is False

    # Bump tos_current_version to "2" as an admin would.
    await db_session.execute(
        text(
            "UPDATE app_config SET value = jsonb_build_object('version', '2') "
            "WHERE key = 'tos_current_version'"
        )
    )
    await db_session.flush()

    me2 = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me2.status_code == 200
    assert me2.json()["requires_terms_reaccept"] is True


@pytest.mark.asyncio
async def test_accept_terms_clears_reaccept(client: AsyncClient, db_session: AsyncSession):
    token = await _register_activate_login(client, db_session, "sprint1_reaccept@example.com")
    # Bump + drop an extra version file so the endpoint has something to load.
    await db_session.execute(
        text(
            "UPDATE app_config SET value = jsonb_build_object('version', '2') "
            "WHERE key = 'tos_current_version'"
        )
    )
    await db_session.flush()

    # Re-accept with the CURRENT versions (tos=2, privacy=1).
    accept = await client.post(
        "/api/v1/legal/accept",
        json={"tos_version": "2", "privacy_version": "1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert accept.status_code == 200

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["requires_terms_reaccept"] is False

    # Archive now has 2 tos rows (v1 from registration, v2 from re-accept).
    result = await db_session.execute(
        select(UserConsentVersion).where(UserConsentVersion.consent_type == "tos")
    )
    tos_versions = sorted(r.version for r in result.scalars().all())
    assert "1" in tos_versions and "2" in tos_versions


@pytest.mark.asyncio
async def test_accept_terms_rejects_stale_submitted_version(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _register_activate_login(client, db_session, "sprint1_stale_accept@example.com")
    await db_session.execute(
        text(
            "UPDATE app_config SET value = jsonb_build_object('version', '2') "
            "WHERE key = 'tos_current_version'"
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/api/v1/legal/accept",
        json={"tos_version": "1", "privacy_version": "1"},  # stale
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# /legal/tos, /legal/privacy, /legal/consent-status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legal_tos_returns_current_version(client: AsyncClient):
    resp = await client.get("/api/v1/legal/tos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "tos"
    assert body["version"] == "1"
    assert "DRAFT" in body["body_markdown"]


@pytest.mark.asyncio
async def test_legal_privacy_returns_current_version(client: AsyncClient):
    resp = await client.get("/api/v1/legal/privacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "privacy"
    assert body["version"] == "1"
    assert "DRAFT" in body["body_markdown"]


@pytest.mark.asyncio
async def test_legal_consent_status_unauth_is_401(client: AsyncClient):
    resp = await client.get("/api/v1/legal/consent-status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /me/profile CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_get_auto_creates_customer_row(client: AsyncClient, db_session: AsyncSession):
    token = await _register_activate_login(client, db_session, "sprint1_profile@example.com")
    resp = await client.get("/api/v1/me/profile", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["submitter_name"] == "Phase2 Customer"
    assert body["email_prefs"]["intake_confirmations"] is True
    assert body["email_prefs"]["sms_opt_in"] is False


@pytest.mark.asyncio
async def test_profile_patch_updates_supplied_fields_only(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _register_activate_login(client, db_session, "sprint1_patch@example.com")
    resp = await client.patch(
        "/api/v1/me/profile",
        json={
            "business_name": "Temple Acme LLC",
            "address_state": "tx",
            "cell_phone": "  555-123-4567  ",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["business_name"] == "Temple Acme LLC"
    assert body["address_state"] == "TX"
    assert body["cell_phone"] == "555-123-4567"
    # Unsupplied fields remain at defaults
    assert body["submitter_name"] == "Phase2 Customer"


@pytest.mark.asyncio
async def test_profile_patch_rejects_bad_state(client: AsyncClient, db_session: AsyncSession):
    token = await _register_activate_login(client, db_session, "sprint1_badstate@example.com")
    resp = await client.patch(
        "/api/v1/me/profile",
        json={"address_state": "ZZ"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_profile_unauth_is_401(client: AsyncClient):
    resp = await client.get("/api/v1/me/profile")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Email prefs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_prefs_defaults_then_patched(client: AsyncClient, db_session: AsyncSession):
    token = await _register_activate_login(client, db_session, "sprint1_prefs@example.com")
    get_resp = await client.get(
        "/api/v1/me/email-prefs", headers={"Authorization": f"Bearer {token}"}
    )
    assert get_resp.status_code == 200
    assert get_resp.json() == {
        "intake_confirmations": True,
        "status_updates": True,
        "marketing": False,
        "sms_opt_in": False,
    }

    patch_resp = await client.patch(
        "/api/v1/me/email-prefs",
        json={
            "intake_confirmations": False,
            "status_updates": True,
            "marketing": True,
            "sms_opt_in": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["marketing"] is True
    assert patch_resp.json()["sms_opt_in"] is True


# ---------------------------------------------------------------------------
# App config seed sanity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_005_seeds_app_config_defaults(db_session: AsyncSession):
    """Migration 005 must seed four defaults so the legal + retention code
    has something to read on day one."""
    result = await db_session.execute(
        select(AppConfig).where(
            AppConfig.key.in_(
                [
                    "tos_current_version",
                    "privacy_current_version",
                    "audit_pii_retention_days",
                    "audit_row_retention_months",
                ]
            )
        )
    )
    rows = {r.key: r.value for r in result.scalars().all()}
    assert set(rows.keys()) == {
        "tos_current_version",
        "privacy_current_version",
        "audit_pii_retention_days",
        "audit_row_retention_months",
    }
    retention = rows["audit_pii_retention_days"]
    if isinstance(retention, str):
        import json as _json

        retention = _json.loads(retention)
    assert retention["days"] == 30
    assert retention["min"] == 30
    assert retention["max"] == 120
    assert retention["step"] == 30
