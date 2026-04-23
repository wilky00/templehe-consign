# ABOUTME: Signed-URL upload + finalize flow for customer intake photos stored in Cloudflare R2.
# ABOUTME: AV scanning is scaffold-only this sprint — scan_status starts 'pending' and never flips.
"""Photo upload flow for customer intake.

Two-step flow:
    1. POST /me/equipment/{id}/photos/upload-url
       → returns a short-lived presigned PUT URL + the final storage key.
    2. Client PUTs the blob directly to R2.
    3. POST /me/equipment/{id}/photos
       → finalize: service writes a ``customer_intake_photos`` row with
         scan_status='pending'. Real AV scanning is deferred.

R2 object keys are immutable by design (R2 does not support versioning).
See ``project_notes/known-issues.md``: photos live under
``photos/{equipment_id}/{uuid}.{ext}``.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

import boto3
import structlog
from botocore.client import Config as BotoConfig
from fastapi import HTTPException

from config import settings

logger = structlog.get_logger(__name__)

# Only image MIMEs accepted at finalize time. The appraiser-side upload
# surface (Phase 5) will extend this for PDFs / videos.
_ALLOWED_IMAGE_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)

# Whitelisted file extensions. Matched case-insensitively; no dots.
_ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic", "heif"})

_PRESIGNED_URL_EXPIRY_SECONDS = 900  # 15 min — enough for slow uplinks


class PhotoUploadIntent:
    """Plain container for what the upload-url endpoint returns."""

    def __init__(self, *, upload_url: str, storage_key: str, expires_in: int) -> None:
        self.upload_url = upload_url
        self.storage_key = storage_key
        self.expires_in = expires_in


def _normalize_extension(filename: str) -> str:
    ext = PurePosixPath(filename).suffix.lstrip(".").lower()
    if not ext or ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file extension. Allowed: {sorted(_ALLOWED_EXTENSIONS)}.",
        )
    return ext


def _validate_content_type(content_type: str) -> None:
    if content_type.lower() not in _ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Only image uploads are allowed for customer intake photos.",
        )


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
        # SigV4 is required for R2. The addressing style is path-style.
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def build_storage_key(equipment_record_id: uuid.UUID, filename: str) -> str:
    """Return an immutable R2 key for a fresh upload."""
    ext = _normalize_extension(filename)
    return f"photos/{equipment_record_id}/{uuid.uuid4()}.{ext}"


def generate_upload_intent(
    *,
    equipment_record_id: uuid.UUID,
    filename: str,
    content_type: str,
) -> PhotoUploadIntent:
    """Return a presigned PUT URL + the storage key the client should upload to."""
    _validate_content_type(content_type)
    storage_key = build_storage_key(equipment_record_id, filename)
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
    return PhotoUploadIntent(
        upload_url=url,
        storage_key=storage_key,
        expires_in=_PRESIGNED_URL_EXPIRY_SECONDS,
    )


def validate_finalize_inputs(
    *,
    storage_key: str,
    equipment_record_id: uuid.UUID,
    content_type: str,
    sha256: str | None,
) -> None:
    """Cheap defenses against a client that tries to finalize a key it
    shouldn't own. The key must live under the record's photo prefix and
    look like a valid UUID.ext; MIME must match the allowlist."""
    _validate_content_type(content_type)
    expected_prefix = f"photos/{equipment_record_id}/"
    if not storage_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=422,
            detail="storage_key does not belong to this equipment record.",
        )
    remainder = storage_key[len(expected_prefix) :]
    parts = remainder.split(".")
    if len(parts) != 2 or parts[1].lower() not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="storage_key format is invalid.")
    try:
        uuid.UUID(parts[0])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="storage_key format is invalid.") from exc
    if sha256 is not None and (
        len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256.lower())
    ):
        raise HTTPException(status_code=422, detail="sha256 must be 64 hex characters.")
