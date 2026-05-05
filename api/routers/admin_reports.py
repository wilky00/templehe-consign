# ABOUTME: Admin reporting endpoints — Phase 8 Sprint 3.
# ABOUTME: GET /admin/reports/{sales-by-period,sales-by-type,sales-by-state,portal-traffic} + CSV export.
from __future__ import annotations

from datetime import date
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.reporting import (
    PortalTrafficResponse,
    SalesByPeriodResponse,
    SalesByStateResponse,
    SalesByTypeResponse,
)
from services import reporting_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])

_require_reporting = require_roles("admin", "reporting")


@router.get("/sales-by-period", response_model=SalesByPeriodResponse)
async def get_sales_by_period(
    period_type: Literal["month", "quarter", "year"] = Query("month"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    _current_user: User = Depends(_require_reporting),
    db: AsyncSession = Depends(get_db),
) -> SalesByPeriodResponse:
    return await reporting_service.sales_by_period(
        db, period_type=period_type, start_date=start_date, end_date=end_date
    )


@router.get("/sales-by-type", response_model=SalesByTypeResponse)
async def get_sales_by_type(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    _current_user: User = Depends(_require_reporting),
    db: AsyncSession = Depends(get_db),
) -> SalesByTypeResponse:
    return await reporting_service.sales_by_type(
        db, start_date=start_date, end_date=end_date
    )


@router.get("/sales-by-state", response_model=SalesByStateResponse)
async def get_sales_by_state(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    _current_user: User = Depends(_require_reporting),
    db: AsyncSession = Depends(get_db),
) -> SalesByStateResponse:
    return await reporting_service.sales_by_state(
        db, start_date=start_date, end_date=end_date
    )


@router.get("/portal-traffic", response_model=PortalTrafficResponse)
async def get_portal_traffic(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user_segment: Literal["all", "new", "returning"] = Query("all"),
    _current_user: User = Depends(_require_reporting),
    db: AsyncSession = Depends(get_db),
) -> PortalTrafficResponse:
    return await reporting_service.portal_traffic(
        db, start_date=start_date, end_date=end_date, user_segment=user_segment
    )


@router.get("/export")
async def export_report(
    report_type: Literal[
        "sales-by-period", "sales-by-type", "sales-by-state", "portal-traffic"
    ] = Query(...),
    period_type: Literal["month", "quarter", "year"] = Query("month"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    _current_user: User = Depends(_require_reporting),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    csv_content, filename = await reporting_service.export_csv(
        db,
        report_type=report_type,
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
    )
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
