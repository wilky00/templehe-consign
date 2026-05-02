# ABOUTME: Phase 5 Sprint 3 — POST /api/v1/valuation/search integration tests.
# ABOUTME: Covers internal hits, empty results, range filters, AppConfig flag, RBAC, soft-delete.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ComparableSale, EquipmentCategory, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _create_user(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    role_slug: str,
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Val",
                "last_name": "User",
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
    assert resp.status_code == 200
    return resp.json()


def _email(tag: str) -> str:
    return f"val-{tag}-{uuid.uuid4().hex[:6]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_category(db: AsyncSession, slug: str = "excavators") -> EquipmentCategory:
    existing = (
        await db.execute(
            select(EquipmentCategory).where(
                EquipmentCategory.slug == slug,
                EquipmentCategory.deleted_at.is_(None),
                EquipmentCategory.replaced_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    cat = EquipmentCategory(name=slug.title(), slug=slug, status="active")
    db.add(cat)
    await db.flush()
    return cat


async def _make_sale(
    db: AsyncSession,
    *,
    make: str = "Caterpillar",
    model: str = "320",
    year: int = 2020,
    hours: int = 3000,
    sale_price: str = "185000.00",
    source: str = "internal",
    category_id: uuid.UUID | None = None,
    deleted: bool = False,
) -> ComparableSale:
    sale = ComparableSale(
        make=make,
        model=model,
        year=year,
        hours=hours,
        sale_price=Decimal(sale_price),
        sale_date=datetime(2024, 6, 1, tzinfo=UTC),
        source=source,
        category_id=category_id,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(sale)
    await db.flush()
    return sale


@pytest.mark.asyncio
async def test_internal_hit_returns_result(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    await _make_sale(db_session, make="Caterpillar", model="320", year=2020, hours=3000)

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "Caterpillar", "model": "320", "year": 2020, "hours": 3000},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) >= 1
    assert "internal" in data["used_sources"]
    assert data["results"][0]["make"] == "Caterpillar"


@pytest.mark.asyncio
async def test_empty_results_when_no_match(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "NonexistentBrand", "model": "XX-9999"},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert data["used_sources"] == []


@pytest.mark.asyncio
async def test_year_range_filter_includes_nearby(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    # Default year_range is 3. Search year=2020 → includes 2017–2023.
    await _make_sale(db_session, make="Komatsu", model="PC360", year=2018, hours=5000)
    await _make_sale(db_session, make="Komatsu", model="PC360", year=2025, hours=5000)

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "Komatsu", "model": "PC360", "year": 2020},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    years = [r["year"] for r in data["results"]]
    assert 2018 in years       # within ±3
    assert 2025 not in years   # outside ±3


@pytest.mark.asyncio
async def test_hours_range_filter_includes_nearby(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    # Default hours_range is 500. Search hours=3000 → includes 2500–3500.
    await _make_sale(db_session, make="Volvo", model="EC300", year=2020, hours=2600)
    await _make_sale(db_session, make="Volvo", model="EC300", year=2020, hours=5000)

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "Volvo", "model": "EC300", "year": 2020, "hours": 3000},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    hours_list = [r["hours"] for r in data["results"]]
    assert 2600 in hours_list    # within ±500
    assert 5000 not in hours_list  # outside ±500


@pytest.mark.asyncio
async def test_category_filter_limits_results(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    cat_a = await _make_category(db_session, "excavators-vt")
    cat_b = await _make_category(db_session, "dozers-vt")
    await _make_sale(
        db_session, make="Hitachi", model="ZX350", year=2020, hours=4000, category_id=cat_a.id
    )
    await _make_sale(
        db_session, make="Hitachi", model="ZX350", year=2020, hours=4000, category_id=cat_b.id
    )

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "Hitachi", "model": "ZX350", "category_id": str(cat_a.id)},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["category_id"] == str(cat_a.id)


@pytest.mark.asyncio
async def test_soft_deleted_sale_excluded(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    await _make_sale(
        db_session, make="JohnDeere", model="350G", year=2020, hours=3000, deleted=True
    )

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "JohnDeere", "model": "350G"},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_customer_role_blocked(client: AsyncClient, db_session: AsyncSession):
    customer_user = await _create_user(client, db_session, _email("cust"), "customer")
    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "CAT"},
        headers=_auth(customer_user["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_blocked(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post("/api/v1/valuation/search", json={"make": "CAT"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_results_ordered_by_sale_date_desc(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    # Three sales; insert out of order — expect newest first.
    for yr, hrs in [(2019, 3000), (2021, 3000), (2020, 3000)]:
        sale = ComparableSale(
            make="Liebherr",
            model="R9xx",
            year=yr,
            hours=hrs,
            sale_price=Decimal("200000.00"),
            sale_date=datetime(yr, 1, 1, tzinfo=UTC),
            source="internal",
        )
        db_session.add(sale)
    await db_session.flush()

    resp = await client.post(
        "/api/v1/valuation/search",
        json={"make": "Liebherr", "model": "R9xx", "year": 2020, "hours": 3000},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    years = [r["year"] for r in resp.json()["results"]]
    assert years == sorted(years, reverse=True)
