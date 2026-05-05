# ABOUTME: Phase 8 Sprint 3 — /admin/reports/* endpoints.
# ABOUTME: Verifies sales-by-period, by-type, by-state, portal-traffic, CSV export, and RBAC.
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
    AnalyticsEvent,
    AppraisalSubmission,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    PublicListing,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _user_with_role(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> str:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Report",
                "last_name": "User",
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


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _seed_approved_record(
    db: AsyncSession,
    *,
    state: str = "TX",
    category_name: str = "Dozers",
    approved_purchase_offer: Decimal = Decimal("50000.00"),
    suggested_consignment_price: Decimal | None = None,
    overall_score: Decimal = Decimal("3.75"),
    approved_at: datetime | None = None,
    publish: bool = True,
) -> tuple[EquipmentRecord, AppraisalSubmission]:
    """Seed an EquipmentRecord with an approved AppraisalSubmission."""
    category = (
        await db.execute(
            select(EquipmentCategory).where(EquipmentCategory.name == category_name)
        )
    ).scalar_one_or_none()
    category_id = category.id if category else None

    customer = Customer(
        submitter_name="Seed Owner",
        invite_email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        address_state=state,
    )
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="listed" if publish else "appraiser_assigned",
        category_id=category_id,
        customer_make="Komatsu",
        customer_model="PC360",
        customer_year=2020,
    )
    db.add(record)
    await db.flush()

    sub = AppraisalSubmission(
        equipment_record_id=record.id,
        status="approved",
        category_id=category_id,
        make="Komatsu",
        model="PC360",
        year=2020,
        overall_score=overall_score,
        approved_purchase_offer=approved_purchase_offer,
        suggested_consignment_price=suggested_consignment_price,
        approved_at=approved_at or datetime.now(UTC),
        submitted_at=datetime.now(UTC),
    )
    db.add(sub)
    await db.flush()

    if publish:
        listing = PublicListing(
            equipment_record_id=record.id,
            listing_title="2020 Komatsu PC360",
            asking_price=approved_purchase_offer,
            status="active",
            published_at=datetime.now(UTC),
        )
        db.add(listing)
        await db.flush()

    return record, sub


async def _seed_analytics_events(db: AsyncSession) -> None:
    """Seed a small set of analytics events for portal traffic tests."""
    events = [
        AnalyticsEvent(session_id="sess-001", event_type="page_view", page="/listings", created_at=datetime.now(UTC)),
        AnalyticsEvent(session_id="sess-001", event_type="page_view", page="/listings/abc", created_at=datetime.now(UTC)),
        AnalyticsEvent(session_id="sess-002", event_type="page_view", page="/listings", created_at=datetime.now(UTC)),
        AnalyticsEvent(session_id="sess-002", event_type="form_step_start", page="/portal/submit", created_at=datetime.now(UTC)),
        AnalyticsEvent(session_id="sess-002", event_type="form_abandon", page="/portal/submit", created_at=datetime.now(UTC)),
        AnalyticsEvent(session_id="sess-003", event_type="pdf_download_click", page="/portal/report", created_at=datetime.now(UTC)),
    ]
    for e in events:
        db.add(e)
    await db.flush()


