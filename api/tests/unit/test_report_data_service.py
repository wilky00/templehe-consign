# ABOUTME: Phase 7 — unit tests for ReportDataService._assemble() and helpers.
# ABOUTME: All tests use in-memory fixture objects; no DB required.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.report_data_service import (
    ReportDataIncompleteError,
    _assemble,
    _build_comparable_sales,
    _build_component_rows,
    _build_red_flags,
    _decimal_or_none,
)

# --------------------------------------------------------------------------- #
# Fixtures — lightweight ORM-like objects using MagicMock
# --------------------------------------------------------------------------- #


def _make_submission(
    *,
    approved_purchase_offer=Decimal("45000.00"),
    suggested_consignment_price=Decimal("52000.00"),
    overall_score=Decimal("3.80"),
    score_band="Strong resale candidate",
    marketability_rating="high",
    management_review_required=False,
    review_notes=None,
    red_flags=None,
    comparable_sales_data=None,
    transport_notes=None,
    component_scores=None,
    appraiser_id=None,
    category_id=None,
    approved_at=None,
    submitted_at=None,
) -> MagicMock:
    sub = MagicMock()
    sub.id = uuid.uuid4()
    sub.equipment_record_id = uuid.uuid4()
    sub.appraiser_id = appraiser_id
    sub.category_id = category_id
    sub.make = "Caterpillar"
    sub.model = "336"
    sub.year = 2019
    sub.serial_number = "CAT0336XXXXX"
    sub.hours_condition = "2400"
    sub.running_status = "running"
    sub.title_status = "clear"
    sub.transport_notes = transport_notes
    sub.approved_purchase_offer = approved_purchase_offer
    sub.suggested_consignment_price = suggested_consignment_price
    sub.overall_score = overall_score
    sub.score_band = score_band
    sub.marketability_rating = marketability_rating
    sub.management_review_required = management_review_required
    sub.review_notes = review_notes
    sub.red_flags = red_flags or []
    sub.comparable_sales_data = comparable_sales_data or []
    sub.component_scores = component_scores or []
    sub.approved_at = approved_at or datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    sub.submitted_at = submitted_at or datetime(2026, 5, 2, 9, 0, tzinfo=UTC)
    return sub


def _make_record(*, reference_number="THE-XXXXXXXX") -> MagicMock:
    rec = MagicMock()
    rec.id = uuid.uuid4()
    rec.reference_number = reference_number
    rec.assigned_sales_rep_id = uuid.uuid4()
    return rec


def _make_category(*, name="Excavators") -> MagicMock:
    cat = MagicMock()
    cat.id = uuid.uuid4()
    cat.name = name
    return cat


def _make_user(*, first_name="Jane", last_name="Smith", email="jane@example.com") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.first_name = first_name
    u.last_name = last_name
    u.email = email
    return u


def _make_component_score(
    *, component_name="Engine", raw_score="4.00", weight="0.3000"
) -> MagicMock:
    cs = MagicMock()
    cs.raw_score = Decimal(raw_score)
    cs.weight_at_time_of_scoring = Decimal(weight)
    cs.component = MagicMock()
    cs.component.name = component_name
    return cs


def _make_photo(
    *,
    slot_label="Engine Compartment",
    gps_missing=False,
    gps_out_of_range=False,
) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.slot_label = slot_label
    p.gcs_path = f"appraisal-photos/{uuid.uuid4()}/engine.jpg"
    p.capture_timestamp = datetime(2026, 4, 15, 10, 32, tzinfo=UTC)
    p.gps_latitude = Decimal("30.3322")
    p.gps_longitude = Decimal("-97.7431")
    p.gps_missing = gps_missing
    p.gps_out_of_range = gps_out_of_range
    return p


def _call_assemble(**overrides):
    kwargs = dict(
        submission=_make_submission(),
        record=_make_record(),
        category=_make_category(),
        appraiser=_make_user(first_name="Tom", last_name="Jones", email="tom@example.com"),
        sales_rep=_make_user(first_name="Sara", last_name="Lee", email="sara@example.com"),
        photos=[_make_photo()],
        logo_url="",
        brand_color="#1E3A5F",
        font_family="Inter, sans-serif",
        page_size="A4",
    )
    kwargs.update(overrides)
    return _assemble(**kwargs)


# --------------------------------------------------------------------------- #
# Happy-path tests
# --------------------------------------------------------------------------- #


def test_assemble_returns_report_data():
    rd = _call_assemble()
    assert rd.equipment.make == "Caterpillar"
    assert rd.equipment.model == "336"
    assert rd.equipment.reference_number == "THE-XXXXXXXX"


def test_equipment_section_category_name():
    rd = _call_assemble(category=_make_category(name="Dozers"))
    assert rd.equipment.category_name == "Dozers"


def test_equipment_section_no_category():
    rd = _call_assemble(category=None)
    assert rd.equipment.category_name is None


def test_valuation_section_pricing():
    rd = _call_assemble()
    assert rd.valuation.approved_purchase_offer == Decimal("45000.00")
    assert rd.valuation.suggested_consignment_price == Decimal("52000.00")


def test_valuation_section_score_and_band():
    rd = _call_assemble()
    assert rd.valuation.overall_score == Decimal("3.80")
    assert rd.valuation.score_band == "Strong resale candidate"


