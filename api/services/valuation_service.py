# ABOUTME: Phase 5 Sprint 3 — valuation search across internal comparable sales + stubbed sources.
# ABOUTME: Reads AppConfig for year/hours range; permanent home for the external provider interface.
"""Valuation service — Phase 5 Sprint 3.

``search()`` is the single entry point for the iOS valuation lookup.
Three source tiers run in order:

1. **Internal** — queries ``comparable_sales`` rows seeded by staff.
2. **External** (stubbed) — returns ``[]``; the interface is fixed so a
   real provider (IronPlanet, EquipmentWatch) swaps in as a Phase 5.5
   mini-sprint after Jim signs a contract.
3. **Playwright scraper** (feature-flagged) — gated on the
   ``enable_playwright_valuation_scraper`` AppConfig key; if true,
   enqueues a background job. No actual scraper code ships in Phase 5.

``used_sources`` in the response tells the iOS client which tiers
contributed results so the UI can surface provenance badges correctly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ComparableSale
from schemas.valuation import ComparableSaleOut, ValuationSearchResponse
from services import app_config_registry


@dataclass
class _SearchParams:
    make: str | None
    model: str | None
    year: int | None
    hours: int | None
    category_id: uuid.UUID | None
    year_range: int
    hours_range: int


async def search(
    db: AsyncSession,
    *,
    make: str | None,
    model: str | None,
    year: int | None,
    hours: int | None,
    category_id: uuid.UUID | None,
) -> ValuationSearchResponse:
    """Search comparable sales from all configured sources.

    Returns up to 50 results ordered by sale_date DESC (most recent first).
    Year and hours filters use configurable range windows from AppConfig.
    """
    year_range = await app_config_registry.get_typed(db, "valuation_year_range")
    hours_range = await app_config_registry.get_typed(db, "valuation_hours_range")

    params = _SearchParams(
        make=make,
        model=model,
        year=year,
        hours=hours,
        category_id=category_id,
        year_range=year_range,
        hours_range=hours_range,
    )

    results: list[ComparableSaleOut] = []
    used_sources: list[str] = []

    internal = await _search_internal(db, params)
    if internal:
        results.extend(internal)
        used_sources.append("internal")

    external = _search_external(params)
    if external:
        results.extend(external)
        used_sources.append("external")

    scraper_enabled = await app_config_registry.get_typed(db, "enable_playwright_valuation_scraper")
    if scraper_enabled:
        _enqueue_scraper_job(params)

    return ValuationSearchResponse(results=results, used_sources=used_sources)


async def _search_internal(
    db: AsyncSession,
    params: _SearchParams,
) -> list[ComparableSaleOut]:
    filters = [ComparableSale.deleted_at.is_(None)]

    if params.make:
        filters.append(ComparableSale.make.ilike(f"%{params.make}%"))
    if params.model:
        filters.append(ComparableSale.model.ilike(f"%{params.model}%"))
    if params.year is not None:
        filters.append(
            and_(
                ComparableSale.year >= params.year - params.year_range,
                ComparableSale.year <= params.year + params.year_range,
            )
        )
    if params.hours is not None:
        lo = max(0, params.hours - params.hours_range)
        filters.append(
            and_(
                ComparableSale.hours >= lo,
                ComparableSale.hours <= params.hours + params.hours_range,
            )
        )
    if params.category_id is not None:
        filters.append(ComparableSale.category_id == params.category_id)

    rows = (
        (
            await db.execute(
                select(ComparableSale)
                .where(*filters)
                .order_by(ComparableSale.sale_date.desc().nulls_last())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    return [ComparableSaleOut.model_validate(r) for r in rows]


def _search_external(params: _SearchParams) -> list[ComparableSaleOut]:
    # Stubbed — real provider (IronPlanet / EquipmentWatch) swaps in here.
    return []


def _enqueue_scraper_job(params: _SearchParams) -> None:
    # Stub — queues a background scrape job when the feature flag is on.
    # Actual Playwright scraper deferred to Phase 5.5.
    pass
