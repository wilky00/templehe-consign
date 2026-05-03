# ABOUTME: Phase 6 Sprint 1 — integration tests for server-side red flag evaluation at submit time.
# ABOUTME: Verifies that management_review_required / hold_for_title_review / marketability are set.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalSubmission,
    CategoryRedFlagRule,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# Helpers — accept plain `db: AsyncSession` (not the pytest fixture name)
# --------------------------------------------------------------------------- #


async def _seed_manager(db: AsyncSession) -> None:
    """Insert a bare active sales_manager user so notification queries return a result."""
    import bcrypt

    hashed = bcrypt.hashpw(_VALID_PASSWORD.encode(), bcrypt.gensalt()).decode()
    email = f"mgr-{_tag()}@example.com"
    role = (await db.execute(select(Role).where(Role.slug == "sales_manager"))).scalar_one()
    user = User(
        email=email,
        password_hash=hashed,
        first_name="Manager",
        last_name="Test",
        status="active",
        role_id=role.id,
    )
    db.add(user)
    await db.flush()


async def _create_appraiser(client: AsyncClient, db: AsyncSession, email: str) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Flag",
                "last_name": "Tester",
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


async def _make_category(db: AsyncSession, slug: str = "flag-test-cat") -> EquipmentCategory:
    cat = EquipmentCategory(name=slug, slug=slug, version=1)
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
        status="appraiser_assigned",
        category_id=category.id,
        reference_number=f"THE-RF{_tag().upper()}",
    )
    db.add(record)
    await db.flush()
    return record


async def _add_rule(
    db: AsyncSession,
    category: EquipmentCategory,
    *,
    condition_field: str,
    condition_operator: str,
    condition_value: str | None = None,
    actions: dict,
    label: str = "Test rule",
) -> CategoryRedFlagRule:
    rule = CategoryRedFlagRule(
        category_id=category.id,
        condition_field=condition_field,
        condition_operator=condition_operator,
        condition_value=condition_value,
        actions=actions,
        label=label,
        active=True,
        version=1,
    )
    db.add(rule)
    await db.flush()
    return rule


async def _submit_draft(
    client: AsyncClient,
    db: AsyncSession,
    *,
    tokens: dict,
    record: EquipmentRecord,
    running_status: str | None = None,
    marketability_rating: str | None = None,
) -> AppraisalSubmission:
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    sub_id = create_resp.json()["id"]

    # Always PATCH to set category_id (so rules load) plus any caller-supplied fields.
    patch_body: dict = {}
    if record.category_id is not None:
        patch_body["category_id"] = str(record.category_id)
    if running_status is not None:
        patch_body["running_status"] = running_status
    if marketability_rating is not None:
        patch_body["marketability_rating"] = marketability_rating
    if patch_body:
        await client.patch(
            f"/api/v1/appraisal-submissions/{sub_id}",
            json=patch_body,
            headers=headers,
        )

    with patch("services.notification_service.enqueue", new_callable=AsyncMock):
        submit_resp = await client.post(
            f"/api/v1/appraisal-submissions/{sub_id}/submit",
            headers=headers,
        )
    assert submit_resp.status_code == 200, submit_resp.text

    await db.refresh(
        (
            await db.execute(select(AppraisalSubmission).where(AppraisalSubmission.id == sub_id))
        ).scalar_one()
    )
    return (
        await db.execute(select(AppraisalSubmission).where(AppraisalSubmission.id == sub_id))
    ).scalar_one()


# --------------------------------------------------------------------------- #
# Tests — use `db_session` as the pytest fixture parameter
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_rules_submission_not_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """With no red flag rules, the submission goes through without flags."""
    tokens = await _create_appraiser(client, db_session, f"noflag-{_tag()}@example.com")
    cat = await _make_category(db_session, "no-flag-cat")
    record = await _make_record(db_session, cat)

    submission = await _submit_draft(client, db_session, tokens=tokens, record=record)
    assert submission.management_review_required is False
    assert submission.hold_for_title_review is False


@pytest.mark.asyncio
async def test_management_review_required_set_by_rule(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A matching equals rule sets management_review_required on the submission."""
    tokens = await _create_appraiser(client, db_session, f"mgmt-review-{_tag()}@example.com")
    cat = await _make_category(db_session, "mgmt-review-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
        label="Non-Running flag",
    )

    submission = await _submit_draft(
        client, db_session, tokens=tokens, record=record, running_status="Non-Running"
    )
    assert submission.management_review_required is True


@pytest.mark.asyncio
async def test_non_running_status_does_not_match_different_value(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"running-{_tag()}@example.com")
    cat = await _make_category(db_session, "running-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
        label="Non-Running flag",
    )

    submission = await _submit_draft(
        client, db_session, tokens=tokens, record=record, running_status="Running"
    )
    assert submission.management_review_required is False


@pytest.mark.asyncio
async def test_marketability_downgraded_by_rule(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A downgrade_marketability action moves the rating one band lower at submit."""
    tokens = await _create_appraiser(client, db_session, f"mktdown-{_tag()}@example.com")
    cat = await _make_category(db_session, "mkt-down-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"downgrade_marketability": True},
        label="Non-Running downgrade",
    )

    submission = await _submit_draft(
        client,
        db_session,
        tokens=tokens,
        record=record,
        running_status="Non-Running",
        marketability_rating="Fast Sell",
    )
    assert submission.marketability_rating == "Average"


@pytest.mark.asyncio
async def test_hold_for_title_review_set_by_rule(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"titlehold-{_tag()}@example.com")
    cat = await _make_category(db_session, "title-hold-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="title_status",
        condition_operator="equals",
        condition_value="missing",
        actions={"hold_for_title_review": True},
        label="Missing title hold",
    )

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    sub_id = create_resp.json()["id"]
    await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={"category_id": str(cat.id), "title_status": "missing"},
        headers=headers,
    )

    with patch("services.notification_service.enqueue", new_callable=AsyncMock):
        submit_resp = await client.post(
            f"/api/v1/appraisal-submissions/{sub_id}/submit", headers=headers
        )
    assert submit_resp.status_code == 200, submit_resp.text

    submission = (
        await db_session.execute(
            select(AppraisalSubmission).where(AppraisalSubmission.id == sub_id)
        )
    ).scalar_one()
    assert submission.hold_for_title_review is True


