# ABOUTME: Request/response shapes for POST/PUT/DELETE /api/v1/record-locks.
# ABOUTME: LockInfoOut mirrors services.record_lock_service.LockInfo (the domain dataclass).
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_ALLOWED_RECORD_TYPES = {"equipment_record"}


class LockAcquireRequest(BaseModel):
    record_id: uuid.UUID
    record_type: str = Field(default="equipment_record")

    model_config = ConfigDict(extra="forbid")

    def validate_record_type(self) -> None:
        if self.record_type not in _ALLOWED_RECORD_TYPES:
            raise ValueError(f"unsupported record_type: {self.record_type}")


class LockInfoOut(BaseModel):
    record_id: uuid.UUID
    record_type: str
    locked_by: uuid.UUID
    locked_at: datetime
    expires_at: datetime


class LockConflictOut(BaseModel):
    """Body of a 409 when another user holds the lock. Mirrors LockInfoOut but is a distinct shape so the caller can render a friendly "editing by X" banner."""

    detail: str
    locked_by: uuid.UUID
    locked_at: datetime
    expires_at: datetime
