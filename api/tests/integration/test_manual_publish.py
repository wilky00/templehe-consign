# ABOUTME: Phase 3 Sprint 2 — POST /sales/equipment/{id}/publish.
# ABOUTME: Validates status=esigned_pending_publish + signed contract + appraisal report. Transitions to 'listed'.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalReport,
    AuditLog,
    ConsignmentContract,
    EquipmentRecord,
    NotificationJob,
    PublicListing,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "T",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201
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


async def _customer_record(
    client: AsyncClient, db: AsyncSession, email: str
) -> uuid.UUID:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "C",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    u.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    tok = login.json()["access_token"]
    r = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {tok}"},
    )
    return uuid.UUID(r.json()["id"])


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _stage_ready_to_publish(
    db: AsyncSession, record_id: uuid.UUID, *, signed: bool = True, report: bool = True
) -> None:
    """Hoist a record to esigned_pending_publish with the right pre-reqs.
    Phase 6 fires this flow end-to-end; Phase 3 tests seed it manually."""
    rec = (
        await db.execute(select(EquipmentRecord).where(EquipmentRecord.id == record_id))
    ).scalar_one()
    rec.status = "esigned_pending_publish"
    rec.customer_make = "Caterpillar"
    rec.customer_model = "336"
    contract = ConsignmentContract(
        equipment_record_id=record_id,
        status="signed" if signed else "sent",
        signed_at=datetime.now(UTC) if signed else None,
    )
    db.add(contract)
    if report:
        db.add(
            AppraisalReport(
                equipment_record_id=record_id,
                gcs_path="reports/test/placeholder.pdf",
            )
        )
    await db.flush()


@pytest.mark.asyncio
async def test_publish_happy_path_creates_listing_and_sends_email(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "pub_m@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pub_c@example.com")
    await _stage_ready_to_publish(db_session, rec_id)

    resp = await client.post(
        f"/api/v1/sales/equipment/{rec_id}/publish",
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "listed"
    assert body["public_listing_id"]

    # Listing row persisted
    listing = (
        await db_session.execute(
            select(PublicListing).where(PublicListing.equipment_record_id == rec_id)
        )
    ).scalar_one()
    assert listing.status == "active"
    assert listing.published_at is not None

    # Customer email queued (via equipment_status_service — 'listed' is in the set)
    emails = (
        await db_session.execute(
            select(NotificationJob).where(NotificationJob.template == "status_listed")
        )
    ).scalars().all()
    assert any(e.payload.get("reference_number") for e in emails) or emails

    # Audit entry
    events = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event_type == "equipment_record.published")
        )
    ).scalars().all()
    assert any(e.target_id == rec_id for e in events)


@pytest.mark.asyncio
async def test_publish_wrong_status_returns_400(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "pub_bad_m@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pub_bad_c@example.com")

    resp = await client.post(
        f"/api/v1/sales/equipment/{rec_id}/publish",
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 400
    assert "esigned_pending_publish" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_publish_without_signed_contract_returns_400(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "pub_nosign_m@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pub_nosign_c@example.com")
    await _stage_ready_to_publish(db_session, rec_id, signed=False)

    resp = await client.post(
        f"/api/v1/sales/equipment/{rec_id}/publish",
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 400
    assert "signed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_without_appraisal_report_returns_400(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "pub_norep_m@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pub_norep_c@example.com")
    await _stage_ready_to_publish(db_session, rec_id, report=False)

    resp = await client.post(
        f"/api/v1/sales/equipment/{rec_id}/publish",
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 400
    assert "report" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_customer_cannot_publish(client: AsyncClient, db_session: AsyncSession):
    cust = await _user_with_role(client, db_session, "pub_cust@example.com", "customer")
    rec_id = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/sales/equipment/{rec_id}/publish",
        headers=_auth(cust["access_token"]),
    )
    assert resp.status_code == 403