@pytest.mark.asyncio
async def test_review_notes_appended_by_rule(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"reviewnote-{_tag()}@example.com")
    cat = await _make_category(db_session, "review-note-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="hours_condition",
        condition_operator="equals",
        condition_value="unverified",
        actions={"append_review_note": "Verify hours history before pricing"},
        label="Hours unverified",
    )

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    sub_id = (
        await client.post(
            "/api/v1/appraisal-submissions",
            json={"equipment_record_id": str(record.id)},
            headers=headers,
        )
    ).json()["id"]
    await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={"category_id": str(cat.id), "hours_condition": "unverified"},
        headers=headers,
    )

    with patch("services.notification_service.enqueue", new_callable=AsyncMock):
        submit_resp = await client.post(
            f"/api/v1/appraisal-submissions/{sub_id}/submit", headers=headers
        )
    assert submit_resp.status_code == 200, submit_resp.text

    submission = (
        await db_session.execute(
            select(AppraisalSubmission).where(AppraisalSubmission.id == sub_id)
        )
    ).scalar_one()
    assert submission.review_notes == "Verify hours history before pricing"


@pytest.mark.asyncio
async def test_manager_notification_enqueued_when_review_required(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """When management_review_required fires, notification_service.enqueue is called."""
    tokens = await _create_appraiser(client, db_session, f"notify-mgmt-{_tag()}@example.com")
    cat = await _make_category(db_session, "notify-mgmt-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
        label="Non-Running",
    )

    await _seed_manager(db_session)

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    sub_id = (
        await client.post(
            "/api/v1/appraisal-submissions",
            json={"equipment_record_id": str(record.id)},
            headers=headers,
        )
    ).json()["id"]
    await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={"category_id": str(cat.id), "running_status": "Non-Running"},
        headers=headers,
    )

    with patch("services.notification_service.enqueue", new_callable=AsyncMock) as mock_enqueue:
        submit_resp = await client.post(
            f"/api/v1/appraisal-submissions/{sub_id}/submit", headers=headers
        )
    assert submit_resp.status_code == 200, submit_resp.text
    assert mock_enqueue.called


@pytest.mark.asyncio
async def test_no_manager_notification_when_no_review_required(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"no-notify-{_tag()}@example.com")
    cat = await _make_category(db_session, "no-notify-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
        label="Non-Running",
    )

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    sub_id = (
        await client.post(
            "/api/v1/appraisal-submissions",
            json={"equipment_record_id": str(record.id)},
            headers=headers,
        )
    ).json()["id"]
    await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={"running_status": "Running"},
        headers=headers,
    )

    with patch("services.notification_service.enqueue", new_callable=AsyncMock) as mock_enqueue:
        await client.post(f"/api/v1/appraisal-submissions/{sub_id}/submit", headers=headers)
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_inactive_rule_does_not_fire(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tokens = await _create_appraiser(client, db_session, f"inactive-rule-{_tag()}@example.com")
    cat = await _make_category(db_session, "inactive-rule-cat")
    record = await _make_record(db_session, cat)
    await _add_rule(
        db_session,
        cat,
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
        label="Inactive",
    )
    rule = (
        await db_session.execute(
            select(CategoryRedFlagRule).where(CategoryRedFlagRule.category_id == cat.id)
        )
    ).scalar_one()
    rule.active = False
    await db_session.flush()

    submission = await _submit_draft(
        client, db_session, tokens=tokens, record=record, running_status="Non-Running"
    )
    assert submission.management_review_required is False


@pytest.mark.asyncio
async def test_submission_without_category_skips_rule_evaluation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A submission with no category set does not error — evaluation is skipped."""
    tokens = await _create_appraiser(client, db_session, f"no-cat-{_tag()}@example.com")
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db_session.add(customer)
    await db_session.flush()
    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraiser_assigned",
        reference_number=f"THE-NOCAT{_tag().upper()[:6]}",
    )
    db_session.add(record)
    await db_session.flush()

    submission = await _submit_draft(client, db_session, tokens=tokens, record=record)
    assert submission.management_review_required is False
    assert submission.hold_for_title_review is False
