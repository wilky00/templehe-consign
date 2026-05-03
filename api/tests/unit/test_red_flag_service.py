# ABOUTME: Phase 6 Sprint 1 — unit tests for red_flag_service.evaluate_rules.
# ABOUTME: Pure tests — no DB, no fixtures. Uses red_flag_service.make_rule() factory.
from __future__ import annotations

from services.red_flag_service import RedFlagResult, evaluate_rules, make_rule

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _result(
    *,
    fields: dict,
    rules: list | None = None,
    current_marketability: str | None = None,
    current_review_notes: str | None = None,
) -> RedFlagResult:
    return evaluate_rules(
        rules or [],
        fields,
        current_marketability=current_marketability,
        current_review_notes=current_review_notes,
    )


# --------------------------------------------------------------------------- #
# No rules / empty input
# --------------------------------------------------------------------------- #


def test_no_rules_returns_clean_result():
    result = _result(fields={"running_status": "Non-Running"})
    assert result.management_review_required is False
    assert result.hold_for_title_review is False
    assert result.triggered_rules == []


def test_empty_fields_no_match():
    rule = make_rule(
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
    )
    result = _result(fields={}, rules=[rule])
    assert result.management_review_required is False
    assert result.triggered_rules == []


# --------------------------------------------------------------------------- #
# Condition operators
# --------------------------------------------------------------------------- #


def test_equals_operator_matches():
    rule = make_rule(
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
    )
    result = _result(fields={"running_status": "Non-Running"}, rules=[rule])
    assert result.management_review_required is True


def test_equals_operator_no_match():
    rule = make_rule(
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_management_review_required": True},
    )
    result = _result(fields={"running_status": "Running"}, rules=[rule])
    assert result.management_review_required is False


def test_is_true_operator_matches():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"set_management_review_required": True},
    )
    result = _result(fields={"structural_damage": True}, rules=[rule])
    assert result.management_review_required is True


def test_is_true_operator_false_value():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"set_management_review_required": True},
    )
    result = _result(fields={"structural_damage": False}, rules=[rule])
    assert result.management_review_required is False


def test_is_false_operator_matches():
    rule = make_rule(
        condition_field="hours_verified",
        condition_operator="is_false",
        actions={"append_review_note": "Verify hours history before pricing"},
    )
    result = _result(fields={"hours_verified": False}, rules=[rule])
    assert result.review_notes == "Verify hours history before pricing"


def test_is_false_operator_true_value():
    rule = make_rule(
        condition_field="hours_verified",
        condition_operator="is_false",
        actions={"append_review_note": "Verify hours history before pricing"},
    )
    result = _result(fields={"hours_verified": True}, rules=[rule])
    assert result.review_notes is None


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


def test_set_management_review_required_new_key():
    rule = make_rule(
        condition_field="active_major_leak",
        condition_operator="is_true",
        actions={"set_management_review_required": True},
    )
    result = _result(fields={"active_major_leak": True}, rules=[rule])
    assert result.management_review_required is True


def test_flag_management_review_legacy_key():
    # Legacy shape used in Phase 4 seed data: {"flag": "management_review"}
    rule = make_rule(
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"flag": "management_review"},
    )
    result = _result(fields={"running_status": "Non-Running"}, rules=[rule])
    assert result.management_review_required is True


def test_hold_for_title_review():
    rule = make_rule(
        condition_field="missing_serial_plate",
        condition_operator="is_true",
        actions={"hold_for_title_review": True},
    )
    result = _result(fields={"missing_serial_plate": True}, rules=[rule])
    assert result.hold_for_title_review is True


def test_downgrade_marketability_from_fast_sell():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"downgrade_marketability": True},
    )
    result = _result(
        fields={"structural_damage": True},
        rules=[rule],
        current_marketability="Fast Sell",
    )
    assert result.marketability_rating == "Average"


def test_downgrade_marketability_from_average():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"downgrade_marketability": True},
    )
    result = _result(
        fields={"structural_damage": True},
        rules=[rule],
        current_marketability="Average",
    )
    assert result.marketability_rating == "Slow Sell"


