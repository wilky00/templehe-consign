# ABOUTME: Phase 7 — assembles all data required for a PDF appraisal report.
# ABOUTME: ReportDataService.build_report_data() is the single entry point; raises ReportDataIncompleteError if required data is missing.
"""Report data assembly service.

Pure data-assembly layer: loads the approved AppraisalSubmission and related
objects, then calls ``_assemble()`` (a pure function) to produce a
``ReportData`` Pydantic model. The rendering and storage layer never touches
the DB directly — it receives a ``ReportData`` and runs from there.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AppraisalPhoto,
    AppraisalSubmission,
    ComponentScore,
    EquipmentCategory,
    EquipmentRecord,
    User,
)
from schemas.report import (
    BrandingSection,
    ComparableSaleRow,
    ComponentScoreRow,
    EquipmentDetailsSection,
    PersonnelMember,
    PersonnelSection,
    PhotoGallerySection,
    PhotoRecord,
    RedFlagEntry,
    ReportData,
    ValuationSection,
)
from services import app_config_registry

logger = structlog.get_logger(__name__)


class ReportDataIncompleteError(Exception):
    """Raised when required data is absent and the PDF cannot be generated."""


async def build_report_data(db: AsyncSession, *, submission_id: uuid.UUID) -> ReportData:
    """Load and assemble all data for one PDF report.

    Raises :exc:`ReportDataIncompleteError` when the submission or its approval
    data is missing. Photos being empty is allowed — a gallery section with zero
    photos is valid (renders an empty gallery, not an error).

    Raises :exc:`LookupError` if the submission does not exist.
    """
    submission = await _load_submission(db, submission_id)

    record = await db.get(
        EquipmentRecord,
        submission.equipment_record_id,
    )
    if record is None:
        raise ReportDataIncompleteError(
            f"Equipment record for submission {submission_id} not found"
        )

    category: EquipmentCategory | None = None
    if submission.category_id is not None:
        category = await db.get(EquipmentCategory, submission.category_id)

    appraiser: User | None = None
    if submission.appraiser_id is not None:
        appraiser = await db.get(User, submission.appraiser_id)

    sales_rep: User | None = None
    if record.assigned_sales_rep_id is not None:
        sales_rep = await db.get(User, record.assigned_sales_rep_id)

    photos = await _load_photos(db, submission_id)

    logo_url = await app_config_registry.get_typed(db, "company_logo_url")
    brand_color = await app_config_registry.get_typed(db, "pdf_brand_primary_color")
    font_family = await app_config_registry.get_typed(db, "pdf_font_family")
    page_size = await app_config_registry.get_typed(db, "pdf_page_size")

    return _assemble(
        submission=submission,
        record=record,
        category=category,
        appraiser=appraiser,
        sales_rep=sales_rep,
        photos=photos,
        logo_url=logo_url or "",
        brand_color=brand_color or "#1E3A5F",
        font_family=font_family or "Inter",
        page_size=page_size or "A4",
    )


def _assemble(
    *,
    submission: AppraisalSubmission,
    record: EquipmentRecord,
    category: EquipmentCategory | None,
    appraiser: User | None,
    sales_rep: User | None,
    photos: list[AppraisalPhoto],
    logo_url: str,
    brand_color: str,
    font_family: str,
    page_size: str,
) -> ReportData:
    """Pure assembly function — no DB calls. Unit-testable with fixture objects."""
    if submission.approved_purchase_offer is None and submission.suggested_consignment_price is None:
        raise ReportDataIncompleteError(
            f"Submission {submission.id} has no approval data "
            "(approved_purchase_offer and suggested_consignment_price are both null). "
            "The report cannot be generated until the manager has approved the submission."
        )

    equipment = EquipmentDetailsSection(
        reference_number=record.reference_number,
        make=submission.make,
        model=submission.model,
        year=submission.year,
        serial_number=submission.serial_number,
        hours_condition=submission.hours_condition,
        running_status=submission.running_status,
        title_status=submission.title_status,
        transport_notes=submission.transport_notes,
        category_name=category.name if category else None,
        appraisal_date=submission.approved_at or submission.submitted_at,
    )

    component_rows = _build_component_rows(submission.component_scores)

    comp_sales = _build_comparable_sales(submission.comparable_sales_data or [])

    red_flags = _build_red_flags(submission.red_flags or [])

    valuation = ValuationSection(
        approved_purchase_offer=submission.approved_purchase_offer,
        suggested_consignment_price=submission.suggested_consignment_price,
        overall_score=submission.overall_score,
        score_band=submission.score_band,
        marketability_rating=submission.marketability_rating,
        component_scores=component_rows,
        comparable_sales=comp_sales,
        red_flags=red_flags,
        management_review_required=submission.management_review_required,
        manager_notes=submission.review_notes,
    )

    gallery = PhotoGallerySection(
        photos=[_photo_to_record(p) for p in photos],
    )

    personnel = PersonnelSection(
        appraiser=_user_to_member(appraiser, "Certified Appraiser"),
        sales_rep=_user_to_member(sales_rep, "Sales Representative"),
    )

    branding = BrandingSection(
        company_logo_url=logo_url,
        brand_primary_color=brand_color,
        font_family=font_family,
        page_size=page_size,
    )

    return ReportData(
        submission_id=submission.id,
        equipment_record_id=record.id,
        equipment=equipment,
        valuation=valuation,
        gallery=gallery,
        personnel=personnel,
        branding=branding,
    )


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


async def _load_submission(db: AsyncSession, submission_id: uuid.UUID) -> AppraisalSubmission:
    result = await db.execute(
        select(AppraisalSubmission)
        .options(
            selectinload(AppraisalSubmission.component_scores).selectinload(
                ComponentScore.component
            ),
        )
        .where(
            AppraisalSubmission.id == submission_id,
            AppraisalSubmission.deleted_at.is_(None),
        )
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise LookupError(f"Submission {submission_id} not found")
    return submission


async def _load_photos(
    db: AsyncSession, submission_id: uuid.UUID
) -> list[AppraisalPhoto]:
    result = await db.execute(
        select(AppraisalPhoto)
        .where(
            AppraisalPhoto.appraisal_submission_id == submission_id,
            AppraisalPhoto.deleted_at.is_(None),
        )
        .order_by(AppraisalPhoto.created_at.asc())
    )
    return list(result.scalars().all())


def _build_component_rows(scores: list[ComponentScore]) -> list[ComponentScoreRow]:
    rows = []
    for cs in scores:
        name = cs.component.name if cs.component else "Unknown"
        weight = cs.weight_at_time_of_scoring
        raw = cs.raw_score
        weighted = (raw * weight).quantize(Decimal("0.01"))
        rows.append(
            ComponentScoreRow(
                component_name=name,
                raw_score=raw,
                weight_pct=weight,
                weighted_contribution=weighted,
            )
        )
    return rows


def _build_comparable_sales(raw: list) -> list[ComparableSaleRow]:
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rows.append(
            ComparableSaleRow(
                sale_price=_decimal_or_none(item.get("sale_price")),
                sale_date=item.get("sale_date"),
                make=item.get("make"),
                model=item.get("model"),
                year=item.get("year"),
                hours=item.get("hours"),
                source=item.get("source"),
            )
        )
    return rows


def _build_red_flags(raw: list) -> list[RedFlagEntry]:
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rows.append(
            RedFlagEntry(
                rule_id=str(item.get("rule_id", "")),
                label=item.get("label") or item.get("action"),
                triggered_at=item.get("triggered_at"),
            )
        )
    return rows


def _photo_to_record(photo: AppraisalPhoto) -> PhotoRecord:
    return PhotoRecord(
        photo_id=photo.id,
        slot_label=photo.slot_label,
        gcs_path=photo.gcs_path,
        capture_timestamp=photo.capture_timestamp,
        gps_latitude=photo.gps_latitude,
        gps_longitude=photo.gps_longitude,
        gps_missing=photo.gps_missing,
        gps_out_of_range=photo.gps_out_of_range,
    )


def _user_to_member(user: User | None, role_label: str) -> PersonnelMember | None:
    if user is None:
        return None
    return PersonnelMember(
        full_name=f"{user.first_name} {user.last_name}",
        email=user.email,
        role_label=role_label,
    )


def _decimal_or_none(val) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None
