# ABOUTME: Phase 3 Sprint 5 — sales-rep notification on phase-6 trigger statuses.
# ABOUTME: Channel via prefs (email default, sms if preferred, slack→email fallback).
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    EquipmentRecord,
    NotificationJob,
    NotificationPreference,
    Role,
    User,
)
from services import equipment_status_service

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email: str,
    role_slug: str,
    first_name: str = "Rep",
) -> User:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": first_name,
                "last_name": "User",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201, reg.json()
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    await db.flush()
    return user


async def _customer_record(
    client: AsyncClient, db: AsyncSession, *, email: str
) -> tuple[EquipmentRecord, User]:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Cust",
                "last_name": "Owner",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    cust = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    cust.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    token = login.json()["access_token"]
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    record_id = uuid.UUID(resp.json()["id"])
    record = (
        await db.execute(select(EquipmentRecord).where(EquipmentRecord.id == record_id))
    ).scalar_one()
    return record, cust


@pytest.mark.asyncio
async def test_approved_pending_esign_emails_assigned_sales_rep(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(
        client, db_session, email="srn_email_rep@example.com", role_slug="sales"
    )
    record, customer = await _customer_record(
        client, db_session, email="srn_email_cust@example.com"
    )
    record.assigned_sales_rep_id = rep.id
    await db_session.flush()

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="approved_pending_esign",
        changed_by=None,
        customer=customer,
    )

    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "sales_rep_approved_pending_esign"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.channel == "email"
    assert job.user_id == rep.id
    assert job.payload["to_email"] == "srn_email_rep@example.com"
    # Subject mirrors spec wording.
    assert "Ready for eSign" in job.payload["subject"]


@pytest.mark.asyncio
async def test_esigned_pending_publish_emails_assigned_sales_rep(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(
        client, db_session, email="srn_pub_rep@example.com", role_slug="sales"
    )
    record, customer = await _customer_record(client, db_session, email="srn_pub_cust@example.com")
    record.assigned_sales_rep_id = rep.id
    await db_session.flush()

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="esigned_pending_publish",
        changed_by=None,
        customer=customer,
    )
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "sales_rep_esigned_pending_publish"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].channel == "email"
    assert "ready to publish" in jobs[0].payload["subject"].lower()


@pytest.mark.asyncio
async def test_sms_pref_routes_to_sms_channel(client: AsyncClient, db_session: AsyncSession):
    rep = await _user_with_role(
        client, db_session, email="srn_sms_rep@example.com", role_slug="sales"
    )
    db_session.add(
        NotificationPreference(user_id=rep.id, channel="sms", phone_number="+15555550199")
    )
    await db_session.flush()
    record, customer = await _customer_record(client, db_session, email="srn_sms_cust@example.com")
    record.assigned_sales_rep_id = rep.id
    await db_session.flush()

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="approved_pending_esign",
        changed_by=None,
        customer=customer,
    )
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "sales_rep_approved_pending_esign"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].channel == "sms"
    assert jobs[0].payload["to_number"] == "+15555550199"
    assert "Manager approved" in jobs[0].payload["body"]


@pytest.mark.asyncio
async def test_slack_pref_falls_back_to_email(client: AsyncClient, db_session: AsyncSession):
    rep = await _user_with_role(
        client, db_session, email="srn_slack_rep@example.com", role_slug="sales"
    )
    db_session.add(NotificationPreference(user_id=rep.id, channel="slack", slack_user_id="U12345"))
    await db_session.flush()
    record, customer = await _customer_record(
        client, db_session, email="srn_slack_cust@example.com"
    )
    record.assigned_sales_rep_id = rep.id
    await db_session.flush()

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="approved_pending_esign",
        changed_by=None,
        customer=customer,
    )
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "sales_rep_approved_pending_esign"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].channel == "email"
    assert jobs[0].payload["to_email"] == "srn_slack_rep@example.com"


@pytest.mark.asyncio
async def test_no_sales_rep_assigned_skips_notification(
    client: AsyncClient, db_session: AsyncSession
):
    record, customer = await _customer_record(
        client, db_session, email="srn_unassigned_cust@example.com"
    )
    assert record.assigned_sales_rep_id is None

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="approved_pending_esign",
        changed_by=None,
        customer=customer,
    )
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(NotificationJob.template.startswith("sales_rep_"))
            )
        )
        .scalars()
        .all()
    )
    assert jobs == []


@pytest.mark.asyncio
async def test_internal_status_does_not_notify_sales_rep(
    client: AsyncClient, db_session: AsyncSession
):
    """`appraiser_assigned` is not in either notify set — verifies the
    sales-rep gate isn't accidentally too wide."""
    rep = await _user_with_role(
        client, db_session, email="srn_internal_rep@example.com", role_slug="sales"
    )
    record, customer = await _customer_record(
        client, db_session, email="srn_internal_cust@example.com"
    )
    record.assigned_sales_rep_id = rep.id
    await db_session.flush()

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraiser_assigned",
        changed_by=None,
        customer=customer,
    )
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(NotificationJob.template.startswith("sales_rep_"))
            )
        )
        .scalars()
        .all()
    )
    assert jobs == []
