# ABOUTME: Admin reporting service — Phase 8 Sprint 3.
# ABOUTME: Aggregation queries for sales-by-period, by-type, by-state, and portal traffic.
from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AnalyticsEvent,
    AppraisalSubmission,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    PublicListing,
)
from schemas.reporting import (
    PageViewMetric,
    PortalTrafficResponse,
    SalesByPeriodResponse,
    SalesByPeriodRow,
    SalesByStateResponse,
    SalesByStateRow,
    SalesByTypeResponse,
    SalesByTypeRow,
)


def _date_bounds(
    start_date: date | None, end_date: date | None
) -> tuple[datetime | None, datetime | None]:
    """Convert optional date bounds to UTC-aware datetimes for timestamp comparisons."""
    start_dt = (
        datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
        if start_date
        else None
    )
    end_dt = (
        datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=UTC)
        if end_date
        else None
    )
    return start_dt, end_dt


def _period_label(dt: datetime, period_type: Literal["month", "quarter", "year"]) -> str:
    if period_type == "month":
        return dt.strftime("%Y-%m")
    if period_type == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year} Q{q}"
    return str(dt.year)


def _period_trunc(period_type: Literal["month", "quarter", "year"]):
    """SQLAlchemy date_trunc expression for approved_at bucketing."""
    return func.date_trunc(period_type, AppraisalSubmission.approved_at)


# ---------------------------------------------------------------------------
# Sales by Period
# ---------------------------------------------------------------------------


