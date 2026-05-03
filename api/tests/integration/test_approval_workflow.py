# ABOUTME: Phase 6 Sprint 2 — integration tests for the manager approval workflow.
# ABOUTME: Covers queue listing, approve/reject status transitions, RBAC, audit log, notifications.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalSubmission,
    AuditLog,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    NotificationJob,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


async def _create_user(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email: str,
    role_slug: str,
) -> dict:
    """Register + activate + grant role + login; returns access token dict."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Test",
                "last_name": role_slug.replace("_", " ").title(),
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
    return resp.json()


async def _make_category(db: AsyncSession) -> EquipmentCategory:
    cat = EquipmentCategory(
        name=f"ApprovalTestCat-{_tag()}",
        slug=f"approval-test-{_tag()}",
        version=1,
    )
    db.add(cat)
    await db.flush()
    return cat


async def _make_record(
    db: AsyncSession,
    *,
    category: EquipmentCategory,
    status: str = "appraiser_assigned",
) -> EquipmentRecord:
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()
    record = EquipmentRecord(
        customer_id=customer.id,
        status=status,
        category_id=category.id,
        reference_number=f"THE-APV{_tag().upper()[:5]}",
    )
    db.add(record)
    await db.flush()
    return record


async def _submit_appraisal(
    client: AsyncClient,
    db: AsyncSession,
    *,
    appraiser_tokens: dict,
    record: EquipmentRecord,
) -> str:
    """Create a draft, patch category, and submit it. Returns submission_id."""
    headers = {"Authorization": f"Bearer {appraiser_tokens['access_token']}"}

    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    sub_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={
            "category_id": str(record.category_id),
            "make": "Caterpillar",
            "model": "320",
        },
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text

    submit_resp = await client.post(
        f"/api/v1/appraisal-submissions/{sub_id}/submit",
        headers=headers,
    )
    assert submit_resp.status_code == 200, submit_resp.text
    return sub_id


# --------------------------------------------------------------------------- #
# Queue tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_approval_queue_shows_submitted_appraisals(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """After an appraiser submits, the record appears in the manager approval queue."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-q1-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-q1-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)

    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.get("/api/v1/manager/approvals", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [item["submission_id"] for item in body["items"]]
    assert sub_id in ids


@pytest.mark.asyncio
async def test_approval_queue_rbac_appraiser_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Appraisers cannot access the manager approval queue."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-q2-{_tag()}@example.com", role_slug="appraiser"
    )
    headers = {"Authorization": f"Bearer {appraiser_tokens['access_token']}"}
    resp = await client.get("/api/v1/manager/approvals", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approval_queue_only_shows_submitted_status(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A draft that was never submitted does not appear in the queue."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-q3-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-q3-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)

    # Create a draft but do not submit it
    headers = {"Authorization": f"Bearer {appraiser_tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers,
    )
    assert create_resp.status_code == 201
    draft_id = create_resp.json()["id"]

    mgr_headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.get("/api/v1/manager/approvals", headers=mgr_headers)
    ids = [item["submission_id"] for item in resp.json()["items"]]
    assert draft_id not in ids


# --------------------------------------------------------------------------- #
# Approve tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_approve_transitions_submission_and_record_status(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Approve sets submission → approved and equipment record → approved_pending_esign."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-a1-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-a1-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)

    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/approve",
        json={"purchase_offer": "15000.00", "consignment_price": "18500.00"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"
    assert body["approved_purchase_offer"] == "15000.00"
    assert body["suggested_consignment_price"] == "18500.00"

    await db_session.refresh(record)
    assert record.status == "approved_pending_esign"


@pytest.mark.asyncio
async def test_approve_writes_audit_log(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Approving a submission inserts an audit_logs row with before/after state."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-a2-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-a2-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    await client.post(
        f"/api/v1/manager/approvals/{sub_id}/approve",
        json={"purchase_offer": "12000.00", "consignment_price": "14000.00"},
        headers=headers,
    )

    log = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.event_type == "appraisal_submission.approved",
                AuditLog.target_id == uuid.UUID(sub_id),
            )
        )
    ).scalar_one()
    assert log.before_state["submission_status"] == "submitted"
    assert log.after_state["submission_status"] == "approved"
    assert log.after_state["record_status"] == "approved_pending_esign"
    assert log.actor_role == "sales_manager"


