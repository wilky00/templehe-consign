# ABOUTME: Phase 4 Sprint 2 — admin CRUD on customers + walk-in creation + portal invite.
# ABOUTME: Soft-delete cascades to equipment_records; every mutation writes an AuditLog diff.
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import AuditLog, Customer, User
from schemas.admin import (
    AdminCustomerCreate,
    AdminCustomerEquipmentSummary,
    AdminCustomerOut,
    AdminCustomerPatch,
    SendInviteResponse,
)
from services import email_service

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _serialize(customer: Customer, *, include_records: bool) -> AdminCustomerOut:
    """Build an AdminCustomerOut. ``include_records`` MUST match how the
    customer was loaded — passing True without selectinload on
    equipment_records triggers an async lazy-load attempt and a
    MissingGreenlet crash. Same goes for the user relationship."""
    records: list[AdminCustomerEquipmentSummary] = []
    if include_records:
        for r in customer.equipment_records or []:
            records.append(
                AdminCustomerEquipmentSummary(
                    id=r.id,
                    reference_number=r.reference_number,
                    status=r.status,
                    make=r.customer_make,
                    model=r.customer_model,
                    year=r.customer_year,
                    deleted_at=r.deleted_at,
                )
            )
    return AdminCustomerOut(
        id=customer.id,
        user_id=customer.user_id,
        user_email=customer.user.email if customer.user else None,
        invite_email=customer.invite_email,
        business_name=customer.business_name,
        submitter_name=customer.submitter_name,
        title=customer.title,
        address_street=customer.address_street,
        address_city=customer.address_city,
        address_state=customer.address_state,
        address_zip=customer.address_zip,
        business_phone=customer.business_phone,
        business_phone_ext=customer.business_phone_ext,
        cell_phone=customer.cell_phone,
        is_walkin=customer.user_id is None,
        is_deleted=customer.deleted_at is not None,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
        deleted_at=customer.deleted_at,
        equipment_records=records,
    )