async def sales_by_period(
    db: AsyncSession,
    *,
    period_type: Literal["month", "quarter", "year"] = "month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> SalesByPeriodResponse:
    start_dt, end_dt = _date_bounds(start_date, end_date)

    trunc_expr = _period_trunc(period_type)

    filters = [
        AppraisalSubmission.status == "approved",
        AppraisalSubmission.deleted_at.is_(None),
    ]
    if start_dt:
        filters.append(AppraisalSubmission.approved_at >= start_dt)
    if end_dt:
        filters.append(AppraisalSubmission.approved_at <= end_dt)

    # Avg days from equipment_record creation → public listing publish
    days_expr = func.avg(
        func.extract(
            "epoch",
            PublicListing.published_at - EquipmentRecord.created_at,
        )
        / 86400.0
    )

    stmt = (
        select(
            trunc_expr.label("period"),
            func.count(AppraisalSubmission.id).label("approved_count"),
            func.count(case((AppraisalSubmission.approved_purchase_offer.is_not(None), 1))).label(
                "direct_purchase_count"
            ),
            func.count(
                case((AppraisalSubmission.suggested_consignment_price.is_not(None), 1))
            ).label("consignment_count"),
            func.coalesce(func.sum(AppraisalSubmission.approved_purchase_offer), 0).label(
                "total_approved_offer"
            ),
            func.coalesce(func.sum(AppraisalSubmission.suggested_consignment_price), 0).label(
                "total_consignment_price"
            ),
            days_expr.label("avg_days_to_publish"),
        )
        .join(EquipmentRecord, AppraisalSubmission.equipment_record_id == EquipmentRecord.id)
        .outerjoin(PublicListing, PublicListing.equipment_record_id == EquipmentRecord.id)
        .where(and_(*filters))
        .group_by(trunc_expr)
        .order_by(trunc_expr)
    )

    rows_raw = (await db.execute(stmt)).all()

    rows: list[SalesByPeriodRow] = []
    for r in rows_raw:
        period_dt: datetime = r.period
        label = _period_label(period_dt, period_type)
        avg_days = float(r.avg_days_to_publish) if r.avg_days_to_publish is not None else None
        rows.append(
            SalesByPeriodRow(
                period_label=label,
                record_count=r.approved_count,
                approved_count=r.approved_count,
                direct_purchase_count=r.direct_purchase_count,
                consignment_count=r.consignment_count,
                total_approved_offer=Decimal(str(r.total_approved_offer)),
                total_consignment_price=Decimal(str(r.total_consignment_price)),
                avg_days_to_publish=avg_days,
            )
        )

    return SalesByPeriodResponse(
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        rows=rows,
    )


# ---------------------------------------------------------------------------
# Sales by Equipment Type
# ---------------------------------------------------------------------------


async def sales_by_type(
    db: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> SalesByTypeResponse:
    start_dt, end_dt = _date_bounds(start_date, end_date)

    filters = [EquipmentRecord.deleted_at.is_(None)]
    approved_filters = [
        AppraisalSubmission.status == "approved",
        AppraisalSubmission.deleted_at.is_(None),
    ]
    if start_dt:
        approved_filters.append(AppraisalSubmission.approved_at >= start_dt)
    if end_dt:
        approved_filters.append(AppraisalSubmission.approved_at <= end_dt)
    if start_dt:
        filters.append(EquipmentRecord.created_at >= start_dt)
    if end_dt:
        filters.append(EquipmentRecord.created_at <= end_dt)

    stmt = (
        select(
            EquipmentCategory.name.label("category_name"),
            func.count(func.distinct(EquipmentRecord.id)).label("record_count"),
            func.count(
                case((AppraisalSubmission.status == "approved", AppraisalSubmission.id))
            ).label("approved_count"),
            func.avg(
                case((AppraisalSubmission.status == "approved", AppraisalSubmission.overall_score))
            ).label("avg_overall_score"),
            func.avg(
                case(
                    (
                        AppraisalSubmission.status == "approved",
                        AppraisalSubmission.approved_purchase_offer,
                    )
                )
            ).label("avg_approved_offer"),
            func.avg(
                case(
                    (
                        AppraisalSubmission.status == "approved",
                        AppraisalSubmission.suggested_consignment_price,
                    )
                )
            ).label("avg_consignment_price"),
        )
        .join(EquipmentCategory, EquipmentRecord.category_id == EquipmentCategory.id)
        .outerjoin(
            AppraisalSubmission,
            and_(
                AppraisalSubmission.equipment_record_id == EquipmentRecord.id,
                AppraisalSubmission.deleted_at.is_(None),
            ),
        )
        .where(and_(*filters))
        .group_by(EquipmentCategory.id, EquipmentCategory.name)
        .order_by(func.count(func.distinct(EquipmentRecord.id)).desc())
    )

    rows_raw = (await db.execute(stmt)).all()

    rows = [
        SalesByTypeRow(
            category_name=r.category_name,
            record_count=r.record_count,
            approved_count=r.approved_count,
            avg_overall_score=(
                Decimal(str(r.avg_overall_score)) if r.avg_overall_score is not None else None
            ),
            avg_approved_offer=(
                Decimal(str(r.avg_approved_offer)) if r.avg_approved_offer is not None else None
            ),
            avg_consignment_price=(
                Decimal(str(r.avg_consignment_price))
                if r.avg_consignment_price is not None
                else None
            ),
        )
        for r in rows_raw
    ]

    return SalesByTypeResponse(start_date=start_date, end_date=end_date, rows=rows)


# ---------------------------------------------------------------------------
# Sales by State
# ---------------------------------------------------------------------------


async def sales_by_state(
    db: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> SalesByStateResponse:
    start_dt, end_dt = _date_bounds(start_date, end_date)

    filters = [EquipmentRecord.deleted_at.is_(None)]
    if start_dt:
        filters.append(EquipmentRecord.created_at >= start_dt)
    if end_dt:
        filters.append(EquipmentRecord.created_at <= end_dt)

    stmt = (
        select(
            Customer.address_state.label("state"),
            func.count(func.distinct(EquipmentRecord.id)).label("record_count"),
            func.count(
                case((AppraisalSubmission.status == "approved", AppraisalSubmission.id))
            ).label("approved_count"),
            func.avg(
                case(
                    (
                        AppraisalSubmission.status == "approved",
                        AppraisalSubmission.approved_purchase_offer,
                    )
                )
            ).label("avg_approved_offer"),
        )
        .join(Customer, EquipmentRecord.customer_id == Customer.id)
        .outerjoin(
            AppraisalSubmission,
            and_(
                AppraisalSubmission.equipment_record_id == EquipmentRecord.id,
                AppraisalSubmission.deleted_at.is_(None),
            ),
        )
        .where(and_(*filters))
        .group_by(Customer.address_state)
        .order_by(func.count(func.distinct(EquipmentRecord.id)).desc())
    )

    rows_raw = (await db.execute(stmt)).all()

    rows = [
        SalesByStateRow(
            state=r.state,
            record_count=r.record_count,
            approved_count=r.approved_count,
            avg_approved_offer=(
                Decimal(str(r.avg_approved_offer)) if r.avg_approved_offer is not None else None
            ),
        )
        for r in rows_raw
    ]

    return SalesByStateResponse(start_date=start_date, end_date=end_date, rows=rows)


# ---------------------------------------------------------------------------
# Portal Traffic
# ---------------------------------------------------------------------------


async def portal_traffic(
    db: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    user_segment: Literal["all", "new", "returning"] = "all",
) -> PortalTrafficResponse:
    start_dt, end_dt = _date_bounds(start_date, end_date)

    filters: list = []
    if start_dt:
        filters.append(AnalyticsEvent.created_at >= start_dt)
    if end_dt:
        filters.append(AnalyticsEvent.created_at <= end_dt)

    base_where = and_(*filters) if filters else True

    # Total distinct sessions
    sessions_stmt = select(func.count(func.distinct(AnalyticsEvent.session_id))).where(base_where)
    total_sessions: int = (await db.execute(sessions_stmt)).scalar_one() or 0

    # Unique authenticated users
    users_stmt = select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
        and_(base_where, AnalyticsEvent.user_id.is_not(None))
    )
    unique_users: int = (await db.execute(users_stmt)).scalar_one() or 0

    # Total page views
    pv_stmt = select(func.count(AnalyticsEvent.id)).where(
        and_(base_where, AnalyticsEvent.event_type == "page_view")
    )
    total_page_views: int = (await db.execute(pv_stmt)).scalar_one() or 0

    # Top pages by view count (limit 10)
    top_pages_stmt = (
        select(
            AnalyticsEvent.page.label("page"),
            func.count(AnalyticsEvent.id).label("view_count"),
        )
        .where(
            and_(
                base_where,
                AnalyticsEvent.event_type == "page_view",
                AnalyticsEvent.page.is_not(None),
            )
        )
        .group_by(AnalyticsEvent.page)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .limit(10)
    )
    top_pages_raw = (await db.execute(top_pages_stmt)).all()
    top_pages = [PageViewMetric(page=r.page, view_count=r.view_count) for r in top_pages_raw]

    # Form abandonment rate: form_abandon / form_step_start * 100
    abandon_stmt = select(func.count(AnalyticsEvent.id)).where(
        and_(base_where, AnalyticsEvent.event_type == "form_abandon")
    )
    start_stmt = select(func.count(AnalyticsEvent.id)).where(
        and_(base_where, AnalyticsEvent.event_type == "form_step_start")
    )
    abandon_count: int = (await db.execute(abandon_stmt)).scalar_one() or 0
    start_count: int = (await db.execute(start_stmt)).scalar_one() or 0
    form_abandon_rate: float | None = (
        round(abandon_count / start_count * 100, 1) if start_count > 0 else None
    )

    # PDF download count
    pdf_stmt = select(func.count(AnalyticsEvent.id)).where(
        and_(base_where, AnalyticsEvent.event_type == "pdf_download_click")
    )
    pdf_download_count: int = (await db.execute(pdf_stmt)).scalar_one() or 0

    return PortalTrafficResponse(
        start_date=start_date,
        end_date=end_date,
        total_sessions=total_sessions,
        unique_users=unique_users,
        total_page_views=total_page_views,
        top_pages=top_pages,
        form_abandon_rate=form_abandon_rate,
        pdf_download_count=pdf_download_count,
    )


# ---------------------------------------------------------------------------
# CSV export helpers
# ---------------------------------------------------------------------------

_REPORT_HEADERS: dict[str, list[str]] = {
    "sales-by-period": [
        "period_label",
        "record_count",
        "approved_count",
        "direct_purchase_count",
        "consignment_count",
        "total_approved_offer",
        "total_consignment_price",
        "avg_days_to_publish",
    ],
    "sales-by-type": [
        "category_name",
        "record_count",
        "approved_count",
        "avg_overall_score",
        "avg_approved_offer",
        "avg_consignment_price",
    ],
    "sales-by-state": ["state", "record_count", "approved_count", "avg_approved_offer"],
    "portal-traffic": ["page", "view_count"],
}


def _rows_to_csv(headers: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


async def export_csv(
    db: AsyncSession,
    *,
    report_type: Literal["sales-by-period", "sales-by-type", "sales-by-state", "portal-traffic"],
    period_type: Literal["month", "quarter", "year"] = "month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[str, str]:
    """Return (csv_content, suggested_filename)."""
    headers = _REPORT_HEADERS[report_type]

    if report_type == "sales-by-period":
        result = await sales_by_period(
            db, period_type=period_type, start_date=start_date, end_date=end_date
        )
        rows = [r.model_dump() for r in result.rows]
    elif report_type == "sales-by-type":
        result = await sales_by_type(db, start_date=start_date, end_date=end_date)
        rows = [r.model_dump() for r in result.rows]
    elif report_type == "sales-by-state":
        result = await sales_by_state(db, start_date=start_date, end_date=end_date)
        rows = [r.model_dump() for r in result.rows]
    else:
        result = await portal_traffic(db, start_date=start_date, end_date=end_date)
        rows = [p.model_dump() for p in result.top_pages]

    csv_content = _rows_to_csv(headers, rows)
    date_suffix = f"{start_date or 'all'}_{end_date or 'now'}"
    filename = f"{report_type}_{date_suffix}.csv"
    return csv_content, filename
