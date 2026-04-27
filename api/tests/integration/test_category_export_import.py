# ABOUTME: Phase 4 Sprint 6 — round-trips a category through export.json + /admin/categories/import.
# ABOUTME: Confirms idempotency on slug, supersede on changed prompts/rules, and additive merges.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _admin(client: AsyncClient, db: AsyncSession, email: str) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Imp",
                "last_name": "Adm",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == "admin"))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return login.json()


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _slug() -> str:
    return f"exp-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_export_then_import_into_fresh_slug_creates(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _admin(client, db_session, "ce_a@example.com")
    h = _auth(admin["access_token"])
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Skid Steers", "slug": _slug()},
        headers=h,
    )
    cat_id = create.json()["id"]
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/components",
        json={"name": "Engine", "weight_pct": 50},
        headers=h,
    )
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/components",
        json={"name": "Hydraulics", "weight_pct": 50},
        headers=h,
    )
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/inspection-prompts",
        json={"label": "Hour meter?", "response_type": "text"},
        headers=h,
    )

    exported = (
        await client.get(f"/api/v1/admin/categories/{cat_id}/export.json", headers=h)
    ).json()

    # Re-import into a brand-new slug — should create.
    exported["slug"] = _slug()
    imported = await client.post("/api/v1/admin/categories/import", json=exported, headers=h)
    assert imported.status_code == 200, imported.json()
    body = imported.json()
    assert body["created"] is True
    assert len(body["added_component_ids"]) == 2
    assert len(body["added_prompt_ids"]) == 1


@pytest.mark.asyncio
async def test_reimport_same_slug_with_changed_prompt_supersedes(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _admin(client, db_session, "ce_b@example.com")
    h = _auth(admin["access_token"])
    slug = _slug()
    create = await client.post(
        "/api/v1/admin/categories", json={"name": "Loaders", "slug": slug}, headers=h
    )
    cat_id = create.json()["id"]
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/inspection-prompts",
        json={"label": "Bucket size?", "response_type": "text"},
        headers=h,
    )

    payload = (await client.get(f"/api/v1/admin/categories/{cat_id}/export.json", headers=h)).json()
    # Same slug → idempotent. Bump the prompt's display_order to force a supersede.
    payload["inspection_prompts"][0]["display_order"] = 99
    imported = await client.post("/api/v1/admin/categories/import", json=payload, headers=h)
    assert imported.status_code == 200, imported.json()
    body = imported.json()
    assert body["created"] is False
    assert len(body["superseded_prompt_ids"]) == 1
    assert len(body["added_prompt_ids"]) == 1

    # GET shows version 2 of the only current prompt.
    detail = await client.get(f"/api/v1/admin/categories/{cat_id}", headers=h)
    prompts = detail.json()["inspection_prompts"]
    assert len(prompts) == 1
    assert prompts[0]["version"] == 2
    assert prompts[0]["display_order"] == 99


@pytest.mark.asyncio
async def test_reimport_same_payload_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    admin = await _admin(client, db_session, "ce_c@example.com")
    h = _auth(admin["access_token"])
    create = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Trenchers", "slug": _slug()},
        headers=h,
    )
    cat_id = create.json()["id"]
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/components",
        json={"name": "Engine", "weight_pct": 60},
        headers=h,
    )
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/components",
        json={"name": "Body", "weight_pct": 40},
        headers=h,
    )
    await client.post(
        f"/api/v1/admin/categories/{cat_id}/inspection-prompts",
        json={"label": "Tracks ok?", "response_type": "yes_no_na"},
        headers=h,
    )

    payload = (await client.get(f"/api/v1/admin/categories/{cat_id}/export.json", headers=h)).json()

    first = (await client.post("/api/v1/admin/categories/import", json=payload, headers=h)).json()
    second = (await client.post("/api/v1/admin/categories/import", json=payload, headers=h)).json()

    assert first["created"] is False  # already exists from create above
    assert second["created"] is False
    # Second import nothing-changed → no supersedes, no new rows.
    assert second["superseded_prompt_ids"] == []
    assert second["added_prompt_ids"] == []
    assert second["added_component_ids"] == []
    assert second["superseded_rule_ids"] == []
