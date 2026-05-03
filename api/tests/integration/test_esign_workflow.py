# ABOUTME: Phase 6 Sprint 3 — integration tests for the eSign workflow.
# ABOUTME: Covers contract dispatch, stub sign page, webhook completion/decline/idempotency, HMAC.
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalSubmission,
    ConsignmentContract,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _create_user(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email: str,
    role_slug: str,
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Test",
                "last_name": role_slug.title(),
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
    from services import user_roles_service

    await user_roles_service.grant(db, user=user, role_slug=role_slug, granted_by=None)
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return resp.json()


async def _setup_approved_record(
    client: AsyncClient,
    db: AsyncSession,
) -> tuple[EquipmentRecord, AppraisalSubmission, str]:
    """Create an approved appraisal + submission; return (record, submission, manager_token)."""
    cat = EquipmentCategory(name=f"ESCat-{_tag()}", slug=f"es-cat-{_tag()}", version=1)
    db.add(cat)
    await db.flush()

    appraiser_tokens = await _create_user(
        client, db, email=f"app-es-{_tag()}@example.com", role_slug="appraiser"
    )
    manager_tokens = await _create_user(
        client, db, email=f"mgr-es-{_tag()}@example.com", role_slug="sales_manager"
    )

    cust_email = f"cust-es-{_tag()}@example.com"
    await _create_user(client, db, email=cust_email, role_slug="customer")
    cust_result = await db.execute(select(User).where(User.email == cust_email.lower()))
    cust_u = cust_result.scalar_one_or_none()

    customer = Customer(submitter_name="ES Customer", invite_email=cust_email)
    if cust_u:
        customer.user_id = cust_u.id
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraiser_assigned",
        category_id=cat.id,
        reference_number=f"THE-ES{_tag().upper()[:5]}",
    )
    db.add(record)
    await db.flush()

    headers_app = {"Authorization": f"Bearer {appraiser_tokens['access_token']}"}
    create_resp = await client.post(
        "/api/v1/appraisal-submissions",
        json={"equipment_record_id": str(record.id)},
        headers=headers_app,
    )
    assert create_resp.status_code == 201, create_resp.text
    sub_id = create_resp.json()["id"]

    await client.patch(
        f"/api/v1/appraisal-submissions/{sub_id}",
        json={"category_id": str(cat.id), "make": "Komatsu", "model": "PC200"},
        headers=headers_app,
    )
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(f"/api/v1/appraisal-submissions/{sub_id}/submit", headers=headers_app)

    headers_mgr = {"Authorization": f"Bearer {manager_tokens['access_token']}"}
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        approve_resp = await client.post(
            f"/api/v1/manager/approvals/{sub_id}/approve",
            json={
                "purchase_offer": "50000.00",
                "consignment_price": "65000.00",
            },
            headers=headers_mgr,
        )
    assert approve_resp.status_code == 200, approve_resp.text

    await db.refresh(record)
    sub_result = await db.execute(
        select(AppraisalSubmission).where(AppraisalSubmission.id == uuid.UUID(sub_id))
    )
    submission = sub_result.scalar_one()

    return record, submission, manager_tokens["access_token"]


# --------------------------------------------------------------------------- #
# Contract dispatch tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_approve_creates_consignment_contract(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Approving an appraisal creates a ConsignmentContract row."""
    record, submission, _ = await _setup_approved_record(client, db_session)

    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one_or_none()
    assert contract is not None
    assert contract.status == "sent"
    assert contract.envelope_id is not None
    assert contract.envelope_id.startswith("stub-")
    assert contract.signed_at is None


