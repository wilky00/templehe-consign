# ABOUTME: Pydantic schemas for the two-step signed-URL photo upload flow.
# ABOUTME: Used by api/routers/equipment.py — /photos/upload-url + /photos finalize.
from __future__ import annotations

from pydantic import BaseModel, Field


class UploadUrlRequest(BaseModel):
    """Client requests a presigned PUT URL. Filename gives us the extension;
    content_type is echoed into the presign so R2 enforces it on upload."""

    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=100)


class UploadUrlResponse(BaseModel):
    upload_url: str
    storage_key: str
    expires_in: int


class FinalizePhotoRequest(BaseModel):
    """Client posts this after a successful PUT to R2.

    The sha256 lets the server record a tamper-evident hash of the blob
    the client *claims* to have uploaded. Real verification would re-
    compute server-side; for Sprint 3 we trust the client and persist.
    """

    storage_key: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=100)
    caption: str | None = Field(default=None, max_length=1000)
    display_order: int = Field(default=0, ge=0, le=99)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
