# ABOUTME: Phase 5 Sprint 3 — Pydantic schemas for the valuation search endpoint.
# ABOUTME: ComparableSaleOut, ValuationSearchRequest, ValuationSearchResponse.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ComparableSaleOut(BaseModel):
    id: uuid.UUID
    make: str | None
    model: str | None
    year: int | None
    hours: int | None
    sale_price: Decimal | None
    sale_date: datetime | None
    source: str | None
    source_url: str | None
    notes: str | None
    category_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class ValuationSearchRequest(BaseModel):
    make: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2100)
    hours: int | None = Field(default=None, ge=0)
    category_id: uuid.UUID | None = None


class ValuationSearchResponse(BaseModel):
    results: list[ComparableSaleOut]
    used_sources: list[str]