def test_valuation_section_management_review_flag():
    sub = _make_submission(management_review_required=True, review_notes="Check serial plate")
    rd = _call_assemble(submission=sub)
    assert rd.valuation.management_review_required is True
    assert rd.valuation.manager_notes == "Check serial plate"


def test_personnel_appraiser_and_sales_rep():
    appraiser = _make_user(first_name="Al", last_name="Baker", email="al@example.com")
    sales_rep = _make_user(first_name="Beth", last_name="Clark", email="beth@example.com")
    rd = _call_assemble(appraiser=appraiser, sales_rep=sales_rep)
    assert rd.personnel.appraiser.full_name == "Al Baker"
    assert rd.personnel.appraiser.role_label == "Certified Appraiser"
    assert rd.personnel.sales_rep.full_name == "Beth Clark"
    assert rd.personnel.sales_rep.role_label == "Sales Representative"


def test_personnel_no_appraiser():
    rd = _call_assemble(appraiser=None)
    assert rd.personnel.appraiser is None


def test_gallery_photos():
    p1 = _make_photo(slot_label="Bucket")
    p2 = _make_photo(slot_label="Hour Meter")
    rd = _call_assemble(photos=[p1, p2])
    assert len(rd.gallery.photos) == 2
    labels = {ph.slot_label for ph in rd.gallery.photos}
    assert labels == {"Bucket", "Hour Meter"}


def test_gallery_empty_photos_ok():
    rd = _call_assemble(photos=[])
    assert rd.gallery.photos == []


def test_branding_section():
    rd = _call_assemble(logo_url="https://cdn.example.com/logo.png", brand_color="#AABBCC")
    assert rd.branding.company_logo_url == "https://cdn.example.com/logo.png"
    assert rd.branding.brand_primary_color == "#AABBCC"
    assert rd.branding.page_size == "A4"


# --------------------------------------------------------------------------- #
# ReportDataIncompleteError cases
# --------------------------------------------------------------------------- #


def test_raises_when_no_approval_data():
    sub = _make_submission(
        approved_purchase_offer=None,
        suggested_consignment_price=None,
    )
    with pytest.raises(ReportDataIncompleteError, match="no approval data"):
        _call_assemble(submission=sub)


def test_does_not_raise_when_only_consignment_price_set():
    sub = _make_submission(
        approved_purchase_offer=None,
        suggested_consignment_price=Decimal("52000.00"),
    )
    # Only both being null triggers the error; partial approval is allowed
    rd = _call_assemble(submission=sub)
    assert rd.valuation.suggested_consignment_price == Decimal("52000.00")


# --------------------------------------------------------------------------- #
# _build_component_rows
# --------------------------------------------------------------------------- #


def test_build_component_rows_weighted_contribution():
    cs = _make_component_score(component_name="Hydraulics", raw_score="3.50", weight="0.2500")
    rows = _build_component_rows([cs])
    assert len(rows) == 1
    assert rows[0].component_name == "Hydraulics"
    assert rows[0].weighted_contribution == Decimal("0.88")  # 3.50 * 0.25 = 0.875 → 0.88


def test_build_component_rows_empty():
    assert _build_component_rows([]) == []


def test_build_component_rows_no_component_object():
    cs = _make_component_score()
    cs.component = None
    rows = _build_component_rows([cs])
    assert rows[0].component_name == "Unknown"


# --------------------------------------------------------------------------- #
# _build_comparable_sales
# --------------------------------------------------------------------------- #


def test_build_comparable_sales_parses_dicts():
    raw = [{"sale_price": "48000", "make": "Komatsu", "model": "PC210", "year": 2018}]
    rows = _build_comparable_sales(raw)
    assert len(rows) == 1
    assert rows[0].make == "Komatsu"
    assert rows[0].sale_price == Decimal("48000")


def test_build_comparable_sales_skips_non_dicts():
    raw = ["not-a-dict", {"sale_price": "30000"}]
    rows = _build_comparable_sales(raw)
    assert len(rows) == 1


def test_build_comparable_sales_empty():
    assert _build_comparable_sales([]) == []


# --------------------------------------------------------------------------- #
# _build_red_flags
# --------------------------------------------------------------------------- #


def test_build_red_flags_parses_label():
    raw = [{"rule_id": str(uuid.uuid4()), "label": "Missing serial plate",
            "triggered_at": "2026-05-03"}]
    flags = _build_red_flags(raw)
    assert len(flags) == 1
    assert flags[0].label == "Missing serial plate"


def test_build_red_flags_falls_back_to_action():
    raw = [{"rule_id": str(uuid.uuid4()), "action": "hold_for_title_review"}]
    flags = _build_red_flags(raw)
    assert flags[0].label == "hold_for_title_review"


def test_build_red_flags_empty():
    assert _build_red_flags([]) == []


# --------------------------------------------------------------------------- #
# _decimal_or_none
# --------------------------------------------------------------------------- #


def test_decimal_or_none_valid():
    assert _decimal_or_none("48000.50") == Decimal("48000.50")


def test_decimal_or_none_none():
    assert _decimal_or_none(None) is None


def test_decimal_or_none_invalid():
    assert _decimal_or_none("not-a-number") is None
