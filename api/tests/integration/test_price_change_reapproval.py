# ABOUTME: Phase 6 Sprint 3 — integration tests for the price change re-approval workflow.
# ABOUTME: Covers threshold evaluation, manager notification, queue endpoint, and RBAC.
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalSubmission,
    ChangeRequest,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    NotificationJob,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _create_user(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email: str,
    role_slug: str,
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Test",
                "last_name": role_slug.title(),
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    db.add(user)
    await db.flush()
    from services import user_roles_service

    await user_roles_service.grant(db, user=user, role_slug=role_slug, granted_by=None)
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return resp.json()


async def _make_approved_record(
    db: AsyncSession,
    *,
    approved_price: Decimal = Decimal("60000.00"),
) -> EquipmentRecord:
    """Create an equipment record with an approved appraisal submission."""
    cat = EquipmentCategory(name=f"PrCat-{_tag()}", slug=f"pr-cat-{_tag()}", version=1)
    db.add(cat)
    await db.flush()

    customer = Customer(submitter_name="Price Customer", invite_email=f"pr-cust-{_tag()}@example.com")
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="approved_pending_esign",
        category_id=cat.id,
        reference_number=f"THE-PR{_tag().upper()[:5]}",
    )
    db.add(record)
    await db.flush()

    submission = AppraisalSubmission(
        equipment_record_id=record.id,
        status="approved",
        make="Volvo",
        model="EC300",
        suggested_consignment_price=approved_price,
    )
    db.add(submission)
    await db.flush()

    return record


# --------------------------------------------------------------------------- #
# PriceChangeService unit-level integration tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_price_change_above_threshold_sets_reapproval_flag(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A proposed price change > 10% sets requires_manager_reapproval = True."""
    record = await _make_approved_record(db_session, approved_price=Decimal("60000.00"))

    change = ChangeRequest(
        equipment_record_id=record.id,
        request_type="update_consignment_price",
        status="pending",
        proposed_consignment_price=Decimal("48000.00"),  # 20% drop
    )
    db_session.add(change)
    await db_session.flush()

    from services import price_change_service

    await price_change_service.evaluate(db_session, change_request=change)

    assert change.requires_manager_reapproval is True


@pytest.mark.asyncio
async def test_price_change_below_threshold_no_flag(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A proposed price change ≤ 10% does not set requires_manager_reapproval."""
    record = await _make_approved_record(db_session, approved_price=Decimal("60000.00"))

    change = ChangeRequest(
        equipment_record_id=record.id,
        request_type="update_consignment_price",
        status="pending",
        proposed_consignment_price=Decimal("57000.00"),  # 5% drop — within threshold
    )
    db_session.add(change)
    await db_session.flush()

    from services import price_change_service

    await price_change_service.evaluate(db_session, change_request=change)

    assert change.requires_manager_reapproval is False


@pytest.mark.asyncio
async def test_price_change_above_threshold_notifies_managers(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """When re-approval is triggered, active sales managers receive a notification."""
    manager_tokens = await _create_user(
        client,
        db_session,
        email=f"mgr-pr-{_tag()}@example.com",
        role_slug="sales_manager",
    )
    record = await _make_approved_record(db_session, approved_price=Decimal("60000.00"))

    change = ChangeRequest(
        equipment_record_id=record.id,
        request_type="update_consignment_price",
        status="pending",
        proposed_consignment_price=Decimal("40000.00"),  # 33% drop
    )
    db_session.add(change)
    await db_session.flush()

    from services import price_change_service

    await price_change_service.evaluate(db_session, change_request=change)
    await db_session.flush()

    jobs = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.template == "manager_price_change_reapproval",
            )
        )
    ).scalars().all()
    assert len(jobs) >= 1
    manager_job = next(
        (j for j in jobs if j.payload.get("to_email", "").endswith("@example.com")),
        None,
    )
    assert manager_job is not None


@pytest.mark.asyncio
async def test_price_change_no_approved_submission_skips(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """If no approved submission exists, evaluate() returns without setting the flag."""
    cat = EquipmentCategory(name=f"PrCat2-{_tag()}", slug=f"pr-cat2-{_tag()}", version=1)
    db_session.add(cat)
    await db_session.flush()
    customer = Customer(submitter_name="Cust2", invite_email=f"c2-{_tag()}@example.com")
    db_session.add(customer)
    await db_session.flush()
    record = EquipmentRecord(
        customer_id=customer.id,
        status="new_request",
        category_id=cat.id,
    )
    db_session.add(record)
    await db_session.flush()

    change = ChangeRequest(
        equipment_record_id=record.id,
        request_type="update_consignment_price",
        status="pending",
        proposed_consignment_price=Decimal("30000.00"),
    )
    db_session.add(change)
    await db_session.flush()

    from services import price_change_service

    await price_change_service.evaluate(db_session, change_request=change)

    assert change.requires_manager_reapproval is False


# --------------------------------------------------------------------------- #
# Price change queue endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_price_change_queue_shows_flagged_requests(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /manager/approvals/price-changes lists ChangeRequests with requires_manager_reapproval."""
    manager_tokens = await _create_user(
        client,
        db_session,
        email=f"mgr-pcq-{_tag()}@example.com",
        role_slug="sales_manager",
    )
    record = await _make_approved_record(db_session, approved_price=Decimal("60000.00"))

    change = ChangeRequest(
        equipment_record_id=record.id,
        request_type="update_consignment_price",
        status="pending",
        proposed_consignment_price=Decimal("45000.00"),
        requires_manager_reapproval=True,
    )
    db_session.add(change)
    await db_session.flush()

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.get("/api/v1/manager/approvals/price-changes", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    ids = [item["change_request_id"] for item in data["items"]]
    assert str(change.id) in ids


@pytest.mark.asyncio
async def test_price_change_queue_rbac(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Customers cannot access the price change re-approval queue."""
    customer_tokens = await _create_user(
        client,
        db_session,
        email=f"cust-pcq-{_tag()}@example.com",
        role_slug="customer",
    )
    headers = {"Authorization": f"Bearer {customer_tokens['access_token']}"}
    resp = await client.get("/api/v1/manager/approvals/price-changes", headers=headers)
    assert resp.status_code == 403