async def list_customers(
    db: AsyncSession,
    *,
    search: str | None = None,
    include_deleted: bool = False,
    walkins_only: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[AdminCustomerOut], int]:
    page = max(1, page)
    per_page = max(1, min(200, per_page))
    base = select(Customer).options(selectinload(Customer.user))
    count_base = select(func.count()).select_from(Customer)
    if not include_deleted:
        base = base.where(Customer.deleted_at.is_(None))
        count_base = count_base.where(Customer.deleted_at.is_(None))
    if walkins_only:
        base = base.where(Customer.user_id.is_(None))
        count_base = count_base.where(Customer.user_id.is_(None))
    if search:
        # Case-insensitive substring search across the most useful
        # admin-finds-this-customer fields. Indexed scans aren't a
        # concern at the org's scale; revisit when customer count > ~10k.
        like = f"%{search.lower()}%"
        base = base.outerjoin(User, User.id == Customer.user_id).where(
            or_(
                func.lower(Customer.submitter_name).like(like),
                func.lower(Customer.business_name).like(like),
                func.lower(Customer.invite_email).like(like),
                func.lower(User.email).like(like),
                func.lower(Customer.business_phone).like(like),
                func.lower(Customer.cell_phone).like(like),
            )
        )
        count_base = count_base.outerjoin(User, User.id == Customer.user_id).where(
            or_(
                func.lower(Customer.submitter_name).like(like),
                func.lower(Customer.business_name).like(like),
                func.lower(Customer.invite_email).like(like),
                func.lower(User.email).like(like),
                func.lower(Customer.business_phone).like(like),
                func.lower(Customer.cell_phone).like(like),
            )
        )
    total = (await db.execute(count_base)).scalar_one()
    stmt = base.order_by(Customer.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    customers = (await db.execute(stmt)).scalars().unique().all()
    return [_serialize(c, include_records=False) for c in customers], total


async def get_customer(db: AsyncSession, *, customer_id: uuid.UUID) -> AdminCustomerOut:
    customer = await _load(db, customer_id=customer_id, include_records=True)
    return _serialize(customer, include_records=True)


async def update_customer(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    patch: AdminCustomerPatch,
    actor: User,
) -> AdminCustomerOut:
    customer = await _load(db, customer_id=customer_id, include_records=False)
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    if "invite_email" in fields and fields["invite_email"] is not None:
        if not _EMAIL_REGEX.match(fields["invite_email"]):
            raise HTTPException(status_code=422, detail="invite_email is not a valid address.")

    if "address_state" in fields and fields["address_state"] is not None:
        fields["address_state"] = fields["address_state"].strip().upper()

    before = {k: getattr(customer, k) for k in fields}
    for k, v in fields.items():
        setattr(customer, k, v)
    db.add(customer)
    await db.flush()
    after = {k: getattr(customer, k) for k in fields}

    db.add(
        AuditLog(
            event_type="customer.admin_update",
            actor_id=actor.id,
            actor_role="admin",
            target_type="customer",
            target_id=customer.id,
            before_state=_jsonable(before),
            after_state=_jsonable(after),
        )
    )
    await db.flush()
    # Reload with records for the response payload.
    customer = await _load(db, customer_id=customer.id, include_records=True)
    return _serialize(customer, include_records=True)


async def soft_delete_customer(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    actor: User,
) -> AdminCustomerOut:
    """Soft-delete the customer + cascade to their equipment_records.
    Idempotent: re-deleting a deleted customer returns the current row
    without writing another audit log entry."""
    customer = await _load(db, customer_id=customer_id, include_records=True)
    if customer.deleted_at is not None:
        return _serialize(customer, include_records=True)

    now = datetime.now(UTC)
    customer.deleted_at = now
    db.add(customer)
    affected_record_ids: list[str] = []
    for rec in customer.equipment_records or []:
        if rec.deleted_at is None:
            rec.deleted_at = now
            db.add(rec)
            affected_record_ids.append(str(rec.id))
    await db.flush()

    db.add(
        AuditLog(
            event_type="customer.admin_soft_delete",
            actor_id=actor.id,
            actor_role="admin",
            target_type="customer",
            target_id=customer.id,
            before_state={"deleted_at": None},
            after_state={
                "deleted_at": now.isoformat(),
                "cascaded_record_ids": affected_record_ids,
            },
        )
    )
    await db.flush()
    return _serialize(customer, include_records=True)


async def create_walkin(
    db: AsyncSession,
    *,
    payload: AdminCustomerCreate,
    actor: User,
) -> AdminCustomerOut:
    """Admin-typed customer with no portal account yet. user_id stays
    NULL until the customer accepts an invite and registers; the
    customer.invite_email field carries the address the invite will go
    to."""
    if not _EMAIL_REGEX.match(payload.invite_email):
        raise HTTPException(status_code=422, detail="invite_email is not a valid address.")
    state = payload.address_state.strip().upper() if payload.address_state is not None else None
    customer = Customer(
        user_id=None,
        invite_email=payload.invite_email.strip().lower(),
        submitter_name=payload.submitter_name.strip(),
        business_name=payload.business_name,
        title=payload.title,
        address_street=payload.address_street,
        address_city=payload.address_city,
        address_state=state,
        address_zip=payload.address_zip,
        business_phone=payload.business_phone,
        business_phone_ext=payload.business_phone_ext,
        cell_phone=payload.cell_phone,
    )
    db.add(customer)
    await db.flush()

    db.add(
        AuditLog(
            event_type="customer.admin_walkin_created",
            actor_id=actor.id,
            actor_role="admin",
            target_type="customer",
            target_id=customer.id,
            before_state=None,
            after_state={
                "submitter_name": customer.submitter_name,
                "invite_email": customer.invite_email,
                "business_name": customer.business_name,
            },
        )
    )
    await db.flush()
    # Re-fetch with relationships eagerly loaded — async sessions can't
    # lazy-load on attribute access during the response build.
    customer = await _load(db, customer_id=customer.id, include_records=True)
    return _serialize(customer, include_records=True)


async def send_walkin_invite(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    actor: User,
    base_url: str,
    background_tasks: BackgroundTasks,
) -> SendInviteResponse:
    customer = await _load(db, customer_id=customer_id, include_records=False)
    if customer.user_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Customer already has a portal account; nothing to invite.",
        )
    if not customer.invite_email:
        raise HTTPException(
            status_code=409,
            detail="Customer has no invite_email set. Update the record first.",
        )

    register_url = f"{base_url.rstrip('/')}/register?email={customer.invite_email}"
    inviter_name = " ".join(p for p in (actor.first_name, actor.last_name) if p) or actor.email
    background_tasks.add_task(
        email_service.send_walkin_invite_email,
        customer.invite_email,
        register_url,
        customer.submitter_name,
        inviter_name,
    )

    sent_at = datetime.now(UTC)
    db.add(
        AuditLog(
            event_type="customer.admin_invite_sent",
            actor_id=actor.id,
            actor_role="admin",
            target_type="customer",
            target_id=customer.id,
            before_state=None,
            after_state={
                "invite_email": customer.invite_email,
                "sent_at": sent_at.isoformat(),
            },
        )
    )
    await db.flush()
    return SendInviteResponse(
        customer_id=customer.id,
        invite_email=customer.invite_email,
        sent_at=sent_at,
    )


async def _load(db: AsyncSession, *, customer_id: uuid.UUID, include_records: bool) -> Customer:
    stmt = select(Customer).where(Customer.id == customer_id)
    options = [selectinload(Customer.user)]
    if include_records:
        options.append(selectinload(Customer.equipment_records))
    stmt = stmt.options(*options)
    customer = (await db.execute(stmt)).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return customer


def _jsonable(d: dict) -> dict:
    """Ensure dict is JSON-serializable for AuditLog.before/after_state.
    Datetimes → ISO strings; UUIDs → str. Everything else passes through."""
    out = {}
    for k, v in d.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out
