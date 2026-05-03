# ABOUTME: Phase 5 Sprint 5 — integration tests for appraisal photo upload and finalize flow.
# ABOUTME: Covers RBAC, EXIF persistence, GPS flags, retake soft-delete, storage_key validation.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalPhoto,
    AppraisalSubmission,
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
    return f"photo-{role}-{_tag()}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_submission(db: AsyncSession, appraiser_id: uuid.UUID) -> AppraisalSubmission:
    cat = EquipmentCategory(
        name=f"TestCat-{_tag()}",
        slug=f"test-cat-{_tag()}",
        status="active",
        display_order=0,
        version=1,
    )
    db.add(cat)
    await db.flush()

    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        category_id=cat.id,
        status="new_request",
        customer_make="CAT",
        customer_model="320",
    )
    db.add(record)
    await db.flush()

    submission = AppraisalSubmission(
        equipment_record_id=record.id,
        appraiser_id=appraiser_id,
        status="draft",
    )
    db.add(submission)
    await db.flush()
    return submission


def _mock_r2():
    """Return a patch context manager that stubs _r2_client with a presigned-URL mock."""
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://r2.example.com/signed"
    return patch(
        "services.appraisal_photo_service._r2_client",
        return_value=mock_client,
    )


def _valid_storage_key(submission_id: uuid.UUID) -> str:
    return f"appraisal-photos/{submission_id}/{uuid.uuid4()}.jpg"


async def _setup(
    client: AsyncClient,
    db: AsyncSession,
    role: str = "appraiser",
) -> tuple[dict, AppraisalSubmission, User]:
    """Create a user + submission and return (auth_response, submission, user)."""
    email = _email(role)
    auth = await _create_user(client, db, email, role)
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    submission = await _make_submission(db, user.id)
    return auth, submission, user


