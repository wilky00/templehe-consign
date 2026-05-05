# ABOUTME: Phase 8 Sprint 1 — GET /public/listings and GET /public/listings/:id.
# ABOUTME: Verifies filter, pagination, sort, detail view, and 404 on inactive/missing listings.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalSubmission,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    PublicListing,
)

_VALID_PASSWORD = "TestPassword1!"


async def _seed_listing(
    db: AsyncSession,
    *,
    title: str = "2019 CAT 336",
    asking_price: Decimal = Decimal("85000.00"),
    status: str = "active",
    category_name: str | None = None,
    hours_condition: str | None = "Good",
    state: str | None = "TX",
) -> tuple[EquipmentRecord, PublicListing]:
    """Insert a minimal EquipmentRecord + PublicListing pair."""
    category_id = None
    if category_name:
        cat = (
            await db.execute(
                select(EquipmentCategory).where(EquipmentCategory.name == category_name)
            )
        ).scalar_one_or_none()
        if cat:
            category_id = cat.id

    # EquipmentRecord requires customer_id FK — create a minimal customer first
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        address_state=state,
    )
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="listed",
        customer_make="Caterpillar",
        customer_model="336",
        customer_year=2019,
        category_id=category_id,
    )
    db.add(record)
    await db.flush()

    listing = PublicListing(
        equipment_record_id=record.id,
        listing_title=title,
        asking_price=asking_price,
        status=status,
        published_at=datetime.now(UTC),
    )
    db.add(listing)
    await db.flush()
    return record, listing


@pytest.mark.asyncio
async def test_listings_returns_active_only(client: AsyncClient, db_session: AsyncSession):
    _, active = await _seed_listing(db_session, title="Active unit", status="active")
    _, withdrawn = await _seed_listing(db_session, title="Withdrawn unit", status="withdrawn")
    await db_session.commit()

    r = await client.get("/api/v1/public/listings")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert str(active.id) in ids
    assert str(withdrawn.id) not in ids


@pytest.mark.asyncio
async def test_listings_pagination(client: AsyncClient, db_session: AsyncSession):
    for i in range(5):
        await _seed_listing(db_session, title=f"Unit {i}")
    await db_session.commit()

    r = await client.get("/api/v1/public/listings", params={"page": 1, "page_size": 3})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) <= 3
    assert body["page"] == 1
    assert body["page_size"] == 3
    assert body["total"] >= 5


@pytest.mark.asyncio
async def test_listings_sort_price_asc(client: AsyncClient, db_session: AsyncSession):
    await _seed_listing(db_session, title="Expensive", asking_price=Decimal("150000"))
    await _seed_listing(db_session, title="Cheap", asking_price=Decimal("20000"))
    await db_session.commit()

    r = await client.get("/api/v1/public/listings", params={"sort": "price_asc"})
    assert r.status_code == 200
    prices = [
        float(item["asking_price"])
        for item in r.json()["items"]
        if item["asking_price"] is not None
    ]
    assert prices == sorted(prices)


@pytest.mark.asyncio
async def test_listings_filter_by_price_range(client: AsyncClient, db_session: AsyncSession):
    _, mid = await _seed_listing(db_session, title="Mid unit", asking_price=Decimal("50000"))
    _, high = await _seed_listing(db_session, title="High unit", asking_price=Decimal("200000"))
    await db_session.commit()

    r = await client.get(
        "/api/v1/public/listings", params={"min_price": "30000", "max_price": "100000"}
    )
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert str(mid.id) in ids
    assert str(high.id) not in ids


@pytest.mark.asyncio
async def test_listing_detail_returns_full_fields(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session, title="2019 CAT 336 EL")
    await db_session.commit()

    r = await client.get(f"/api/v1/public/listings/{listing.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(listing.id)
    assert body["listing_title"] == "2019 CAT 336 EL"
    # make falls back to customer_make since no AppraisalSubmission in this seed
    assert body["make"] == "Caterpillar"


@pytest.mark.asyncio
async def test_listing_detail_404_for_withdrawn(client: AsyncClient, db_session: AsyncSession):
    _, listing = await _seed_listing(db_session, title="Gone", status="withdrawn")
    await db_session.commit()

    r = await client.get(f"/api/v1/public/listings/{listing.id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_listing_detail_404_for_unknown_id(client: AsyncClient, db_session: AsyncSession):
    r = await client.get(f"/api/v1/public/listings/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_listings_no_auth_required(client: AsyncClient, db_session: AsyncSession):
    """Public listing endpoint must work without a Bearer token."""
    await _seed_listing(db_session)
    await db_session.commit()
    r = await client.get("/api/v1/public/listings")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_listings_filter_by_condition(client: AsyncClient, db_session: AsyncSession):
    """Condition filter uses AppraisalSubmission.hours_condition (appraiser-verified)."""
    _, excellent = await _seed_listing(db_session, title="Excellent unit")
    _, poor = await _seed_listing(db_session, title="Poor unit")

    # Attach approved AppraisalSubmissions with the relevant condition values
    for listing, condition in [(excellent, "Excellent"), (poor, "Poor")]:
        sub = AppraisalSubmission(
            equipment_record_id=listing.equipment_record_id,
            status="approved",
            hours_condition=condition,
        )
        db_session.add(sub)
    await db_session.commit()

    r = await client.get("/api/v1/public/listings", params={"condition": "Excellent"})
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert str(excellent.id) in ids
    assert str(poor.id) not in ids


@pytest.mark.asyncio
async def test_listings_pagination_structure(client: AsyncClient, db_session: AsyncSession):
    await db_session.commit()
    r = await client.get("/api/v1/public/listings", params={"page": 1, "page_size": 24})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "total_pages" in body
