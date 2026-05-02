# ABOUTME: Phase 5 Sprint 3 — POST /api/v1/valuation/search for the iOS valuation lookup.
# ABOUTME: Appraiser-scoped; delegates to valuation_service for multi-source comparable search.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.valuation import ValuationSearchRequest, ValuationSearchResponse
from services import valuation_service

router = APIRouter(prefix="/valuation", tags=["mobile"])

_require_appraiser = require_roles("appraiser", "admin")


@router.post("/search", response_model=ValuationSearchResponse)
async def search_comparables(
    body: ValuationSearchRequest,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> ValuationSearchResponse:
    """Search comparable sales by make, model, year, hours, and category.

    Results come from internal seeded data (and a stubbed external
    provider). The ``used_sources`` field in the response lists every
    tier that contributed rows so the iOS client can display provenance
    badges."""
    return await valuation_service.search(
        db,
        make=body.make,
        model=body.model,
        year=body.year,
        hours=body.hours,
        category_id=body.category_id,
    )
