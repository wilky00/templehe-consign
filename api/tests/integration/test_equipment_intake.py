# ABOUTME: Phase 2 Sprint 2 integration tests for /me/equipment intake + list + detail.
# ABOUTME: Exercises bleach, batch-501 stub, and cross-customer isolation.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentCategory, EquipmentRecord, NotificationJob, User

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Intake",
        "last_name": "Customer",
        "tos_version": "1",
        "privacy_version": "1",
    }


async def _login_as_active_customer(client: AsyncClient, db: AsyncSession, email: str) -> str:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post("/api/v1/auth/register", json=_register_payload(email))
    assert reg.status_code == 201, reg.json()
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    assert user is not None
    user.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert login.status_code == 200, login.json()
    return login.json()["access_token"]


async def _get_category_id(db: AsyncSession, slug: str) -> str:
    result = await db.execute(select(EquipmentCategory).where(EquipmentCategory.slug == slug))
    cat = result.scalar_one_or_none()
    assert cat is not None, f"category {slug} not seeded"
    return str(cat.id)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_happy_path_creates_record_and_enqueues_email(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _login_as_active_customer(client, db_session, "intake_happy@example.com")
    category_id = await _get_category_id(db_session, "dozers")

    payload = {
        "category_id": category_id,
        "make": "  Caterpillar  ",
        "model": "D6",
        "year": 2015,
        "serial_number": "CAT-D6-00123",
        "hours": 4200,
        "running_status": "running",
        "ownership_type": "owned",
        "location_text": "Yard #2 — 1234 Industrial Dr, Houston TX",
        "description": "Runs well, no known issues.",
        "photos": [
            {"storage_key": "intake/abc/p1.jpg", "caption": "front-left"},
            {"storage_key": "intake/abc/p2.jpg", "caption": None},
        ],
    }

    resp = await client.post(
        "/api/v1/me/equipment",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["reference_number"].startswith("THE-")
    assert len(body["reference_number"]) == 12  # THE- + 8 chars
    assert body["status"] == "new_request"
    assert body["make"] == "Caterpillar"  # strip applied
    assert body["running_status"] == "running"
    assert body["ownership_type"] == "owned"
    assert len(body["photos"]) == 2

    # Notification job row was enqueued.
    notif_result = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "intake_confirmation")
    )
    jobs = list(notif_result.scalars().all())
    assert len(jobs) == 1
    job = jobs[0]
    assert job.channel == "email"
    assert job.status == "pending"
    assert body["reference_number"] in job.payload["subject"]
    assert job.payload["to_email"] == "intake_happy@example.com"
    assert job.idempotency_key.startswith("intake_confirmation:")


@pytest.mark.asyncio
async def test_intake_bleach_strips_script_and_markup(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _login_as_active_customer(client, db_session, "intake_bleach@example.com")
    payload = {
        "make": "<script>alert('xss')</script>Kubota",
        "model": "<b>SVL-90</b>",
        "description": "Good condition<script>steal()</script> ready to go.",
        "photos": [],
    }
    resp = await client.post(
        "/api/v1/me/equipment",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert "<" not in (body["make"] or "")
    assert "Kubota" in body["make"]
    assert "<" not in (body["model"] or "")
    assert "SVL-90" in body["model"]
    assert "script" not in (body["description"] or "").lower()
    assert "Good condition" in body["description"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_rejects_invalid_running_status(client: AsyncClient, db_session: AsyncSession):
    token = await _login_as_active_customer(client, db_session, "intake_bad_status@example.com")
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"running_status": "maybe_sometimes", "photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_intake_rejects_unknown_category(client: AsyncClient, db_session: AsyncSession):
    token = await _login_as_active_customer(client, db_session, "intake_bad_cat@example.com")
    resp = await client.post(
        "/api/v1/me/equipment",
        json={
            "category_id": "00000000-0000-0000-0000-000000000000",
            "photos": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert "category" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_intake_photo_cap_enforced(client: AsyncClient, db_session: AsyncSession):
    token = await _login_as_active_customer(client, db_session, "intake_photos@example.com")
    photos = [{"storage_key": f"intake/over/p{i}.jpg"} for i in range(21)]
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": photos},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_intake_unauth_is_401(client: AsyncClient):
    resp = await client.post("/api/v1/me/equipment", json={"photos": []})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Batch endpoint stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_batch_returns_501(client: AsyncClient, db_session: AsyncSession):
    token = await _login_as_active_customer(client, db_session, "intake_batch@example.com")
    resp = await client.post(
        "/api/v1/me/equipment/batch",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# List + detail + cross-customer isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_list_returns_only_callers_records(
    client: AsyncClient, db_session: AsyncSession
):
    alice = await _login_as_active_customer(client, db_session, "intake_alice@example.com")
    await client.post(
        "/api/v1/me/equipment",
        json={"make": "Alice's Dozer", "photos": []},
        headers={"Authorization": f"Bearer {alice}"},
    )

    bob = await _login_as_active_customer(client, db_session, "intake_bob@example.com")
    await client.post(
        "/api/v1/me/equipment",
        json={"make": "Bob's Backhoe", "photos": []},
        headers={"Authorization": f"Bearer {bob}"},
    )

    alice_list = await client.get(
        "/api/v1/me/equipment", headers={"Authorization": f"Bearer {alice}"}
    )
    assert alice_list.status_code == 200
    alice_items = alice_list.json()
    assert len(alice_items) == 1
    assert alice_items[0]["make"] == "Alice's Dozer"


@pytest.mark.asyncio
async def test_intake_detail_cross_customer_is_404(client: AsyncClient, db_session: AsyncSession):
    """Bob must not be able to GET Alice's record by ID."""
    alice_token = await _login_as_active_customer(client, db_session, "intake_alice2@example.com")
    create = await client.post(
        "/api/v1/me/equipment",
        json={"make": "Alice's private item", "photos": []},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    alice_record_id = create.json()["id"]

    bob_token = await _login_as_active_customer(client, db_session, "intake_bob2@example.com")
    resp = await client.get(
        f"/api/v1/me/equipment/{alice_record_id}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    # 404 (not 403) so we don't leak the ID space.
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_intake_reference_number_is_unique(client: AsyncClient, db_session: AsyncSession):
    token = await _login_as_active_customer(client, db_session, "intake_refs@example.com")
    refs = set()
    for _ in range(5):
        resp = await client.post(
            "/api/v1/me/equipment",
            json={"photos": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        refs.add(resp.json()["reference_number"])
    assert len(refs) == 5

    # Also verify they all persisted with unique values at the DB level.
    result = await db_session.execute(
        select(EquipmentRecord.reference_number).where(
            EquipmentRecord.reference_number.in_(list(refs))
        )
    )
    persisted = [row[0] for row in result.fetchall()]
    assert set(persisted) == refs
