# ABOUTME: Phase 7 — integration tests for PDF generation worker and download endpoint.
# ABOUTME: WeasyPrint rendering and R2 upload are mocked; DB interactions are real.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppraisalPhoto,
    AppraisalReport,
    AppraisalSubmission,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)
from services.pdf_generation_worker import generate_and_store
from services.report_data_service import ReportDataIncompleteError

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# Helpers — copied from test_report_data_service pattern
# --------------------------------------------------------------------------- #


async def _create_active_user(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email: str,
    role_slug: str,
) -> User:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Test",
                "last_name": "User",
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
    return user


async def _seed_approved_submission(
    db: AsyncSession,
    *,
    appraiser: User,
    sales_rep: User,
    with_photos: bool = False,
    has_approval: bool = True,
) -> tuple[AppraisalSubmission, EquipmentRecord]:
    customer = Customer(
        submitter_name="PDF Test Owner",
        invite_email=f"owner-pdf-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()

    cat = EquipmentCategory(
        name=f"PDFCat-{_tag()}",
        slug=f"pdfcat-{_tag()}",
        version=1,
    )
    db.add(cat)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="approved_pending_esign",
        category_id=cat.id,
        reference_number=f"THE-PDF{_tag().upper()[:5]}",
        assigned_appraiser_id=appraiser.id,
        assigned_sales_rep_id=sales_rep.id,
    )
    db.add(record)
    await db.flush()

    sub = AppraisalSubmission(
        equipment_record_id=record.id,
        appraiser_id=appraiser.id,
        status="approved",
        category_id=cat.id,
        category_version=1,
        make="Komatsu",
        model="PC210",
        year=2020,
        serial_number="KOM210XXX",
        hours_condition="1800",
        running_status="running",
        overall_score=Decimal("4.10"),
        score_band="Strong resale candidate",
        marketability_rating="high",
        management_review_required=False,
        approved_purchase_offer=Decimal("55000.00") if has_approval else None,
        suggested_consignment_price=Decimal("65000.00") if has_approval else None,
        approved_by_id=sales_rep.id,
        approved_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        submitted_at=datetime(2026, 5, 2, 9, 0, tzinfo=UTC),
    )
    db.add(sub)
    await db.flush()

    if with_photos:
        photo = AppraisalPhoto(
            appraisal_submission_id=sub.id,
            slot_label="Cab Interior",
            gcs_path=f"appraisal-photos/{sub.id}/cab.jpg",
            gps_missing=False,
            gps_out_of_range=False,
        )
        db.add(photo)
        await db.flush()

    return sub, record


# --------------------------------------------------------------------------- #
# generate_and_store tests (mocked render + upload)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_and_store_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    """generate_and_store inserts an AppraisalReport row when rendering succeeds."""
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf1-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf1-{t}@example.com", role_slug="sales"
    )
    sub, record = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep
    )

    with patch("services.pdf_render_service.render_pdf", return_value=b"%PDF-1.4 fake"), \
         patch("services.pdf_generation_worker._upload_pdf"):
        report_row = await generate_and_store(db_session, submission_id=sub.id)

    assert report_row.appraisal_submission_id == sub.id
    assert report_row.equipment_record_id == record.id
    assert report_row.gcs_path.startswith(f"reports/{record.id}/")
    assert report_row.generated_at is not None


@pytest.mark.asyncio
async def test_generate_and_store_idempotent_overwrites_existing(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    """Calling generate_and_store twice updates the existing AppraisalReport row."""
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf2-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf2-{t}@example.com", role_slug="sales"
    )
    sub, record = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep
    )

    with patch("services.pdf_render_service.render_pdf", return_value=b"%PDF-1.4 v1"), \
         patch("services.pdf_generation_worker._upload_pdf"):
        await generate_and_store(db_session, submission_id=sub.id)

    with patch("services.pdf_render_service.render_pdf", return_value=b"%PDF-1.4 v2"), \
         patch("services.pdf_generation_worker._upload_pdf"):
        report_row = await generate_and_store(db_session, submission_id=sub.id)

    all_reports = (
        await db_session.execute(
            select(AppraisalReport).where(AppraisalReport.appraisal_submission_id == sub.id)
        )
    ).scalars().all()
    assert len(all_reports) == 1
    assert all_reports[0].id == report_row.id


