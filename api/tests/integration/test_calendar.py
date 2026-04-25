# ABOUTME: Phase 3 Sprint 4 — /calendar/events end-to-end: list / create / update / cancel + atomic conflict.
# ABOUTME: Drive-time service is mocked; tests exercise the fallback path that runs without a Google API key.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    CalendarEvent,
    EquipmentRecord,
    NotificationJob,
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
    assert reg.status_code == 201, reg.json()
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
    client: AsyncClient, db: AsyncSession, email: str, *, address: str | None = None
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
    payload = {"photos": []}
    if address:
        payload["location_text"] = address
    resp = await client.post(
        "/api/v1/me/equipment",
        json=payload,
        headers={"Authorization": f"Bearer {tok}"},
    )
    return uuid.UUID(resp.json()["id"])


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


# --- create ---------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_event_happy_path_transitions_record_and_audits(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_create_s@example.com", "sales")
    appraiser = await _user_with_role(
        client, db_session, "cal_create_a@example.com", "appraiser"
    )
    rec_id = await _customer_record(
        client, db_session, "cal_create_c@example.com", address="123 Main St, Atlanta, GA"
    )

    when = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
    resp = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_id),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(when),
            "duration_minutes": 90,
            "site_address": "456 Park Ave, Decatur, GA",
        },
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["appraiser_id"] == appraiser["user_id"]
    assert body["duration_minutes"] == 90

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.status == "appraisal_scheduled"

    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event_type == "calendar_event.created")
        )
    ).scalars().all()
    assert any(a.actor_id == uuid.UUID(sales["user_id"]) for a in audits)

    notifs = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.template == "appraisal_scheduled_appraiser"
            )
        )
    ).scalars().all()
    assert len(notifs) >= 1


@pytest.mark.asyncio
async def test_create_event_rejects_non_appraiser(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_role_s@example.com", "sales")
    not_appraiser = await _user_with_role(
        client, db_session, "cal_role_x@example.com", "sales"
    )
    rec_id = await _customer_record(client, db_session, "cal_role_c@example.com")

    resp = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_id),
            "appraiser_id": not_appraiser["user_id"],
            "scheduled_at": _iso(datetime.now(UTC) + timedelta(days=2)),
        },
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 422
    assert "appraiser" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_blocked_when_record_not_in_new_request(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_st_s@example.com", "sales")
    appraiser = await _user_with_role(
        client, db_session, "cal_st_a@example.com", "appraiser"
    )
    rec_id = await _customer_record(client, db_session, "cal_st_c@example.com")

    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    rec.status = "appraisal_complete"
    await db_session.flush()

    resp = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_id),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(datetime.now(UTC) + timedelta(days=2)),
        },
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 422


# --- conflict detection ---------------------------------------------------- #


@pytest.mark.asyncio
async def test_overlapping_event_for_same_appraiser_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_ov_s@example.com", "sales")
    appraiser = await _user_with_role(
        client, db_session, "cal_ov_a@example.com", "appraiser"
    )
    rec_a = await _customer_record(client, db_session, "cal_ov_c1@example.com")
    rec_b = await _customer_record(client, db_session, "cal_ov_c2@example.com")

    base = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3, hours=10)

    first = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_a),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert first.status_code == 201, first.json()

    second = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_b),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base + timedelta(minutes=30)),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert second.status_code == 409, second.json()
    body = second.json()
    assert body["next_available_at"] is not None
    assert body["conflicting_event_id"] is not None


