# ABOUTME: Phase 4 Sprint 5 — admin overrides notification template subject/body w/o redeploy.
# ABOUTME: Render uses override when present; deletion reverts to the registered code default.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NotificationTemplateOverride, Role, User
from services import notification_templates

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "T",
                "last_name": "O",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    body = login.json()
    body["user_id"] = str(user.id)
    return body


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_list_returns_every_registered_template(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "tov_admin1@example.com", "admin")
    resp = await client.get(
        "/api/v1/admin/notification-templates",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    names = {t["name"] for t in resp.json()["templates"]}
    expected = {spec.name for spec in notification_templates.all_specs()}
    assert names == expected
    # Spot-check shape.
    one = resp.json()["templates"][0]
    assert {
        "name",
        "channel",
        "category",
        "description",
        "variables",
        "subject_template",
        "body_template",
        "has_override",
    }.issubset(one)


@pytest.mark.asyncio
async def test_patch_persists_override_and_render_uses_it(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "tov_admin2@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/notification-templates/status_update",
        json={
            "subject_md": "Custom subject for {{ reference_number }}",
            "body_md": "<p>Custom body for {{ first_name }}</p>",
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["has_override"] is True
    assert body["override_subject"] == "Custom subject for {{ reference_number }}"

    # render_with_overrides picks up the new subject + body.
    rendered = await notification_templates.render_with_overrides(
        db_session,
        "status_update",
        variables={
            "first_name": "Alice",
            "reference_number": "THE-99",
            "to_status_display": "Listed",
            "to_status": "listed",
            "note_html": "",
        },
    )
    assert rendered.subject == "Custom subject for THE-99"
    assert rendered.body == "<p>Custom body for Alice</p>"


@pytest.mark.asyncio
async def test_delete_reverts_to_code_default(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tov_admin3@example.com", "admin")
    # Write an override.
    await client.patch(
        "/api/v1/admin/notification-templates/status_update",
        json={"subject_md": "X", "body_md": "<p>Y</p>"},
        headers=_auth(admin["access_token"]),
    )
    # Then delete it.
    resp = await client.patch(
        "/api/v1/admin/notification-templates/status_update",
        json={"delete": True},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["has_override"] is False
    rows = (
        (
            await db_session.execute(
                select(NotificationTemplateOverride).where(
                    NotificationTemplateOverride.name == "status_update"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_patch_email_template_requires_subject(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tov_admin4@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/notification-templates/status_update",
        json={"body_md": "<p>only body</p>"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "subject_md" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_sms_template_does_not_require_subject(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "tov_admin5@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/notification-templates/record_lock_overridden_sms",
        json={"body_md": "Custom SMS body for {{ reference }}"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()


@pytest.mark.asyncio
async def test_patch_unknown_template_returns_404(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tov_admin6@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/notification-templates/bogus_template",
        json={"body_md": "x"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_blocked_for_non_admin(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "tov_sales@example.com", "sales")
    resp = await client.get(
        "/api/v1/admin/notification-templates",
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403
