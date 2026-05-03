# ABOUTME: Phase 5 Sprint 5 — appraisal photo upload endpoints (presigned URL + finalize).
# ABOUTME: Appraiser-scoped; must own the parent submission. Two-step: upload-url → finalize.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.appraisal_photo import (
    FinalizePhotoRequest,
    PhotoOut,
    UploadIntentRequest,
    UploadIntentResponse,
)
from services import appraisal_photo_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/appraisal-photos", tags=["mobile"])

_require_appraiser = require_roles("appraiser", "admin")


def _photo_to_out(photo) -> PhotoOut:
    return PhotoOut(
        id=photo.id,
        appraisal_submission_id=photo.appraisal_submission_id,
        slot_label=photo.slot_label,
        storage_key=photo.gcs_path,
        content_type=photo.content_type,
        sha256=photo.sha256,
        file_size_bytes=photo.file_size_bytes,
        capture_timestamp=photo.capture_timestamp,
        gps_timestamp=photo.gps_timestamp,
        gps_latitude=float(photo.gps_latitude) if photo.gps_latitude is not None else None,
        gps_longitude=float(photo.gps_longitude) if photo.gps_longitude is not None else None,
        gps_missing=photo.gps_missing,
        gps_out_of_range=photo.gps_out_of_range,
        created_at=photo.created_at,
    )


@router.post("/upload-url", response_model=UploadIntentResponse)
async def get_upload_url(
    body: UploadIntentRequest,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> UploadIntentResponse:
    """Return a presigned PUT URL for direct-to-R2 photo upload.

    The client PUTs the image bytes to ``upload_url``, then calls ``/finalize``
    with the returned ``storage_key`` and EXIF metadata."""
    try:
        upload_url, storage_key, expires_in = await appraisal_photo_service.generate_upload_intent(
            db,
            submission_id=body.submission_id,
            slot_label=body.slot_label,
            content_type=body.content_type,
            user=current_user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return UploadIntentResponse(
        upload_url=upload_url,
        storage_key=storage_key,
        expires_in=expires_in,
    )


@router.post("/finalize", response_model=PhotoOut, status_code=201)
async def finalize_photo(
    body: FinalizePhotoRequest,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> PhotoOut:
    """Persist the finalized photo after a successful R2 PUT.

    Soft-deletes any existing photo for the same submission + slot so a retake
    replaces cleanly. EXIF metadata and GPS flags are recorded as-received from
    the iOS client."""
    try:
        photo = await appraisal_photo_service.finalize(
            db,
            submission_id=body.submission_id,
            slot_label=body.slot_label,
            storage_key=body.storage_key,
            sha256=body.sha256,
            content_type=body.content_type,
            file_size_bytes=body.file_size_bytes,
            capture_timestamp=body.capture_timestamp,
            gps_timestamp=body.gps_timestamp,
            gps_latitude=body.gps_latitude,
            gps_longitude=body.gps_longitude,
            gps_missing=body.gps_missing,
            gps_out_of_range=body.gps_out_of_range,
            user=current_user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _photo_to_out(photo)
