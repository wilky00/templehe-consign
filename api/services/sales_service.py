# ABOUTME: Sales rep dashboard queries + cascade assignment + helpers consumed by the sales router.
# ABOUTME: Grouping-by-customer and filter logic lives here; the router is a thin pass-through.
"""Sales service.

Grouped dashboard query, cascade assignment, and the lock-checked
per-record update helper. The router delegates to these so the business
rules stay unit-testable and so future callers (Phase 4 admin panel)
can reuse the same entry points.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AppraisalReport,
    AuditLog,
    ChangeRequest,
    ConsignmentContract,
    Customer,
    EquipmentRecord,
    PublicListing,
    RecordLock,
    Role,
    StatusEvent,
    User,
)
from services import equipment_service, equipment_status_service

logger = structlog.get_logger(__name__)

# Statuses that block a cascade assignment. Records past new_request have
# real work attached (scheduled appraisers, signed contracts) — a cascade
# re-assignment would clobber that context. Spec Feature 3.1.3.
_CASCADE_ASSIGNABLE_STATUSES = frozenset({"new_request"})


async def list_dashboard(
    db: AsyncSession,
    *,
    acting_user: User,
    acting_role_slug: str,
    scope: str = "mine",
    status_filter: str | None = None,
    assigned_rep_id: uuid.UUID | None = None,
) -> tuple[list[Customer], int]:
    """Return customers + their equipment records matching the scope/filter.

    ``scope``:
      - ``"mine"`` — only records assigned to ``acting_user``. Default for
        the ``sales`` role; still honored for managers/admins who want
        their personal list.
      - ``"all"`` — no rep filter. Restricted to ``sales_manager``/
        ``admin``; a ``sales`` caller who passes ``all`` is demoted to
        ``mine`` without error.

    Only returns customers that have at least one record in the filtered
    set, so managers browsing ``all`` don't see long tails of empty rows.
    """
    effective_scope = scope
    if scope == "all" and acting_role_slug not in ("sales_manager", "admin"):
        effective_scope = "mine"

    stmt = (
        select(EquipmentRecord)
        .options(selectinload(EquipmentRecord.customer))
        .where(EquipmentRecord.deleted_at.is_(None))
    )
    if effective_scope == "mine":
        stmt = stmt.where(EquipmentRecord.assigned_sales_rep_id == acting_user.id)
    elif assigned_rep_id is not None:
        stmt = stmt.where(EquipmentRecord.assigned_sales_rep_id == assigned_rep_id)
    if status_filter is not None:
        stmt = stmt.where(EquipmentRecord.status == status_filter)
    stmt = stmt.order_by(EquipmentRecord.created_at.asc())

    result = await db.execute(stmt)
    records = list(result.scalars().all())

    by_customer: dict[uuid.UUID, tuple[Customer, list[EquipmentRecord]]] = {}
    for rec in records:
        entry = by_customer.setdefault(rec.customer_id, (rec.customer, []))
        entry[1].append(rec)

    # Stable ordering: earliest first-submission first, so a customer
    # with a new request shows near the bottom.
    ordered: list[Customer] = []
    for customer, recs in sorted(
        by_customer.values(),
        key=lambda pair: min((r.created_at for r in pair[1]), default=datetime.now(UTC)),
    ):
        customer._filtered_records = recs  # type: ignore[attr-defined]
        ordered.append(customer)

    return ordered, len(records)


async def get_record_detail(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    acting_user: User,
    acting_role_slug: str,
) -> EquipmentRecord:
    """Return an equipment record with every relationship needed by the detail view."""
    stmt = (
        select(EquipmentRecord)
        .where(
            EquipmentRecord.id == record_id,
            EquipmentRecord.deleted_at.is_(None),
        )
        .options(
            selectinload(EquipmentRecord.customer).selectinload(Customer.user),
            selectinload(EquipmentRecord.status_events),
            selectinload(EquipmentRecord.change_requests),
            selectinload(EquipmentRecord.consignment_contract),
            selectinload(EquipmentRecord.appraisal_reports),
            selectinload(EquipmentRecord.public_listing),
        )
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="record not found")
    return record


async def ensure_lock_held(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Require that ``user_id`` holds a live lock on the record before a write.

    Raises 409 if no lock exists for this user. Matches the UI contract
    from Epic 3.1.2: the record must be opened (acquire) before edits.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(RecordLock).where(
            RecordLock.record_id == record_id,
            RecordLock.record_type == "equipment_record",
            RecordLock.locked_by == user_id,
            RecordLock.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="You must acquire the record lock before making changes.",
        )


async def apply_assignment(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    acting_user: User,
    acting_role_slug: str,
    set_sales_rep: bool,
    sales_rep_id: uuid.UUID | None,
    set_appraiser: bool,
    appraiser_id: uuid.UUID | None,
) -> EquipmentRecord:
    """Apply an assignment change. Caller must have already verified the lock.

    Writes one audit event capturing both the before + after assignment state.
    Validates any referenced user exists and has the expected role.
    """
    before = {
        "assigned_sales_rep_id": str(record.assigned_sales_rep_id)
        if record.assigned_sales_rep_id
        else None,
        "assigned_appraiser_id": str(record.assigned_appraiser_id)
        if record.assigned_appraiser_id
        else None,
    }

    prior_sales_rep_id = record.assigned_sales_rep_id
    if set_sales_rep:
        if sales_rep_id is not None:
            await _require_user_has_role(db, sales_rep_id, ("sales", "sales_manager", "admin"))
        record.assigned_sales_rep_id = sales_rep_id
    if set_appraiser:
        if appraiser_id is not None:
            await _require_user_has_role(db, appraiser_id, ("appraiser",))
        record.assigned_appraiser_id = appraiser_id

    db.add(record)
    await db.flush()

    after = {
        "assigned_sales_rep_id": str(record.assigned_sales_rep_id)
        if record.assigned_sales_rep_id
        else None,
        "assigned_appraiser_id": str(record.assigned_appraiser_id)
        if record.assigned_appraiser_id
        else None,
    }
    db.add(
        AuditLog(
            event_type="equipment_record.assignment_changed",
            actor_id=acting_user.id,
            actor_role=acting_role_slug,
            target_type="equipment_record",
            target_id=record.id,
            before_state=before,
            after_state=after,
        )
    )
    await db.flush()

    # Spec Feature 3.3.3: notify the newly-assigned sales rep on a manual
    # change. Only fire when the assignment actually changed to a non-null
    # user — re-assigning the same rep or clearing the field is a no-op.
    if (
        set_sales_rep
        and sales_rep_id is not None
        and sales_rep_id != prior_sales_rep_id
    ):
        await equipment_service.enqueue_assignment_notification(
            db,
            record=record,
            assigned_user_id=sales_rep_id,
            trigger="manual_override",
        )
    return record


async def cascade_assignment(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    acting_user: User,
    acting_role_slug: str,
    set_sales_rep: bool,
    sales_rep_id: uuid.UUID | None,
    set_appraiser: bool,
    appraiser_id: uuid.UUID | None,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Bulk assign across all of a customer's records in ``new_request``.

    Returns (updated_ids, skipped_ids). Skipped = records past new_request
    that aren't eligible for the sweep. Writes one audit event listing all
    affected + skipped IDs — matches spec Feature 3.1.3.
    """
    customer_exists = await db.execute(
        select(Customer.id).where(Customer.id == customer_id, Customer.deleted_at.is_(None))
    )
    if customer_exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="customer not found")

    if set_sales_rep and sales_rep_id is not None:
        await _require_user_has_role(db, sales_rep_id, ("sales", "sales_manager", "admin"))
    if set_appraiser and appraiser_id is not None:
        await _require_user_has_role(db, appraiser_id, ("appraiser",))

    result = await db.execute(
        select(EquipmentRecord).where(
            EquipmentRecord.customer_id == customer_id,
            EquipmentRecord.deleted_at.is_(None),
        )
    )
    records = list(result.scalars().all())
    updated: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    for rec in records:
        if rec.status not in _CASCADE_ASSIGNABLE_STATUSES:
            skipped.append(rec.id)
            continue
        if set_sales_rep:
            rec.assigned_sales_rep_id = sales_rep_id
        if set_appraiser:
            rec.assigned_appraiser_id = appraiser_id
        db.add(rec)
        updated.append(rec.id)

    await db.flush()

    db.add(
        AuditLog(
            event_type="customer.cascade_assignment",
            actor_id=acting_user.id,
            actor_role=acting_role_slug,
            target_type="customer",
            target_id=customer_id,
            after_state={
                "assigned_sales_rep_id": str(sales_rep_id) if set_sales_rep else None,
                "assigned_appraiser_id": str(appraiser_id) if set_appraiser else None,
                "updated_record_ids": [str(r) for r in updated],
                "skipped_record_ids": [str(r) for r in skipped],
            },
        )
    )
    await db.flush()
    return updated, skipped


