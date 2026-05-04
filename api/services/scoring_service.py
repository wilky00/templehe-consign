# ABOUTME: Phase 5 Sprint 4 — weighted-average scoring for appraisal component scores.
# ABOUTME: Phase 6 Sprint 1 updated score band labels to match the manager-facing condition scale.
# ABOUTME: Pure function; no DB access. Called by appraisal_submission_service after score upsert.
"""Scoring service — weighted average of component 0–5 scores.

Public surface:

- :func:`calculate_overall` — given a dict of ``{component_id: (score, weight)}``,
  returns an :class:`ScoringResult` with the weighted average, score band, and a flag
  indicating whether the weights were normalized (i.e., they didn't sum to 100).

Score bands (Phase 6 condition scale, from 00_condition_scale_and_scoring.md):
    4.50–5.00 → "Premium resale-ready"
    3.75–4.49 → "Strong resale candidate"
    3.00–3.74 → "Usable with value deductions"
    2.00–2.99 → "Heavy discount / repair candidate"
    1.00–1.99 → "Project, salvage, or parts-biased"
    0.00–0.99 → "Insufficient data"
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# (threshold, band) — evaluated in order; first match wins.
# Thresholds and labels per dev_plan/01_checklists/00_condition_scale_and_scoring.md.
_SCORE_BANDS: list[tuple[Decimal, str]] = [
    (Decimal("4.50"), "Premium resale-ready"),
    (Decimal("3.75"), "Strong resale candidate"),
    (Decimal("3.00"), "Usable with value deductions"),
    (Decimal("2.00"), "Heavy discount / repair candidate"),
    (Decimal("1.00"), "Project, salvage, or parts-biased"),
    (Decimal("0.00"), "Insufficient data"),
]


@dataclass
class ScoringResult:
    overall: Decimal
    band: str
    # True when input weights didn't sum to 100 ± 0.5 and normalization was applied
    weight_normalized: bool


def calculate_overall(
    component_scores: dict[str, tuple[float, float]],
) -> ScoringResult:
    """Compute weighted-average score.

    ``component_scores`` maps component_id (str) to
    ``(raw_score: 0–5, weight_pct: any positive float)``.

    Weights are normalized if they don't sum to 100 ± 0.5; the caller
    should surface ``weight_normalized=True`` as a UI warning.

    Returns a zero/salvage result for empty or zero-weight input.
    """
    if not component_scores:
        return ScoringResult(
            overall=Decimal("0.00"), band="Insufficient data", weight_normalized=False
        )

    total_weight = sum(w for _, w in component_scores.values())
    if total_weight == 0:
        return ScoringResult(
            overall=Decimal("0.00"), band="Insufficient data", weight_normalized=False
        )

    weight_normalized = not (99.5 <= total_weight <= 100.5)

    weighted_sum = sum(score * weight for score, weight in component_scores.values())
    # Divide by total_weight so the result is always on the 0–5 scale
    # regardless of whether weights happen to sum to 100.
    overall_raw = weighted_sum / total_weight

    overall = Decimal(str(overall_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    overall = max(Decimal("0.00"), min(Decimal("5.00"), overall))

    band = "salvage"
    for threshold, label in _SCORE_BANDS:
        if overall >= threshold:
            band = label
            break

    return ScoringResult(overall=overall, band=band, weight_normalized=weight_normalized)
