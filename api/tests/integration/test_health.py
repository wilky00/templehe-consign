# ABOUTME: Integration tests for the /api/v1/health endpoint.
# ABOUTME: Verifies response shape, status codes, and all three dependency checks.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from httpx import AsyncClient

from config import settings
from routers.health import _check_database, _check_migrations, _check_r2


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
    """In non-production, R2 failure is informational — overall stays 200."""
    with patch("routers.health._check_r2", return_value="error"):
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["checks"]["r2"] == "error"


@pytest.mark.asyncio
async def test_health_r2_unconfigured_in_production_returns_503(client: AsyncClient):
    """In production, missing R2 credentials is a config-drift incident.
    Previously this reported 200 ok, silently masking a rotated or deleted
    R2 key. Now the probe fails so UptimeRobot / Fly notice."""
    with patch.object(settings, "environment", "production"):
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["checks"]["r2"] == "unconfigured"


@pytest.mark.asyncio
async def test_health_r2_error_in_production_returns_503(client: AsyncClient):
    """Runtime R2 outage in production also fails the probe."""
    with (
        patch.object(settings, "environment", "production"),
        patch("routers.health._check_r2", return_value="error"),
    ):
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Direct unit tests for helper functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_database_returns_error_on_exception():
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("simulated DB error")
    result = await _check_database(mock_db)
    assert result == "error"


@pytest.mark.asyncio
async def test_check_migrations_returns_error_on_exception():
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("simulated DB error")
    result = await _check_migrations(mock_db)
    assert result == "error"


@pytest.mark.asyncio
async def test_check_r2_ok_when_configured():
    with (
        patch.object(settings, "r2_access_key_id", "fake_key_id"),
        patch.object(settings, "r2_secret_access_key", "fake_secret"),
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_thread.return_value = None
        result = await _check_r2()
    assert result == "ok"


@pytest.mark.asyncio
async def test_check_r2_returns_error_on_botocore_error():
    with (
        patch.object(settings, "r2_access_key_id", "fake_key_id"),
        patch.object(settings, "r2_secret_access_key", "fake_secret"),
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_thread.side_effect = BotoCoreError()
        result = await _check_r2()
    assert result == "error"


@pytest.mark.asyncio
async def test_check_r2_returns_error_on_client_error():
    with (
        patch.object(settings, "r2_access_key_id", "fake_key_id"),
        patch.object(settings, "r2_secret_access_key", "fake_secret"),
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_thread.side_effect = ClientError(
            error_response={"Error": {"Code": "NoSuchBucket", "Message": "Not found"}},
            operation_name="HeadBucket",
        )
        result = await _check_r2()
    assert result == "error"


@pytest.mark.asyncio
async def test_check_r2_returns_error_on_generic_exception():
    with (
        patch.object(settings, "r2_access_key_id", "fake_key_id"),
        patch.object(settings, "r2_secret_access_key", "fake_secret"),
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_thread.side_effect = RuntimeError("unexpected")
        result = await _check_r2()
    assert result == "error"


def test_check_r2_imports_are_present():
    # Verify BotoCoreError / ClientError are importable — used in except clauses.
    assert BotoCoreError is not None
    assert ClientError is not None
    assert MagicMock is not None