async def publish_record(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    acting_user: User,
    acting_role_slug: str,
) -> tuple[EquipmentRecord, PublicListing]:
    """Manually publish a record. Spec Feature 3.1.4.

    Validates:
    - status == ``esigned_pending_publish``
    - a ``ConsignmentContract`` row exists with ``signed_at`` set
    - at least one ``AppraisalReport`` row exists

    Transitions to ``listed`` (the code's name for "published publicly";
    see equipment_status_service._CUSTOMER_EMAIL_STATUSES) and creates
    or updates the ``PublicListing`` row. Customer notification fires
    automatically via ``record_transition``.
    """
    stmt = (
        select(EquipmentRecord)
        .where(
            EquipmentRecord.id == record_id,
            EquipmentRecord.deleted_at.is_(None),
        )
        .options(
            selectinload(EquipmentRecord.customer).selectinload(Customer.user),
            selectinload(EquipmentRecord.consignment_contract),
            selectinload(EquipmentRecord.appraisal_reports),
            selectinload(EquipmentRecord.public_listing),
        )
    )
    record = (await db.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="record not found")

    if record.status != "esigned_pending_publish":
        raise HTTPException(
            status_code=400,
            detail=(
                f"record is in '{record.status}', not 'esigned_pending_publish'; "
                "publish is only valid after eSign"
            ),
        )
    if record.consignment_contract is None or record.consignment_contract.signed_at is None:
        raise HTTPException(
            status_code=400,
            detail="no signed consignment contract on file",
        )
    if not record.appraisal_reports:
        raise HTTPException(status_code=400, detail="no appraisal report on file")

    listing = record.public_listing
    if listing is None:
        listing = PublicListing(
            equipment_record_id=record.id,
            listing_title=f"{record.customer_make or ''} {record.customer_model or ''}".strip()
            or (record.reference_number or str(record.id)),
            status="active",
            published_at=datetime.now(UTC),
        )
        db.add(listing)
    else:
        listing.status = "active"
        listing.published_at = datetime.now(UTC)
        db.add(listing)
    await db.flush()

    await equipment_status_service.record_transition(
        db,
        record=record,
        to_status="listed",
        changed_by=acting_user,
        note="Listing published by sales rep.",
        customer=record.customer.user,
    )

    db.add(
        AuditLog(
            event_type="equipment_record.published",
            actor_id=acting_user.id,
            actor_role=acting_role_slug,
            target_type="equipment_record",
            target_id=record.id,
            after_state={
                "public_listing_id": str(listing.id),
                "published_at": listing.published_at.isoformat()
                if listing.published_at
                else None,
            },
        )
    )
    await db.flush()
    return record, listing


async def _require_user_has_role(
    db: AsyncSession, user_id: uuid.UUID, allowed_slugs: tuple[str, ...]
) -> None:
    result = await db.execute(
        select(User, Role.slug)
        .join(Role, Role.id == User.role_id)
        .where(User.id == user_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=422, detail=f"assigned user {user_id} not found"
        )
    _, slug = row
    if slug not in allowed_slugs:
        raise HTTPException(
            status_code=422,
            detail=f"user {user_id} has role '{slug}', expected one of {list(allowed_slugs)}",
        )
