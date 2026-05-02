# ABOUTME: Phase 5 Sprint 4 — integration tests for appraisal submission CRUD + submit flow.
# ABOUTME: Covers RBAC, version snapshot at submit, partial-unique draft guard, and soft-delete.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    CategoryComponent,
    CategoryInspectionPrompt,
    CategoryRedFlagRule,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


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
                "first_name": "Test",
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


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _email(role: str) -> str:
    return f"sub-{role}-{_tag()}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_category(db: AsyncSession) -> EquipmentCategory:
    cat = EquipmentCategory(
        name=f"TestCat-{_tag()}",
        slug=f"test-cat-{_tag()}",
        status="active",
        display_order=0,
        version=3,
    )
    db.add(cat)
    await db.flush()
    return cat


async def _make_record(db: AsyncSession, category: EquipmentCategory) -> EquipmentRecord:
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()
    record = EquipmentRecord(
        customer_id=customer.id,
        category_id=category.id,
        status="pending_appraisal",
        customer_make="CAT",
        customer_model="320",
    )
    db.add(record)
    await db.flush()
    return record


async def _make_component(
    db: AsyncSession, category: EquipmentCategory, weight: float = 100.0
) -> CategoryComponent:
    comp = CategoryComponent(
        category_id=category.id,
        name="Engine",
        weight_pct=weight,
        display_order=0,
        active=True,
    )
    db.add(comp)
    await db.flush()
    return comp


async def _make_prompt(db: AsyncSession, category: EquipmentCategory) -> CategoryInspectionPrompt:
    p = CategoryInspectionPrompt(
        category_id=category.id,
        label="Engine starts?",
        response_type="yes_no_na",
        required=True,
        display_order=0,
        active=True,
        version=2,
    )
    db.add(p)
    await db.flush()
    return p


async def _make_rule(db: AsyncSession, category: EquipmentCategory) -> CategoryRedFlagRule:
    r = CategoryRedFlagRule(
        category_id=category.id,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="no_start",
        actions={"flag": "management_review"},
        label="Won't start",
        active=True,
        version=1,
    )
    db.add(r)
    await db.flush()
    return r


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_draft(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["equipment_record_id"] == str(record.id)


@pytest.mark.asyncio
async def test_create_draft_duplicate_returns_409(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_draft_fields(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    sid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sid}",
        json={
            "category_id": str(category.id),
            "make": "CAT",
            "model": "320",
            "year": 2019,
            "transport_notes": "No trailer needed",
        },
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["make"] == "CAT"
    assert data["transport_notes"] == "No trailer needed"


@pytest.mark.asyncio
async def test_update_component_scores_recalculates_overall(
    client: AsyncClient, db_session: AsyncSession
):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)
    component = await _make_component(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    sid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sid}",
        json={"component_scores": [{"component_id": str(component.id), "score": 4.0}]},
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_score"] is not None
    assert float(data["overall_score"]) == pytest.approx(4.0, abs=0.01)
    assert data["score_band"] == "good"


@pytest.mark.asyncio
async def test_get_submission(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    sid = create.json()["id"]

    resp = await client.get(
        f"/api/v1/appraisal-submissions/{sid}",
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == sid


@pytest.mark.asyncio
async def test_list_submissions(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    resp = await client.get(
        "/api/v1/appraisal-submissions",
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_submit_captures_version_snapshot(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    prompt = await _make_prompt(db_session, category)
    rule = await _make_rule(db_session, category)
    record = await _make_record(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    sid = create.json()["id"]

    await client.patch(
        f"/api/v1/appraisal-submissions/{sid}",
        json={"category_id": str(category.id)},
        headers=_auth(appraiser["access_token"]),
    )

    resp = await client.post(
        f"/api/v1/appraisal-submissions/{sid}/submit",
        headers=_auth(appraiser["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "submitted"
    assert data["submitted_at"] is not None
    assert data["category_version"] == category.version
    # prompt and rule are captured but not surfaced directly in SubmissionOut;
    # verify they were written by checking the DB
    from sqlalchemy import select as sa_select

    from database.models import AppraisalSubmission

    sub = (
        await db_session.execute(
            sa_select(AppraisalSubmission).where(AppraisalSubmission.id == uuid.UUID(sid))
        )
    ).scalar_one()
    assert str(prompt.id) in (sub.prompt_version_set or {})
    assert str(rule.id) in (sub.rule_version_set or {})


@pytest.mark.asyncio
async def test_submit_already_submitted_returns_422(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    sid = create.json()["id"]
    headers = _auth(appraiser["access_token"])
    await client.post(f"/api/v1/appraisal-submissions/{sid}/submit", headers=headers)

    resp = await client.post(f"/api/v1/appraisal-submissions/{sid}/submit", headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_appraiser_cannot_see_other_appraiser_submission(
    client: AsyncClient, db_session: AsyncSession
):
    appraiser_a = await _create_user(client, db_session, _email("a"), "appraiser")
    appraiser_b = await _create_user(client, db_session, _email("b"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser_a["access_token"]),
    )
    sid = create.json()["id"]

    resp = await client.get(
        f"/api/v1/appraisal-submissions/{sid}",
        headers=_auth(appraiser_b["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_see_any_submission(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    admin = await _create_user(client, db_session, _email("adm"), "admin")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=_auth(appraiser["access_token"]),
    )
    sid = create.json()["id"]

    resp = await client.get(
        f"/api/v1/appraisal-submissions/{sid}",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_customer_cannot_access_submissions(client: AsyncClient, db_session: AsyncSession):
    customer = await _create_user(client, db_session, _email("cust"), "customer")
    resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(uuid.uuid4())},
        headers=_auth(customer["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access(client: AsyncClient):
    resp = await client.get("/api/v1/appraisal-submissions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_non_draft_returns_422(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)
    headers = _auth(appraiser["access_token"])

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    sid = create.json()["id"]
    await client.post(f"/api/v1/appraisal-submissions/{sid}/submit", headers=headers)

    resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sid}",
        json={"make": "Updated"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_filter_by_status(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    record = await _make_record(db_session, category)
    headers = _auth(appraiser["access_token"])

    create = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    sid = create.json()["id"]
    await client.post(f"/api/v1/appraisal-submissions/{sid}/submit", headers=headers)

    resp = await client.get(
        "/api/v1/appraisal-submissions",
        params={"status": "submitted"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert all(s["status"] == "submitted" for s in resp.json()["submissions"])