@pytest.mark.asyncio
async def test_drive_time_buffer_blocks_when_addresses_far_apart(
    client: AsyncClient, db_session: AsyncSession
):
    """Two events same day, far apart — fallback minutes should block them
    if scheduled too close even when the times don't directly overlap."""
    sales = await _user_with_role(client, db_session, "cal_dt_s@example.com", "sales")
    appraiser = await _user_with_role(
        client, db_session, "cal_dt_a@example.com", "appraiser"
    )
    rec_a = await _customer_record(client, db_session, "cal_dt_c1@example.com")
    rec_b = await _customer_record(client, db_session, "cal_dt_c2@example.com")

    base = datetime.now(UTC).replace(microsecond=0) + timedelta(days=4, hours=9)

    # Event A: 9–10am at location 1.
    first = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_a),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
            "site_address": "1 First St, Atlanta, GA",
        },
        headers=_auth(sales["access_token"]),
    )
    assert first.status_code == 201

    # Event B: 10:15am at location 2 — 15 min after A ends. Fallback is 60 min.
    second = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_b),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base + timedelta(minutes=75)),
            "duration_minutes": 60,
            "site_address": "999 Far Out Rd, Macon, GA",
        },
        headers=_auth(sales["access_token"]),
    )
    assert second.status_code == 409
    assert "drive time" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_different_appraisers_no_conflict(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_diff_s@example.com", "sales")
    a1 = await _user_with_role(client, db_session, "cal_diff_a1@example.com", "appraiser")
    a2 = await _user_with_role(client, db_session, "cal_diff_a2@example.com", "appraiser")
    rec1 = await _customer_record(client, db_session, "cal_diff_c1@example.com")
    rec2 = await _customer_record(client, db_session, "cal_diff_c2@example.com")

    base = datetime.now(UTC).replace(microsecond=0) + timedelta(days=5, hours=10)

    r1 = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec1),
            "appraiser_id": a1["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    r2 = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec2),
            "appraiser_id": a2["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert r1.status_code == 201
    assert r2.status_code == 201


# --- update ---------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_patch_reschedule_re_runs_conflict_check(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_patch_s@example.com", "sales")
    appraiser = await _user_with_role(
        client, db_session, "cal_patch_a@example.com", "appraiser"
    )
    rec1 = await _customer_record(client, db_session, "cal_patch_c1@example.com")
    rec2 = await _customer_record(client, db_session, "cal_patch_c2@example.com")

    base = datetime.now(UTC).replace(microsecond=0) + timedelta(days=6, hours=9)

    # Event A 9–10
    a = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec1),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert a.status_code == 201
    # Event B 12–1
    b = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec2),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base + timedelta(hours=3)),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert b.status_code == 201
    b_id = b.json()["id"]

    # Try to move B onto A.
    resp = await client.patch(
        f"/api/v1/calendar/events/{b_id}",
        json={"scheduled_at": _iso(base + timedelta(minutes=30))},
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 409


# --- cancel ---------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cancel_reverts_status_and_emails_both_parties(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_can_s@example.com", "sales")
    appraiser = await _user_with_role(
        client, db_session, "cal_can_a@example.com", "appraiser"
    )
    rec_id = await _customer_record(client, db_session, "cal_can_c@example.com")

    base = datetime.now(UTC).replace(microsecond=0) + timedelta(days=7, hours=10)
    create = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec_id),
            "appraiser_id": appraiser["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    event_id = create.json()["id"]

    cancel = await client.delete(
        f"/api/v1/calendar/events/{event_id}",
        headers=_auth(sales["access_token"]),
    )
    assert cancel.status_code == 200
    assert cancel.json()["cancelled_at"] is not None

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.status == "new_request"

    appraiser_emails = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.template == "appraisal_cancelled_appraiser"
            )
        )
    ).scalars().all()
    customer_emails = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.template == "appraisal_cancelled_customer"
            )
        )
    ).scalars().all()
    assert len(appraiser_emails) >= 1
    assert len(customer_emails) >= 1


# --- list ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_list_filters_by_appraiser_and_window(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "cal_l_s@example.com", "sales")
    a1 = await _user_with_role(client, db_session, "cal_l_a1@example.com", "appraiser")
    a2 = await _user_with_role(client, db_session, "cal_l_a2@example.com", "appraiser")
    rec1 = await _customer_record(client, db_session, "cal_l_c1@example.com")
    rec2 = await _customer_record(client, db_session, "cal_l_c2@example.com")

    base = datetime.now(UTC).replace(microsecond=0) + timedelta(days=8, hours=10)
    e1 = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec1),
            "appraiser_id": a1["user_id"],
            "scheduled_at": _iso(base),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert e1.status_code == 201
    e2 = await client.post(
        "/api/v1/calendar/events",
        json={
            "equipment_record_id": str(rec2),
            "appraiser_id": a2["user_id"],
            "scheduled_at": _iso(base + timedelta(hours=2)),
            "duration_minutes": 60,
        },
        headers=_auth(sales["access_token"]),
    )
    assert e2.status_code == 201

    week_start = base - timedelta(days=1)
    week_end = base + timedelta(days=2)
    listed = await client.get(
        "/api/v1/calendar/events",
        params={"start": _iso(week_start), "end": _iso(week_end)},
        headers=_auth(sales["access_token"]),
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 2

    # Filter to a1 only.
    only_a1 = await client.get(
        "/api/v1/calendar/events",
        params={
            "start": _iso(week_start),
            "end": _iso(week_end),
            "appraiser_id": a1["user_id"],
        },
        headers=_auth(sales["access_token"]),
    )
    a1_body = only_a1.json()
    assert all(e["appraiser_id"] == a1["user_id"] for e in a1_body["events"])


# --- RBAC ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_customer_cannot_access_calendar(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _user_with_role(client, db_session, "cal_rbac@example.com", "customer")
    resp = await client.get(
        "/api/v1/calendar/events",
        params={
            "start": _iso(datetime.now(UTC)),
            "end": _iso(datetime.now(UTC) + timedelta(days=1)),
        },
        headers=_auth(cust["access_token"]),
    )
    assert resp.status_code == 403
