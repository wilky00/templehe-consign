# ABOUTME: Inquiry creation service — Phase 8.
# ABOUTME: Creates Inquiry rows, sends rep alert + buyer confirmation via BackgroundTasks.
from __future__ import annotations

import uuid

import structlog
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord, Inquiry, PublicListing, User
from schemas.public_listing import InquiryCreate
from services import email_service

logger = structlog.get_logger(__name__)


async def create_inquiry(
    db: AsyncSession,
    listing_id: uuid.UUID,
    body: InquiryCreate,
    background_tasks: BackgroundTasks,
) -> Inquiry:
    """Persist the inquiry and schedule notification emails."""
    # Verify listing exists and is active
    listing_stmt = (
        select(PublicListing)
        .where(PublicListing.id == listing_id)
        .where(PublicListing.status == "active")
    )
    listing = (await db.execute(listing_stmt)).scalar_one_or_none()
    if listing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Listing not found")

    inquiry = Inquiry(
        public_listing_id=listing_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=str(body.email),
        phone=body.phone,
        message=body.message,
    )
    db.add(inquiry)
    await db.flush()

    buyer_name = f"{body.first_name} {body.last_name}"

    # Confirmation email to buyer (best-effort)
    background_tasks.add_task(
        email_service.send_inquiry_confirmation_email,
        str(body.email),
        buyer_name,
        listing.listing_title,
    )

    # Alert email to assigned sales rep
    rep_stmt = (
        select(User, EquipmentRecord)
        .select_from(PublicListing)
        .join(EquipmentRecord, PublicListing.equipment_record_id == EquipmentRecord.id)
        .outerjoin(User, EquipmentRecord.assigned_sales_rep_id == User.id)
        .where(PublicListing.id == listing_id)
    )
    rep_row = (await db.execute(rep_stmt)).first()
    if rep_row and rep_row.User:
        rep = rep_row.User
        rep_name = f"{rep.first_name or ''} {rep.last_name or ''}".strip() or "Sales team"
        background_tasks.add_task(
            email_service.send_inquiry_alert_email,
            rep.email,
            rep_name,
            buyer_name,
            str(body.email),
            body.phone,
            listing.listing_title,
            body.message,
        )
        logger.info(
            "inquiry_created",
            inquiry_id=str(inquiry.id),
            listing_id=str(listing_id),
            rep_id=str(rep.id),
        )
    else:
        logger.warning("inquiry_no_rep", listing_id=str(listing_id))

    return inquiry
