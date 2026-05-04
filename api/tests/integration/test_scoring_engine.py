# ABOUTME: Phase 6 Sprint 1 — integration tests for scoring engine via submission update.
# ABOUTME: Verifies score calculation, band labels, and score persistence via submission service.
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    CategoryComponent,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _create_appraiser(client: AsyncClient, db: AsyncSession, email: str) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Appraiser",
                "last_name": "Test",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == "appraiser"))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    db.add(user)
    await db.flush()
    from services import user_roles_service

    await user_roles_service.grant(db, user=user, role_slug="appraiser", granted_by=None)
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return resp.json()


async def _make_category_with_components(
    db: AsyncSession,
    *,
    weight_a: float = 60.0,
    weight_b: float = 40.0,
) -> tuple[EquipmentCategory, CategoryComponent, CategoryComponent]:
    """Create a category with two components for scoring tests."""
    cat = EquipmentCategory(name="ScoreTestCat", slug="score-test-cat", version=1)
    db.add(cat)
    await db.flush()
    comp_a = CategoryComponent(
        category_id=cat.id,
        name="Engine",
        weight_pct=weight_a,
        display_order=1,
    )
    comp_b = CategoryComponent(
        category_id=cat.id,
        name="Undercarriage",
        weight_pct=weight_b,
        display_order=2,
    )
    db.add_all([comp_a, comp_b])
    await db.flush()
    return cat, comp_a, comp_b


async def _make_record(db: AsyncSession, *, category: EquipmentCategory) -> EquipmentRecord:
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()
    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraiser_assigned",
        category_id=category.id,
        reference_number=f"THE-SCORE{_tag().upper()[:6]}",
    )
    db.add(record)
    await db.flush()
    return record


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_component_scores_calculate_weighted_average(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Updating component scores persists the weighted average on the submission."""
    tokens = await _create_appraiser(client, db_session, f"scorer1-{_tag()}@example.com")
    cat, comp_a, comp_b = await _make_category_with_components(
        db_session, weight_a=60.0, weight_b=40.0
    )
    record = await _make_record(db_session, category=cat)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    sub_id = create_resp.json()["id"]

    # 5.0 at weight 60 + 3.0 at weight 40 → (5.0*60 + 3.0*40) / 100 = 4.20
    update_resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "component_scores": [
                {"component_id": str(comp_a.id), "score": 5.0},
                {"component_id": str(comp_b.id), "score": 3.0},
            ]
        },
        headers=headers,
    )
    assert update_resp.status_code == 200, update_resp.text
    body = update_resp.json()
    assert Decimal(body["overall_score"]) == Decimal("4.20")
    assert body["score_band"] == "Strong resale candidate"


@pytest.mark.asyncio
async def test_perfect_score_gives_premium_band(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"scorer2-{_tag()}@example.com")
    cat, comp_a, comp_b = await _make_category_with_components(db_session)
    record = await _make_record(db_session, category=cat)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    sub_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "component_scores": [
                {"component_id": str(comp_a.id), "score": 5.0},
                {"component_id": str(comp_b.id), "score": 5.0},
            ]
        },
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert update_resp.json()["score_band"] == "Premium resale-ready"


@pytest.mark.asyncio
async def test_low_score_gives_insufficient_data_band(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"scorer3-{_tag()}@example.com")
    cat, comp_a, comp_b = await _make_category_with_components(db_session)
    record = await _make_record(db_session, category=cat)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    sub_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "component_scores": [
                {"component_id": str(comp_a.id), "score": 0.5},
                {"component_id": str(comp_b.id), "score": 0.5},
            ]
        },
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert update_resp.json()["score_band"] == "Insufficient data"


@pytest.mark.asyncio
async def test_score_recalculates_on_each_update(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Re-patching component scores updates the stored overall_score each time."""
    tokens = await _create_appraiser(client, db_session, f"scorer4-{_tag()}@example.com")
    cat, comp_a, comp_b = await _make_category_with_components(
        db_session, weight_a=50.0, weight_b=50.0
    )
    record = await _make_record(db_session, category=cat)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    sub_id = (
        await client.post(
            "/api/v1/appraisal-submissions",
            json={"equipment_record_id": str(record.id)},
            headers=headers,
        )
    ).json()["id"]

    # First update: 3.0 + 3.0 → 3.00
    r1 = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "component_scores": [
                {"component_id": str(comp_a.id), "score": 3.0},
                {"component_id": str(comp_b.id), "score": 3.0},
            ]
        },
        headers=headers,
    )
    assert Decimal(r1.json()["overall_score"]) == Decimal("3.00")

    # Second update: 5.0 + 5.0 → 5.00
    r2 = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "component_scores": [
                {"component_id": str(comp_a.id), "score": 5.0},
                {"component_id": str(comp_b.id), "score": 5.0},
            ]
        },
        headers=headers,
    )
    assert Decimal(r2.json()["overall_score"]) == Decimal("5.00")
    assert r2.json()["score_band"] == "Premium resale-ready"


@pytest.mark.asyncio
async def test_mismatched_weights_normalize_silently(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Weights summing to 60 instead of 100 still produce a correct 0–5 result."""
    tokens = await _create_appraiser(client, db_session, f"scorer5-{_tag()}@example.com")
    cat, comp_a, comp_b = await _make_category_with_components(
        db_session, weight_a=30.0, weight_b=30.0
    )
    record = await _make_record(db_session, category=cat)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    sub_id = (
        await client.post(
            "/api/v1/appraisal-submissions",
            json={"equipment_record_id": str(record.id)},
            headers=headers,
        )
    ).json()["id"]

    r = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "component_scores": [
                {"component_id": str(comp_a.id), "score": 4.0},
                {"component_id": str(comp_b.id), "score": 4.0},
            ]
        },
        headers=headers,
    )
    body = r.json()
    # Weights normalize: 30/60 * 4.0 + 30/60 * 4.0 = 4.0
    assert Decimal(body["overall_score"]) == Decimal("4.00")
    assert r.status_code == 200
