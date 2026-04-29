# ABOUTME: Phase 5 Sprint 1 — POST/DELETE/GET /api/v1/me/device-token integration tests.
# ABOUTME: Real DB; covers register/upsert/revoke/list/RBAC/cross-user revocation.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DeviceToken, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    role_slug: str,
) -> dict:
    """Register, activate, swap to the requested role, log in. Returns
    the login response body (access_token + token_type)."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Dev",
                "last_name": "Token",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )

    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    db.add(user)
    await db.flush()

    # Mirror role into user_roles so require_roles() finds it.
    from services import user_roles_service

    await user_roles_service.grant(db, user=user, role_slug=role_slug, granted_by=None)

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert login_resp.status_code == 200, login_resp.text
    return login_resp.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email(slug: str) -> str:
    import uuid

    return f"{slug}-{uuid.uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------------------
# Register / upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_creates_row(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("appraiser"), "appraiser")

    long_token = "abc123" * 16  # 96 chars
    resp = await client.post(
        "/api/v1/me/device-token",
        json={
            "platform": "ios",
            "token": long_token,
            "environment": "development",
        },
        headers=_auth(body["access_token"]),
    )
    assert resp.status_code == 201
    out = resp.json()
    assert out["platform"] == "ios"
    assert out["environment"] == "development"
    # token_preview is the last 8 chars of the raw token.
    assert out["token_preview"] == long_token[-8:]
    # The full token is intentionally not echoed back.
    assert "token" not in out


@pytest.mark.asyncio
async def test_register_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("appraiser"), "appraiser")

    resp1 = await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "abc123", "environment": "development"},
        headers=_auth(body["access_token"]),
    )
    resp2 = await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "abc123", "environment": "production"},
        headers=_auth(body["access_token"]),
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    # Same row id — upsert by (user_id, token) — environment flipped.
    assert resp1.json()["id"] == resp2.json()["id"]
    assert resp2.json()["environment"] == "production"


@pytest.mark.asyncio
async def test_register_revives_soft_deleted_row(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("appraiser"), "appraiser")
    headers = _auth(body["access_token"])

    await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "abc", "environment": "development"},
        headers=headers,
    )
    await client.request(
        "DELETE",
        "/api/v1/me/device-token",
        json={"token": "abc"},
        headers=headers,
    )
    # Re-register — should clear deleted_at and bring the row back active.
    resp = await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "abc", "environment": "development"},
        headers=headers,
    )
    assert resp.status_code == 201

    list_resp = await client.get("/api/v1/me/device-token", headers=headers)
    assert list_resp.status_code == 200
    tokens = list_resp.json()["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["token_preview"] == "abc"


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_soft_deletes(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("appraiser"), "appraiser")
    headers = _auth(body["access_token"])

    await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "del-me", "environment": "development"},
        headers=headers,
    )
    resp = await client.request(
        "DELETE",
        "/api/v1/me/device-token",
        json={"token": "del-me"},
        headers=headers,
    )
    assert resp.status_code == 204

    # GET no longer returns the revoked row.
    list_resp = await client.get("/api/v1/me/device-token", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["tokens"] == []


@pytest.mark.asyncio
async def test_revoke_unknown_token_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("appraiser"), "appraiser")
    resp = await client.request(
        "DELETE",
        "/api/v1/me/device-token",
        json={"token": "never-registered"},
        headers=_auth(body["access_token"]),
    )
    # No row to flip, but the contract is idempotent — 204 either way.
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_cross_user_revocation_blocked(client: AsyncClient, db_session: AsyncSession):
    """User B attempting to revoke User A's token must NOT affect A's row.
    The service-layer predicate pins to (user_id, token); B's revoke is
    a no-op against a token belonging to A."""
    user_a = await _user_with_role(client, db_session, _email("apr-a"), "appraiser")
    user_b = await _user_with_role(client, db_session, _email("apr-b"), "appraiser")

    await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "alice-token", "environment": "development"},
        headers=_auth(user_a["access_token"]),
    )

    # B tries to revoke A's token.
    resp = await client.request(
        "DELETE",
        "/api/v1/me/device-token",
        json={"token": "alice-token"},
        headers=_auth(user_b["access_token"]),
    )
    assert resp.status_code == 204

    # A's token must still be active.
    list_resp = await client.get(
        "/api/v1/me/device-token",
        headers=_auth(user_a["access_token"]),
    )
    tokens = list_resp.json()["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["token_preview"] == "alice-token"[-8:]


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_caller_tokens(client: AsyncClient, db_session: AsyncSession):
    user_a = await _user_with_role(client, db_session, _email("apr-a"), "appraiser")
    user_b = await _user_with_role(client, db_session, _email("apr-b"), "appraiser")

    await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "tok-a", "environment": "development"},
        headers=_auth(user_a["access_token"]),
    )
    await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "tok-b", "environment": "development"},
        headers=_auth(user_b["access_token"]),
    )

    resp = await client.get("/api/v1/me/device-token", headers=_auth(user_a["access_token"]))
    tokens = resp.json()["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["token_preview"] == "tok-a"[-8:]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_role_blocked(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("cust"), "customer")
    resp = await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "x", "environment": "development"},
        headers=_auth(body["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["appraiser", "admin", "sales", "sales_manager"])
@pytest.mark.asyncio
async def test_field_user_roles_allowed(client: AsyncClient, db_session: AsyncSession, role: str):
    body = await _user_with_role(client, db_session, _email(role), role)
    resp = await client.post(
        "/api/v1/me/device-token",
        json={
            "platform": "ios",
            "token": f"{role}-token",
            "environment": "development",
        },
        headers=_auth(body["access_token"]),
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_platform_rejected(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("apr"), "appraiser")
    resp = await client.post(
        "/api/v1/me/device-token",
        json={"platform": "windows", "token": "x", "environment": "development"},
        headers=_auth(body["access_token"]),
    )
    # Pydantic Literal rejects at the schema layer with 422.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_environment_rejected(client: AsyncClient, db_session: AsyncSession):
    body = await _user_with_role(client, db_session, _email("apr"), "appraiser")
    resp = await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "x", "environment": "staging"},
        headers=_auth(body["access_token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_environment_is_persisted(client: AsyncClient, db_session: AsyncSession):
    """Round-trip the environment field through the DB to confirm CHECK
    constraint is satisfied on both allowed values."""
    body = await _user_with_role(client, db_session, _email("apr"), "appraiser")
    headers = _auth(body["access_token"])

    await client.post(
        "/api/v1/me/device-token",
        json={"platform": "ios", "token": "tok", "environment": "production"},
        headers=headers,
    )
    rows = (
        (await db_session.execute(select(DeviceToken).where(DeviceToken.token == "tok")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].environment == "production"
