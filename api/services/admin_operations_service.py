# ABOUTME: Read model for admin operations dashboard — records, filters, sort, CSV export.
# ABOUTME: Days-in-status from latest StatusEvent; overdue threshold defaults to 7d.
from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import coalesce

from database.models import Customer, EquipmentRecord, StatusEvent, User
from schemas.admin import AdminOperationsRow, SortDirection, SortField
from services import app_config_registry, equipment_status_machine

# Pre-Sprint-3 default. Now lives on the AppConfig spec
# (`equipment_record_overdue_threshold_days`). Kept here only as the
# fallback value when the AppConfig key is missing or malformed; the
# runtime always reads through `_resolve_overdue_threshold` so admin
# can tune the threshold without a deploy.
DEFAULT_OVERDUE_THRESHOLD_DAYS = 7

_SortField = SortField
_SortDirection = SortDirection


def _full_name(first: str | None, last: str | None) -> str:
    parts = [p for p in (first, last) if p]
    return " ".join(parts) if parts else "(no name)"


async def _entered_current_status_at_map(
    db: AsyncSession, *, record_ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """For each record id, return the timestamp when it last entered its
    current ``status``. Falls back to ``record.created_at`` when the
    record has no StatusEvent rows yet (legacy seed data, mostly)."""
    if not record_ids:
        return {}
    rows = (
        await db.execute(
            select(
                StatusEvent.equipment_record_id,
                func.max(StatusEvent.created_at).label("entered_at"),
            )
            .where(StatusEvent.equipment_record_id.in_(record_ids))
            .group_by(StatusEvent.equipment_record_id)
        )
    ).all()
    return {row.equipment_record_id: row.entered_at for row in rows}


def _build_base_query(
    *,
    status: str | None,
    assignee_id: uuid.UUID | None,
    customer_id: uuid.UUID | None,
    overdue_only: bool,
    overdue_threshold_days: int,
) -> Select:
    """Build the filtered SELECT before pagination + sort. Returns a
    statement selecting EquipmentRecord plus the related Customer +
    aliased sales/appraiser users — joined eagerly so the row builder
    doesn't trigger lazy loads."""
    sales_rep = aliased(User, name="sales_rep")
    appraiser = aliased(User, name="appraiser")

    stmt = (
        select(EquipmentRecord, Customer, sales_rep, appraiser)
        .join(Customer, Customer.id == EquipmentRecord.customer_id)
        .join(sales_rep, sales_rep.id == EquipmentRecord.assigned_sales_rep_id, isouter=True)
        .join(appraiser, appraiser.id == EquipmentRecord.assigned_appraiser_id, isouter=True)
        .where(EquipmentRecord.deleted_at.is_(None))
    )
    if status:
        stmt = stmt.where(EquipmentRecord.status == status)
    if assignee_id:
        stmt = stmt.where(
            (EquipmentRecord.assigned_sales_rep_id == assignee_id)
            | (EquipmentRecord.assigned_appraiser_id == assignee_id)
        )
    if customer_id:
        stmt = stmt.where(EquipmentRecord.customer_id == customer_id)
    if overdue_only:
        # Records that haven't transitioned in the threshold window.
        # equipment_records.updated_at can't drive this — a DB trigger
        # bumps it on every UPDATE (assignment changes, etc.), so a
        # record can be young in the row sense and still stale in the
        # status sense. The status-event timestamp is the right anchor.
        stmt = stmt.where(_overdue_predicate(overdue_threshold_days))
    return stmt


def _overdue_predicate(overdue_threshold_days: int):
    """Build the WHERE clause that says "this record's current status
    has been held for at least ``overdue_threshold_days`` days." Uses
    the latest StatusEvent's ``created_at`` per record, falling back to
    ``equipment_records.created_at`` when no event has fired yet."""
    cutoff = datetime.now(UTC) - timedelta(days=overdue_threshold_days)
    latest_event_at = (
        select(func.max(StatusEvent.created_at))
        .where(StatusEvent.equipment_record_id == EquipmentRecord.id)
        .correlate(EquipmentRecord)
        .scalar_subquery()
    )
    return coalesce(latest_event_at, EquipmentRecord.created_at) < cutoff


def _apply_sort(stmt: Select, *, sort: _SortField, direction: _SortDirection) -> Select:
    direction_fn = asc if direction == "asc" else desc
    if sort == "updated_at":
        return stmt.order_by(direction_fn(EquipmentRecord.updated_at))
    if sort == "submitted_at":
        return stmt.order_by(direction_fn(EquipmentRecord.customer_submitted_at))
    if sort == "status":
        return stmt.order_by(direction_fn(EquipmentRecord.status))
    if sort == "customer_name":
        return stmt.order_by(direction_fn(Customer.submitter_name))
    # days_in_status sort happens client-side over the row builder; the SQL
    # layer falls back to updated_at to keep pagination stable.
    return stmt.order_by(direction_fn(EquipmentRecord.updated_at))


def _row_from_join(
    record: EquipmentRecord,
    customer: Customer,
    sales_rep: User | None,
    appraiser: User | None,
    *,
    entered_at: datetime,
    overdue_threshold_days: int,
) -> AdminOperationsRow:
    now = datetime.now(UTC)
    days_in_status = max(0, (now - entered_at).days)
    is_overdue = days_in_status >= overdue_threshold_days
    return AdminOperationsRow(
        id=record.id,
        reference_number=record.reference_number,
        status=record.status,
        status_display=equipment_status_machine.display_name(record.status),
        days_in_status=days_in_status,
        customer_id=customer.id,
        customer_name=customer.submitter_name,
        business_name=customer.business_name,
        state=customer.address_state,
        make=record.customer_make,
        model=record.customer_model,
        year=record.customer_year,
        assigned_sales_rep_id=record.assigned_sales_rep_id,
        assigned_sales_rep_name=(
            _full_name(sales_rep.first_name, sales_rep.last_name) if sales_rep else None
        ),
        assigned_appraiser_id=record.assigned_appraiser_id,
        assigned_appraiser_name=(
            _full_name(appraiser.first_name, appraiser.last_name) if appraiser else None
        ),
        is_overdue=is_overdue,
        submitted_at=record.customer_submitted_at,
        updated_at=record.updated_at,
    )


async def _resolve_overdue_threshold(db: AsyncSession, *, override: int | None) -> int:
    """Caller can pin the threshold (tests, ad-hoc one-off queries);
    otherwise read the AppConfig key. Falls back to the registry's
    declared default when the key is unset (no DB row)."""
    if override is not None:
        return override
    value = await app_config_registry.get_typed(
        db, app_config_registry.EQUIPMENT_RECORD_OVERDUE_THRESHOLD_DAYS.name
    )
    if isinstance(value, int) and value >= 1:
        return value
    return DEFAULT_OVERDUE_THRESHOLD_DAYS


async def list_records(
    db: AsyncSession,
    *,
    status: str | None = None,
    assignee_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    overdue_threshold_days: int | None = None,
    sort: _SortField = "updated_at",
    direction: _SortDirection = "desc",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[AdminOperationsRow], int]:
    """Return (rows, total). Total is the unpaginated count for client-side
    pagination controls. Rows already include days-in-status + overdue flag.

    ``overdue_threshold_days`` defaults to the AppConfig value; tests can
    pin an explicit number to keep their fixtures deterministic."""
    page = max(1, page)
    per_page = max(1, min(200, per_page))
    overdue_threshold_days = await _resolve_overdue_threshold(db, override=overdue_threshold_days)
    base = _build_base_query(
        status=status,
        assignee_id=assignee_id,
        customer_id=customer_id,
        overdue_only=overdue_only,
        overdue_threshold_days=overdue_threshold_days,
    )
    count_stmt = (
        select(func.count())
        .select_from(EquipmentRecord)
        .where(EquipmentRecord.deleted_at.is_(None))
    )
    for clause in _active_filter_clauses(
        status=status, assignee_id=assignee_id, customer_id=customer_id
    ):
        count_stmt = count_stmt.where(clause)
    if overdue_only:
        count_stmt = count_stmt.where(_overdue_predicate(overdue_threshold_days))
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        _apply_sort(base, sort=sort, direction=direction)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    join_rows = (await db.execute(stmt)).all()
    record_ids = [r[0].id for r in join_rows]
    entered_map = await _entered_current_status_at_map(db, record_ids=record_ids)

    out: list[AdminOperationsRow] = []
    for record, customer, sales_rep, appraiser in join_rows:
        entered = entered_map.get(record.id, record.created_at)
        out.append(
            _row_from_join(
                record,
                customer,
                sales_rep,
                appraiser,
                entered_at=entered,
                overdue_threshold_days=overdue_threshold_days,
            )
        )

    if sort == "days_in_status":
        out.sort(key=lambda r: r.days_in_status, reverse=(direction == "desc"))

    return out, total


def _active_filter_clauses(
    *, status: str | None, assignee_id: uuid.UUID | None, customer_id: uuid.UUID | None
) -> list:
    """Return COUNT(*) WHERE clauses mirroring _build_base_query
    (without the overdue pre-filter, which the caller adds separately
    when requested)."""
    clauses: list = []
    if status:
        clauses.append(EquipmentRecord.status == status)
    if assignee_id:
        clauses.append(
            (EquipmentRecord.assigned_sales_rep_id == assignee_id)
            | (EquipmentRecord.assigned_appraiser_id == assignee_id)
        )
    if customer_id:
        clauses.append(EquipmentRecord.customer_id == customer_id)
    return clauses


async def export_csv(
    db: AsyncSession,
    *,
    status: str | None = None,
    assignee_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    overdue_threshold_days: int | None = None,
    sort: _SortField = "updated_at",
    direction: _SortDirection = "desc",
) -> str:
    """Return CSV text for the full filtered set (no pagination). Caller
    streams it back as text/csv. Capped at 5000 rows so a runaway export
    doesn't OOM the worker; later phase turns this into a chunked stream.
    Like list_records, ``overdue_threshold_days`` defaults to AppConfig."""
    rows, _ = await list_records(
        db,
        status=status,
        assignee_id=assignee_id,
        customer_id=customer_id,
        overdue_only=overdue_only,
        overdue_threshold_days=overdue_threshold_days,
        sort=sort,
        direction=direction,
        page=1,
        per_page=5000,
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "reference_number",
            "status",
            "status_display",
            "days_in_status",
            "is_overdue",
            "customer_name",
            "business_name",
            "state",
            "make",
            "model",
            "year",
            "assigned_sales_rep",
            "assigned_appraiser",
            "submitted_at",
            "updated_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.reference_number or "",
                r.status,
                r.status_display,
                r.days_in_status,
                "yes" if r.is_overdue else "no",
                r.customer_name,
                r.business_name or "",
                r.state or "",
                r.make or "",
                r.model or "",
                r.year if r.year is not None else "",
                r.assigned_sales_rep_name or "",
                r.assigned_appraiser_name or "",
                r.submitted_at.isoformat() if r.submitted_at else "",
                r.updated_at.isoformat(),
            ]
        )
    return buf.getvalue()
