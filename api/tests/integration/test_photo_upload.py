# ABOUTME: Phase 2 Sprint 3 tests for the signed-URL photo upload flow.
# ABOUTME: boto3's presigned_url is patched so we don't need real R2 creds.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import CustomerIntakePhoto, User

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Upload",
        "last_name": "Customer",
        "tos_version": "1",
        "privacy_version": "1",
    }


async def _login_customer(client: AsyncClient, db: AsyncSession, email: str) -> str:
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
    assert login.status_code == 200
    return login.json()["access_token"]


async def _create_record(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _mock_r2_client():
    """Patch target: boto3 client with a stubbed presigned_url method."""
    client = MagicMock()
    client.generate_presigned_url.return_value = (
        "https://r2.example.com/temple-he-photos/photos/xxx/yyy.jpg?signed=1"
    )
    return client


# ---------------------------------------------------------------------------
# upload-url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_url_returns_presigned_url_and_key(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _login_customer(client, db_session, "upload_url@example.com")
    record_id = await _create_record(client, token)

    with (
        patch.object(
            __import__("services.photo_upload_service", fromlist=["_r2_client"]),
            "_r2_client",
            return_value=_mock_r2_client(),
        ),
        patch.object(
            __import__("services.photo_upload_service", fromlist=["settings"]).settings,
            "r2_access_key_id",
            "fake-access-key",
        ),
        patch.object(
            __import__("services.photo_upload_service", fromlist=["settings"]).settings,
            "r2_secret_access_key",
            "fake-secret",
        ),
    ):
        resp = await client.post(
            f"/api/v1/me/equipment/{record_id}/photos/upload-url",
            json={"filename": "front-left.jpg", "content_type": "image/jpeg"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["upload_url"].startswith("https://")
    assert body["storage_key"].startswith(f"photos/{record_id}/")
    assert body["storage_key"].endswith(".jpg")
    assert body["expires_in"] == 900


@pytest.mark.asyncio
async def test_upload_url_rejects_unknown_extension(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "upload_ext@example.com")
    record_id = await _create_record(client, token)

    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/photos/upload-url",
        json={"filename": "malware.exe", "content_type": "image/jpeg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_url_rejects_non_image_content_type(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _login_customer(client, db_session, "upload_mime@example.com")
    record_id = await _create_record(client, token)

    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/photos/upload-url",
        json={"filename": "whatever.pdf", "content_type": "application/pdf"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_url_cross_customer_is_404(client: AsyncClient, db_session: AsyncSession):
    alice = await _login_customer(client, db_session, "upload_alice@example.com")
    alice_record = await _create_record(client, alice)
    bob = await _login_customer(client, db_session, "upload_bob@example.com")

    resp = await client.post(
        f"/api/v1/me/equipment/{alice_record}/photos/upload-url",
        json={"filename": "a.jpg", "content_type": "image/jpeg"},
        headers={"Authorization": f"Bearer {bob}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_photo_persists_metadata(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "finalize_happy@example.com")
    record_id = await _create_record(client, token)
    storage_key = f"photos/{record_id}/00000000-0000-0000-0000-000000000001.jpg"

    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/photos",
        json={
            "storage_key": storage_key,
            "content_type": "image/jpeg",
            "caption": "front-left exterior",
            "display_order": 1,
            "sha256": "a" * 64,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["storage_key"] == storage_key
    assert body["scan_status"] == "pending"
    assert body["content_type"] == "image/jpeg"

    # DB row has the sha256 lowercased + scan_status=pending.
    row = await db_session.execute(
        select(CustomerIntakePhoto).where(CustomerIntakePhoto.storage_key == storage_key)
    )
    photo = row.scalar_one()
    assert photo.sha256 == "a" * 64
    assert photo.caption == "front-left exterior"
    assert photo.scan_status == "pending"


@pytest.mark.asyncio
async def test_finalize_photo_rejects_wrong_prefix(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "finalize_wrongpath@example.com")
    record_id = await _create_record(client, token)
    # A storage_key that doesn't match this record's prefix — must 422.
    other_key = "photos/00000000-0000-0000-0000-000000000000/evil.jpg"

    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/photos",
        json={"storage_key": other_key, "content_type": "image/jpeg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert "belong" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_finalize_photo_rejects_bad_sha256(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "finalize_shabad@example.com")
    record_id = await _create_record(client, token)
    storage_key = f"photos/{record_id}/11111111-1111-1111-1111-111111111111.png"

    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/photos",
        json={
            "storage_key": storage_key,
            "content_type": "image/png",
            "sha256": "not-a-real-hash",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_detail_includes_finalized_photo(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "finalize_detail@example.com")
    record_id = await _create_record(client, token)
    storage_key = f"photos/{record_id}/22222222-2222-2222-2222-222222222222.jpg"

    await client.post(
        f"/api/v1/me/equipment/{record_id}/photos",
        json={"storage_key": storage_key, "content_type": "image/jpeg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    detail = await client.get(
        f"/api/v1/me/equipment/{record_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["photos"]) == 1
    assert body["photos"][0]["scan_status"] == "pending"
    assert body["photos"][0]["content_type"] == "image/jpeg"
    # Also verifies the EquipmentRecord.record_with_photos selectinload
    # doesn't blow up when invoked after a photo finalize.


@pytest.mark.asyncio
async def test_r2_storage_unconfigured_returns_503(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "finalize_unconfig@example.com")
    record_id = await _create_record(client, token)

    # Test env leaves R2 creds empty by default — no patching needed.
    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/photos/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503
