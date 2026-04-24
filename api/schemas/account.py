# ABOUTME: Pydantic schemas for /me/account/* — deletion request + cancel + data export.
# ABOUTME: Used by api/routers/account.py.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeletionRequestResponse(BaseModel):
    status: str
    deletion_grace_until: datetime | None = None
    message: str


class DataExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    requested_at: datetime
    completed_at: datetime | None = None
    download_url: str | None = None
    url_expires_at: datetime | None = None
    error: str | None = None
