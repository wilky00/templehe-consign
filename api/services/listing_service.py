# ABOUTME: Listing query service — Phase 8 public listing and listing management.
# ABOUTME: Joins AppraisalSubmission for verified field data; falls back to customer_* columns.
from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalSubmission,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    PublicListing,
    User,
)
from schemas.public_listing import ListingPatch, PublicListingCard, PublicListingDetail

logger = structlog.get_logger(__name__)


def _base_stmt():
    """Base SELECT joining the four tables needed for both list and detail views."""
    return (
        select(
            PublicListing, EquipmentRecord, AppraisalSubmission, Customer, EquipmentCategory, User
        )
        .join(EquipmentRecord, PublicListing.equipment_record_id == EquipmentRecord.id)
        .outerjoin(
            AppraisalSubmission,
            (AppraisalSubmission.equipment_record_id == EquipmentRecord.id)
            & (AppraisalSubmission.status == "approved")
            & (AppraisalSubmission.deleted_at.is_(None)),
        )
        .outerjoin(Customer, EquipmentRecord.customer_id == Customer.id)
        .outerjoin(EquipmentCategory, EquipmentRecord.category_id == EquipmentCategory.id)
        .outerjoin(User, EquipmentRecord.assigned_sales_rep_id == User.id)
    )


def _card_from_row(row) -> PublicListingCard:
    listing: PublicListing = row.PublicListing
    record: EquipmentRecord = row.EquipmentRecord
    sub: AppraisalSubmission | None = row.AppraisalSubmission
    customer: Customer | None = row.Customer
    category: EquipmentCategory | None = row.EquipmentCategory

    return PublicListingCard(
        id=listing.id,
        listing_title=listing.listing_title,
        asking_price=listing.asking_price,
        status=listing.status,
        published_at=listing.published_at,
        make=sub.make if sub else record.customer_make,
        model=sub.model if sub else record.customer_model,
        year=sub.year if sub else record.customer_year,
        category_name=category.name if category else None,
        hours_condition=sub.hours_condition if sub else None,
        marketability_rating=sub.marketability_rating if sub else None,
        state=customer.address_state if customer else None,
        primary_photo_url=listing.primary_photo_gcs_path,
    )


async def list_public_listings(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 24,
    category: list[str] | None = None,
    condition: list[str] | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    state: str | None = None,
    min_hours: str | None = None,
    max_hours: str | None = None,
    sort: str = "newest",
) -> tuple[list[PublicListingCard], int]:
    """Return paginated active listings matching the given filters."""
    stmt = _base_stmt().where(PublicListing.status == "active")

    if category:
        stmt = stmt.where(EquipmentCategory.name.in_(category))
    if condition:
        stmt = stmt.where(AppraisalSubmission.hours_condition.in_(condition))
    if min_price is not None:
        stmt = stmt.where(PublicListing.asking_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(PublicListing.asking_price <= max_price)
    if state:
        stmt = stmt.where(Customer.address_state == state)

    # Count total matching rows before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    if sort == "price_asc":
        stmt = stmt.order_by(PublicListing.asking_price.asc().nulls_last())
    elif sort == "price_desc":
        stmt = stmt.order_by(PublicListing.asking_price.desc().nulls_last())
    else:
        stmt = stmt.order_by(PublicListing.published_at.desc().nulls_last())

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    rows = (await db.execute(stmt)).all()
    return [_card_from_row(r) for r in rows], total


async def get_public_listing_detail(
    db: AsyncSession,
    listing_id: uuid.UUID,
) -> PublicListingDetail | None:
    """Return full listing detail for the public detail page."""
    stmt = (
        _base_stmt().where(PublicListing.id == listing_id).where(PublicListing.status == "active")
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None

    listing: PublicListing = row.PublicListing
    record: EquipmentRecord = row.EquipmentRecord
    sub: AppraisalSubmission | None = row.AppraisalSubmission
    customer: Customer | None = row.Customer
    category: EquipmentCategory | None = row.EquipmentCategory
    rep: User | None = row.User

    rep_name: str | None = None
    if rep:
        parts = [rep.first_name, rep.last_name]
        rep_name = " ".join(p for p in parts if p) or None

    return PublicListingDetail(
        id=listing.id,
        listing_title=listing.listing_title,
        asking_price=listing.asking_price,
        published_at=listing.published_at,
        make=sub.make if sub else record.customer_make,
        model=sub.model if sub else record.customer_model,
        year=sub.year if sub else record.customer_year,
        serial_number=sub.serial_number if sub else record.customer_serial_number,
        category_name=category.name if category else None,
        hours_condition=sub.hours_condition if sub else None,
        running_status=sub.running_status if sub else record.customer_running_status,
        marketability_rating=sub.marketability_rating if sub else None,
        transport_notes=sub.transport_notes if sub else None,
        listing_notes=sub.listing_notes if sub else None,
        state=customer.address_state if customer else None,
        primary_photo_url=listing.primary_photo_gcs_path,
        assigned_rep_name=rep_name,
        contact_phone=customer.business_phone if customer else None,
    )


async def patch_listing(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    patch: ListingPatch,
    acting_user_id: uuid.UUID,
    acting_role_slug: str,
) -> PublicListing:
    """Update asking_price or status on an equipment record's public listing."""
    stmt = (
        select(PublicListing)
        .join(EquipmentRecord, PublicListing.equipment_record_id == EquipmentRecord.id)
        .where(EquipmentRecord.id == record_id)
    )
    listing = (await db.execute(stmt)).scalar_one_or_none()
    if listing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Listing not found for this equipment record")

    if patch.asking_price is not None:
        listing.asking_price = patch.asking_price
    if patch.status is not None:
        from datetime import UTC, datetime

        listing.status = patch.status
        if patch.status == "sold":
            listing.sold_at = datetime.now(UTC)
        else:
            listing.sold_at = None

    await db.flush()
    logger.info(
        "listing_patched",
        listing_id=str(listing.id),
        actor_id=str(acting_user_id),
        actor_role=acting_role_slug,
        new_status=listing.status,
        new_price=str(listing.asking_price),
    )
    return listing
