# ABOUTME: Integration tests for RBAC — verifies require_roles() enforces the permission matrix.
# ABOUTME: Registers a temporary test route on the app fixture to isolate RBAC behavior.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Role, User
from main import app
from middleware.rbac import require_roles

_VALID_PASSWORD = "TestPassword1!"

# ---------------------------------------------------------------------------
# Test route registration (added once per module)
# ---------------------------------------------------------------------------

_ADMIN_ROUTE = "/api/v1/test/admin-only"
_SALES_OR_MANAGER_ROUTE = "/api/v1/test/sales-or-manager"


@pytest.fixture(scope="module", autouse=True)
def register_test_routes():
    """Add temporary routes to the live app for RBAC testing."""
    from fastapi import APIRouter

    from database.models import User as UserModel

    router = APIRouter()

    @router.get("/test/admin-only")
    async def admin_only(user: UserModel = Depends(require_roles("admin"))):
        return {"role": "admin", "user_id": str(user.id)}

    @router.get("/test/sales-or-manager")
    async def sales_or_manager(
        user: UserModel = Depends(require_roles("sales", "sales_manager")),
    ):
        return {"user_id": str(user.id)}

    app.include_router(router, prefix="/api/v1")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_active_user(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> dict:
    """Register, activate, and set role using the test session. Returns login JSON."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Test",
                "last_name": "User",
            },
        )
    assert reg.status_code == 201, reg.json()

    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    assert user is not None
    role_result = await db.execute(select(Role).where(Role.slug == role_slug))
    role = role_result.scalar_one_or_none()
    assert role is not None, f"Role '{role_slug}' not found in test DB"
    user.status = "active"
    user.role_id = role.id
    await db.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert login.status_code == 200, login.json()
    return login.json()


# ---------------------------------------------------------------------------
# Tests: unauthenticated / wrong role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_no_token_returns_401(client: AsyncClient):
    resp = await client.get(_ADMIN_ROUTE)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rbac_wrong_role_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    login_data = await _create_active_user(
        client, db_session, "customer_rbac@example.com", "customer"
    )
    token = login_data["access_token"]
    resp = await client.get(
        _ADMIN_ROUTE, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    assert "permission" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rbac_403_message_is_human_readable(
    client: AsyncClient, db_session: AsyncSession
):
    login_data = await _create_active_user(
        client, db_session, "sales_rbac_403@example.com", "sales"
    )
    token = login_data["access_token"]
    resp = await client.get(
        _ADMIN_ROUTE, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert len(detail) > 10
    assert detail[0].isupper()


# ---------------------------------------------------------------------------
# Tests: correct role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_correct_role_succeeds(
    client: AsyncClient, db_session: AsyncSession
):
    login_data = await _create_active_user(
        client, db_session, "admin_rbac@example.com", "admin"
    )
    token = login_data["access_token"]
    resp = await client.get(
        _ADMIN_ROUTE, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_rbac_multi_role_first_allowed(
    client: AsyncClient, db_session: AsyncSession
):
    login_data = await _create_active_user(
        client, db_session, "sales_multi@example.com", "sales"
    )
    token = login_data["access_token"]
    resp = await client.get(
        _SALES_OR_MANAGER_ROUTE, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rbac_multi_role_second_allowed(
    client: AsyncClient, db_session: AsyncSession
):
    login_data = await _create_active_user(
        client, db_session, "manager_multi@example.com", "sales_manager"
    )
    token = login_data["access_token"]
    resp = await client.get(
        _SALES_OR_MANAGER_ROUTE, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rbac_multi_role_excluded_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    login_data = await _create_active_user(
        client, db_session, "appraiser_multi@example.com", "appraiser"
    )
    token = login_data["access_token"]
    resp = await client.get(
        _SALES_OR_MANAGER_ROUTE, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: security headers present on responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    headers = resp.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert "strict-origin-when-cross-origin" in headers.get("referrer-policy", "")
    assert "geolocation=()" in headers.get("permissions-policy", "")
    csp = headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.asyncio
async def test_request_id_header_returned(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) == 36  # UUID format


@pytest.mark.asyncio
async def test_request_id_passthrough(client: AsyncClient):
    """Client-supplied X-Request-ID should be echoed back unchanged."""
    custom_id = "my-trace-id-12345"
    resp = await client.get(
        "/api/v1/health", headers={"X-Request-ID": custom_id}
    )
    assert resp.headers.get("x-request-id") == custom_id
