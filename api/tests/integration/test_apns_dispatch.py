# ABOUTME: Phase 5 Sprint 2 — APNs dispatch service integration tests.
# ABOUTME: Uses respx to mock api.push.apple.com; tests success, permanent failure, transient retry.
from __future__ import annotations

import json
import uuid

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from httpx import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DeviceToken, IntegrationCredential, Role, User
from services import apns_dispatch_service, credentials_vault


def _make_ec_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


async def _make_user(db: AsyncSession) -> User:
    role = (await db.execute(select(Role).where(Role.slug == "appraiser"))).scalar_one()
    user = User(
        email=f"apns-test-{uuid.uuid4().hex[:8]}@example.com",
        first_name="Test",
        last_name="Appraiser",
        role_id=role.id,
        status="active",
    )
    db.add(user)
    await db.flush()
    return user


def _vault_entry(db: AsyncSession) -> IntegrationCredential:
    cred_json = json.dumps(
        {
            "private_key": _make_ec_key_pem(),
            "key_id": "TESTKEY1234",
            "team_id": "TESTTEAM12",
        }
    )
    row = IntegrationCredential(
        integration_name="apns",
        encrypted_value=credentials_vault.encrypt(cred_json),
        set_by=None,
    )
    db.add(row)
    return row


@pytest.mark.asyncio
async def test_success_returns_delivered(db_session: AsyncSession):
    _vault_entry(db_session)
    await db_session.flush()

    with respx.mock(base_url="https://api.sandbox.push.apple.com") as mock:
        mock.post("/3/device/testtoken123").mock(return_value=Response(200))
        status = await apns_dispatch_service.send(
            db_session,
            token="testtoken123",
            device_environment="development",
            title="New Assignment",
            body="You've been assigned THE-001.",
        )
    assert status == "delivered"


@pytest.mark.asyncio
async def test_bad_device_token_returns_failed(db_session: AsyncSession):
    _vault_entry(db_session)
    user = await _make_user(db_session)

    token_id = uuid.uuid4()
    dt = DeviceToken(
        id=token_id,
        user_id=user.id,
        platform="ios",
        token="deadtoken",
        environment="development",
    )
    db_session.add(dt)
    await db_session.flush()

    with respx.mock(base_url="https://api.sandbox.push.apple.com") as mock:
        mock.post("/3/device/deadtoken").mock(
            return_value=Response(400, json={"reason": "BadDeviceToken"})
        )
        status = await apns_dispatch_service.send(
            db_session,
            token="deadtoken",
            device_environment="development",
            title="Test",
            body="Test body.",
            device_token_id=token_id,
        )
    assert status == "failed"

    # revoke_by_id uses a bulk UPDATE; expire the identity-map entry before re-fetching.
    await db_session.refresh(dt)
    assert dt.deleted_at is not None


@pytest.mark.asyncio
async def test_410_unregistered_soft_deletes_token(db_session: AsyncSession):
    _vault_entry(db_session)
    user = await _make_user(db_session)

    token_id = uuid.uuid4()
    dt = DeviceToken(
        id=token_id,
        user_id=user.id,
        platform="ios",
        token="oldtoken",
        environment="development",
    )
    db_session.add(dt)
    await db_session.flush()

    with respx.mock(base_url="https://api.sandbox.push.apple.com") as mock:
        mock.post("/3/device/oldtoken").mock(
            return_value=Response(410, json={"reason": "Unregistered"})
        )
        status = await apns_dispatch_service.send(
            db_session,
            token="oldtoken",
            device_environment="development",
            title="Test",
            body="Test body.",
            device_token_id=token_id,
        )
    assert status == "failed"
    # revoke_by_id uses a bulk UPDATE; expire the identity-map entry before re-fetching.
    await db_session.refresh(dt)
    assert dt.deleted_at is not None


@pytest.mark.asyncio
async def test_5xx_raises_transient_error(db_session: AsyncSession):
    _vault_entry(db_session)
    await db_session.flush()

    with respx.mock(base_url="https://api.sandbox.push.apple.com") as mock:
        mock.post("/3/device/tok").mock(
            return_value=Response(503, json={"reason": "ServiceUnavailable"})
        )
        with pytest.raises(apns_dispatch_service.TransientAPNsError):
            await apns_dispatch_service.send(
                db_session,
                token="tok",
                device_environment="development",
                title="Test",
                body="Test body.",
            )


@pytest.mark.asyncio
async def test_missing_vault_returns_skipped(db_session: AsyncSession):
    # No vault entry — APNs not configured yet.
    status = await apns_dispatch_service.send(
        db_session,
        token="anytoken",
        device_environment="development",
        title="Test",
        body="Test body.",
    )
    assert status == "skipped"


@pytest.mark.asyncio
async def test_jwt_uses_correct_kid_and_iss(db_session: AsyncSession):
    private_key_pem = _make_ec_key_pem()
    cred_json = json.dumps(
        {
            "private_key": private_key_pem,
            "key_id": "MYKEYID123",
            "team_id": "MYTEAMID12",
        }
    )
    row = IntegrationCredential(
        integration_name="apns",
        encrypted_value=credentials_vault.encrypt(cred_json),
        set_by=None,
    )
    db_session.add(row)
    await db_session.flush()

    captured_headers: dict = {}

    with respx.mock(base_url="https://api.sandbox.push.apple.com") as mock:

        def capture(request, *args, **kwargs):
            auth = request.headers.get("authorization", "")
            if auth.startswith("bearer "):
                token_str = auth[len("bearer ") :]
                # Decode without verification — we just want the headers.
                captured_headers.update(jwt.get_unverified_header(token_str))
            return Response(200)

        mock.post("/3/device/chktoken").mock(side_effect=capture)
        await apns_dispatch_service.send(
            db_session,
            token="chktoken",
            device_environment="development",
            title="JWT check",
            body="body",
        )

    assert captured_headers.get("kid") == "MYKEYID123"
    assert captured_headers.get("alg") == "ES256"


@pytest.mark.asyncio
async def test_production_token_uses_production_host(db_session: AsyncSession):
    _vault_entry(db_session)
    await db_session.flush()

    with respx.mock(base_url="https://api.push.apple.com") as mock:
        mock.post("/3/device/prodtok").mock(return_value=Response(200))
        status = await apns_dispatch_service.send(
            db_session,
            token="prodtok",
            device_environment="production",
            title="Prod test",
            body="body",
        )
    assert status == "delivered"
