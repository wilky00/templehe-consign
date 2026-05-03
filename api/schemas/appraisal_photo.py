# ABOUTME: Phase 5 Sprint 5 — Pydantic schemas for appraisal photo upload and finalize flow.
# ABOUTME: Covers presigned-URL intent request, finalize request, and photo response shape.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class UploadIntentRequest(BaseModel):
    submission_id: uuid.UUID
    slot_label: str
    content_type: str = "image/jpeg"


class UploadIntentResponse(BaseModel):
    upload_url: str
    storage_key: str
    expires_in: int


class FinalizePhotoRequest(BaseModel):
    submission_id: uuid.UUID
    slot_label: str
    storage_key: str
    sha256: str | None = None
    content_type: str = "image/jpeg"
    file_size_bytes: int | None = None
    capture_timestamp: datetime | None = None
    gps_timestamp: datetime | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_missing: bool = False
    gps_out_of_range: bool = False

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, v: str | None) -> str | None:
        if v is not None and (
            len(v) != 64 or not all(c in "0123456789abcdef" for c in v.lower())
        ):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return v


class PhotoOut(BaseModel):
    id: uuid.UUID
    appraisal_submission_id: uuid.UUID
    slot_label: str
    storage_key: str
    content_type: str | None
    sha256: str | None
    file_size_bytes: int | None
    capture_timestamp: datetime | None
    gps_timestamp: datetime | None
    gps_latitude: float | None
    gps_longitude: float | None
    gps_missing: bool
    gps_out_of_range: bool
    created_at: datetime
