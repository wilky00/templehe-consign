# ABOUTME: Phase 6 Sprint 1 — server-side red flag evaluation for appraisal submissions.
# ABOUTME: Pure evaluate_rules() for unit testing; async evaluate() for the submit path.
"""Red flag evaluation service.

Public surface:

- :class:`RuleSpec` — lightweight rule description passed to the pure evaluator.
- :class:`RedFlagResult` — output of evaluation: flags + updated marketability + notes.
- :func:`evaluate_rules` — pure (no DB). Given a list of :class:`RuleSpec` and a flat
  field dict, returns a :class:`RedFlagResult`. Unit-testable without DB fixtures.
- :func:`evaluate` — async. Loads active :class:`CategoryRedFlagRule` rows for the
  submission's category, builds the field dict from the submission's direct columns,
  delegates to :func:`evaluate_rules`, and returns the result. Called by
  ``appraisal_submission_service.submit()``.

Actions schema (``RuleSpec.actions`` / ``CategoryRedFlagRule.actions`` JSONB):

    set_management_review_required: true   — set management_review_required = True
    flag: "management_review"              — same (legacy shape from Phase 4 seed data)
    hold_for_title_review: true            — set hold_for_title_review = True
    downgrade_marketability: true          — move marketability one band lower
    set_marketability: "<band>"            — force a specific marketability band
    append_review_note: "<text>"           — append text to review_notes

Condition operators:

    equals    — field value (coerced to str) == condition_value
    is_true   — field value is truthy
    is_false  — field value is falsy

Field extraction:

    The ``fields`` dict is built by the caller from direct columns on
    ``AppraisalSubmission`` (``running_status``, ``title_status``, etc.).
    Rules whose ``condition_field`` names a key absent from ``fields`` are
    silently skipped — the condition cannot be evaluated without a value.

    Phase 6 limitation: ``field_values`` stores inspection prompt answers
    keyed by ``prompt_id`` UUID, not by field name. Rules referencing prompt-
    derived fields (e.g. ``structural_damage``) can only fire if the caller
    adds those fields to the dict explicitly. A follow-up migration that adds
    a ``field_key`` slug to ``CategoryInspectionPrompt`` will allow automatic
    extraction. Until then, direct-column fields cover the core red flag paths.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AppraisalSubmission, CategoryRedFlagRule

logger = structlog.get_logger(__name__)

# Marketability bands ordered from best to worst.
_MARKETABILITY_BANDS: tuple[str, ...] = ("Fast Sell", "Average", "Slow Sell", "Salvage Risk")


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RuleSpec:
    """Portable rule description used by the pure evaluator.

    Mirrors the DB columns of :class:`CategoryRedFlagRule` without the ORM
    dependency, so unit tests can construct rules without a DB fixture.
    """

    id: str
    label: str
    condition_field: str
    condition_operator: str  # "equals" | "is_true" | "is_false"
    condition_value: str | None
    actions: dict[str, Any]


@dataclass
class RedFlagResult:
    management_review_required: bool = False
    hold_for_title_review: bool = False
    marketability_rating: str | None = None
    review_notes: str | None = None
    triggered_rules: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pure evaluation
# --------------------------------------------------------------------------- #


def evaluate_rules(
    rules: list[RuleSpec],
    fields: dict[str, Any],
    *,
    current_marketability: str | None,
    current_review_notes: str | None,
) -> RedFlagResult:
    """Evaluate ``rules`` against ``fields`` and return aggregated flag state.

    Does not read from the database. Thread-safe.
    """
    result = RedFlagResult(
        management_review_required=False,
        hold_for_title_review=False,
        marketability_rating=current_marketability,
        review_notes=current_review_notes,
    )

    for rule in rules:
        if _condition_matches(rule, fields):
            _apply_actions(rule, result)

    return result


def _condition_matches(rule: RuleSpec, fields: dict[str, Any]) -> bool:
    """Return True if the rule's condition fires against ``fields``."""
    value = fields.get(rule.condition_field)
    if value is None and rule.condition_field not in fields:
        return False

    op = rule.condition_operator
    if op == "is_true":
        return bool(value)
    if op == "is_false":
        return not bool(value)
    if op == "equals":
        return str(value) == str(rule.condition_value)
    logger.warning("red_flag_unknown_operator", operator=op, rule_id=rule.id)
    return False


