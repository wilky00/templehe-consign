# ABOUTME: Phase 8 Sprint 1 — POST /public/listings/:id/inquiries.
# ABOUTME: Covers creation, email dispatch, honeypot rejection, and listing management PATCH.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Customer,
    EquipmentRecord,
    Inquiry,
    PublicListing,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


async def _make_user(client: AsyncClient, db: AsyncSession, email: str, role_slug: str) -> str:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Sales",
                "last_name": "Rep",
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
    return login.json()["access_token"]


async def _seed_listing(
    db: AsyncSession,
    *,
    status: str = "active",
    asking_price: Decimal = Decimal("75000.00"),
) -> tuple[EquipmentRecord, PublicListing]:
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(customer)
    await db.flush()
    record = EquipmentRecord(
        customer_id=customer.id,
        status="listed",
        customer_make="Komatsu",
        customer_model="PC210",
        customer_year=2020,
    )
    db.add(record)
    await db.flush()
    listing = PublicListing(
        equipment_record_id=record.id,
        listing_title="2020 Komatsu PC210",
        asking_price=asking_price,
        status=status,
        published_at=datetime.now(UTC),
    )
    db.add(listing)
    await db.flush()
    return record, listing


_INQUIRY_PAYLOAD = {
    "first_name": "Bob",
    "last_name": "Buyer",
    "email": "bob@example.com",
    "phone": "555-1234",
    "message": "Is this still available?",
}


@pytest.mark.asyncio
async def test_inquiry_creates_record(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session)
    await db_session.commit()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        r = await client.post(
            f"/api/v1/public/listings/{listing.id}/inquiries",
            json=_INQUIRY_PAYLOAD,
        )
    assert r.status_code == 201
    body = r.json()
    assert "id" in body

    await db_session.rollback()
    inquiry = (
        await db_session.execute(select(Inquiry).where(Inquiry.id == uuid.UUID(body["id"])))
    ).scalar_one_or_none()
    assert inquiry is not None
    assert inquiry.email == "bob@example.com"
    assert inquiry.first_name == "Bob"


@pytest.mark.asyncio
async def test_inquiry_sends_confirmation_email(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session)
    await db_session.commit()

    with patch("services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        r = await client.post(
            f"/api/v1/public/listings/{listing.id}/inquiries",
            json=_INQUIRY_PAYLOAD,
        )
    assert r.status_code == 201
    assert mock_send.called


@pytest.mark.asyncio
async def test_inquiry_honeypot_silently_succeeds(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session)
    listing_id = listing.id  # capture before any session state changes
    await db_session.commit()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        r = await client.post(
            f"/api/v1/public/listings/{listing_id}/inquiries",
            json={**_INQUIRY_PAYLOAD, "web_address": "http://spambot.example.com"},
        )
    assert r.status_code == 201
    # Expire session cache to read what the endpoint committed
    await db_session.rollback()
    rows = (
        await db_session.execute(select(Inquiry).where(Inquiry.public_listing_id == listing_id))
    ).all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_inquiry_404_for_inactive_listing(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session, status="withdrawn")
    await db_session.commit()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        r = await client.post(
            f"/api/v1/public/listings/{listing.id}/inquiries",
            json=_INQUIRY_PAYLOAD,
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_inquiry_validates_email_format(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/public/listings/{listing.id}/inquiries",
        json={**_INQUIRY_PAYLOAD, "email": "not-an-email"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_inquiry_no_auth_required(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session)
    await db_session.commit()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        r = await client.post(
            f"/api/v1/public/listings/{listing.id}/inquiries",
            json=_INQUIRY_PAYLOAD,
        )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_listing_patch_status_sold(client: AsyncClient, db_session: AsyncSession):
    """Sales rep can mark a listing as sold via PATCH /sales/equipment/{id}/listing."""
    tok = await _make_user(client, db_session, "sales_rep@example.com", "sales")
    record, listing = await _seed_listing(db_session)
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/sales/equipment/{record.id}/listing",
        json={"status": "sold"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "sold"

    await db_session.rollback()
    await db_session.refresh(listing)
    assert listing.status == "sold"
    assert listing.sold_at is not None


@pytest.mark.asyncio
async def test_listing_patch_asking_price(client: AsyncClient, db_session: AsyncSession):
    tok = await _make_user(client, db_session, "price_rep@example.com", "sales")
    record, _ = await _seed_listing(db_session, asking_price=Decimal("60000"))
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/sales/equipment/{record.id}/listing",
        json={"asking_price": "72000.00"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["asking_price"] == pytest.approx(72000.0)


@pytest.mark.asyncio
async def test_listing_patch_requires_auth(client: AsyncClient, db_session: AsyncSession):
    record, _ = await _seed_listing(db_session)
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/sales/equipment/{record.id}/listing",
        json={"status": "sold"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_listing_patch_404_when_no_listing(client: AsyncClient, db_session: AsyncSession):
    tok = await _make_user(client, db_session, "no_listing_rep@example.com", "sales")
    customer = Customer(
        submitter_name="Ghost Owner",
        invite_email="ghost@example.com",
    )
    db_session.add(customer)
    await db_session.flush()
    record = EquipmentRecord(customer_id=customer.id, status="new_request")
    db_session.add(record)
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/sales/equipment/{record.id}/listing",
        json={"status": "sold"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 404