def test_downgrade_marketability_from_slow_sell():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"downgrade_marketability": True},
    )
    result = _result(
        fields={"structural_damage": True},
        rules=[rule],
        current_marketability="Slow Sell",
    )
    assert result.marketability_rating == "Salvage Risk"


def test_downgrade_marketability_bottoms_out_at_salvage_risk():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"downgrade_marketability": True},
    )
    result = _result(
        fields={"structural_damage": True},
        rules=[rule],
        current_marketability="Salvage Risk",
    )
    assert result.marketability_rating == "Salvage Risk"


def test_downgrade_marketability_from_none():
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"downgrade_marketability": True},
    )
    result = _result(
        fields={"structural_damage": True},
        rules=[rule],
        current_marketability=None,
    )
    assert result.marketability_rating == "Salvage Risk"


def test_set_marketability_force():
    rule = make_rule(
        condition_field="running_status",
        condition_operator="equals",
        condition_value="Non-Running",
        actions={"set_marketability": "Salvage Risk"},
    )
    result = _result(
        fields={"running_status": "Non-Running"},
        rules=[rule],
        current_marketability="Fast Sell",
    )
    assert result.marketability_rating == "Salvage Risk"


def test_append_review_note_to_empty():
    rule = make_rule(
        condition_field="hours_verified",
        condition_operator="is_false",
        actions={"append_review_note": "Verify hours history before pricing"},
    )
    result = _result(fields={"hours_verified": False}, rules=[rule], current_review_notes=None)
    assert result.review_notes == "Verify hours history before pricing"


def test_append_review_note_extends_existing():
    rule = make_rule(
        condition_field="hours_verified",
        condition_operator="is_false",
        actions={"append_review_note": "Verify hours history before pricing"},
    )
    result = _result(
        fields={"hours_verified": False},
        rules=[rule],
        current_review_notes="Prior note",
    )
    assert result.review_notes == "Prior note\nVerify hours history before pricing"


# --------------------------------------------------------------------------- #
# Multiple rules
# --------------------------------------------------------------------------- #


def test_multiple_rules_accumulate_flags():
    rules = [
        make_rule(
            condition_field="structural_damage",
            condition_operator="is_true",
            actions={"set_management_review_required": True, "downgrade_marketability": True},
        ),
        make_rule(
            condition_field="missing_serial_plate",
            condition_operator="is_true",
            actions={"hold_for_title_review": True},
        ),
        make_rule(
            condition_field="hours_verified",
            condition_operator="is_false",
            actions={"append_review_note": "Verify hours history before pricing"},
        ),
    ]
    fields = {
        "structural_damage": True,
        "missing_serial_plate": True,
        "hours_verified": False,
    }
    result = _result(fields=fields, rules=rules, current_marketability="Fast Sell")

    assert result.management_review_required is True
    assert result.hold_for_title_review is True
    assert result.marketability_rating == "Average"
    assert result.review_notes == "Verify hours history before pricing"
    assert len(result.triggered_rules) == 3


def test_only_matching_rules_trigger():
    rules = [
        make_rule(
            condition_field="structural_damage",
            condition_operator="is_true",
            actions={"set_management_review_required": True},
        ),
        make_rule(
            condition_field="active_major_leak",
            condition_operator="is_true",
            actions={"set_management_review_required": True},
        ),
    ]
    # Only structural_damage is true
    result = _result(fields={"structural_damage": True, "active_major_leak": False}, rules=rules)
    assert result.management_review_required is True
    assert len(result.triggered_rules) == 1


def test_triggered_rules_records_rule_id():
    rule_id = "rule-abc-123"
    rule = make_rule(
        condition_field="structural_damage",
        condition_operator="is_true",
        actions={"set_management_review_required": True},
        rule_id=rule_id,
    )
    result = _result(fields={"structural_damage": True}, rules=[rule])
    assert rule_id in result.triggered_rules
