# ABOUTME: Phase 4 Sprint 6 — admin CRUD over /admin/categories with versioning + hard-delete guard.
# ABOUTME: Confirms RBAC, version increments, and the "active records block delete" path.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)

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
                "first_name": "Cat",
                "last_name": "Admin",
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


def _slug(prefix: str = "cat") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_create_then_get_returns_detail_with_empty_collections(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cat_a@example.com", "admin")
    slug = _slug()
    resp = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Forklifts", "slug": slug, "display_order": 5},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["name"] == "Forklifts"
    assert body["slug"] == slug
    assert body["version"] == 1
    assert body["components"] == []
    assert body["weight_warning"] is False  # 0 != 100 but no components yet — see below

    # GET reflects the same.
    cat_id = body["id"]
    resp2 = await client.get(
        f"/api/v1/admin/categories/{cat_id}", headers=_auth(admin["access_token"])
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == cat_id


@pytest.mark.asyncio
async def test_create_duplicate_slug_returns_409(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cat_b@example.com", "admin")
    slug = _slug()
    r1 = await client.post(
        "/api/v1/admin/categories",
        json={"name": "First", "slug": slug},
        headers=_auth(admin["access_token"]),
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Dup", "slug": slug},
        headers=_auth(admin["access_token"]),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_rename_supersedes_and_increments_version(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cat_c@example.com", "admin")
    slug = _slug()
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Skid", "slug": slug},
        headers=_auth(admin["access_token"]),
    )
    v1_id = create.json()["id"]
    patch = await client.patch(
        f"/api/v1/admin/categories/{v1_id}",
        json={"name": "Skid Steer Loaders"},
        headers=_auth(admin["access_token"]),
    )
    assert patch.status_code == 200, patch.json()
    body = patch.json()
    assert body["version"] == 2
    assert body["name"] == "Skid Steer Loaders"
    assert body["id"] != v1_id

    # The list endpoint shows only the current version.
    listed = await client.get("/api/v1/admin/categories", headers=_auth(admin["access_token"]))
    cats = listed.json()["categories"]
    matches = [c for c in cats if c["slug"] == slug]
    assert len(matches) == 1
    assert matches[0]["id"] == body["id"]


@pytest.mark.asyncio
async def test_component_weights_under_100_emit_warning(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cat_d@example.com", "admin")
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Excavators", "slug": _slug()},
        headers=_auth(admin["access_token"]),
    )
    cat_id = create.json()["id"]
    for name, weight in [("Engine", 30), ("Hydraulics", 30), ("Body", 25)]:
        await client.post(
            f"/api/v1/admin/categories/{cat_id}/components",
            json={"name": name, "weight_pct": weight},
            headers=_auth(admin["access_token"]),
        )
    resp = await client.get(
        f"/api/v1/admin/categories/{cat_id}", headers=_auth(admin["access_token"])
    )
    body = resp.json()
    assert body["weight_total"] == 85.0
    assert body["weight_warning"] is True


@pytest.mark.asyncio
async def test_component_weights_at_100_no_warning(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cat_e@example.com", "admin")
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Loaders", "slug": _slug()},
        headers=_auth(admin["access_token"]),
    )
    cat_id = create.json()["id"]
    for name, weight in [("Engine", 50), ("Body", 50)]:
        await client.post(
            f"/api/v1/admin/categories/{cat_id}/components",
            json={"name": name, "weight_pct": weight},
            headers=_auth(admin["access_token"]),
        )
    body = (
        await client.get(f"/api/v1/admin/categories/{cat_id}", headers=_auth(admin["access_token"]))
    ).json()
    assert body["weight_total"] == 100.0
    assert body["weight_warning"] is False


@pytest.mark.asyncio
async def test_inspection_prompt_edit_supersedes(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cat_f@example.com", "admin")
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Backhoes", "slug": _slug()},
        headers=_auth(admin["access_token"]),
    )
    cat_id = create.json()["id"]
    add = await client.post(
        f"/api/v1/admin/categories/{cat_id}/inspection-prompts",
        json={"label": "Hour meter?", "response_type": "text"},
        headers=_auth(admin["access_token"]),
    )
    prompt_id = add.json()["inspection_prompts"][0]["id"]
    edit = await client.patch(
        f"/api/v1/admin/categories/{cat_id}/inspection-prompts/{prompt_id}",
        json={"label": "Hours on meter?"},
        headers=_auth(admin["access_token"]),
    )
    assert edit.status_code == 200
    prompts = edit.json()["inspection_prompts"]
    assert len(prompts) == 1
    assert prompts[0]["label"] == "Hours on meter?"
    assert prompts[0]["version"] == 2
    assert prompts[0]["id"] != prompt_id


@pytest.mark.asyncio
async def test_delete_blocked_when_records_reference_category(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cat_g@example.com", "admin")
    cust_user = await _user_with_role(client, db_session, "ac_cat_g_cust@example.com", "customer")
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Tractors", "slug": _slug()},
        headers=_auth(admin["access_token"]),
    )
    cat_id = uuid.UUID(create.json()["id"])

    customer = Customer(
        user_id=uuid.UUID(cust_user["user_id"]),
        submitter_name="Cust",
    )
    db_session.add(customer)
    await db_session.flush()

    rec = EquipmentRecord(
        customer_id=customer.id,
        category_id=cat_id,
        status="new_request",
    )
    db_session.add(rec)
    await db_session.flush()

    resp = await client.delete(
        f"/api/v1/admin/categories/{cat_id}", headers=_auth(admin["access_token"])
    )
    assert resp.status_code == 409
    assert "1 equipment record" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_succeeds_when_no_records(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cat_h@example.com", "admin")
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Cranes", "slug": _slug()},
        headers=_auth(admin["access_token"]),
    )
    cat_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/admin/categories/{cat_id}", headers=_auth(admin["access_token"])
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is not None


@pytest.mark.asyncio
async def test_deactivate_marks_status_inactive_and_supersedes(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cat_i@example.com", "admin")
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Compactors", "slug": _slug()},
        headers=_auth(admin["access_token"]),
    )
    v1_id = create.json()["id"]
    resp = await client.post(
        f"/api/v1/admin/categories/{v1_id}/deactivate",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "inactive"
    assert body["version"] == 2


@pytest.mark.asyncio
async def test_non_admin_cannot_create(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "ac_cat_sales@example.com", "sales")
    resp = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Nope", "slug": _slug()},
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_partial_unique_slug_index_blocks_concurrent_current(
    db_session: AsyncSession,
):
    """Two un-superseded rows with the same slug must violate the partial unique index."""
    slug = _slug()
    a = EquipmentCategory(name="A", slug=slug, status="active")
    db_session.add(a)
    await db_session.flush()
    b = EquipmentCategory(name="B", slug=slug, status="active")
    db_session.add(b)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
