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
    AuditLog,
    Customer,
    CustomerIntakePhoto,
    EquipmentCategory,
    EquipmentRecord,
    User,
)
from schemas.equipment import IntakeSubmission
from services import (
    customer_service,
    lead_routing_service,
    notification_service,
    sanitization,
)
from services.equipment_status_machine import Status

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
        status=Status.NEW_REQUEST.value,
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
    # Ensure record.intake_photos + status_events are populated for
    # serialization. Without the explicit refresh, SQLAlchemy marks the
    # collections as needing lazy load on access, which blows up outside
    # a greenlet-providing context.
    await db.refresh(record, attribute_names=["intake_photos", "status_events"])

    await _route_and_assign(db, user=user, record=record, customer=customer)
    await _enqueue_confirmation(db, user=user, record=record)
    return record


async def _route_and_assign(
    db: AsyncSession,
    *,
    user: User,
    record: EquipmentRecord,
    customer: Customer,
) -> None:
    """Run the lead routing waterfall and apply the assignment.

    A failure here must not block intake — log and leave unassigned so
    a manager can triage rather than dropping the customer's submission.
    """
    try:
        # Customer.user is a relationship; ensure it's loaded for ad_hoc
        # email-domain matching. ensure_profile_for_user returns the row
        # but the user relation may not be hydrated.
        if customer.user is None:
            customer.user = user
        decision = await lead_routing_service.route_for_record(db, record=record, customer=customer)
    except Exception:
        logger.exception(
            "lead_routing_failed",
            record_id=str(record.id),
            customer_id=str(customer.id),
        )
        return

    if decision.assigned_user_id is None:
        logger.info(
            "lead_routing_unassigned",
            record_id=str(record.id),
            customer_id=str(customer.id),
        )
        # Still write an audit row so the gap is visible in forensics.
        db.add(
            AuditLog(
                event_type="equipment_record.routed",
                actor_id=None,
                actor_role="system",
                target_type="equipment_record",
                target_id=record.id,
                after_state={
                    "trigger": decision.trigger,
                    "rule_id": None,
                    "rule_type": None,
                    "assigned_sales_rep_id": None,
                },
            )
        )
        await db.flush()
        return

    record.assigned_sales_rep_id = decision.assigned_user_id
    db.add(record)
    db.add(
        AuditLog(
            event_type="equipment_record.routed",
            actor_id=None,
            actor_role="system",
            target_type="equipment_record",
            target_id=record.id,
            after_state={
                "trigger": decision.trigger,
                "rule_id": str(decision.rule_id) if decision.rule_id else None,
                "rule_type": decision.rule_type,
                "assigned_sales_rep_id": str(decision.assigned_user_id),
            },
        )
    )
    await db.flush()
    await enqueue_assignment_notification(
        db,
        record=record,
        assigned_user_id=decision.assigned_user_id,
        trigger=decision.trigger,
    )


async def enqueue_assignment_notification(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    assigned_user_id: uuid.UUID,
    trigger: str,
) -> None:
    """Email the newly-assigned rep that they own this record.

    Idempotency key includes the trigger so a manual reassignment doesn't
    collide with the routing-time enqueue (different idempotency keys ⇒
    both deliver).
    """
    rep_result = await db.execute(select(User).where(User.id == assigned_user_id))
    rep = rep_result.scalar_one_or_none()
    if rep is None or rep.status != "active" or not rep.email:
        logger.info(
            "assignment_notification_skipped",
            record_id=str(record.id),
            assigned_user_id=str(assigned_user_id),
            reason="rep_inactive_or_missing",
        )
        return

    ref = record.reference_number or str(record.id)
    make_model = " ".join(filter(None, [record.customer_make, record.customer_model])).strip()
    descriptor = f"{make_model} ({ref})" if make_model else ref
    subject = f"You've been assigned {ref}"
    body = (
        f"<p>Hi {rep.first_name or 'team'},</p>"
        f"<p>You have been assigned equipment record <strong>{descriptor}</strong>.</p>"
        f"<p>Trigger: <strong>{trigger}</strong></p>"
        "<p>Open the sales console to review and respond.</p>"
    )
    await notification_service.enqueue(
        db,
        idempotency_key=f"record_assigned:{record.id}:{assigned_user_id}:{trigger}",
        user_id=assigned_user_id,
        channel="email",
        template="record_assigned",
        payload={
            "to_email": rep.email,
            "subject": subject,
            "html_body": body,
            "reference_number": ref,
            "trigger": trigger,
        },
    )


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
        .options(
            selectinload(EquipmentRecord.intake_photos),
            selectinload(EquipmentRecord.status_events),
        )
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
        .options(
            selectinload(EquipmentRecord.intake_photos),
            selectinload(EquipmentRecord.status_events),
        )
        .where(
            EquipmentRecord.id == record_id,
            EquipmentRecord.customer_id == customer.id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Equipment record not found.")
    return record


async def finalize_intake_photo(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    storage_key: str,
    content_type: str,
    caption: str | None,
    display_order: int,
    sha256: str | None,
) -> CustomerIntakePhoto:
    """Persist metadata for a photo the client has already PUT to R2."""
    photo = CustomerIntakePhoto(
        equipment_record_id=record.id,
        storage_key=storage_key,
        caption=sanitization.sanitize_plain(caption),
        display_order=display_order,
        content_type=content_type,
        sha256=(sha256.lower() if sha256 else None),
        scan_status="pending",
    )
    db.add(photo)
    await db.flush()
    return photo
