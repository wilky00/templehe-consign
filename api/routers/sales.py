# ABOUTME: Sales rep endpoints — dashboard, record detail, assignment, cascade, publish, change-request resolution.
# ABOUTME: sales / sales_manager / admin only. Writes to a record require the caller to hold its lock.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import ChangeRequest, Role, User
from middleware.rbac import require_roles
from schemas.sales import (
    AssignmentPatch,
    CascadePatch,
    CascadeResult,
    ChangeRequestResolve,
    ChangeRequestResolveOut,
    ChangeRequestSummary,
    CustomerGroupOut,
    DashboardResponse,
    EquipmentDetailOut,
    EquipmentRowOut,
    PublishResponse,
    StatusEventSummary,
)
from services import change_request_service, sales_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/sales", tags=["sales"])

_require_sales = require_roles("sales", "sales_manager", "admin")


async def _acting_role_slug(db: AsyncSession, user: User) -> str:
    result = await db.execute(select(Role.slug).where(Role.id == user.role_id))
    slug = result.scalar_one_or_none()
    if slug is None:
        # Middleware should already have rejected this, but belt-and-suspenders.
        raise HTTPException(status_code=403, detail="role not resolved")
    return slug


def _row(record) -> EquipmentRowOut:
    return EquipmentRowOut(
        id=record.id,
        reference_number=record.reference_number,
        status=record.status,
        make=record.customer_make,
        model=record.customer_model,
        year=record.customer_year,
        serial_number=record.customer_serial_number,
        submitted_at=record.customer_submitted_at,
        assigned_sales_rep_id=record.assigned_sales_rep_id,
        assigned_appraiser_id=record.assigned_appraiser_id,
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    status: str | None = Query(default=None, max_length=40),
    assigned_rep_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    role_slug = await _acting_role_slug(db, current_user)
    customers, total_records = await sales_service.list_dashboard(
        db,
        acting_user=current_user,
        acting_role_slug=role_slug,
        scope=scope,
        status_filter=status,
        assigned_rep_id=assigned_rep_id,
    )
    groups: list[CustomerGroupOut] = []
    for c in customers:
        recs = getattr(c, "_filtered_records", [])
        first_submitted = min(
            (r.customer_submitted_at for r in recs if r.customer_submitted_at is not None),
            default=None,
        )
        assigned_rep = recs[0].assigned_sales_rep_id if recs else None
        groups.append(
            CustomerGroupOut(
                customer_id=c.id,
                business_name=c.business_name,
                submitter_name=c.submitter_name,
                cell_phone=c.cell_phone,
                business_phone=c.business_phone,
                business_phone_ext=c.business_phone_ext,
                state=c.address_state,
                first_submission_at=first_submitted,
                total_items=len(recs),
                assigned_sales_rep_id=assigned_rep,
                records=[_row(r) for r in recs],
            )
        )
    return DashboardResponse(
        customers=groups,
        total_customers=len(groups),
        total_records=total_records,
    )


# ---------------------------------------------------------------------------
# Detail + assignment
# ---------------------------------------------------------------------------


@router.get("/equipment/{record_id}", response_model=EquipmentDetailOut)
async def equipment_detail(
    record_id: uuid.UUID,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> EquipmentDetailOut:
    role_slug = await _acting_role_slug(db, current_user)
    record = await sales_service.get_record_detail(
        db,
        record_id=record_id,
        acting_user=current_user,
        acting_role_slug=role_slug,
    )
    customer = record.customer
    customer_user = customer.user
    return EquipmentDetailOut(
        id=record.id,
        reference_number=record.reference_number,
        status=record.status,
        make=record.customer_make,
        model=record.customer_model,
        year=record.customer_year,
        serial_number=record.customer_serial_number,
        hours=record.customer_hours,
        running_status=record.customer_running_status,
        ownership_type=record.customer_ownership_type,
        location_text=record.customer_location_text,
        description=record.customer_description,
        submitted_at=record.customer_submitted_at,
        created_at=record.created_at,
        assigned_sales_rep_id=record.assigned_sales_rep_id,
        assigned_appraiser_id=record.assigned_appraiser_id,
        customer_id=customer.id,
        customer_business_name=customer.business_name,
        customer_submitter_name=customer.submitter_name,
        customer_cell_phone=customer.cell_phone,
        customer_business_phone=customer.business_phone,
        customer_email=customer_user.email,
        has_signed_contract=record.consignment_contract is not None
        and record.consignment_contract.signed_at is not None,
        has_appraisal_report=bool(record.appraisal_reports),
        public_listing_status=record.public_listing.status if record.public_listing else None,
        status_history=[
            StatusEventSummary(
                from_status=e.from_status,
                to_status=e.to_status,
                changed_by=e.changed_by,
                note=e.note,
                created_at=e.created_at,
            )
            for e in sorted(record.status_events, key=lambda x: x.created_at)
        ],
        change_requests=[
            ChangeRequestSummary(
                id=cr.id,
                request_type=cr.request_type,
                customer_notes=cr.customer_notes,
                status=cr.status,
                resolution_notes=cr.resolution_notes,
                resolved_by=cr.resolved_by,
                submitted_at=cr.submitted_at,
                resolved_at=cr.resolved_at,
            )
            for cr in sorted(record.change_requests, key=lambda x: x.submitted_at, reverse=True)
        ],
    )


@router.patch("/equipment/{record_id}", response_model=EquipmentDetailOut)
async def update_assignment(
    record_id: uuid.UUID,
    body: AssignmentPatch,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> EquipmentDetailOut:
    role_slug = await _acting_role_slug(db, current_user)
    await sales_service.ensure_lock_held(db, record_id=record_id, user_id=current_user.id)
    record = await sales_service.get_record_detail(
        db,
        record_id=record_id,
        acting_user=current_user,
        acting_role_slug=role_slug,
    )
    set_sales_rep = "assigned_sales_rep_id" in body.model_fields_set
    set_appraiser = "assigned_appraiser_id" in body.model_fields_set
    if not set_sales_rep and not set_appraiser:
        raise HTTPException(status_code=422, detail="no fields to update")
    await sales_service.apply_assignment(
        db,
        record=record,
        acting_user=current_user,
        acting_role_slug=role_slug,
        set_sales_rep=set_sales_rep,
        sales_rep_id=body.assigned_sales_rep_id,
        set_appraiser=set_appraiser,
        appraiser_id=body.assigned_appraiser_id,
    )
    return await equipment_detail(record_id, current_user, db)


# ---------------------------------------------------------------------------
# Cascade
# ---------------------------------------------------------------------------


@router.patch(
    "/customers/{customer_id}/cascade-assignments",
    response_model=CascadeResult,
)
async def cascade_customer_assignments(
    customer_id: uuid.UUID,
    body: CascadePatch,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> CascadeResult:
    role_slug = await _acting_role_slug(db, current_user)
    set_sales_rep = "assigned_sales_rep_id" in body.model_fields_set
    set_appraiser = "assigned_appraiser_id" in body.model_fields_set
    if not set_sales_rep and not set_appraiser:
        raise HTTPException(status_code=422, detail="no fields to cascade")
    updated, skipped = await sales_service.cascade_assignment(
        db,
        customer_id=customer_id,
        acting_user=current_user,
        acting_role_slug=role_slug,
        set_sales_rep=set_sales_rep,
        sales_rep_id=body.assigned_sales_rep_id,
        set_appraiser=set_appraiser,
        appraiser_id=body.assigned_appraiser_id,
    )
    skipped_reason = (
        f"{len(skipped)} record(s) past 'new_request' were left untouched"
        if skipped
        else None
    )
    return CascadeResult(
        updated_record_ids=updated,
        skipped_record_ids=skipped,
        skipped_reason=skipped_reason,
    )


# ---------------------------------------------------------------------------
# Manual publish
# ---------------------------------------------------------------------------


@router.post("/equipment/{record_id}/publish", response_model=PublishResponse)
async def publish(
    record_id: uuid.UUID,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> PublishResponse:
    role_slug = await _acting_role_slug(db, current_user)
    record, listing = await sales_service.publish_record(
        db,
        record_id=record_id,
        acting_user=current_user,
        acting_role_slug=role_slug,
    )
    return PublishResponse(
        equipment_record_id=record.id,
        status=record.status,
        public_listing_id=listing.id,
        published_at=listing.published_at,
    )


# ---------------------------------------------------------------------------
# Change-request resolution
# ---------------------------------------------------------------------------


@router.patch(
    "/change-requests/{change_request_id}",
    response_model=ChangeRequestResolveOut,
)
async def resolve_change_request(
    change_request_id: uuid.UUID,
    body: ChangeRequestResolve,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> ChangeRequestResolveOut:
    role_slug = await _acting_role_slug(db, current_user)
    change = await change_request_service.resolve_change_request(
        db,
        change_request_id=change_request_id,
        resolver=current_user,
        resolver_role_slug=role_slug,
        new_status=body.status,
        resolution_notes=body.resolution_notes,
    )
    # Re-read the record status since the withdraw path may have flipped it.
    refreshed = (
        await db.execute(
            select(ChangeRequest.equipment_record_id).where(
                ChangeRequest.id == change_request_id
            )
        )
    ).scalar_one()
    from database.models import EquipmentRecord

    record_status = (
        await db.execute(select(EquipmentRecord.status).where(EquipmentRecord.id == refreshed))
    ).scalar_one()
    return ChangeRequestResolveOut(
        id=change.id,
        status=change.status,
        resolution_notes=change.resolution_notes,
        resolved_by=change.resolved_by,
        resolved_at=change.resolved_at,
        equipment_record_id=refreshed,
        equipment_record_status=record_status,
    )
