# ABOUTME: Phase 5 Sprint 4 — unit tests for scoring_service.calculate_overall.
# ABOUTME: Phase 6 Sprint 1 — updated band labels to match the Phase 6 condition scale.
# ABOUTME: Covers weighted average, band labels, weight normalization, edge cases.
from __future__ import annotations

from decimal import Decimal

from services.scoring_service import calculate_overall


def test_empty_scores_returns_insufficient_data():
    result = calculate_overall({})
    assert result.overall == Decimal("0.00")
    assert result.band == "Insufficient data"
    assert result.weight_normalized is False


def test_zero_total_weight_returns_insufficient_data():
    result = calculate_overall({"a": (4.0, 0.0), "b": (5.0, 0.0)})
    assert result.overall == Decimal("0.00")
    assert result.band == "Insufficient data"


def test_single_component_perfect_score():
    result = calculate_overall({"comp-1": (5.0, 100.0)})
    assert result.overall == Decimal("5.00")
    assert result.band == "Premium resale-ready"
    assert result.weight_normalized is False


def test_weighted_average_two_components():
    # 3.0 at weight 50 + 5.0 at weight 50 → avg 4.0
    result = calculate_overall({"a": (3.0, 50.0), "b": (5.0, 50.0)})
    assert result.overall == Decimal("4.00")
    assert result.band == "Strong resale candidate"


def test_score_band_premium():
    result = calculate_overall({"a": (4.5, 100.0)})
    assert result.band == "Premium resale-ready"


def test_score_band_strong():
    # 3.75 is the threshold for "Strong resale candidate"
    result = calculate_overall({"a": (3.75, 100.0)})
    assert result.band == "Strong resale candidate"


def test_score_band_usable():
    result = calculate_overall({"a": (3.0, 100.0)})
    assert result.band == "Usable with value deductions"


def test_score_band_heavy_discount():
    result = calculate_overall({"a": (2.0, 100.0)})
    assert result.band == "Heavy discount / repair candidate"


def test_score_band_project():
    result = calculate_overall({"a": (1.0, 100.0)})
    assert result.band == "Project, salvage, or parts-biased"


def test_score_band_insufficient_data():
    result = calculate_overall({"a": (0.5, 100.0)})
    assert result.band == "Insufficient data"


def test_score_band_boundary_3_75():
    # 3.74 falls in "Usable", 3.75 falls in "Strong"
    result_below = calculate_overall({"a": (3.74, 100.0)})
    result_at = calculate_overall({"a": (3.75, 100.0)})
    assert result_below.band == "Usable with value deductions"
    assert result_at.band == "Strong resale candidate"


def test_score_band_boundary_4_50():
    # 4.49 falls in "Strong", 4.50 falls in "Premium"
    result_below = calculate_overall({"a": (4.49, 100.0)})
    result_at = calculate_overall({"a": (4.50, 100.0)})
    assert result_below.band == "Strong resale candidate"
    assert result_at.band == "Premium resale-ready"


def test_weight_normalization_flagged_when_weights_not_100():
    # Weights sum to 60 instead of 100 → normalized but flag is set
    result = calculate_overall({"a": (4.0, 30.0), "b": (4.0, 30.0)})
    assert result.weight_normalized is True
    # Normalized result should still be 4.0 (equal weights)
    assert result.overall == Decimal("4.00")


def test_weight_normalization_not_flagged_near_100():
    result = calculate_overall({"a": (4.0, 100.0)})
    assert result.weight_normalized is False


def test_score_clamped_at_five():
    # Even if somehow score exceeds 5 (shouldn't happen, but guard exists)
    result = calculate_overall({"a": (5.0, 100.0), "b": (5.0, 0.0001)})
    assert result.overall <= Decimal("5.00")


def test_score_clamped_at_zero():
    result = calculate_overall({"a": (0.0, 100.0)})
    assert result.overall == Decimal("0.00")
    assert result.band == "Insufficient data"
