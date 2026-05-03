# ABOUTME: Phase 5 Sprint 6 — integration tests for appraisal submission finalize behavior.
# ABOUTME: Covers required-photo slot validation, sync notification enqueueing, and retake logic.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalPhoto,
    AppraisalSubmission,
    CategoryPhotoSlot,
    Customer,
    DeviceToken,
    EquipmentCategory,
    EquipmentRecord,
    NotificationJob,
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
) -> tuple[dict, User]:
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
    return resp.json(), user


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _email(role: str) -> str:
    return f"fin-{role}-{_tag()}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_category(db: AsyncSession) -> EquipmentCategory:
    cat = EquipmentCategory(
        name=f"TestCat-{_tag()}",
        slug=f"test-cat-{_tag()}",
        status="active",
        display_order=0,
        version=1,
    )
    db.add(cat)
    await db.flush()
    return cat


async def _make_required_slot(
    db: AsyncSession, category: EquipmentCategory, label: str
) -> CategoryPhotoSlot:
    slot = CategoryPhotoSlot(
        category_id=category.id,
        label=label,
        required=True,
        display_order=0,
        active=True,
    )
    db.add(slot)
    await db.flush()
    return slot


async def _make_submission(
    db: AsyncSession,
    appraiser_id: uuid.UUID,
    category: EquipmentCategory,
) -> AppraisalSubmission:
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        category_id=category.id,
        status="new_request",
        customer_make="CAT",
        customer_model="320",
    )
    db.add(record)
    await db.flush()

    submission = AppraisalSubmission(
        equipment_record_id=record.id,
        appraiser_id=appraiser_id,
        category_id=category.id,
        status="draft",
    )
    db.add(submission)
    await db.flush()
    return submission


async def _add_photo(
    db: AsyncSession,
    submission: AppraisalSubmission,
    slot_label: str,
) -> AppraisalPhoto:
    photo = AppraisalPhoto(
        appraisal_submission_id=submission.id,
        slot_label=slot_label,
        gcs_path=f"appraisal-photos/{submission.id}/{uuid.uuid4()}.jpg",
        content_type="image/jpeg",
    )
    db.add(photo)
    await db.flush()
    return photo


async def _add_device_token(db: AsyncSession, user: User) -> DeviceToken:
    dt = DeviceToken(
        user_id=user.id,
        platform="ios",
        token=f"fake-apns-token-{_tag()}",
        environment="development",
    )
    db.add(dt)
    await db.flush()
    return dt


# --------------------------------------------------------------------------- #
# Required photo slot validation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_submit_missing_required_photo_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    await _make_required_slot(db_session, category, "Front View")
    submission = await _make_submission(db_session, user.id, category)

    resp = await client.post(
        f"/api/v1/appraisal-submissions/{submission.id}/submit",
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 422
    assert "Front View" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_with_all_required_photos_succeeds(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    await _make_required_slot(db_session, category, "Front View")
    submission = await _make_submission(db_session, user.id, category)
    await _add_photo(db_session, submission, "Front View")

    resp = await client.post(
        f"/api/v1/appraisal-submissions/{submission.id}/submit",
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_submit_no_required_slots_succeeds_without_photos(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    # No required slots — submit without any photos
    submission = await _make_submission(db_session, user.id, category)

    resp = await client.post(
        f"/api/v1/appraisal-submissions/{submission.id}/submit",
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_submit_optional_slot_missing_does_not_block(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    # Required slot is captured; optional slot is not — should still succeed
    await _make_required_slot(db_session, category, "Front View")
    optional = CategoryPhotoSlot(
        category_id=category.id,
        label="Optional Detail",
        required=False,
        display_order=1,
        active=True,
    )
    db_session.add(optional)
    await db_session.flush()
    submission = await _make_submission(db_session, user.id, category)
    await _add_photo(db_session, submission, "Front View")

    resp = await client.post(
        f"/api/v1/appraisal-submissions/{submission.id}/submit",
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_submit_retaken_photo_satisfies_required_slot(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    await _make_required_slot(db_session, category, "Front View")
    submission = await _make_submission(db_session, user.id, category)

    # First capture then soft-delete it (simulating a retake)
    old_photo = await _add_photo(db_session, submission, "Front View")
    from datetime import UTC, datetime

    old_photo.deleted_at = datetime.now(UTC)
    db_session.add(old_photo)
    await db_session.flush()

    # New capture for the same slot
    await _add_photo(db_session, submission, "Front View")

    resp = await client.post(
        f"/api/v1/appraisal-submissions/{submission.id}/submit",
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Sync notification enqueueing
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_enqueue_sync_confirmation_creates_notification_job(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    submission = await _make_submission(db_session, user.id, category)
    device_token = await _add_device_token(db_session, user)

    from services import notification_service

    await notification_service.enqueue_sync_confirmation(db_session, submission=submission)
    await db_session.flush()

    job = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.channel == "apns",
                NotificationJob.template == "sync_confirmation_apns",
                NotificationJob.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    assert job is not None
    assert job.payload["token"] == device_token.token
    assert job.payload["data"]["content-available"] == 1


@pytest.mark.asyncio
async def test_enqueue_sync_failed_creates_notification_job(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    submission = await _make_submission(db_session, user.id, category)
    device_token = await _add_device_token(db_session, user)

    from services import notification_service

    await notification_service.enqueue_sync_failed(
        db_session, submission=submission, reason="network timeout"
    )
    await db_session.flush()

    job = (
        await db_session.execute(
            select(NotificationJob).where(
                NotificationJob.channel == "apns",
                NotificationJob.template == "sync_failed_apns",
                NotificationJob.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    assert job is not None
    assert job.payload["token"] == device_token.token
    assert job.payload["data"]["error_reason"] == "network timeout"


@pytest.mark.asyncio
async def test_enqueue_sync_confirmation_no_tokens_is_noop(
    client: AsyncClient, db_session: AsyncSession
):
    auth, user = await _create_user(client, db_session, _email("apr"), "appraiser")
    category = await _make_category(db_session)
    submission = await _make_submission(db_session, user.id, category)
    # No device tokens registered

    from services import notification_service

    await notification_service.enqueue_sync_confirmation(db_session, submission=submission)
    await db_session.flush()

    count = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "sync_confirmation_apns",
                    NotificationJob.user_id == user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(count) == 0
