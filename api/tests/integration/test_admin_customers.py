# ABOUTME: Phase 4 Sprint 2 — admin CRUD over /admin/customers + walk-in create + invite send.
# ABOUTME: Soft-delete cascade to equipment_records + audit_log diffs + invite-email guard.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, Customer, EquipmentRecord, Role, User

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
                "first_name": "Cust",
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


async def _create_record_for(client: AsyncClient, token: str) -> str:
    resp = await client.post("/api/v1/me/equipment", json={"photos": []}, headers=_auth(token))
    assert resp.status_code in (200, 201), resp.json()
    return resp.json()["id"]


# --- list / get ----------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_customers_includes_registered_and_walkins(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin1@example.com", "admin")
    cust = await _user_with_role(client, db_session, "ac_cust1@example.com", "customer")
    await _create_record_for(client, cust["access_token"])

    # Create a walk-in directly via the endpoint.
    walkin_resp = await client.post(
        "/api/v1/admin/customers",
        json={
            "submitter_name": "Walking Wally",
            "invite_email": "wally@example.com",
            "business_name": "Wally Excavation LLC",
        },
        headers=_auth(admin["access_token"]),
    )
    assert walkin_resp.status_code == 201, walkin_resp.json()

    resp = await client.get("/api/v1/admin/customers", headers=_auth(admin["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    walkin_rows = [c for c in body["customers"] if c["is_walkin"]]
    assert any(c["invite_email"] == "wally@example.com" for c in walkin_rows)
    registered_rows = [c for c in body["customers"] if not c["is_walkin"]]
    assert any(c["user_email"] == "ac_cust1@example.com" for c in registered_rows)


@pytest.mark.asyncio
async def test_list_customers_filter_walkins_only(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_admin2@example.com", "admin")
    await _user_with_role(client, db_session, "ac_cust2@example.com", "customer")
    await client.post(
        "/api/v1/admin/customers",
        json={"submitter_name": "Solo Walkin", "invite_email": "solo@example.com"},
        headers=_auth(admin["access_token"]),
    )

    resp = await client.get(
        "/api/v1/admin/customers?walkins_only=true",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(c["is_walkin"] for c in body["customers"])


@pytest.mark.asyncio
async def test_list_customers_search_by_name_and_email(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin3@example.com", "admin")
    await client.post(
        "/api/v1/admin/customers",
        json={
            "submitter_name": "Searchable Susan",
            "invite_email": "susan@example.com",
            "business_name": "Susan's Construction",
        },
        headers=_auth(admin["access_token"]),
    )

    by_name = await client.get(
        "/api/v1/admin/customers?search=susan",
        headers=_auth(admin["access_token"]),
    )
    assert by_name.status_code == 200
    assert any("susan" in (c["submitter_name"] or "").lower() for c in by_name.json()["customers"])


@pytest.mark.asyncio
async def test_get_customer_returns_equipment_summary(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin4@example.com", "admin")
    cust = await _user_with_role(client, db_session, "ac_cust4@example.com", "customer")
    await _create_record_for(client, cust["access_token"])

    customer = (
        await db_session.execute(select(Customer).where(Customer.user_id == cust["user_id"]))
    ).scalar_one()
    resp = await client.get(
        f"/api/v1/admin/customers/{customer.id}",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_email"] == "ac_cust4@example.com"
    assert len(body["equipment_records"]) == 1


# --- update --------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_patch_customer_writes_audit_log_diff(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_admin5@example.com", "admin")
    cust = await _user_with_role(client, db_session, "ac_cust5@example.com", "customer")
    await _create_record_for(client, cust["access_token"])  # materializes Customer
    customer = (
        await db_session.execute(select(Customer).where(Customer.user_id == cust["user_id"]))
    ).scalar_one()

    resp = await client.patch(
        f"/api/v1/admin/customers/{customer.id}",
        json={"business_name": "Brand New Co", "address_state": "tx"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["business_name"] == "Brand New Co"
    assert body["address_state"] == "TX"

    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "customer.admin_update")
            .where(AuditLog.target_id == customer.id)
        )
    ).scalar_one()
    assert audit.actor_role == "admin"
    assert audit.before_state["business_name"] is None
    assert audit.after_state["business_name"] == "Brand New Co"
    assert audit.after_state["address_state"] == "TX"


@pytest.mark.asyncio
async def test_patch_customer_rejects_bad_invite_email(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin6@example.com", "admin")
    cust = await _user_with_role(client, db_session, "ac_cust6@example.com", "customer")
    await _create_record_for(client, cust["access_token"])  # materializes Customer
    customer = (
        await db_session.execute(select(Customer).where(Customer.user_id == cust["user_id"]))
    ).scalar_one()

    resp = await client.patch(
        f"/api/v1/admin/customers/{customer.id}",
        json={"invite_email": "not-an-email"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_customer_404_when_missing(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_admin7@example.com", "admin")
    fake = uuid.uuid4()
    resp = await client.patch(
        f"/api/v1/admin/customers/{fake}",
        json={"business_name": "X"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


# --- soft delete ----------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_customer_cascades_to_equipment_records(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin8@example.com", "admin")
    cust = await _user_with_role(client, db_session, "ac_cust8@example.com", "customer")
    rec_id = await _create_record_for(client, cust["access_token"])
    customer = (
        await db_session.execute(select(Customer).where(Customer.user_id == cust["user_id"]))
    ).scalar_one()

    resp = await client.delete(
        f"/api/v1/admin/customers/{customer.id}",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["is_deleted"] is True

    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert rec.deleted_at is not None

    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "customer.admin_soft_delete")
            .where(AuditLog.target_id == customer.id)
        )
    ).scalar_one()
    assert str(rec.id) in audit.after_state["cascaded_record_ids"]


# --- walk-in creation ----------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_walkin_persists_with_null_user_id(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin9@example.com", "admin")
    resp = await client.post(
        "/api/v1/admin/customers",
        json={
            "submitter_name": "New Walkin",
            "invite_email": "newwalkin@example.com",
            "business_name": "Field & Forklift",
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["is_walkin"] is True
    assert body["user_id"] is None
    assert body["invite_email"] == "newwalkin@example.com"

    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "customer.admin_walkin_created")
            .where(AuditLog.target_id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert audit.actor_role == "admin"
    assert audit.after_state["invite_email"] == "newwalkin@example.com"


@pytest.mark.asyncio
async def test_create_walkin_rejects_invalid_email(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_admin10@example.com", "admin")
    resp = await client.post(
        "/api/v1/admin/customers",
        json={"submitter_name": "Bad Email", "invite_email": "not an email"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422


# --- send invite --------------------------------------------------------- #


@pytest.mark.asyncio
async def test_send_invite_dispatches_walkin_invite_email(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin11@example.com", "admin")
    walkin = await client.post(
        "/api/v1/admin/customers",
        json={"submitter_name": "Wally", "invite_email": "wally2@example.com"},
        headers=_auth(admin["access_token"]),
    )
    customer_id = walkin.json()["id"]

    with patch(
        "services.email_service.send_walkin_invite_email", new_callable=AsyncMock
    ) as mock_send:
        resp = await client.post(
            f"/api/v1/admin/customers/{customer_id}/send-invite",
            headers=_auth(admin["access_token"]),
        )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["invite_email"] == "wally2@example.com"
    # BackgroundTasks runs the dispatch after the response is built.
    mock_send.assert_awaited_once()
    args, _ = mock_send.call_args
    assert args[0] == "wally2@example.com"  # to_email
    assert "/register?email=wally2@example.com" in args[1]  # register_url

    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "customer.admin_invite_sent")
            .where(AuditLog.target_id == uuid.UUID(customer_id))
        )
    ).scalar_one()
    assert audit.after_state["invite_email"] == "wally2@example.com"


@pytest.mark.asyncio
async def test_send_invite_409_for_registered_customer(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_admin12@example.com", "admin")
    cust = await _user_with_role(client, db_session, "ac_cust12@example.com", "customer")
    await _create_record_for(client, cust["access_token"])  # materializes Customer
    customer = (
        await db_session.execute(select(Customer).where(Customer.user_id == cust["user_id"]))
    ).scalar_one()

    resp = await client.post(
        f"/api/v1/admin/customers/{customer.id}/send-invite",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 409


# --- RBAC --------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_customers_blocked_for_sales_role(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "ac_sales@example.com", "sales")
    resp = await client.get("/api/v1/admin/customers", headers=_auth(sales["access_token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_walkin_blocked_for_reporting_role(
    client: AsyncClient, db_session: AsyncSession
):
    reporting = await _user_with_role(client, db_session, "ac_reporting@example.com", "reporting")
    resp = await client.post(
        "/api/v1/admin/customers",
        json={"submitter_name": "Try", "invite_email": "try@example.com"},
        headers=_auth(reporting["access_token"]),
    )
    assert resp.status_code == 403