@pytest.mark.asyncio
async def test_approve_idempotent_contract(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Calling dispatch_contract twice on the same record doesn't create a duplicate."""
    from services.esign_service import dispatch_contract

    record, _, _ = await _setup_approved_record(client, db_session)

    first = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    first_contract = first.scalar_one_or_none()
    assert first_contract is not None
    original_envelope_id = first_contract.envelope_id

    # Re-calling dispatch should be a no-op.
    await db_session.refresh(record)
    result = await dispatch_contract(db_session, equipment_record=record)
    assert result is not None
    assert result.envelope_id == original_envelope_id


# --------------------------------------------------------------------------- #
# Stub preview + sign
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_stub_preview_renders_html(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The stub preview page returns HTML with the envelope_id and a Sign Now form."""
    record, _, _ = await _setup_approved_record(client, db_session)

    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one()
    envelope_id = contract.envelope_id

    resp = await client.get(f"/api/v1/esign/stub-preview/{envelope_id}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert envelope_id in resp.text
    assert "Sign Now" in resp.text


@pytest.mark.asyncio
async def test_stub_sign_completes_contract(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /esign/stub-sign/:id fires the signed event and advances the record status."""
    from database.models import EquipmentRecord as _ER

    record, _, _ = await _setup_approved_record(client, db_session)
    await db_session.refresh(record)

    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one()
    envelope_id = contract.envelope_id

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(f"/api/v1/esign/stub-sign/{envelope_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "signed"

    await db_session.refresh(contract)
    assert contract.status == "completed"
    assert contract.signed_at is not None

    refreshed_record = await db_session.get(_ER, record.id)
    assert refreshed_record.status == "esigned_pending_publish"


# --------------------------------------------------------------------------- #
# Webhook tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_webhook_envelope_completed(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """envelope_completed webhook transitions the record to esigned_pending_publish."""
    from database.models import EquipmentRecord as _ER

    record, _, _ = await _setup_approved_record(client, db_session)
    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one()
    envelope_id = contract.envelope_id

    payload = json.dumps({"event": "envelope_completed", "envelope_id": envelope_id}).encode()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/esign/webhook",
            content=payload,
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 200

    await db_session.refresh(contract)
    assert contract.status == "completed"
    assert contract.signed_at is not None

    refreshed = await db_session.get(_ER, record.id)
    assert refreshed.status == "esigned_pending_publish"


@pytest.mark.asyncio
async def test_webhook_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Sending envelope_completed twice doesn't error or double-transition the record."""

    record, _, _ = await _setup_approved_record(client, db_session)
    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one()
    envelope_id = contract.envelope_id

    payload = json.dumps({"event": "envelope_completed", "envelope_id": envelope_id}).encode()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        r1 = await client.post(
            "/api/v1/esign/webhook",
            content=payload,
            headers={"content-type": "application/json"},
        )
        r2 = await client.post(
            "/api/v1/esign/webhook",
            content=payload,
            headers={"content-type": "application/json"},
        )
    assert r1.status_code == 200
    assert r2.status_code == 200

    await db_session.refresh(contract)
    assert contract.status == "completed"


@pytest.mark.asyncio
async def test_webhook_envelope_declined(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """envelope_declined reverts the equipment record to approved_pending_esign."""
    from database.models import EquipmentRecord as _ER

    record, _, _ = await _setup_approved_record(client, db_session)
    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one()
    envelope_id = contract.envelope_id

    payload = json.dumps({"event": "envelope_declined", "envelope_id": envelope_id}).encode()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/esign/webhook",
            content=payload,
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 200

    await db_session.refresh(contract)
    assert contract.status == "declined"

    refreshed = await db_session.get(_ER, record.id)
    assert refreshed.status == "approved_pending_esign"


@pytest.mark.asyncio
async def test_webhook_hmac_invalid(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A webhook with an invalid HMAC signature is rejected with 403."""
    from config import settings

    original_secret = getattr(settings, "esign_webhook_secret", "")
    settings.esign_webhook_secret = "correct-secret"
    try:
        payload = json.dumps({"event": "envelope_completed", "envelope_id": "stub-fake"}).encode()
        resp = await client.post(
            "/api/v1/esign/webhook",
            content=payload,
            headers={
                "content-type": "application/json",
                "x-esign-signature": "wrong-sig",
            },
        )
        assert resp.status_code == 403
    finally:
        settings.esign_webhook_secret = original_secret


@pytest.mark.asyncio
async def test_webhook_unknown_envelope(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A webhook referencing an unknown envelope_id is handled gracefully."""
    data = {"event": "envelope_completed", "envelope_id": "stub-nonexistent"}
    payload = json.dumps(data).encode()
    resp = await client.post(
        "/api/v1/esign/webhook",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_webhook_unknown_event_is_ignored(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Unknown event types are accepted without error."""
    record, _, _ = await _setup_approved_record(client, db_session)
    contract_result = await db_session.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == record.id
        )
    )
    contract = contract_result.scalar_one()

    payload = json.dumps(
        {"event": "envelope_future_event", "envelope_id": contract.envelope_id}
    ).encode()
    resp = await client.post(
        "/api/v1/esign/webhook",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["received"] is True
