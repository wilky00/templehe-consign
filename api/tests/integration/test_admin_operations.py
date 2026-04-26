# ABOUTME: Phase 4 Sprint 1 — /admin/operations dashboard + CSV export + reporting RBAC.
# ABOUTME: Filter combinations, days-in-status math, overdue flag, role gates.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord, Role, StatusEvent, User

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
                "first_name": "Op",
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
    body = login.json()
    body["user_id"] = str(user.id)
    body["user"] = user
    return body


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _create_record_for(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers=_auth(token),
    )
    assert resp.status_code in (200, 201), resp.json()
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_list_returns_records_with_status_display_and_days_in_status(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "admin_ops_a@example.com", "admin")
    customer = await _user_with_role(client, db_session, "admin_ops_c@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    # Backdate the record's StatusEvent so days_in_status > 0.
    se = (
        (
            await db_session.execute(
                select(StatusEvent).where(StatusEvent.equipment_record_id == rec_id)
            )
        )
        .scalars()
        .first()
    )
    if se is not None:
        se.created_at = datetime.now(UTC) - timedelta(days=3)
    else:
        # Older code paths may not have written one; emit one ourselves.
        db_session.add(
            StatusEvent(
                equipment_record_id=rec_id,
                from_status=None,
                to_status="new_request",
                created_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
    await db_session.flush()

    resp = await client.get(
        "/api/v1/admin/operations",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["total"] >= 1
    rows = body["rows"]
    target = next(r for r in rows if r["id"] == rec_id)
    assert target["status"] == "new_request"
    assert target["status_display"]  # human-readable, non-empty
    assert target["days_in_status"] >= 3


@pytest.mark.asyncio
async def test_filter_by_status_returns_only_matching_rows(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "admin_ops_filter_a@example.com", "admin")
    customer = await _user_with_role(
        client, db_session, "admin_ops_filter_c@example.com", "customer"
    )
    rec_id = await _create_record_for(client, customer["access_token"])

    # Mutate one record's status directly so we have two distinct buckets
    # in the same dataset to filter against.
    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    rec.status = "appraisal_scheduled"
    await db_session.flush()

    resp = await client.get(
        "/api/v1/admin/operations?status=appraisal_scheduled",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(row["status"] == "appraisal_scheduled" for row in body["rows"])
    assert any(row["id"] == rec_id for row in body["rows"])


@pytest.mark.asyncio
async def test_overdue_filter_only_returns_records_past_threshold(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "admin_ops_ovd_a@example.com", "admin")
    customer = await _user_with_role(client, db_session, "admin_ops_ovd_c@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    # Push the entry-into-status event back 10 days; default threshold is 7.
    # Note: equipment_records.updated_at is bumped by a DB trigger on every
    # UPDATE so it can't anchor "stale" — the StatusEvent timestamp is what
    # the dashboard's overdue filter uses.
    se = (
        (
            await db_session.execute(
                select(StatusEvent).where(StatusEvent.equipment_record_id == rec_id)
            )
        )
        .scalars()
        .first()
    )
    if se is not None:
        se.created_at = datetime.now(UTC) - timedelta(days=10)
    else:
        db_session.add(
            StatusEvent(
                equipment_record_id=rec_id,
                from_status=None,
                to_status="new_request",
                created_at=datetime.now(UTC) - timedelta(days=10),
            )
        )
    await db_session.flush()

    resp = await client.get(
        "/api/v1/admin/operations?overdue_only=true",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(row["id"] == rec_id for row in body["rows"]), body
    assert all(row["is_overdue"] for row in body["rows"])


@pytest.mark.asyncio
async def test_csv_export_returns_filtered_text_csv(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "admin_ops_csv_a@example.com", "admin")
    customer = await _user_with_role(client, db_session, "admin_ops_csv_c@example.com", "customer")
    await _create_record_for(client, customer["access_token"])

    resp = await client.get(
        "/api/v1/admin/operations/export.csv",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "operations.csv" in resp.headers.get("content-disposition", "")
    text = resp.text
    # Header row + at least one data row.
    lines = [line for line in text.splitlines() if line]
    assert lines[0].startswith("reference_number,status,status_display,days_in_status,is_overdue")
    assert len(lines) >= 2


@pytest.mark.asyncio
async def test_non_admin_blocked_from_operations(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "admin_ops_sales@example.com", "sales")
    resp = await client.get(
        "/api/v1/admin/operations",
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reporting_role_blocked_from_operations(
    client: AsyncClient, db_session: AsyncSession
):
    reporting = await _user_with_role(
        client, db_session, "admin_ops_reporting@example.com", "reporting"
    )
    resp = await client.get(
        "/api/v1/admin/operations",
        headers=_auth(reporting["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reporting_role_can_access_reports_index(
    client: AsyncClient, db_session: AsyncSession
):
    reporting = await _user_with_role(
        client, db_session, "admin_reports_reporting@example.com", "reporting"
    )
    resp = await client.get(
        "/api/v1/admin/reports",
        headers=_auth(reporting["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(tab["slug"] == "sales_by_period" for tab in body["tabs"])


@pytest.mark.asyncio
async def test_admin_can_access_reports_index(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "admin_reports_admin@example.com", "admin")
    resp = await client.get(
        "/api/v1/admin/reports",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    assert len(resp.json()["tabs"]) == 4


@pytest.mark.asyncio
async def test_customer_blocked_from_reports_index(client: AsyncClient, db_session: AsyncSession):
    customer = await _user_with_role(
        client, db_session, "admin_reports_customer@example.com", "customer"
    )
    resp = await client.get(
        "/api/v1/admin/reports",
        headers=_auth(customer["access_token"]),
    )
    assert resp.status_code == 403
