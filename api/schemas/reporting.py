# ABOUTME: Admin reporting schemas — Phase 8 Sprint 3.
# ABOUTME: Request query-param models and response shapes for all four report types.
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class DateRangeParams(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


# ---------------------------------------------------------------------------
# Sales by Period
# ---------------------------------------------------------------------------


class SalesByPeriodRow(BaseModel):
    period_label: str
    record_count: int
    approved_count: int
    direct_purchase_count: int
    consignment_count: int
    total_approved_offer: Decimal
    total_consignment_price: Decimal
    avg_days_to_publish: float | None


class SalesByPeriodResponse(BaseModel):
    period_type: Literal["month", "quarter", "year"]
    start_date: date | None
    end_date: date | None
    rows: list[SalesByPeriodRow]


# ---------------------------------------------------------------------------
# Sales by Equipment Type
# ---------------------------------------------------------------------------


class SalesByTypeRow(BaseModel):
    category_name: str
    record_count: int
    approved_count: int
    avg_overall_score: Decimal | None
    avg_approved_offer: Decimal | None
    avg_consignment_price: Decimal | None


class SalesByTypeResponse(BaseModel):
    start_date: date | None
    end_date: date | None
    rows: list[SalesByTypeRow]


# ---------------------------------------------------------------------------
# Sales by State
# ---------------------------------------------------------------------------


class SalesByStateRow(BaseModel):
    state: str | None
    record_count: int
    approved_count: int
    avg_approved_offer: Decimal | None


class SalesByStateResponse(BaseModel):
    start_date: date | None
    end_date: date | None
    rows: list[SalesByStateRow]


# ---------------------------------------------------------------------------
# Portal Traffic
# ---------------------------------------------------------------------------


class PageViewMetric(BaseModel):
    page: str
    view_count: int


class PortalTrafficResponse(BaseModel):
    start_date: date | None
    end_date: date | None
    total_sessions: int
    unique_users: int
    total_page_views: int
    top_pages: list[PageViewMetric]
    form_abandon_rate: float | None
    pdf_download_count: int
