# ABOUTME: Pydantic schemas for ToS/Privacy document fetch + consent acceptance.
# ABOUTME: Used by api/routers/legal.py; text bodies come from files under api/content/.
from __future__ import annotations

from pydantic import BaseModel, Field


class LegalDocument(BaseModel):
    """Public ToS/Privacy doc payload. Served from api/content/<type>/v<N>.md."""

    document_type: str  # 'tos' or 'privacy'
    version: str
    body_markdown: str


class AcceptTermsRequest(BaseModel):
    """Called when a logged-in user accepts a version bump (interstitial flow)."""

    tos_version: str = Field(..., min_length=1, max_length=20)
    privacy_version: str = Field(..., min_length=1, max_length=20)


class ConsentStatus(BaseModel):
    """Current vs accepted versions. Drives the re-accept interstitial."""

    tos_current_version: str
    privacy_current_version: str
    tos_accepted_version: str | None = None
    privacy_accepted_version: str | None = None
    requires_reaccept: bool
