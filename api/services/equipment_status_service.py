# ABOUTME: Records equipment_records.status transitions and notifies the customer via email.
# ABOUTME: Called from tests + future Phase 3 sales-rep endpoints; compose-once, use-everywhere.
"""Status transition service.

``record_transition`` is the one entry point for any code that changes
``equipment_records.status``. It:

1. Validates the ``(from, to)`` edge (stops typo-grade mistakes, not a
   full state machine — Phase 3 will tighten).
2. Writes an immutable ``status_events`` row.
3. Updates ``record.status`` and ``updated_at``.
4. Enqueues a customer-facing status-update email through
   ``NotificationService`` when the destination status warrants it.

Templates for status emails live inline here so the mapping of
``to_status → (subject, body)`` is reviewable in one place. Richer
templating can migrate to Jinja later without changing the contract.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord, StatusEvent, User
from services import notification_service

logger = structlog.get_logger(__name__)


# Destination statuses that should trigger a customer-facing email. The set
# is deliberately narrow — we don't want to spam users on every internal
# tick (e.g. appraiser_assigned). Phase 3 and the Admin Panel let this
# evolve via app_config, but day-one we hardcode the important ones.
_CUSTOMER_EMAIL_STATUSES = frozenset(
    {
        "appraisal_scheduled",
        "appraisal_complete",
        "offer_ready",
        "listed",
        "sold",
        "declined",
    }
)

# Minimal state machine. True = allowed. All other (from, to) pairs are
# accepted by default — Phase 3 hardens this. The explicit rejects here
# catch obvious bugs (e.g. moving from sold back to new_request).
_FORBIDDEN_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("sold", "new_request"),
        ("declined", "new_request"),
        ("sold", "listed"),
        ("sold", "appraisal_scheduled"),
    }
)


def _compose_email(
    *, user: User, record: EquipmentRecord, to_status: str, note: str | None
) -> tuple[str, str]:
    ref = record.reference_number or "(no reference yet)"
    display = {
        "appraisal_scheduled": "An appraisal has been scheduled",
        "appraisal_complete": "Your appraisal is complete",
        "offer_ready": "Your offer is ready to review",
        "listed": "Your equipment is now listed",
        "sold": "Your equipment has sold",
        "declined": "Your submission has been declined",
    }.get(to_status, f"Status update: {to_status}")
    subject = f"{display} — {ref}"

    note_html = f"<p>{note}</p>" if note else ""
    body = (
        f"<p>Hi {user.first_name},</p>"
        f"<p>The status of your equipment submission "
        f"(<strong>{ref}</strong>) has changed to <strong>{to_status}</strong>.</p>"
        f"{note_html}"
        "<p>You can see the full timeline from your customer portal.</p>"
        "<p>— The Temple Heavy Equipment team</p>"
    )
    return subject, body


async def record_transition(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    to_status: str,
    changed_by: User | None,
    note: str | None = None,
    customer: User | None = None,
) -> StatusEvent:
    """Apply a status transition.

    ``customer`` is the User whose email receives the notification.
    Typically resolved via ``record.customer.user`` in the caller; kept
    as an explicit arg so callers that already have the User object
    don't have to re-fetch it.
    """
    from_status = record.status
    if from_status == to_status:
        raise HTTPException(
            status_code=409,
            detail=f"Record is already in status '{to_status}'.",
        )
    if (from_status, to_status) in _FORBIDDEN_TRANSITIONS:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from '{from_status}' to '{to_status}'.",
        )

    event = StatusEvent(
        equipment_record_id=record.id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by.id if changed_by is not None else None,
        note=note,
    )
    db.add(event)
    record.status = to_status
    db.add(record)
    await db.flush()

    if customer is not None and to_status in _CUSTOMER_EMAIL_STATUSES:
        subject, body = _compose_email(user=customer, record=record, to_status=to_status, note=note)
        await notification_service.enqueue(
            db,
            idempotency_key=_email_idempotency_key(record.id, to_status),
            user_id=customer.id,
            channel="email",
            template=f"status_{to_status}",
            payload={
                "to_email": customer.email,
                "subject": subject,
                "html_body": body,
                "reference_number": record.reference_number,
                "to_status": to_status,
            },
        )
    return event


def _email_idempotency_key(record_id: uuid.UUID, to_status: str) -> str:
    """One email per (record, destination status). A bounce-back re-transition
    to the same status is blocked upstream, so this key never double-delivers."""
    return f"status_update:{record_id}:{to_status}"
