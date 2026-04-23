# ABOUTME: Customer equipment intake — creates records, generates THE-XXXXXXXX, enqueues email.
# ABOUTME: Called by api/routers/equipment.py. Never touches HTTP directly.
"""Customer intake service.

The public entry point is ``submit_intake`` — it creates the
``equipment_records`` row, attaches photo metadata, enqueues a durable
intake-confirmation email through ``NotificationService``, and returns
the persisted record for the router to serialize.

Reference numbers are a Crockford-ish base32 of 8 random chars prefixed
``THE-``. The DB column is ``UNIQUE`` so collisions resolve by retry;
with 32^8 ≈ 10^12 keyspace a second-generation collision in this
business's lifetime is effectively zero.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Customer,
    CustomerIntakePhoto,
    EquipmentCategory,
    EquipmentRecord,
    User,
)
from schemas.equipment import IntakeSubmission
from services import customer_service, notification_service, sanitization

logger = structlog.get_logger(__name__)

# Crockford-32 minus I, L, O, U — same character set Stripe uses for IDs.
_REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_REF_LENGTH = 8
_MAX_REF_ATTEMPTS = 10


def _generate_reference_number() -> str:
    suffix = "".join(secrets.choice(_REF_ALPHABET) for _ in range(_REF_LENGTH))
    return f"THE-{suffix}"


async def _reserve_reference_number(db: AsyncSession) -> str:
    """Return a reference number that isn't already taken.

    Works by optimistic generate-and-check: collisions are vanishingly
    rare and the UNIQUE index on the column is the real defense.
    """
    for _ in range(_MAX_REF_ATTEMPTS):
        candidate = _generate_reference_number()
        result = await db.execute(
            select(EquipmentRecord.id).where(EquipmentRecord.reference_number == candidate)
        )
        if result.scalar_one_or_none() is None:
            return candidate
    # If we're here something's off — the alphabet + length gives ~10^12 keys.
    raise HTTPException(
        status_code=500,
        detail="Could not allocate a reference number. Please retry.",
    )


async def _validate_category(db: AsyncSession, category_id: uuid.UUID | None) -> None:
    if category_id is None:
        return
    result = await db.execute(
        select(EquipmentCategory).where(
            EquipmentCategory.id == category_id,
            EquipmentCategory.status == "active",
            EquipmentCategory.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=422, detail="Unknown or inactive equipment category.")


def _sanitized_payload(payload: IntakeSubmission) -> dict:
    """Apply bleach to every free-text field so no raw markup lands in the DB."""
    return {
        "customer_make": sanitization.sanitize_plain(payload.make),
        "customer_model": sanitization.sanitize_plain(payload.model),
        "customer_serial_number": sanitization.sanitize_plain(payload.serial_number),
        "customer_location_text": sanitization.sanitize_plain(payload.location_text),
        "customer_description": sanitization.sanitize_plain(payload.description),
    }


async def submit_intake(
    db: AsyncSession,
    *,
    user: User,
    payload: IntakeSubmission,
) -> EquipmentRecord:
    await _validate_category(db, payload.category_id)
    customer = await customer_service.ensure_profile_for_user(db, user)

    sanitized = _sanitized_payload(payload)
    reference = await _reserve_reference_number(db)

    record = EquipmentRecord(
        customer_id=customer.id,
        status="new_request",
        reference_number=reference,
        category_id=payload.category_id,
        customer_make=sanitized["customer_make"],
        customer_model=sanitized["customer_model"],
        customer_year=payload.year,
        customer_serial_number=sanitized["customer_serial_number"],
        customer_hours=payload.hours,
        customer_running_status=payload.running_status,
        customer_ownership_type=payload.ownership_type,
        customer_location_text=sanitized["customer_location_text"],
        customer_description=sanitized["customer_description"],
        customer_submitted_at=datetime.now(UTC),
    )
    # Attach photos via the relationship rather than db.add so the
    # `record.intake_photos` collection is populated on the Python side —
    # lets the router serialize without triggering a lazy load (which
    # would need a greenlet context we don't have in the request path).
    for idx, photo in enumerate(payload.photos):
        record.intake_photos.append(
            CustomerIntakePhoto(
                storage_key=photo.storage_key.strip(),
                caption=sanitization.sanitize_plain(photo.caption),
                display_order=photo.display_order if photo.display_order else idx,
            )
        )
    db.add(record)
    await db.flush()
    # Ensure record.intake_photos is populated for serialization — without
    # this, SQLAlchemy can mark the collection as needing lazy load after
    # flush, which blows up outside a greenlet-providing context.
    await db.refresh(record, attribute_names=["intake_photos"])

    await _enqueue_confirmation(db, user=user, record=record)
    return record


async def _enqueue_confirmation(
    db: AsyncSession,
    *,
    user: User,
    record: EquipmentRecord,
) -> None:
    """Queue the intake confirmation email. One per record — idempotent."""
    subject = f"Your submission has been received — {record.reference_number}"
    html_body = (
        f"<p>Hi {user.first_name},</p>"
        f"<p>We received your equipment submission. Your reference number is "
        f"<strong>{record.reference_number}</strong>. "
        "A Temple Heavy Equipment sales representative will follow up shortly.</p>"
        "<p>— The Temple Heavy Equipment team</p>"
    )
    await notification_service.enqueue(
        db,
        idempotency_key=f"intake_confirmation:{record.id}",
        user_id=user.id,
        channel="email",
        template="intake_confirmation",
        payload={
            "to_email": user.email,
            "subject": subject,
            "html_body": html_body,
            "reference_number": record.reference_number,
        },
    )


async def list_records_for_user(db: AsyncSession, user: User) -> list[EquipmentRecord]:
    customer_result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = customer_result.scalar_one_or_none()
    if customer is None:
        return []
    result = await db.execute(
        select(EquipmentRecord)
        .options(selectinload(EquipmentRecord.intake_photos))
        .where(EquipmentRecord.customer_id == customer.id)
        .order_by(EquipmentRecord.created_at.desc())
    )
    return list(result.scalars().all())


async def get_record_for_user(
    db: AsyncSession, user: User, record_id: uuid.UUID
) -> EquipmentRecord:
    customer_result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = customer_result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Equipment record not found.")
    result = await db.execute(
        select(EquipmentRecord)
        .options(selectinload(EquipmentRecord.intake_photos))
        .where(
            EquipmentRecord.id == record_id,
            EquipmentRecord.customer_id == customer.id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Equipment record not found.")
    return record