# ---------------------------------------------------------------------------
# Sales by Period
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sales_by_period_requires_auth(client: AsyncClient, db_session: AsyncSession):
    await db_session.commit()
    r = await client.get("/api/v1/admin/reports/sales-by-period")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_sales_by_period_forbidden_for_sales_rep(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "period_sales@example.com", "sales")
    await db_session.commit()
    r = await client.get("/api/v1/admin/reports/sales-by-period", headers=_auth(tok))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sales_by_period_admin_can_access(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "period_admin@example.com", "admin")
    await _seed_approved_record(db_session)
    await db_session.commit()

    r = await client.get(
        "/api/v1/admin/reports/sales-by-period",
        params={"period_type": "month"},
        headers=_auth(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["period_type"] == "month"
    assert isinstance(body["rows"], list)
    assert len(body["rows"]) >= 1


@pytest.mark.asyncio
async def test_sales_by_period_reporting_role_can_access(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "period_reporting@example.com", "reporting")
    await _seed_approved_record(db_session)
    await db_session.commit()

    r = await client.get(
        "/api/v1/admin/reports/sales-by-period",
        params={"period_type": "year"},
        headers=_auth(tok),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_sales_by_period_row_shape(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "period_shape@example.com", "admin")
    await _seed_approved_record(
        db_session,
        approved_purchase_offer=Decimal("75000.00"),
        suggested_consignment_price=Decimal("80000.00"),
    )
    await db_session.commit()

    r = await client.get(
        "/api/v1/admin/reports/sales-by-period",
        params={"period_type": "month"},
        headers=_auth(tok),
    )
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert "period_label" in row
    assert "record_count" in row
    assert "direct_purchase_count" in row
    assert "consignment_count" in row
    assert float(row["total_approved_offer"]) >= 75000.0
    assert float(row["total_consignment_price"]) >= 80000.0


# ---------------------------------------------------------------------------
# Sales by Type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sales_by_type_returns_category_rows(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "type_admin@example.com", "admin")
    await _seed_approved_record(db_session, category_name="Dozers")
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/sales-by-type", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    names = [row["category_name"] for row in body["rows"]]
    assert "Dozers" in names


@pytest.mark.asyncio
async def test_sales_by_type_row_shape(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "type_shape@example.com", "admin")
    await _seed_approved_record(db_session, overall_score=Decimal("4.00"))
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/sales-by-type", headers=_auth(tok))
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert "category_name" in row
    assert "record_count" in row
    assert "approved_count" in row
    assert row["avg_overall_score"] is not None


@pytest.mark.asyncio
async def test_sales_by_type_forbidden_for_customer(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "type_customer@example.com", "customer")
    await db_session.commit()
    r = await client.get("/api/v1/admin/reports/sales-by-type", headers=_auth(tok))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Sales by State
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sales_by_state_groups_by_state(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "state_admin@example.com", "admin")
    await _seed_approved_record(db_session, state="TX")
    await _seed_approved_record(db_session, state="CA")
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/sales-by-state", headers=_auth(tok))
    assert r.status_code == 200
    states = [row["state"] for row in r.json()["rows"]]
    assert "TX" in states
    assert "CA" in states


@pytest.mark.asyncio
async def test_sales_by_state_row_shape(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "state_shape@example.com", "admin")
    await _seed_approved_record(db_session, state="TX")
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/sales-by-state", headers=_auth(tok))
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert "state" in row
    assert "record_count" in row
    assert "approved_count" in row


@pytest.mark.asyncio
async def test_sales_by_state_reporting_role_allowed(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "state_reporting@example.com", "reporting")
    await db_session.commit()
    r = await client.get("/api/v1/admin/reports/sales-by-state", headers=_auth(tok))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Portal Traffic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portal_traffic_counts_sessions(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "traffic_admin@example.com", "admin")
    await _seed_analytics_events(db_session)
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/portal-traffic", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["total_sessions"] >= 3
    assert body["total_page_views"] >= 3


@pytest.mark.asyncio
async def test_portal_traffic_form_abandon_rate(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "traffic_abandon@example.com", "admin")
    await _seed_analytics_events(db_session)
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/portal-traffic", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    # 1 abandon / 1 form_step_start = 100.0
    assert body["form_abandon_rate"] == 100.0


@pytest.mark.asyncio
async def test_portal_traffic_pdf_download_count(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "traffic_pdf@example.com", "admin")
    await _seed_analytics_events(db_session)
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/portal-traffic", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["pdf_download_count"] >= 1


@pytest.mark.asyncio
async def test_portal_traffic_top_pages(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "traffic_pages@example.com", "admin")
    await _seed_analytics_events(db_session)
    await db_session.commit()

    r = await client.get("/api/v1/admin/reports/portal-traffic", headers=_auth(tok))
    assert r.status_code == 200
    top_pages = r.json()["top_pages"]
    assert len(top_pages) >= 1
    assert all("page" in p and "view_count" in p for p in top_pages)
    # /listings should be the top page (2 views)
    assert top_pages[0]["page"] == "/listings"


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_csv_sales_by_period(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "export_period@example.com", "admin")
    await _seed_approved_record(db_session)
    await db_session.commit()

    r = await client.get(
        "/api/v1/admin/reports/export",
        params={"report_type": "sales-by-period", "period_type": "month"},
        headers=_auth(tok),
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.splitlines()
    assert lines[0].startswith("period_label")
    assert len(lines) >= 2


@pytest.mark.asyncio
async def test_export_csv_sales_by_state(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "export_state@example.com", "admin")
    await _seed_approved_record(db_session, state="TX")
    await db_session.commit()

    r = await client.get(
        "/api/v1/admin/reports/export",
        params={"report_type": "sales-by-state"},
        headers=_auth(tok),
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.splitlines()
    assert lines[0].startswith("state")
    assert "TX" in r.text


@pytest.mark.asyncio
async def test_export_csv_forbidden_for_appraiser(client: AsyncClient, db_session: AsyncSession):
    tok = await _user_with_role(client, db_session, "export_appraiser@example.com", "appraiser")
    await db_session.commit()
    r = await client.get(
        "/api/v1/admin/reports/export",
        params={"report_type": "sales-by-type"},
        headers=_auth(tok),
    )
    assert r.status_code == 403
