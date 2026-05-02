# ABOUTME: Phase 5 Sprint 2 — verifies APNs jobs are enqueued alongside email on assignment.
# ABOUTME: Confirms per-token job creation and idempotency key structure.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DeviceToken, EquipmentRecord, NotificationJob, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _active_appraiser(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
) -> User:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Field",
                "last_name": "Appraiser",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == "appraiser"))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    db.add(user)
    await db.flush()
    from services import user_roles_service

    await user_roles_service.grant(db, user=user, role_slug="appraiser", granted_by=None)
    await db.flush()
    return user


def _unique_email() -> str:
    return f"aprapr-{uuid.uuid4().hex[:8]}@example.com"


@pytest.mark.asyncio
async def test_assignment_enqueues_apns_job_per_token(
    client: AsyncClient, db_session: AsyncSession
):
    appraiser = await _active_appraiser(client, db_session, _unique_email())

    # Register 2 iOS device tokens for this appraiser.
    tokens = []
    for raw in ["tok-aaa", "tok-bbb"]:
        dt = DeviceToken(
            user_id=appraiser.id,
            platform="ios",
            token=raw,
            environment="development",
        )
        db_session.add(dt)
        tokens.append(dt)
    await db_session.flush()

    from database.models import Customer
    from services import equipment_service

    customer = Customer(
        submitter_name="Owner", cell_phone="555-000-0001", invite_email="owner1@example.com"
    )
    db_session.add(customer)
    await db_session.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraiser_assigned",
        reference_number="THE-APNSTEST",
        customer_make="CAT",
        customer_model="336",
        customer_year=2021,
    )
    db_session.add(record)
    await db_session.flush()

    await equipment_service.enqueue_assignment_notification(
        db_session,
        record=record,
        assigned_user_id=appraiser.id,
        trigger="test",
    )

    # Should have 1 email job + 2 APNs jobs.
    jobs = list(
        (
            await db_session.execute(
                select(NotificationJob).where(NotificationJob.user_id == appraiser.id)
            )
        )
        .scalars()
        .all()
    )
    channels = [j.channel for j in jobs]
    assert channels.count("email") == 1
    assert channels.count("apns") == 2

    apns_jobs = [j for j in jobs if j.channel == "apns"]
    token_values = {j.payload["token"] for j in apns_jobs}
    assert token_values == {"tok-aaa", "tok-bbb"}


@pytest.mark.asyncio
async def test_assignment_no_tokens_enqueues_only_email(
    client: AsyncClient, db_session: AsyncSession
):
    appraiser = await _active_appraiser(client, db_session, _unique_email())

    from database.models import Customer
    from services import equipment_service

    customer = Customer(
        submitter_name="Owner2", cell_phone="555-000-0002", invite_email="owner2@example.com"
    )
    db_session.add(customer)
    await db_session.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraiser_assigned",
        reference_number="THE-NOAPNS",
        customer_make="JD",
        customer_model="310L",
        customer_year=2020,
    )
    db_session.add(record)
    await db_session.flush()

    await equipment_service.enqueue_assignment_notification(
        db_session,
        record=record,
        assigned_user_id=appraiser.id,
        trigger="test",
    )

    jobs = list(
        (
            await db_session.execute(
                select(NotificationJob).where(NotificationJob.user_id == appraiser.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(j.channel == "email" for j in jobs)


@pytest.mark.asyncio
async def test_assignment_apns_enqueue_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    """Calling enqueue_assignment_notification twice with the same trigger
    must not create duplicate APNs jobs."""
    appraiser = await _active_appraiser(client, db_session, _unique_email())

    dt = DeviceToken(
        user_id=appraiser.id,
        platform="ios",
        token="idem-tok",
        environment="development",
    )
    db_session.add(dt)
    await db_session.flush()

    from database.models import Customer
    from services import equipment_service

    customer = Customer(submitter_name="IdempotentOwner", invite_email="idem@example.com")
    db_session.add(customer)
    await db_session.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraiser_assigned",
        reference_number="THE-IDEM",
        customer_make="Komatsu",
        customer_model="PC360",
        customer_year=2022,
    )
    db_session.add(record)
    await db_session.flush()

    for _ in range(2):
        await equipment_service.enqueue_assignment_notification(
            db_session,
            record=record,
            assigned_user_id=appraiser.id,
            trigger="routing",
        )

    apns_jobs = list(
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.user_id == appraiser.id,
                    NotificationJob.channel == "apns",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(apns_jobs) == 1
