# ABOUTME: Phase 3 Sprint 4 — Google Maps Distance Matrix + Geocoding with read-through cache.
# ABOUTME: Returns None on every failure (no key, network, bad status) so callers can no-op.
"""Google Maps Platform integration.

Two surfaces:

- ``get_drive_time_seconds(origin, destination)`` — Distance Matrix API.
  Cached for 6h via ``drive_time_cache``. Returns ``None`` when no key is
  configured, when the API call fails, or when the response is malformed.
  Callers (``calendar_service``) treat ``None`` as "use the AppConfig
  fallback minutes".

- ``geocode(address)`` — Geocoding API. Cached for 30d via
  ``geocode_cache``. Returns ``(lat, lon)`` or ``None`` on the same
  failure modes. Callers (``lead_routing_service`` metro-area matcher)
  treat ``None`` as "rule does not match" — never raises so a flaky API
  can't drop a customer's intake.

Both functions are read-through: cache hit → return; miss → call API →
write back → return. Cache is a Postgres table for the POC (matches
ADR-002's no-Redis-in-POC stance) — swap path is `SETEX 21600` /
`SETEX 2592000` at GCP migration without touching the public surface.

The API key lives in ``settings.google_maps_api_key``. When empty (the
default in dev/test/staging), every call short-circuits to ``None`` so
the test suite never hits the live API and the calendar can be exercised
end-to-end without provisioning a key.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import AppConfig, DriveTimeCache, GeocodeCache

logger = structlog.get_logger(__name__)

_DRIVE_TIME_TTL = timedelta(hours=6)
_GEOCODE_TTL = timedelta(days=30)
_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_HTTP_TIMEOUT_SECONDS = 5.0
_FALLBACK_MINUTES_KEY = "drive_time_fallback_minutes"
_DEFAULT_FALLBACK_MINUTES = 60


def _hash(value: str) -> str:
    """SHA-256 of the lowercased + stripped string. Stable cache key."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Distance Matrix
# --------------------------------------------------------------------------- #


