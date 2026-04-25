# ABOUTME: Phase 3 Sprint 4 — read-through cache + fallback paths for drive_time + geocode services.
# ABOUTME: httpx is mocked end-to-end; no live Google API calls in CI or local test runs.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DriveTimeCache, GeocodeCache
from services import google_maps_service


def _ok_distance_response(seconds: int) -> dict:
    return {
        "status": "OK",
        "rows": [
            {
                "elements": [
                    {
                        "status": "OK",
                        "duration_in_traffic": {"value": seconds, "text": "x"},
                    }
                ]
            }
        ],
    }


def _ok_geocode_response(lat: float, lon: float) -> dict:
    return {
        "status": "OK",
        "results": [{"geometry": {"location": {"lat": lat, "lng": lon}}}],
    }


# --- drive time ------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_drive_time_returns_none_when_no_api_key(db_session: AsyncSession):
    with patch.object(google_maps_service.settings, "google_maps_api_key", ""):
        result = await google_maps_service.get_drive_time_seconds(
            db_session, origin="A", destination="B"
        )
    assert result is None


@pytest.mark.asyncio
async def test_drive_time_returns_none_when_origin_or_dest_blank(db_session: AsyncSession):
    assert await google_maps_service.get_drive_time_seconds(
        db_session, origin="", destination="X"
    ) is None
    assert await google_maps_service.get_drive_time_seconds(
        db_session, origin="X", destination=""
    ) is None


@pytest.mark.asyncio
async def test_drive_time_caches_first_call(db_session: AsyncSession):
    captured = {"calls": 0}

    async def fake_get(self, url, params=None):  # noqa: ARG001 — match httpx signature
        captured["calls"] += 1
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=_ok_distance_response(1234), request=req)

    with (
        patch.object(google_maps_service.settings, "google_maps_api_key", "TEST_KEY"),
        patch.object(httpx.AsyncClient, "get", fake_get),
    ):
        first = await google_maps_service.get_drive_time_seconds(
            db_session, origin="123 A St, Atlanta, GA", destination="456 B Ave, Decatur, GA"
        )
        second = await google_maps_service.get_drive_time_seconds(
            db_session, origin="123 A St, Atlanta, GA", destination="456 B Ave, Decatur, GA"
        )

    assert first == 1234
    assert second == 1234
    assert captured["calls"] == 1, "second call must hit the cache"

    rows = (
        await db_session.execute(select(DriveTimeCache))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].duration_seconds == 1234
    assert rows[0].expires_at > datetime.now(UTC) + timedelta(hours=5)


@pytest.mark.asyncio
async def test_drive_time_returns_none_on_http_error(db_session: AsyncSession):
    async def fake_get(self, url, params=None):  # noqa: ARG001
        raise httpx.ConnectTimeout("simulated")

    with (
        patch.object(google_maps_service.settings, "google_maps_api_key", "TEST_KEY"),
        patch.object(httpx.AsyncClient, "get", fake_get),
    ):
        result = await google_maps_service.get_drive_time_seconds(
            db_session, origin="x", destination="y"
        )
    assert result is None
    # Failure should NOT poison the cache.
    rows = (await db_session.execute(select(DriveTimeCache))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_drive_time_returns_none_on_non_ok_response(db_session: AsyncSession):
    async def fake_get(self, url, params=None):  # noqa: ARG001
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"status": "ZERO_RESULTS", "rows": []}, request=req)

    with (
        patch.object(google_maps_service.settings, "google_maps_api_key", "TEST_KEY"),
        patch.object(httpx.AsyncClient, "get", fake_get),
    ):
        result = await google_maps_service.get_drive_time_seconds(
            db_session, origin="x", destination="y"
        )
    assert result is None


@pytest.mark.asyncio
async def test_drive_time_falls_back_to_duration_when_no_traffic(db_session: AsyncSession):
    """``departure_time=now`` should give us ``duration_in_traffic`` but if the API
    responds with only ``duration`` we still return that value."""
    body = {
        "status": "OK",
        "rows": [{"elements": [{"status": "OK", "duration": {"value": 600}}]}],
    }

    async def fake_get(self, url, params=None):  # noqa: ARG001
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=body, request=req)

    with (
        patch.object(google_maps_service.settings, "google_maps_api_key", "TEST_KEY"),
        patch.object(httpx.AsyncClient, "get", fake_get),
    ):
        result = await google_maps_service.get_drive_time_seconds(
            db_session, origin="x", destination="y"
        )
    assert result == 600


# --- geocode --------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_geocode_returns_none_when_no_api_key(db_session: AsyncSession):
    with patch.object(google_maps_service.settings, "google_maps_api_key", ""):
        result = await google_maps_service.geocode(db_session, address="1 Main St")
    assert result is None


@pytest.mark.asyncio
async def test_geocode_caches_first_call(db_session: AsyncSession):
    captured = {"calls": 0}

    async def fake_get(self, url, params=None):  # noqa: ARG001
        captured["calls"] += 1
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=_ok_geocode_response(33.7, -84.4), request=req)

    with (
        patch.object(google_maps_service.settings, "google_maps_api_key", "TEST_KEY"),
        patch.object(httpx.AsyncClient, "get", fake_get),
    ):
        first = await google_maps_service.geocode(db_session, address="Atlanta, GA")
        second = await google_maps_service.geocode(db_session, address="atlanta, ga")

    assert first == (33.7, -84.4)
    assert second == (33.7, -84.4)
    assert captured["calls"] == 1, "case-insensitive cache hit on second call"

    rows = (await db_session.execute(select(GeocodeCache))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_geocode_returns_none_on_zero_results(db_session: AsyncSession):
    async def fake_get(self, url, params=None):  # noqa: ARG001
        req = httpx.Request("GET", url)
        return httpx.Response(
            200, json={"status": "ZERO_RESULTS", "results": []}, request=req
        )

    with (
        patch.object(google_maps_service.settings, "google_maps_api_key", "TEST_KEY"),
        patch.object(httpx.AsyncClient, "get", fake_get),
    ):
        result = await google_maps_service.geocode(db_session, address="nowhere")
    assert result is None


# --- fallback minutes ------------------------------------------------------ #


@pytest.mark.asyncio
async def test_drive_time_fallback_minutes_uses_seeded_default(db_session: AsyncSession):
    """Migration 011 seeded ``drive_time_fallback_minutes = 60``."""
    minutes = await google_maps_service.read_drive_time_fallback_minutes(db_session)
    assert minutes == 60
