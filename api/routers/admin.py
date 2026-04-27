# ABOUTME: Phase 4 admin endpoints — operations dashboard, CSV export, manual transitions.
# ABOUTME: Admin-only RBAC. Reporting role uses the dedicated /admin/reports surface (Phase 8).
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import AuditLog, Customer, EquipmentRecord, User
from middleware.rbac import require_roles
from schemas.admin import (
    AddWatcherRequest,
    AdminCustomerCreate,
    AdminCustomerListResponse,
    AdminCustomerOut,
    AdminCustomerPatch,
    AdminOperationsResponse,
    DeactivateUserRequest,
    DeactivateUserResponse,
    ManualTransitionRequest,
    ManualTransitionResponse,
    SendInviteResponse,
    SortDirection,
    SortField,
    UnifiedNotificationPrefsOut,
    WatcherListResponse,
    WatcherOut,
)
from services import (
    admin_customer_service,
    admin_operations_service,
    admin_user_service,
    equipment_status_machine,
    equipment_status_service,
    unified_notification_prefs_service,
    watchers_service,
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


# --- Customer admin (Sprint 2) --------------------------------------------- #


@router.get("/customers", response_model=AdminCustomerListResponse)
async def list_customers(
    search: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    walkins_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCustomerListResponse:
    customers, total = await admin_customer_service.list_customers(
        db,
        search=search,
        include_deleted=include_deleted,
        walkins_only=walkins_only,
        page=page,
        per_page=per_page,
    )
    return AdminCustomerListResponse(customers=customers, total=total, page=page, per_page=per_page)


@router.get("/customers/{customer_id}", response_model=AdminCustomerOut)
async def get_customer(
    customer_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCustomerOut:
    return await admin_customer_service.get_customer(db, customer_id=customer_id)


@router.post("/customers", response_model=AdminCustomerOut, status_code=201)
async def create_walkin_customer(
    body: AdminCustomerCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCustomerOut:
    return await admin_customer_service.create_walkin(db, payload=body, actor=admin)


@router.patch("/customers/{customer_id}", response_model=AdminCustomerOut)
async def update_customer(
    customer_id: uuid.UUID,
    body: AdminCustomerPatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCustomerOut:
    return await admin_customer_service.update_customer(
        db, customer_id=customer_id, patch=body, actor=admin
    )


@router.delete("/customers/{customer_id}", response_model=AdminCustomerOut)
async def soft_delete_customer(
    customer_id: uuid.UUID,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCustomerOut:
    return await admin_customer_service.soft_delete_customer(
        db, customer_id=customer_id, actor=admin
    )


@router.post(
    "/customers/{customer_id}/send-invite",
    response_model=SendInviteResponse,
)
async def send_walkin_invite(
    customer_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> SendInviteResponse:
    return await admin_customer_service.send_walkin_invite(
        db,
        customer_id=customer_id,
        actor=admin,
        base_url=str(request.base_url).rstrip("/"),
        background_tasks=background_tasks,
    )


# --- Watchers + unified notification prefs (Sprint 5) --------------------- #


def _watcher_to_out(w) -> WatcherOut:
    return WatcherOut(
        user_id=w.user_id,
        email=w.user.email,
        first_name=w.user.first_name,
        last_name=w.user.last_name,
        added_by=w.added_by,
        added_at=w.added_at,
    )


@router.get("/equipment/{record_id}/watchers", response_model=WatcherListResponse)
async def list_record_watchers(
    record_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> WatcherListResponse:
    rows = await watchers_service.list_watchers(db, record_id=record_id)
    return WatcherListResponse(watchers=[_watcher_to_out(w) for w in rows])


@router.post(
    "/equipment/{record_id}/watchers",
    response_model=WatcherOut,
    status_code=201,
)
async def add_record_watcher(
    record_id: uuid.UUID,
    body: AddWatcherRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> WatcherOut:
    watcher = await watchers_service.add_watcher(
        db, record_id=record_id, user_id=body.user_id, added_by=admin.id
    )
    return _watcher_to_out(watcher)


@router.delete(
    "/equipment/{record_id}/watchers/{user_id}",
    status_code=204,
)
async def remove_record_watcher(
    record_id: uuid.UUID,
    user_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    removed = await watchers_service.remove_watcher(db, record_id=record_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Watcher not found.")
    return Response(status_code=204)


@router.get(
    "/users/{user_id}/notification-summary",
    response_model=UnifiedNotificationPrefsOut,
)
async def get_user_notification_summary(
    user_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> UnifiedNotificationPrefsOut:
    """Sprint 5 — Architectural Debt #5. Merged read of
    customers.communication_prefs (per-event opt-in) +
    notification_preferences (channel choice)."""
    view = await unified_notification_prefs_service.for_user(db, user_id=user_id)
    return UnifiedNotificationPrefsOut(
        user_id=view.user_id,
        email=view.email,
        role_slug=view.role_slug,
        channel=view.channel,
        phone_number=view.phone_number,
        slack_user_id=view.slack_user_id,
        intake_confirmations=view.intake_confirmations,
        status_updates=view.status_updates,
        marketing=view.marketing,
        sms_opt_in=view.sms_opt_in,
    )


# --- User deactivation (Sprint 2) ------------------------------------------ #


@router.post(
    "/users/{user_id}/deactivate",
    response_model=DeactivateUserResponse,
)
async def deactivate_user(
    user_id: uuid.UUID,
    body: DeactivateUserRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> DeactivateUserResponse:
    return await admin_user_service.deactivate_user(
        db,
        user_id=user_id,
        reassign_to_id=body.reassign_to_id,
        actor=admin,
    )


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
