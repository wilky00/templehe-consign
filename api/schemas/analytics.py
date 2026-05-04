# ABOUTME: Analytics event schema — Phase 8.
# ABOUTME: Fire-and-forget client events; no PII allowed in metadata.
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AnalyticsEventCreate(BaseModel):
    session_id: str | None = Field(None, max_length=100)
    event_type: str = Field(..., min_length=1, max_length=100)
    page: str | None = Field(None, max_length=255)
    metadata: dict | None = None

    @field_validator("metadata")
    @classmethod
    def no_pii_in_metadata(cls, v: dict | None) -> dict | None:
        """Reject metadata that looks like it contains PII."""
        if v is None:
            return v
        import re

        email_re = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
        for val in v.values():
            if isinstance(val, str) and email_re.search(val):
                raise ValueError("metadata must not contain email addresses")
        return v


class AnalyticsEventResponse(BaseModel):
    recorded: bool
