# ABOUTME: Pure-function tests for the status registry + a drift guard
# ABOUTME: against migration 013's CHECK list. No DB needed.
from __future__ import annotations

import re
from pathlib import Path

from services import equipment_status_machine
from services.equipment_status_machine import Status


def test_all_status_values_returns_every_enum_member():
    assert set(equipment_status_machine.all_status_values()) == {s.value for s in Status}


def test_is_known_recognises_registered_statuses():
    for s in Status:
        assert equipment_status_machine.is_known(s.value)


def test_is_known_rejects_garbage():
    assert not equipment_status_machine.is_known("definitely_not_a_status")
    assert not equipment_status_machine.is_known("")


def test_display_name_for_known_status_is_human_readable():
    assert (
        equipment_status_machine.display_name(Status.APPRAISAL_SCHEDULED.value)
        == "An appraisal has been scheduled"
    )


def test_display_name_for_unknown_status_falls_back_to_slug():
    assert equipment_status_machine.display_name("future_status") == "future_status"


def test_notifies_customer_matches_registry_intent():
    # Statuses the customer cares about: scheduled / complete / offer /
    # listed / sold / declined. Internal ticks (new_request,
    # appraiser_assigned, approved_pending_esign, esigned_pending_publish)
    # don't reach the customer.
    assert equipment_status_machine.notifies_customer(Status.APPRAISAL_SCHEDULED.value)
    assert equipment_status_machine.notifies_customer(Status.LISTED.value)
    assert not equipment_status_machine.notifies_customer(Status.NEW_REQUEST.value)
    assert not equipment_status_machine.notifies_customer(Status.APPROVED_PENDING_ESIGN.value)


def test_notifies_sales_rep_matches_phase5_spec_features_321_322():
    assert equipment_status_machine.notifies_sales_rep(Status.APPROVED_PENDING_ESIGN.value)
    assert equipment_status_machine.notifies_sales_rep(Status.ESIGNED_PENDING_PUBLISH.value)
    assert not equipment_status_machine.notifies_sales_rep(Status.NEW_REQUEST.value)
    assert not equipment_status_machine.notifies_sales_rep(Status.LISTED.value)


def test_is_terminal_only_true_for_sold_declined_withdrawn():
    terminals = {Status.SOLD, Status.DECLINED, Status.WITHDRAWN}
    for s in Status:
        assert equipment_status_machine.is_terminal(s.value) is (s in terminals), s


def test_forbidden_transitions_block_obvious_typos():
    assert equipment_status_machine.is_forbidden_transition(
        Status.SOLD.value, Status.NEW_REQUEST.value
    )
    assert equipment_status_machine.is_forbidden_transition(
        Status.DECLINED.value, Status.NEW_REQUEST.value
    )


def test_forbidden_transitions_does_not_block_normal_paths():
    # Common forward transitions stay allowed.
    assert not equipment_status_machine.is_forbidden_transition(
        Status.NEW_REQUEST.value, Status.APPRAISAL_SCHEDULED.value
    )
    assert not equipment_status_machine.is_forbidden_transition(
        Status.ESIGNED_PENDING_PUBLISH.value, Status.LISTED.value
    )


def test_unknown_status_is_not_blocked_by_helpers():
    """Phase 1 chose denylist semantics. Unknown destination statuses
    should pass through the per-helper checks (so a future status added
    to the registry doesn't surprise existing call sites). The DB CHECK
    constraint catches the actual write."""
    assert not equipment_status_machine.notifies_customer("unregistered")
    assert not equipment_status_machine.notifies_sales_rep("unregistered")
    assert not equipment_status_machine.is_terminal("unregistered")


def test_migration_check_list_matches_runtime_registry():
    """Drift guard. The CHECK-constraint migration enumerates the same
    set of statuses the runtime registers — if either is updated without
    the other, this test fails before the change ships."""
    here = Path(__file__).resolve()
    migration_path = (
        here.parent.parent.parent
        / "alembic"
        / "versions"
        / "013_phase4_prework_status_check_constraint.py"
    )
    text = migration_path.read_text()
    block = re.search(r"_VALID_STATUSES:.*?\)\n", text, re.DOTALL)
    assert block is not None, "Could not locate _VALID_STATUSES tuple in migration 013"
    migration_statuses = set(re.findall(r'"([a-z_]+)"', block.group(0)))
    assert migration_statuses == set(equipment_status_machine.all_status_values()), (
        "Migration 013's _VALID_STATUSES drifted from "
        "services/equipment_status_machine.Status. Update one to match the other."
    )
