# ABOUTME: Phase 4 admin endpoints — operations dashboard, CSV export, manual transitions.
# ABOUTME: Admin-only RBAC. Reporting role uses the dedicated /admin/reports surface (Phase 8).
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import AuditLog, Customer, EquipmentRecord, User
from middleware.rbac import require_roles
from schemas.admin import (
    AdminOperationsResponse,
    ManualTransitionRequest,
    ManualTransitionResponse,
    SortDirection,
    SortField,
)
from services import (
    admin_operations_service,
    equipment_status_machine,
    equipment_status_service,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_require_admin = require_roles("admin")
_require_admin_or_reporting = require_roles("admin", "reporting")


@router.get("/operations", response_model=AdminOperationsResponse)
async def list_operations(
    status: str | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    customer_id: uuid.UUID | None = Query(default=None),
    overdue_only: bool = Query(default=False),
    sort: SortField = Query(default="updated_at"),
    direction: SortDirection = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationsResponse:
    rows, total = await admin_operations_service.list_records(
        db,
        status=status,
        assignee_id=assignee_id,
        customer_id=customer_id,
        overdue_only=overdue_only,
        sort=sort,
        direction=direction,
        page=page,
        per_page=per_page,
    )
    return AdminOperationsResponse(rows=rows, total=total, page=page, per_page=per_page)


@router.get("/operations/export.csv")
async def export_operations_csv(
    status: str | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    customer_id: uuid.UUID | None = Query(default=None),
    overdue_only: bool = Query(default=False),
    sort: SortField = Query(default="updated_at"),
    direction: SortDirection = Query(default="desc"),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    csv_text = await admin_operations_service.export_csv(
        db,
        status=status,
        assignee_id=assignee_id,
        customer_id=customer_id,
        overdue_only=overdue_only,
        sort=sort,
        direction=direction,
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="operations.csv"'},
    )


@router.post(
    "/equipment/{record_id}/transition",
    response_model=ManualTransitionResponse,
)
async def manual_transition(
    record_id: uuid.UUID,
    body: ManualTransitionRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> ManualTransitionResponse:
    """Admin override of equipment_records.status.

    Audit trail is split: the StatusEvent (timeline) is written by
    record_transition; the AuditLog row here records *that an admin used
    the override*, including the reason + notification choice. Without
    that, the timeline alone can't distinguish a legitimate admin
    correction from a regular sales-rep transition.
    """
    if not equipment_status_machine.is_known(body.to_status):
        raise HTTPException(status_code=422, detail=f"Unknown status '{body.to_status}'.")

    record = (
        await db.execute(
            select(EquipmentRecord)
            .where(EquipmentRecord.id == record_id)
            .where(EquipmentRecord.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Equipment record not found.")

    customer_user = await _resolve_customer_user(db, record=record)
    from_status = record.status

    event = await equipment_status_service.record_transition(
        db,
        record=record,
        to_status=body.to_status,
        changed_by=admin,
        note=body.reason,
        customer=customer_user,
        notify_override=body.send_notifications,
    )

    notifications_dispatched = (
        body.send_notifications
        if body.send_notifications is not None
        else (
            equipment_status_machine.notifies_customer(body.to_status)
            or equipment_status_machine.notifies_sales_rep(body.to_status)
        )
    )

    audit = AuditLog(
        event_type="equipment_record.status_admin_override",
        actor_id=admin.id,
        actor_role="admin",
        target_type="equipment_record",
        target_id=record.id,
        before_state={"status": from_status},
        after_state={
            "status": body.to_status,
            "reason": body.reason,
            "notifications_dispatched": notifications_dispatched,
            "status_event_id": str(event.id),
        },
    )
    db.add(audit)
    await db.flush()

    return ManualTransitionResponse(
        record_id=record.id,
        from_status=from_status,
        to_status=body.to_status,
        notifications_dispatched=notifications_dispatched,
        audit_log_id=audit.id,
    )


async def _resolve_customer_user(db: AsyncSession, *, record: EquipmentRecord) -> User | None:
    """Find the User to email for customer-facing notifications. Returns
    None when the record's customer has no user account (Sprint 2 walk-ins)
    so dispatch silently no-ops at the next step."""
    user = (
        await db.execute(
            select(User)
            .join(Customer, Customer.user_id == User.id)
            .where(Customer.id == record.customer_id)
        )
    ).scalar_one_or_none()
    return user


# --- Reporting role passthrough --------------------------------------------- #
# Sprint 1 ships only the placeholder so the `reporting` role gate is wired
# end-to-end; Phase 8 builds the real reports payloads.


@router.get("/reports", response_model=dict)
async def reports_index(
    _user: User = Depends(_require_admin_or_reporting),
) -> dict:
    return {
        "tabs": [
            {"slug": "sales_by_period", "label": "Sales by Period", "status": "phase8"},
            {
                "slug": "sales_by_type_location",
                "label": "Sales by Type/Location",
                "status": "phase8",
            },
            {"slug": "user_traffic", "label": "User Traffic", "status": "phase8"},
            {"slug": "export_center", "label": "Export Center", "status": "phase8"},
        ]
    }