async def get_drive_time_seconds(
    db: AsyncSession,
    *,
    origin: str,
    destination: str,
) -> int | None:
    """Return drive-time in seconds, or ``None`` to signal "use the fallback".

    Order of operations:
    1. Cache lookup keyed by SHA-256 of (origin, destination).
    2. If miss and we have a key, call the Distance Matrix API.
    3. Cache the result for 6h. Return seconds.
    4. On any failure (no key, network, non-OK status, malformed body),
       log and return ``None`` — never raise.
    """
    if not origin or not destination:
        return None

    origin_hash = _hash(origin)
    dest_hash = _hash(destination)
    now = datetime.now(UTC)

    # 1. Cache hit?
    cached = (
        await db.execute(
            select(DriveTimeCache).where(
                DriveTimeCache.origin_hash == origin_hash,
                DriveTimeCache.dest_hash == dest_hash,
                DriveTimeCache.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if cached is not None:
        return cached.duration_seconds

    if not settings.google_maps_api_key:
        # No key in dev/test/staging — caller falls back to AppConfig minutes.
        return None

    # 2. API call.
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                _DISTANCE_MATRIX_URL,
                params={
                    "origins": origin,
                    "destinations": destination,
                    "mode": "driving",
                    "departure_time": "now",
                    "key": settings.google_maps_api_key,
                },
            )
        resp.raise_for_status()
        body = resp.json()
        seconds = _parse_distance_matrix(body)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(
            "google_maps_drive_time_failed",
            origin_hash=origin_hash,
            dest_hash=dest_hash,
            error=str(exc),
        )
        return None

    if seconds is None:
        return None

    # 3. Write through.
    await _upsert_drive_time(
        db,
        origin_hash=origin_hash,
        dest_hash=dest_hash,
        duration_seconds=seconds,
        expires_at=now + _DRIVE_TIME_TTL,
    )
    return seconds


def _parse_distance_matrix(body: dict) -> int | None:
    """Pull ``duration_in_traffic.value`` (or ``duration.value``) from a row.

    Google's response shape: ``rows[0].elements[0].duration_in_traffic.value``
    is seconds. ``duration_in_traffic`` only appears with ``departure_time``
    set; fall back to ``duration`` if the API responded without traffic info.
    """
    if body.get("status") != "OK":
        return None
    rows = body.get("rows") or []
    if not rows:
        return None
    elements = rows[0].get("elements") or []
    if not elements:
        return None
    el = elements[0]
    if el.get("status") != "OK":
        return None
    duration = el.get("duration_in_traffic") or el.get("duration")
    if not isinstance(duration, dict):
        return None
    value = duration.get("value")
    if not isinstance(value, int):
        return None
    return value


async def _upsert_drive_time(
    db: AsyncSession,
    *,
    origin_hash: str,
    dest_hash: str,
    duration_seconds: int,
    expires_at: datetime,
) -> None:
    stmt = (
        pg_insert(DriveTimeCache)
        .values(
            origin_hash=origin_hash,
            dest_hash=dest_hash,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=["origin_hash", "dest_hash"],
            set_={
                "duration_seconds": duration_seconds,
                "fetched_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        )
    )
    await db.execute(stmt)


# --------------------------------------------------------------------------- #
# Geocoding
# --------------------------------------------------------------------------- #


async def geocode(db: AsyncSession, *, address: str) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` or ``None`` to signal "no usable coordinates"."""
    if not address:
        return None

    address_hash = _hash(address)
    now = datetime.now(UTC)

    cached = (
        await db.execute(
            select(GeocodeCache).where(
                GeocodeCache.address_hash == address_hash,
                GeocodeCache.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if cached is not None:
        return cached.lat, cached.lon

    if not settings.google_maps_api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                _GEOCODE_URL,
                params={"address": address, "key": settings.google_maps_api_key},
            )
        resp.raise_for_status()
        body = resp.json()
        coords = _parse_geocode(body)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(
            "google_maps_geocode_failed",
            address_hash=address_hash,
            error=str(exc),
        )
        return None

    if coords is None:
        return None

    await _upsert_geocode(
        db,
        address_hash=address_hash,
        lat=coords[0],
        lon=coords[1],
        expires_at=now + _GEOCODE_TTL,
    )
    return coords


def _parse_geocode(body: dict) -> tuple[float, float] | None:
    if body.get("status") != "OK":
        return None
    results = body.get("results") or []
    if not results:
        return None
    location = (results[0].get("geometry") or {}).get("location") or {}
    lat = location.get("lat")
    lon = location.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return float(lat), float(lon)


async def _upsert_geocode(
    db: AsyncSession,
    *,
    address_hash: str,
    lat: float,
    lon: float,
    expires_at: datetime,
) -> None:
    stmt = (
        pg_insert(GeocodeCache)
        .values(address_hash=address_hash, lat=lat, lon=lon, expires_at=expires_at)
        .on_conflict_do_update(
            index_elements=["address_hash"],
            set_={
                "lat": lat,
                "lon": lon,
                "fetched_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        )
    )
    await db.execute(stmt)


# --------------------------------------------------------------------------- #
# Fallback helper
# --------------------------------------------------------------------------- #


async def read_drive_time_fallback_minutes(db: AsyncSession) -> int:
    """Return the manager-configured fallback minutes.

    Read from ``app_config`` key ``drive_time_fallback_minutes``; default
    60 if missing or malformed.
    """
    raw = (
        await db.execute(select(AppConfig.value).where(AppConfig.key == _FALLBACK_MINUTES_KEY))
    ).scalar_one_or_none()
    if isinstance(raw, dict):
        minutes = raw.get("minutes")
        if isinstance(minutes, int) and minutes > 0:
            return minutes
    return _DEFAULT_FALLBACK_MINUTES
