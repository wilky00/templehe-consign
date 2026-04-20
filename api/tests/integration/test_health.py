# ABOUTME: Integration tests for the /api/v1/health endpoint.
# ABOUTME: Verifies response shape, status codes, and all three dependency checks.
from __future__ import annotations

import pytest
from httpx import AsyncClient
from unittest.mock import patch


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_status_ok(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_response_shape(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    body = resp.json()
    assert "status" in body
    assert "version" in body
    assert "checks" in body
    checks = body["checks"]
    assert "database" in checks
    assert "migrations" in checks
    assert "r2" in checks


@pytest.mark.asyncio
async def test_health_database_ok(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.json()["checks"]["database"] == "ok"


@pytest.mark.asyncio
async def test_health_migrations_ok(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.json()["checks"]["migrations"] == "ok"


@pytest.mark.asyncio
async def test_health_r2_unconfigured_in_test_env(client: AsyncClient):
    """R2 credentials are not set in test env — check should report unconfigured, not error."""
    resp = await client.get("/api/v1/health")
    assert resp.json()["checks"]["r2"] == "unconfigured"


@pytest.mark.asyncio
async def test_health_degraded_returns_503(client: AsyncClient):
    """Simulate a DB failure — health should return 503 with status degraded."""
    from sqlalchemy.exc import OperationalError

    with patch("routers.health._check_database", return_value="error"):
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_degraded_bad_migration(client: AsyncClient):
    """Simulate a stale migration — health should return 503."""
    with patch("routers.health._check_migrations", return_value="error"):
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_r2_error_does_not_degrade(client: AsyncClient):
    """R2 failure alone should not degrade overall status — it's non-required."""
    with patch("routers.health._check_r2", return_value="error"):
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["checks"]["r2"] == "error"
