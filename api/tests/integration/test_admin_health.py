# ABOUTME: Phase 4 Sprint 7 — admin health dashboard + red-flip alert dispatch.
# ABOUTME: Verifies state persistence, rate-limited alerts, and RBAC.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    IntegrationCredential,
    NotificationJob,
    NotificationPreference,
    Role,
    ServiceHealthState,
    User,
)
from services import credentials_vault, health_check_service

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Heal",
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
    body["user_id"] = str(user.id)
    return body


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _email() -> str:
    return f"hl_{uuid.uuid4().hex[:8]}@example.com"


async def _create_admin_with_pref(db: AsyncSession) -> User:
    """Create an active admin with an email-channel notification preference.

    Uses the auth-service register flow so the user_roles join row gets
    populated by the existing role-mirror listener (an inline ``User(...)``
    add hits an FK ordering trap because ``user_roles`` would INSERT before
    the parent ``users`` row lands)."""
    from services.auth_service import register_user

    user = await register_user(
        email=_email(),
        password=_VALID_PASSWORD,
        first_name="A",
        last_name="A",
        tos_version="1",
        privacy_version="1",
        ip_address="127.0.0.1",
        user_agent="pytest",
        db=db,
    )
    admin_role = (await db.execute(select(Role).where(Role.slug == "admin"))).scalar_one()
    user.status = "active"
    user.role_id = admin_role.id
    db.add(NotificationPreference(user_id=user.id, channel="email"))
    await db.flush()
    return user


# --------------------------------------------------------------------------- #
# GET /admin/health
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_health_endpoint_returns_state_for_all_services(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, _email(), "admin")
    resp = await client.get("/api/v1/admin/health", headers=_auth(admin["access_token"]))
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    names = {s["service_name"] for s in body["services"]}
    # All services in the registry should be represented after an initial probe.
    assert {"database", "r2", "slack", "twilio", "sendgrid", "google_maps"}.issubset(names)


@pytest.mark.asyncio
async def test_health_endpoint_rbac(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, _email(), "sales")
    resp = await client.get("/api/v1/admin/health", headers=_auth(sales["access_token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_database_probe_is_green_in_test_env(db_session: AsyncSession):
    """Sanity check on the probe layer — DB is always green in tests
    (the probe runs against the same async session)."""
    rows = await health_check_service.run_all(db_session)
    by_name = {r.service_name: r for r in rows}
    assert by_name["database"].status == "green"


# --------------------------------------------------------------------------- #
# Red-flip alert dispatch
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_red_flip_dispatches_admin_alerts(db_session: AsyncSession):
    """Save a Slack credential pointing at a webhook that 500s; running
    the probe should flip slack→red and enqueue an alert per active admin."""
    # Active admin with a (default-email) notification preference.
    admin = await _create_admin_with_pref(db_session)
    # Bad slack credential — probe will hit the webhook and fail.
    db_session.add(
        IntegrationCredential(
            integration_name="slack",
            encrypted_value=credentials_vault.encrypt("https://hooks.slack.com/services/T/B/X"),
        )
    )
    await db_session.flush()
    respx.post("https://hooks.slack.com/services/T/B/X").respond(
        status_code=500, text="upstream error"
    )

    rows = await health_check_service.run_all(db_session)
    by_name = {r.service_name: r for r in rows}
    assert by_name["slack"].status == "red"

    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "service_health_red_alert"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].user_id == admin.id


@pytest.mark.asyncio
@respx.mock
async def test_red_flip_alert_rate_limited_within_15_minutes(db_session: AsyncSession):
    """Once an alert fires, the next probe within 15 minutes — even if
    the service is still red — must not enqueue a duplicate alert."""
    await _create_admin_with_pref(db_session)
    db_session.add(
        IntegrationCredential(
            integration_name="slack",
            encrypted_value=credentials_vault.encrypt("https://hooks.slack.com/services/T/B/X"),
        )
    )
    await db_session.flush()
    respx.post("https://hooks.slack.com/services/T/B/X").respond(status_code=500)

    await health_check_service.run_all(db_session)
    await health_check_service.run_all(db_session)  # second pass, still red

    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "service_health_red_alert"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


@pytest.mark.asyncio
@respx.mock
async def test_alert_re_fires_after_cooldown(db_session: AsyncSession):
    """If 15 minutes elapse between flips, the next red flip alerts again.

    The idempotency key for an alert seeds off ``last_checked_at`` at
    seconds resolution, so two passes within the same wall-clock second
    enqueue the same key (good — production-level race dedup). This test
    sleeps briefly to step the seed forward; production needn't."""
    import asyncio

    await _create_admin_with_pref(db_session)
    db_session.add(
        IntegrationCredential(
            integration_name="slack",
            encrypted_value=credentials_vault.encrypt("https://hooks.slack.com/services/T/B/X"),
        )
    )
    await db_session.flush()
    respx.post("https://hooks.slack.com/services/T/B/X").respond(status_code=500)

    # First pass — flip + alert.
    await health_check_service.run_all(db_session)
    state_row = (
        await db_session.execute(
            select(ServiceHealthState).where(ServiceHealthState.service_name == "slack")
        )
    ).scalar_one()
    # Backdate last_alerted_at to 16 min ago, flip to green, and step
    # last_checked_at back so the next pass writes a different second
    # into the idempotency-key seed (otherwise the queue's idempotent
    # ON CONFLICT collapses the two enqueues onto the same row).
    state_row.last_alerted_at = datetime.now(UTC) - timedelta(minutes=16)
    state_row.last_checked_at = datetime.now(UTC) - timedelta(minutes=16)
    state_row.status = "green"
    await db_session.flush()

    # Step past the seconds-resolution idempotency seed.
    await asyncio.sleep(1.1)
    # Second pass — webhook still 500s, status flips green → red, alert fires.
    await health_check_service.run_all(db_session)
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "service_health_red_alert"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 2  # one from initial flip + one after cooldown


@pytest.mark.asyncio
async def test_unconfigured_integration_is_unknown_not_red(db_session: AsyncSession):
    """A Slack credential that's never been saved → status='unknown', not
    'red'. We don't want admins to get paged for "you haven't set this up
    yet" — that's not a degradation."""
    rows = await health_check_service.run_all(db_session)
    by_name = {r.service_name: r for r in rows}
    assert by_name["slack"].status == "unknown"

    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "service_health_red_alert"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 0
