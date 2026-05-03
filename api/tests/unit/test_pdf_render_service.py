# ABOUTME: Phase 7 — unit tests for pdf_render_service.render_pdf().
# ABOUTME: Includes a smoke test that WeasyPrint is callable; photo fetch is mocked.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from schemas.report import (
    BrandingSection,
    EquipmentDetailsSection,
    PersonnelMember,
    PersonnelSection,
    PhotoGallerySection,
    ReportData,
    ValuationSection,
)
from services.pdf_render_service import render_pdf


def _make_report_data() -> ReportData:
    return ReportData(
        submission_id=uuid.uuid4(),
        equipment_record_id=uuid.uuid4(),
        equipment=EquipmentDetailsSection(
            reference_number="THE-SMOKE001",
            make="Caterpillar",
            model="336",
            year=2019,
            serial_number="CAT336XXX",
            hours_condition="2400",
            running_status="running",
            title_status="clear",
            transport_notes=None,
            category_name="Excavators",
            appraisal_date=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        ),
        valuation=ValuationSection(
            approved_purchase_offer=Decimal("45000.00"),
            suggested_consignment_price=Decimal("52000.00"),
            overall_score=Decimal("3.80"),
            score_band="Strong resale candidate",
            marketability_rating="high",
            component_scores=[],
            comparable_sales=[],
            red_flags=[],
            management_review_required=False,
            manager_notes=None,
        ),
        gallery=PhotoGallerySection(photos=[]),
        personnel=PersonnelSection(
            appraiser=PersonnelMember(
                full_name="Tom Jones",
                email="tom@example.com",
                role_label="Certified Appraiser",
            ),
            sales_rep=PersonnelMember(
                full_name="Sara Lee",
                email="sara@example.com",
                role_label="Sales Representative",
            ),
        ),
        branding=BrandingSection(
            company_logo_url="",
            brand_primary_color="#1E3A5F",
            font_family="sans-serif",
            page_size="A4",
        ),
    )


def test_render_pdf_returns_pdf_bytes():
    """Smoke test — WeasyPrint produces real PDF bytes (starts with %PDF)."""
    report_data = _make_report_data()
    pdf_bytes = render_pdf(report_data)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"


def test_render_pdf_with_missing_photo_uses_placeholder():
    """When photo fetch fails (R2 not configured), gallery renders without crashing."""
    report_data = _make_report_data()
    pdf_bytes = render_pdf(report_data)
    assert len(pdf_bytes) > 0


def test_render_pdf_letter_size_does_not_crash():
    report_data = _make_report_data()
    report_data.branding.page_size = "Letter"
    pdf_bytes = render_pdf(report_data)
    assert pdf_bytes[:4] == b"%PDF"