def _apply_actions(rule: RuleSpec, result: RedFlagResult) -> None:
    """Mutate ``result`` based on ``rule.actions``."""
    actions = rule.actions
    result.triggered_rules.append(rule.id)

    # management_review_required — two accepted shapes for backwards compat.
    if actions.get("set_management_review_required") or actions.get("flag") == "management_review":
        result.management_review_required = True

    if actions.get("hold_for_title_review"):
        result.hold_for_title_review = True

    if actions.get("downgrade_marketability"):
        result.marketability_rating = _downgrade(result.marketability_rating)

    if forced := actions.get("set_marketability"):
        result.marketability_rating = forced

    if note := actions.get("append_review_note"):
        if result.review_notes:
            result.review_notes = f"{result.review_notes}\n{note}"
        else:
            result.review_notes = note


def _downgrade(current: str | None) -> str:
    """Move marketability one band lower; bottoms out at 'Salvage Risk'."""
    if current is None:
        return "Salvage Risk"
    try:
        idx = _MARKETABILITY_BANDS.index(current)
    except ValueError:
        return "Salvage Risk"
    return _MARKETABILITY_BANDS[min(idx + 1, len(_MARKETABILITY_BANDS) - 1)]


# --------------------------------------------------------------------------- #
# Async entry point (DB-backed)
# --------------------------------------------------------------------------- #


async def evaluate(
    db: AsyncSession,
    submission: AppraisalSubmission,
) -> RedFlagResult:
    """Load active red flag rules for the submission's category and evaluate.

    Returns a :class:`RedFlagResult` reflecting the aggregate state of all
    triggered rules. The caller is responsible for writing the result back
    to the submission and persisting the changes.
    """
    rules: list[RuleSpec] = []

    if submission.category_id is not None:
        db_rules = (
            (
                await db.execute(
                    select(CategoryRedFlagRule).where(
                        CategoryRedFlagRule.category_id == submission.category_id,
                        CategoryRedFlagRule.replaced_at.is_(None),
                        CategoryRedFlagRule.active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

        rules = [
            RuleSpec(
                id=str(r.id),
                label=r.label,
                condition_field=r.condition_field,
                condition_operator=r.condition_operator,
                condition_value=r.condition_value,
                actions=r.actions,
            )
            for r in db_rules
        ]

    fields = _extract_fields(submission)

    result = evaluate_rules(
        rules,
        fields,
        current_marketability=submission.marketability_rating,
        current_review_notes=submission.review_notes,
    )

    if result.triggered_rules:
        logger.info(
            "red_flags_triggered",
            submission_id=str(submission.id),
            triggered=result.triggered_rules,
            management_review_required=result.management_review_required,
            hold_for_title_review=result.hold_for_title_review,
        )

    return result


def _extract_fields(submission: AppraisalSubmission) -> dict[str, Any]:
    """Build a flat field dict from direct columns on the submission.

    Only direct columns are included. Prompt-answer fields stored in
    ``field_values`` (keyed by prompt UUID) are not yet extractable by name;
    see module docstring for the planned resolution path.
    """
    return {
        "running_status": submission.running_status,
        "title_status": submission.title_status,
        "hours_condition": submission.hours_condition,
        "marketability_rating": submission.marketability_rating,
        "serial_number": submission.serial_number,
    }


# --------------------------------------------------------------------------- #
# Helpers for tests
# --------------------------------------------------------------------------- #


def make_rule(
    *,
    condition_field: str,
    condition_operator: str,
    condition_value: str | None = None,
    actions: dict[str, Any],
    label: str = "Test rule",
    rule_id: str | None = None,
) -> RuleSpec:
    """Convenience factory for unit tests."""
    return RuleSpec(
        id=rule_id or str(uuid.uuid4()),
        label=label,
        condition_field=condition_field,
        condition_operator=condition_operator,
        condition_value=condition_value,
        actions=actions,
    )
