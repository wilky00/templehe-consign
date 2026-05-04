# ABOUTME: Phase 7 — integration tests for ReportDataService.build_report_data().
# ABOUTME: Exercises real DB queries; validates data assembly against seeded submissions.
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
    AppraisalSubmission,
    CategoryComponent,
    ComponentScore,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    Role,
    User,
)
from services.report_data_service import ReportDataIncompleteError, build_report_data

_VALID_PASSWORD = "TestPassword1!"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# Seed helpers
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


async def _seed_category(db: AsyncSession) -> EquipmentCategory:
    cat = EquipmentCategory(
        name=f"RDS-Cat-{_tag()}",
        slug=f"rds-cat-{_tag()}",
        version=1,
    )
    db.add(cat)
    await db.flush()
    return cat


async def _seed_component(db: AsyncSession, *, category: EquipmentCategory) -> CategoryComponent:
    comp = CategoryComponent(
        category_id=category.id,
        name="Engine",
        weight_pct=Decimal("0.4000"),
    )
    db.add(comp)
    await db.flush()
    return comp


async def _seed_approved_submission(
    db: AsyncSession,
    *,
    appraiser: User,
    sales_rep: User,
    category: EquipmentCategory,
    component: CategoryComponent | None = None,
    with_photos: bool = False,
    with_comparable_sales: bool = False,
    approved_purchase_offer: Decimal | None = Decimal("42000.00"),
    suggested_consignment_price: Decimal | None = Decimal("50000.00"),
) -> AppraisalSubmission:
    customer = Customer(
        submitter_name="Test Owner",
        invite_email=f"owner-{_tag()}@example.com",
    )
    db.add(customer)
    await db.flush()

    record = EquipmentRecord(
        customer_id=customer.id,
        status="approved_pending_esign",
        category_id=category.id,
        reference_number=f"THE-RDS{_tag().upper()[:5]}",
        assigned_appraiser_id=appraiser.id,
        assigned_sales_rep_id=sales_rep.id,
    )
    db.add(record)
    await db.flush()

    sub = AppraisalSubmission(
        equipment_record_id=record.id,
        appraiser_id=appraiser.id,
        status="approved",
        category_id=category.id,
        category_version=1,
        make="Caterpillar",
        model="336",
        year=2019,
        serial_number="CATXX123",
        hours_condition="2400",
        running_status="running",
        title_status="clear",
        overall_score=Decimal("3.80"),
        score_band="Strong resale candidate",
        marketability_rating="high",
        management_review_required=False,
        approved_purchase_offer=approved_purchase_offer,
        suggested_consignment_price=suggested_consignment_price,
        approved_by_id=sales_rep.id,
        approved_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        submitted_at=datetime(2026, 5, 2, 9, 0, tzinfo=UTC),
        comparable_sales_data=(
            [{"sale_price": "38000", "make": "Komatsu", "model": "PC210", "year": 2017}]
            if with_comparable_sales
            else []
        ),
    )
    db.add(sub)
    await db.flush()

    if component is not None:
        cs = ComponentScore(
            appraisal_submission_id=sub.id,
            category_component_id=component.id,
            raw_score=Decimal("4.00"),
            weight_at_time_of_scoring=Decimal("0.4000"),
        )
        db.add(cs)
        await db.flush()

    if with_photos:
        photo = AppraisalPhoto(
            appraisal_submission_id=sub.id,
            slot_label="Engine Compartment",
            gcs_path=f"appraisal-photos/{sub.id}/engine.jpg",
            capture_timestamp=datetime(2026, 4, 15, 10, 32, tzinfo=UTC),
            gps_latitude=Decimal("30.3322"),
            gps_longitude=Decimal("-97.7431"),
            gps_missing=False,
            gps_out_of_range=False,
        )
        db.add(photo)
        await db.flush()

    return sub


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_build_report_data_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    """build_report_data returns a complete ReportData for an approved submission."""
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-rds-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-rds-{t}@example.com", role_slug="sales"
    )
    cat = await _seed_category(db_session)
    comp = await _seed_component(db_session, category=cat)
    sub = await _seed_approved_submission(
        db_session,
        appraiser=appraiser,
        sales_rep=sales_rep,
        category=cat,
        component=comp,
        with_photos=True,
        with_comparable_sales=True,
    )

    rd = await build_report_data(db_session, submission_id=sub.id)

    assert rd.submission_id == sub.id
    assert rd.equipment.make == "Caterpillar"
    assert rd.equipment.category_name == cat.name
    assert rd.equipment.reference_number is not None
    assert rd.valuation.approved_purchase_offer == Decimal("42000.00")
    assert len(rd.valuation.component_scores) == 1
    assert rd.valuation.component_scores[0].component_name == "Engine"
    assert len(rd.valuation.comparable_sales) == 1
    assert len(rd.gallery.photos) == 1
    assert rd.gallery.photos[0].slot_label == "Engine Compartment"
    assert rd.personnel.appraiser.email == appraiser.email
    assert rd.personnel.sales_rep.email == sales_rep.email


@pytest.mark.asyncio
async def test_build_report_data_raises_for_missing_submission(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    with pytest.raises(LookupError, match="not found"):
        await build_report_data(db_session, submission_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_build_report_data_raises_when_no_approval_data(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-rds2-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-rds2-{t}@example.com", role_slug="sales"
    )
    cat = await _seed_category(db_session)
    sub = await _seed_approved_submission(
        db_session,
        appraiser=appraiser,
        sales_rep=sales_rep,
        category=cat,
        approved_purchase_offer=None,
        suggested_consignment_price=None,
    )

    with pytest.raises(ReportDataIncompleteError, match="no approval data"):
        await build_report_data(db_session, submission_id=sub.id)


@pytest.mark.asyncio
async def test_build_report_data_no_photos_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    """Gallery with zero photos is not an error."""
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-rds3-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-rds3-{t}@example.com", role_slug="sales"
    )
    cat = await _seed_category(db_session)
    sub = await _seed_approved_submission(
        db_session,
        appraiser=appraiser,
        sales_rep=sales_rep,
        category=cat,
        with_photos=False,
    )

    rd = await build_report_data(db_session, submission_id=sub.id)
    assert rd.gallery.photos == []


@pytest.mark.asyncio
async def test_build_report_data_personnel_fallback_when_unassigned(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_test_db,
) -> None:
    """When no appraiser is assigned, personnel.appraiser is None."""
    t = _tag()
    appraiser = await _create_active_user(
        client, db_session, email=f"app-rds4-{t}@example.com", role_slug="appraiser"
    )
    sales_rep = await _create_active_user(
        client, db_session, email=f"sales-rds4-{t}@example.com", role_slug="sales"
    )
    cat = await _seed_category(db_session)
    sub = await _seed_approved_submission(
        db_session,
        appraiser=appraiser,
        sales_rep=sales_rep,
        category=cat,
    )
    # Clear appraiser_id to simulate unassigned
    sub.appraiser_id = None
    await db_session.flush()

    rd = await build_report_data(db_session, submission_id=sub.id)
    assert rd.personnel.appraiser is None
    assert rd.personnel.sales_rep is not None
