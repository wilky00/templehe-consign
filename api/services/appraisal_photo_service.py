# ABOUTME: Phase 5 Sprint 5 — generate presigned upload URLs and finalize appraisal photos.
# ABOUTME: Stores EXIF/GPS metadata; soft-deletes previous photo when a slot is retaken.
"""Appraisal photo service — presigned upload + finalize lifecycle.

Two-step flow mirrors the customer intake photo pattern (Phase 2):
    1. POST /appraisal-photos/upload-url  → presigned PUT URL + storage_key.
    2. iOS PUTs the JPEG directly to R2.
    3. POST /appraisal-photos/finalize    → writes an appraisal_photos row;
       soft-deletes any prior photo for the same submission + slot_label.

Storage keys live under ``appraisal-photos/{submission_id}/`` to separate
them from customer intake photos (``photos/{record_id}/``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import boto3
import structlog
from botocore.client import Config as BotoConfig
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import AppraisalPhoto, AppraisalSubmission, User
from services import user_roles_service

logger = structlog.get_logger(__name__)

_ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)
_ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic", "heif"})
_CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}
_PRESIGNED_URL_EXPIRY_SECONDS = 900  # 15 min — enough for slow uplinks


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def generate_upload_intent(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    slot_label: str,
    content_type: str,
    user: User,
) -> tuple[str, str, int]:
    """Return ``(upload_url, storage_key, expires_in)`` for a direct R2 PUT.

    Validates that the user owns the submission and that the content_type is
    an allowed image MIME. The storage_key is stable enough for finalize to
    reference immediately after the PUT completes.
    """
    _validate_content_type(content_type)
    submission = await _get_submission(db, submission_id=submission_id)
    await _check_access(db, submission=submission, user=user)

    storage_key = _build_storage_key(submission_id, content_type)
    client = _r2_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket_photos,
            "Key": storage_key,
            "ContentType": content_type,
        },
        ExpiresIn=_PRESIGNED_URL_EXPIRY_SECONDS,
        HttpMethod="PUT",
    )
    logger.info(
        "appraisal_photo_upload_intent",
        submission_id=str(submission_id),
        slot_label=slot_label,
        storage_key=storage_key,
    )
    return url, storage_key, _PRESIGNED_URL_EXPIRY_SECONDS


async def finalize(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    slot_label: str,
    storage_key: str,
    sha256: str | None,
    content_type: str,
    file_size_bytes: int | None,
    capture_timestamp: datetime | None,
    gps_timestamp: datetime | None,
    gps_latitude: float | None,
    gps_longitude: float | None,
    gps_missing: bool,
    gps_out_of_range: bool,
    user: User,
) -> AppraisalPhoto:
    """Persist the finalized photo record.

    Validates that ``storage_key`` belongs to this submission's namespace.
    Soft-deletes any previous non-deleted photo for the same slot so a
    retake replaces without leaving dangling active rows.
    """
    _validate_content_type(content_type)
    _validate_storage_key(storage_key, submission_id)

    submission = await _get_submission(db, submission_id=submission_id)
    await _check_access(db, submission=submission, user=user)

    # Soft-delete any prior capture for this slot
    existing = await db.execute(
        select(AppraisalPhoto).where(
            AppraisalPhoto.appraisal_submission_id == submission_id,
            AppraisalPhoto.slot_label == slot_label,
            AppraisalPhoto.deleted_at.is_(None),
        )
    )
    for prior in existing.scalars().all():
        prior.deleted_at = datetime.now(UTC)
        db.add(prior)

    photo = AppraisalPhoto(
        appraisal_submission_id=submission_id,
        slot_label=slot_label,
        gcs_path=storage_key,
        sha256=sha256,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        capture_timestamp=capture_timestamp,
        gps_timestamp=gps_timestamp,
        gps_latitude=gps_latitude,
        gps_longitude=gps_longitude,
        gps_missing=gps_missing,
        gps_out_of_range=gps_out_of_range,
    )
    db.add(photo)
    await db.flush()
    logger.info(
        "appraisal_photo_finalized",
        submission_id=str(submission_id),
        photo_id=str(photo.id),
        slot_label=slot_label,
        gps_missing=gps_missing,
        gps_out_of_range=gps_out_of_range,
    )
    return photo


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


def _r2_client():
    if not (settings.r2_access_key_id and settings.r2_secret_access_key):
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured. Contact support.",
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def _build_storage_key(submission_id: uuid.UUID, content_type: str) -> str:
    ext = _CONTENT_TYPE_TO_EXT.get(content_type.lower(), "jpg")
    return f"appraisal-photos/{submission_id}/{uuid.uuid4()}.{ext}"


def _validate_content_type(content_type: str) -> None:
    if content_type.lower() not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Only image uploads are allowed for appraisal photos.",
        )


def _validate_storage_key(storage_key: str, submission_id: uuid.UUID) -> None:
    """Reject keys that don't belong to this submission's namespace."""
    expected_prefix = f"appraisal-photos/{submission_id}/"
    if not storage_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=422,
            detail="storage_key does not belong to this submission.",
        )
    remainder = storage_key[len(expected_prefix) :]
    parts = remainder.split(".")
    if len(parts) != 2 or parts[1].lower() not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="storage_key format is invalid.")
    try:
        uuid.UUID(parts[0])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="storage_key format is invalid.") from exc


async def _get_submission(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
) -> AppraisalSubmission:
    result = await db.execute(
        select(AppraisalSubmission).where(
            AppraisalSubmission.id == submission_id,
            AppraisalSubmission.deleted_at.is_(None),
        )
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise LookupError(f"Submission {submission_id} not found")
    return submission


async def _check_access(
    db: AsyncSession,
    *,
    submission: AppraisalSubmission,
    user: User,
) -> None:
    roles = await user_roles_service.role_slugs_for_user(db, user=user)
    if "admin" in roles:
        return
    if submission.appraiser_id != user.id:
        raise PermissionError("Access denied to submission")
