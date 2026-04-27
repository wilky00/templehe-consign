# ABOUTME: Phase 4 Sprint 5 — equipment record watchers CRUD + dispatch fan-out.
# ABOUTME: Watchers receive customer-facing status emails; missing/inactive watchers are skipped.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    EquipmentRecordWatcher,
    NotificationJob,
    Role,
    User,
)
from services import equipment_status_service

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
                "first_name": "W",
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
    return body


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _create_record(client: AsyncClient, token: str) -> str:
    resp = await client.post("/api/v1/me/equipment", json={"photos": []}, headers=_auth(token))
    assert resp.status_code in (200, 201)
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_admin_adds_and_lists_watcher(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "w_admin1@example.com", "admin")
    cust = await _user_with_role(client, db_session, "w_cust1@example.com", "customer")
    rep = await _user_with_role(client, db_session, "w_rep1@example.com", "sales")
    rec_id = await _create_record(client, cust["access_token"])

    add = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        json={"user_id": rep["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    assert add.status_code == 201, add.json()
    assert add.json()["user_id"] == rep["user_id"]

    listed = await client.get(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        headers=_auth(admin["access_token"]),
    )
    body = listed.json()
    assert len(body["watchers"]) == 1
    assert body["watchers"][0]["email"] == "w_rep1@example.com"


@pytest.mark.asyncio
async def test_add_watcher_idempotent(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "w_admin2@example.com", "admin")
    cust = await _user_with_role(client, db_session, "w_cust2@example.com", "customer")
    rep = await _user_with_role(client, db_session, "w_rep2@example.com", "sales")
    rec_id = await _create_record(client, cust["access_token"])

    a = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        json={"user_id": rep["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    b = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        json={"user_id": rep["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    assert a.status_code == 201
    assert b.status_code == 201  # idempotent — same row returned
    rows = (
        (
            await db_session.execute(
                select(EquipmentRecordWatcher).where(EquipmentRecordWatcher.record_id == rec_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_remove_watcher_returns_204(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "w_admin3@example.com", "admin")
    cust = await _user_with_role(client, db_session, "w_cust3@example.com", "customer")
    rep = await _user_with_role(client, db_session, "w_rep3@example.com", "sales")
    rec_id = await _create_record(client, cust["access_token"])

    await client.post(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        json={"user_id": rep["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    resp = await client.delete(
        f"/api/v1/admin/equipment/{rec_id}/watchers/{rep['user_id']}",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 204
    rows = (
        (
            await db_session.execute(
                select(EquipmentRecordWatcher).where(EquipmentRecordWatcher.record_id == rec_id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_watcher_receives_status_update_email(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "w_admin4@example.com", "admin")
    cust = await _user_with_role(client, db_session, "w_cust4@example.com", "customer")
    rep = await _user_with_role(client, db_session, "w_rep4@example.com", "sales")
    rec_id = await _create_record(client, cust["access_token"])

    await client.post(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        json={"user_id": rep["user_id"]},
        headers=_auth(admin["access_token"]),
    )

    # Fire a customer-facing transition. Customer + watcher should both
    # receive a notification.
    from database.models import EquipmentRecord

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    customer_user = (
        await db_session.execute(select(User).where(User.email == "w_cust4@example.com"))
    ).scalar_one()
    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraisal_scheduled",
        changed_by=None,
        customer=customer_user,
    )

    watcher_jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(NotificationJob.template == "status_update_watcher")
            )
        )
        .scalars()
        .all()
    )
    assert len(watcher_jobs) == 1
    assert watcher_jobs[0].user_id == uuid.UUID(rep["user_id"])
    assert watcher_jobs[0].payload["to_email"] == "w_rep4@example.com"


@pytest.mark.asyncio
async def test_remove_nonexistent_watcher_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "w_admin5@example.com", "admin")
    cust = await _user_with_role(client, db_session, "w_cust5@example.com", "customer")
    rec_id = await _create_record(client, cust["access_token"])
    fake_user = uuid.uuid4()
    resp = await client.delete(
        f"/api/v1/admin/equipment/{rec_id}/watchers/{fake_user}",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_watchers_blocked_for_non_admin(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "w_sales@example.com", "sales")
    cust = await _user_with_role(client, db_session, "w_cust_rb@example.com", "customer")
    rec_id = await _create_record(client, cust["access_token"])
    resp = await client.get(
        f"/api/v1/admin/equipment/{rec_id}/watchers",
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403