# --------------------------------------------------------------------------- #
# upload-url tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_upload_url_returns_presigned_url(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)

    with _mock_r2():
        resp = await client.post(
            "/api/v1/appraisal-photos/upload-url",
            json={
                "submission_id": str(submission.id),
                "slot_label": "Front View",
                "content_type": "image/jpeg",
            },
            headers=_auth(auth["access_token"]),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["upload_url"] == "https://r2.example.com/signed"
    assert data["storage_key"].startswith(f"appraisal-photos/{submission.id}/")
    assert data["expires_in"] == 900


@pytest.mark.asyncio
async def test_upload_url_requires_appraiser_role(client: AsyncClient, db_session: AsyncSession):
    email = _email("cust")
    customer = await _create_user(client, db_session, email, "customer")
    resp = await client.post(
        "/api/v1/appraisal-photos/upload-url",
        json={
            "submission_id": str(uuid.uuid4()),
            "slot_label": "Front View",
            "content_type": "image/jpeg",
        },
        headers=_auth(customer["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_url_other_appraiser_denied(client: AsyncClient, db_session: AsyncSession):
    auth_a, submission, _ = await _setup(client, db_session)
    email_b = _email("b")
    auth_b = await _create_user(client, db_session, email_b, "appraiser")

    with _mock_r2():
        resp = await client.post(
            "/api/v1/appraisal-photos/upload-url",
            json={
                "submission_id": str(submission.id),
                "slot_label": "Front View",
                "content_type": "image/jpeg",
            },
            headers=_auth(auth_b["access_token"]),
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_url_invalid_content_type(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)

    with _mock_r2():
        resp = await client.post(
            "/api/v1/appraisal-photos/upload-url",
            json={
                "submission_id": str(submission.id),
                "slot_label": "Front View",
                "content_type": "application/pdf",
            },
            headers=_auth(auth["access_token"]),
        )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# finalize tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_finalize_creates_photo_record(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)
    storage_key = _valid_storage_key(submission.id)

    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Front View",
            "storage_key": storage_key,
            "content_type": "image/jpeg",
        },
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slot_label"] == "Front View"
    assert data["storage_key"] == storage_key
    assert data["gps_missing"] is False
    assert data["gps_out_of_range"] is False


@pytest.mark.asyncio
async def test_finalize_records_exif_fields(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)
    storage_key = _valid_storage_key(submission.id)

    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Engine",
            "storage_key": storage_key,
            "content_type": "image/jpeg",
            "capture_timestamp": "2026-05-02T10:30:00Z",
            "gps_timestamp": "2026-05-02T10:30:01Z",
            "gps_latitude": 36.174465,
            "gps_longitude": -86.767960,
            "file_size_bytes": 512000,
            "sha256": "a" * 64,
        },
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert abs(data["gps_latitude"] - 36.174465) < 0.0001
    assert abs(data["gps_longitude"] - -86.767960) < 0.0001
    assert data["capture_timestamp"] is not None
    assert data["gps_timestamp"] is not None
    assert data["file_size_bytes"] == 512000
    assert data["sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_finalize_gps_missing_flagged(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)
    storage_key = _valid_storage_key(submission.id)

    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Side View",
            "storage_key": storage_key,
            "content_type": "image/jpeg",
            "gps_missing": True,
        },
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["gps_missing"] is True


@pytest.mark.asyncio
async def test_finalize_gps_out_of_range_flagged(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)
    storage_key = _valid_storage_key(submission.id)

    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Rear View",
            "storage_key": storage_key,
            "content_type": "image/jpeg",
            "gps_out_of_range": True,
            "gps_latitude": 40.712776,
            "gps_longitude": -74.005974,
        },
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["gps_out_of_range"] is True


@pytest.mark.asyncio
async def test_finalize_retake_soft_deletes_previous(client: AsyncClient, db_session: AsyncSession):
    auth, submission, _ = await _setup(client, db_session)
    first_key = _valid_storage_key(submission.id)
    second_key = _valid_storage_key(submission.id)
    headers = _auth(auth["access_token"])

    await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Front View",
            "storage_key": first_key,
            "content_type": "image/jpeg",
        },
        headers=headers,
    )
    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Front View",
            "storage_key": second_key,
            "content_type": "image/jpeg",
        },
        headers=headers,
    )
    assert resp.status_code == 201

    # Only one active photo remains for this slot
    active = (
        (
            await db_session.execute(
                select(AppraisalPhoto).where(
                    AppraisalPhoto.appraisal_submission_id == submission.id,
                    AppraisalPhoto.slot_label == "Front View",
                    AppraisalPhoto.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(active) == 1
    assert active[0].gcs_path == second_key

    # First photo is soft-deleted
    deleted = (
        await db_session.execute(select(AppraisalPhoto).where(AppraisalPhoto.gcs_path == first_key))
    ).scalar_one()
    assert deleted.deleted_at is not None


@pytest.mark.asyncio
async def test_finalize_wrong_submission_key_rejected(
    client: AsyncClient, db_session: AsyncSession
):
    auth, submission, _ = await _setup(client, db_session)
    bad_key = f"appraisal-photos/{uuid.uuid4()}/{uuid.uuid4()}.jpg"

    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Front View",
            "storage_key": bad_key,
            "content_type": "image/jpeg",
        },
        headers=_auth(auth["access_token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_finalize_unauthenticated_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(uuid.uuid4()),
            "slot_label": "Front View",
            "storage_key": f"appraisal-photos/{uuid.uuid4()}/{uuid.uuid4()}.jpg",
            "content_type": "image/jpeg",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_finalize_any_submission(client: AsyncClient, db_session: AsyncSession):
    auth_appraiser, submission, _ = await _setup(client, db_session)
    email_admin = _email("adm")
    auth_admin = await _create_user(client, db_session, email_admin, "admin")
    storage_key = _valid_storage_key(submission.id)

    resp = await client.post(
        "/api/v1/appraisal-photos/finalize",
        json={
            "submission_id": str(submission.id),
            "slot_label": "Admin Override",
            "storage_key": storage_key,
            "content_type": "image/jpeg",
        },
        headers=_auth(auth_admin["access_token"]),
    )
    assert resp.status_code == 201
