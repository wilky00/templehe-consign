# ABOUTME: Phase 8 public endpoints — listing catalog and inquiry form.
# ABOUTME: All routes are unauthenticated; rate-limited by IP at the router level.
from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from middleware.rate_limit import rate_limit_by_ip
from schemas.public_listing import (
    InquiryCreate,
    InquiryResponse,
    PublicListingDetail,
    PublicListingsResponse,
)
from services import inquiry_service, listing_service

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["public"])

# 60 requests / minute / IP for browsing listings
_listings_limiter = rate_limit_by_ip(limit=60, window_seconds=60, endpoint="public_listings")
# 5 inquiry submissions / hour / IP to limit bot spam
_inquiry_limiter = rate_limit_by_ip(limit=5, window_seconds=3600, endpoint="public_inquiry")


@router.get("/public/listings", response_model=PublicListingsResponse)
async def get_listings(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    category: list[str] = Query(default=[]),
    condition: list[str] = Query(default=[]),
    min_price: Decimal | None = Query(None),
    max_price: Decimal | None = Query(None),
    state: str | None = Query(None, max_length=2),
    min_hours: str | None = Query(None),
    max_hours: str | None = Query(None),
    sort: str = Query("newest", pattern="^(newest|price_asc|price_desc)$"),
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_listings_limiter),
) -> PublicListingsResponse:
    items, total = await listing_service.list_public_listings(
        db,
        page=page,
        page_size=page_size,
        category=category or None,
        condition=condition or None,
        min_price=min_price,
        max_price=max_price,
        state=state,
        min_hours=min_hours,
        max_hours=max_hours,
        sort=sort,
    )
    import math

    total_pages = math.ceil(total / page_size) if total else 0
    return PublicListingsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/public/listings/{listing_id}", response_model=PublicListingDetail)
async def get_listing_detail(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_listings_limiter),
) -> PublicListingDetail:
    detail = await listing_service.get_public_listing_detail(db, listing_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return detail


@router.post("/public/listings/{listing_id}/inquiries", response_model=InquiryResponse, status_code=201)
async def submit_inquiry(
    listing_id: uuid.UUID,
    body: InquiryCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_inquiry_limiter),
) -> InquiryResponse:
    # Honeypot: bots fill in `web_address`; silently succeed without creating a real record
    if body.web_address:
        logger.info("inquiry_honeypot_triggered", listing_id=str(listing_id))
        return InquiryResponse(id=uuid.uuid4())

    inquiry = await inquiry_service.create_inquiry(db, listing_id, body, background_tasks)
    await db.commit()
    return InquiryResponse(id=inquiry.id)
