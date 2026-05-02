# ABOUTME: Phase 5 Sprint 4 — unit tests for scoring_service.calculate_overall.
# ABOUTME: Covers weighted average, band labels, weight normalization, edge cases.
from __future__ import annotations

from decimal import Decimal

from services.scoring_service import calculate_overall


def test_empty_scores_returns_salvage():
    result = calculate_overall({})
    assert result.overall == Decimal("0.00")
    assert result.band == "salvage"
    assert result.weight_normalized is False


def test_zero_total_weight_returns_salvage():
    result = calculate_overall({"a": (4.0, 0.0), "b": (5.0, 0.0)})
    assert result.overall == Decimal("0.00")
    assert result.band == "salvage"


def test_single_component_perfect_score():
    result = calculate_overall({"comp-1": (5.0, 100.0)})
    assert result.overall == Decimal("5.00")
    assert result.band == "excellent"
    assert result.weight_normalized is False


def test_weighted_average_two_components():
    # 3.0 at weight 50 + 5.0 at weight 50 → avg 4.0
    result = calculate_overall({"a": (3.0, 50.0), "b": (5.0, 50.0)})
    assert result.overall == Decimal("4.00")
    assert result.band == "good"


def test_score_band_excellent():
    result = calculate_overall({"a": (4.5, 100.0)})
    assert result.band == "excellent"


def test_score_band_good():
    result = calculate_overall({"a": (3.5, 100.0)})
    assert result.band == "good"


def test_score_band_fair():
    result = calculate_overall({"a": (2.5, 100.0)})
    assert result.band == "fair"


def test_score_band_poor():
    result = calculate_overall({"a": (1.5, 100.0)})
    assert result.band == "poor"


def test_score_band_salvage():
    result = calculate_overall({"a": (1.0, 100.0)})
    assert result.band == "salvage"


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
    assert result.band == "salvage"
