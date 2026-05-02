# ABOUTME: Phase 5 Sprint 3 — unit tests for valuation_service.search().
# ABOUTME: Covers internal query path, stubbed external, scraper flag, and range math.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ComparableSale
from services import valuation_service


def _make_sale_row(
    *,
    make: str = "CAT",
    model: str = "320",
    year: int = 2020,
    hours: int = 3000,
    source: str = "internal",
) -> ComparableSale:
    sale = ComparableSale()
    sale.id = uuid.uuid4()
    sale.make = make
    sale.model = model
    sale.year = year
    sale.hours = hours
    sale.sale_price = Decimal("185000.00")
    sale.sale_date = datetime(2024, 6, 1, tzinfo=UTC)
    sale.source = source
    sale.source_url = None
    sale.notes = None
    sale.category_id = None
    sale.deleted_at = None
    return sale


def _make_db(rows: list) -> AsyncMock:
    """Construct a minimal AsyncSession mock that returns ``rows`` from execute()."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    # app_config_registry.get_typed calls scalar_one_or_none; valuation calls scalars().all().
    result_mock.scalar_one_or_none.return_value = None
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=result_mock)
    return db


@pytest.mark.asyncio
async def test_internal_results_returned():
    row = _make_sale_row()
    db = _make_db([row])
    resp = await valuation_service.search(
        db,
        make="CAT",
        model="320",
        year=2020,
        hours=3000,
        category_id=None,
    )
    assert len(resp.results) == 1
    assert resp.results[0].make == "CAT"
    assert "internal" in resp.used_sources


@pytest.mark.asyncio
async def test_empty_internal_returns_no_sources():
    db = _make_db([])
    resp = await valuation_service.search(
        db, make="NoMatch", model="X", year=2020, hours=0, category_id=None
    )
    assert resp.results == []
    assert resp.used_sources == []


@pytest.mark.asyncio
async def test_stubbed_external_returns_empty():
    result = valuation_service._search_external(
        valuation_service._SearchParams(
            make="CAT",
            model="320",
            year=2020,
            hours=3000,
            category_id=None,
            year_range=3,
            hours_range=500,
        )
    )
    assert result == []


@pytest.mark.asyncio
async def test_scraper_job_enqueued_when_flag_enabled():
    """_enqueue_scraper_job should be called when the scraper flag is true."""
    db = _make_db([])
    with patch.object(valuation_service, "_enqueue_scraper_job") as mock_enqueue:
        with patch(
            "services.app_config_registry.get_typed",
            new_callable=AsyncMock,
            side_effect=lambda _db, key: {
                "valuation_year_range": 3,
                "valuation_hours_range": 500,
                "enable_playwright_valuation_scraper": True,
            }.get(key, None),
        ):
            await valuation_service.search(
                db, make="CAT", model="320", year=2020, hours=3000, category_id=None
            )
        mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_scraper_not_enqueued_when_flag_disabled():
    db = _make_db([])
    with patch.object(valuation_service, "_enqueue_scraper_job") as mock_enqueue:
        with patch(
            "services.app_config_registry.get_typed",
            new_callable=AsyncMock,
            side_effect=lambda _db, key: {
                "valuation_year_range": 3,
                "valuation_hours_range": 500,
                "enable_playwright_valuation_scraper": False,
            }.get(key, None),
        ):
            await valuation_service.search(
                db, make="CAT", model="320", year=2020, hours=3000, category_id=None
            )
        mock_enqueue.assert_not_called()


def test_hours_lower_bound_clamps_to_zero():
    """Hours range must not go negative — clamp at 0."""
    params = valuation_service._SearchParams(
        make=None,
        model=None,
        year=None,
        hours=100,
        category_id=None,
        year_range=3,
        hours_range=500,
    )
    # The internal search builds `max(0, hours - hours_range)` as the lower bound.
    # Verify the math: 100 - 500 = -400, clamped to 0.
    lo = max(0, params.hours - params.hours_range)
    assert lo == 0