@pytest.mark.asyncio
async def test_approve_title_hold_blocked_without_confirmation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Approval of a hold_for_title_review submission requires title_review_confirmed."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-a3-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-a3-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    # Manually set hold_for_title_review on the submission
    sub = (
        await db_session.execute(
            select(AppraisalSubmission).where(AppraisalSubmission.id == uuid.UUID(sub_id))
        )
    ).scalar_one()
    sub.hold_for_title_review = True
    await db_session.flush()

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/approve",
        json={"purchase_offer": "10000.00", "consignment_price": "12000.00"},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "title hold" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_title_hold_passes_with_confirmation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """hold_for_title_review submission approves successfully when title_review_confirmed=true."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-a4-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-a4-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    sub = (
        await db_session.execute(
            select(AppraisalSubmission).where(AppraisalSubmission.id == uuid.UUID(sub_id))
        )
    ).scalar_one()
    sub.hold_for_title_review = True
    await db_session.flush()

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/approve",
        json={
            "purchase_offer": "10000.00",
            "consignment_price": "12000.00",
            "title_review_confirmed": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_already_approved_fails(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Approving a submission that is already approved returns 422."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-a5-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-a5-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    first = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/approve",
        json={"purchase_offer": "10000.00", "consignment_price": "12000.00"},
        headers=headers,
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/approve",
        json={"purchase_offer": "10000.00", "consignment_price": "12000.00"},
        headers=headers,
    )
    assert second.status_code == 422


# --------------------------------------------------------------------------- #
# Reject tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reject_permanent_sets_submission_and_record_status(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Permanent rejection sets submission → rejected, equipment record → declined."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-r1-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-r1-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/reject",
        json={"rejection_notes": "Hours not verifiable.", "send_back": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["rejection_notes"] == "Hours not verifiable."

    await db_session.refresh(record)
    assert record.status == "declined"


@pytest.mark.asyncio
async def test_reject_send_back_returns_record_to_new_request(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """send_back=true returns the equipment record to new_request for re-appraisal."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-r2-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-r2-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.post(
        f"/api/v1/manager/approvals/{sub_id}/reject",
        json={"rejection_notes": "Photos were blurry.", "send_back": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(record)
    assert record.status == "new_request"


@pytest.mark.asyncio
async def test_reject_writes_audit_log(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Rejecting a submission inserts an audit_logs row with before/after state."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-r3-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-r3-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    await client.post(
        f"/api/v1/manager/approvals/{sub_id}/reject",
        json={"rejection_notes": "Missing serial plate.", "send_back": False},
        headers=headers,
    )

    log = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.event_type == "appraisal_submission.rejected",
                AuditLog.target_id == uuid.UUID(sub_id),
            )
        )
    ).scalar_one()
    assert log.before_state["submission_status"] == "submitted"
    assert log.after_state["submission_status"] == "rejected"
    assert log.after_state["send_back"] is False
    assert "Missing serial plate" in log.after_state["rejection_notes"]


@pytest.mark.asyncio
async def test_reject_send_back_enqueues_appraiser_notification(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """send_back rejection enqueues a notification to the appraiser."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-r4-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-r4-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    # Resolve appraiser user for notification query
    submission = (
        await db_session.execute(
            select(AppraisalSubmission).where(AppraisalSubmission.id == uuid.UUID(sub_id))
        )
    ).scalar_one()
    appraiser_id = submission.appraiser_id

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    await client.post(
        f"/api/v1/manager/approvals/{sub_id}/reject",
        json={"rejection_notes": "Re-inspect engine bay.", "send_back": True},
        headers=headers,
    )

    job = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.user_id == appraiser_id,
                NotificationJob.template == "appraisal_rejected_appraiser_email",
            )
        )
    ).scalar_one_or_none()
    assert job is not None


@pytest.mark.asyncio
async def test_reject_not_found_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Rejecting a nonexistent submission returns 404."""
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-r5-{_tag()}@example.com", role_slug="sales_manager"
    )
    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.post(
        f"/api/v1/manager/approvals/{uuid.uuid4()}/reject",
        json={"rejection_notes": "Gone.", "send_back": False},
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_transitions_equipment_record_to_appraisal_complete(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Submitting an appraisal transitions the equipment record to appraisal_complete."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-s1-{_tag()}@example.com", role_slug="appraiser"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)

    await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    await db_session.refresh(record)
    assert record.status == "appraisal_complete"


@pytest.mark.asyncio
async def test_approval_detail_returns_full_submission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /manager/approvals/{id} returns the full submission detail."""
    appraiser_tokens = await _create_user(
        client, db_session, email=f"app-d1-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db_session, email=f"mgr-d1-{_tag()}@example.com", role_slug="sales_manager"
    )
    cat = await _make_category(db_session)
    record = await _make_record(db_session, category=cat)
    sub_id = await _submit_appraisal(
        client, db_session, appraiser_tokens=appraiser_tokens, record=record
    )

    headers = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    resp = await client.get(f"/api/v1/manager/approvals/{sub_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == sub_id
    assert body["status"] == "submitted"
    assert body["make"] == "Caterpillar"
    assert "management_review_required" in body
    assert "hold_for_title_review" in body