@pytest.mark.asyncio
async def test_generate_and_store_raises_when_no_approval_data(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf3-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf3-{t}@example.com", role_slug="sales"
    )
    sub, _ = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep, has_approval=False
    )

    with pytest.raises(ReportDataIncompleteError):
        await generate_and_store(db_session, submission_id=sub.id)


# --------------------------------------------------------------------------- #
# Download endpoint tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_download_endpoint_returns_202_when_no_report(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf4-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf4-{t}@example.com", role_slug="sales"
    )
    _, record = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep
    )

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": sales_rep.email, "password": _VALID_PASSWORD},
        )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"/api/v1/equipment-records/{record.id}/report/pdf", headers=headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "generating"


@pytest.mark.asyncio
async def test_download_endpoint_returns_url_when_report_exists(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf5-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf5-{t}@example.com", role_slug="sales"
    )
    sub, record = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep
    )

    report = AppraisalReport(
        equipment_record_id=record.id,
        appraisal_submission_id=sub.id,
        gcs_path=f"reports/{record.id}/{sub.id}.pdf",
        generated_at=datetime.now(UTC),
    )
    db_session.add(report)
    await db_session.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": sales_rep.email, "password": _VALID_PASSWORD},
        )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    expires = datetime(2026, 5, 3, 13, 0, tzinfo=UTC)
    with patch("routers.reports.settings") as mock_settings, \
         patch("services.pdf_generation_worker.generate_download_url",
               return_value=("https://r2.example.com/signed-url", expires)):
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        url = f"/api/v1/equipment-records/{record.id}/report/pdf"
        resp = await client.get(url, headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["download_url"] == "https://r2.example.com/signed-url"
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_download_endpoint_customer_own_record_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf6-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf6-{t}@example.com", role_slug="sales"
    )
    sub, record = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep
    )

    # Create a customer user linked to the equipment record's customer
    eq_record = await db_session.get(EquipmentRecord, record.id)
    customer_obj = await db_session.get(Customer, eq_record.customer_id)
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"cust-pdf6-{t}@example.com",
                "password": _VALID_PASSWORD,
                "first_name": "Cust",
                "last_name": "Owner",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    cust_user = (await db_session.execute(
        select(User).where(User.email == f"cust-pdf6-{t}@example.com")
    )).scalar_one()
    role = (await db_session.execute(select(Role).where(Role.slug == "customer"))).scalar_one()
    cust_user.status = "active"
    cust_user.role_id = role.id
    customer_obj.user_id = cust_user.id
    db_session.add(cust_user)
    db_session.add(customer_obj)
    await db_session.flush()
    from services import user_roles_service
    await user_roles_service.grant(
        db_session, user=cust_user, role_slug="customer", granted_by=None
    )

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": f"cust-pdf6-{t}@example.com", "password": _VALID_PASSWORD},
        )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"/api/v1/equipment-records/{record.id}/report/pdf", headers=headers)
    # No report row seeded → 202 (not 403 — customer is allowed to see their own)
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_download_endpoint_customer_other_record_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-pdf7-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf7-{t}@example.com", role_slug="sales"
    )
    _, record = await _seed_approved_submission(
        db_session, appraiser=appraiser, sales_rep=sales_rep
    )

    # A different customer (no profile linkage to this record)
    await _create_active_user(
        client, db_session, email=f"diffcust-{t}@example.com", role_slug="customer"
    )
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": f"diffcust-{t}@example.com", "password": _VALID_PASSWORD},
        )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"/api/v1/equipment-records/{record.id}/report/pdf", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_download_endpoint_record_not_found_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-pdf8-{t}@example.com", role_slug="sales"
    )
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": sales_rep.email, "password": _VALID_PASSWORD},
        )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"/api/v1/equipment-records/{uuid.uuid4()}/report/pdf", headers=headers)
    assert resp.status_code == 404
