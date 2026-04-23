# ABOUTME: Phase 2 Sprint 4 tests for /me/account/data-export.
# ABOUTME: boto3 is patched so we never hit R2; we verify the ZIP content in-memory.
from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DataExportJob, NotificationJob, User
from services import data_export_service

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Export",
        "last_name": "Customer",
        "tos_version": "1",
        "privacy_version": "1",
    }


async def _login_customer(client: AsyncClient, db: AsyncSession, email: str) -> tuple[str, User]:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post("/api/v1/auth/register", json=_register_payload(email))
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one()
    user.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return login.json()["access_token"], user


def _mock_r2_client() -> MagicMock:
    client = MagicMock()
    client.generate_presigned_url.return_value = (
        "https://r2.example.com/temple-he-photos/exports/xxx/yyy.zip?signed=1"
    )
    return client


class _R2Patches:
    """Patch both the client factory and the credential check at once."""

    def __enter__(self):
        svc = __import__("services.data_export_service", fromlist=["_r2_client", "settings"])
        self._patches = [
            patch.object(svc, "_r2_client", return_value=_mock_r2_client()),
            patch.object(svc.settings, "r2_access_key_id", "fake"),
            patch.object(svc.settings, "r2_secret_access_key", "fake"),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_persists_job_and_returns_download_url(
    client: AsyncClient, db_session: AsyncSession
):
    token, _ = await _login_customer(client, db_session, "export_happy@example.com")
    # Add one intake record so the export has something interesting to package.
    await client.post(
        "/api/v1/me/equipment",
        json={"make": "Caterpillar", "photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    with _R2Patches():
        resp = await client.post(
            "/api/v1/me/account/data-export",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["status"] == "complete"
    assert body["download_url"].startswith("https://")
    assert body["url_expires_at"] is not None

    job_id = body["id"]
    row = await db_session.execute(select(DataExportJob).where(DataExportJob.id == job_id))
    job = row.scalar_one()
    assert job.storage_key.startswith("exports/")
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_export_sends_email_with_download_link(client: AsyncClient, db_session: AsyncSession):
    token, _ = await _login_customer(client, db_session, "export_email@example.com")
    with _R2Patches():
        await client.post(
            "/api/v1/me/account/data-export",
            headers={"Authorization": f"Bearer {token}"},
        )
    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "data_export_ready")
    )
    emails = list(jobs.scalars().all())
    assert len(emails) == 1
    assert "download_url" in emails[0].payload
    assert emails[0].payload["to_email"] == "export_email@example.com"


@pytest.mark.asyncio
async def test_export_zip_contents_include_all_entities(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify the in-memory ZIP contains the expected per-entity JSON files."""
    token, user = await _login_customer(client, db_session, "export_zip@example.com")
    await client.post(
        "/api/v1/me/equipment",
        json={"make": "JCB", "photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Drive the generator directly so we can inspect the zip bytes.
    payload = await data_export_service._gather_user_data(db_session, user)
    zip_bytes = data_export_service._build_zip(payload)
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = set(zf.namelist())
    assert {
        "manifest.txt",
        "user.json",
        "customer.json",
        "consent_versions.json",
        "equipment_records.json",
        "change_requests.json",
        "notifications_sent.json",
    }.issubset(names)
    # user.json contains the right email
    user_json = json.loads(zf.read("user.json"))
    assert user_json["email"] == "export_zip@example.com"
    # equipment_records.json has the record we created
    records = json.loads(zf.read("equipment_records.json"))
    assert len(records) == 1
    assert records[0]["make"] == "JCB"


@pytest.mark.asyncio
async def test_export_lists_past_jobs(client: AsyncClient, db_session: AsyncSession):
    token, _ = await _login_customer(client, db_session, "export_list@example.com")
    with _R2Patches():
        await client.post(
            "/api/v1/me/account/data-export",
            headers={"Authorization": f"Bearer {token}"},
        )
        await client.post(
            "/api/v1/me/account/data-export",
            headers={"Authorization": f"Bearer {token}"},
        )
    resp = await client.get(
        "/api/v1/me/account/data-exports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    # Newest first.
    assert items[0]["requested_at"] >= items[1]["requested_at"]


@pytest.mark.asyncio
async def test_export_unauth_is_401(client: AsyncClient):
    resp = await client.post("/api/v1/me/account/data-export")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_export_failure_marks_job_failed(client: AsyncClient, db_session: AsyncSession):
    """If the R2 upload blows up, the job row ends as 'failed' with an error."""
    token, _ = await _login_customer(client, db_session, "export_err@example.com")

    svc = __import__("services.data_export_service", fromlist=["_upload_zip", "settings"])
    with (
        patch.object(svc.settings, "r2_access_key_id", "fake"),
        patch.object(svc.settings, "r2_secret_access_key", "fake"),
        patch.object(svc, "_upload_zip", side_effect=RuntimeError("s3 boom")),
    ):
        resp = await client.post(
            "/api/v1/me/account/data-export",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 500

    jobs = await db_session.execute(select(DataExportJob))
    job = jobs.scalars().first()
    assert job is not None
    assert job.status == "failed"
    assert "s3 boom" in (job.error or "")
