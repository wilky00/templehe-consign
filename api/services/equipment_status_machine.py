# ABOUTME: Canonical equipment_records.status registry — enum, metadata, transition rules.
# ABOUTME: Single source of truth for every consumer that needs to know the valid statuses.
"""Equipment record state machine.

Phase 1–3 hardcoded the valid status names + their per-status behavior
(customer email visibility, sales-rep notify, display label) across at
least four files (``equipment_status_service``, ``calendar_service``,
``sales_service``, ``equipment_service``). Phase 4 ships an admin UI
that needs to render the canonical state list and per-status
metadata; that's only sound if there's a single source of truth.

This module owns:

- ``Status`` — StrEnum with every legal value of ``equipment_records.status``.
- ``StatusMeta`` — per-status metadata (display label, notify rules,
  customer visibility, terminal flag).
- ``FORBIDDEN_TRANSITIONS`` — explicit denylist of (from, to) edges that
  must always be blocked. Phase 1's pragmatic choice was a denylist (any
  pair not in the list is allowed) so Phase 6 / iOS can introduce new
  workflow paths without a code change here. The registry enumerates the
  list; the policy stays the same.
- Helper functions consumers should use instead of inline string
  comparisons: ``display_name``, ``notifies_customer``,
  ``notifies_sales_rep``, ``is_terminal``, ``is_forbidden_transition``,
  ``all_status_values``.

Adding a new status is a one-place change here; the consumers pick it up
automatically. The Postgres CHECK constraint (migration 013) is also
generated from ``all_status_values`` so the runtime registry and the DB
constraint can't drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    """Every legal value of ``equipment_records.status``.

    Order in this enum is the rough lifecycle order; not load-bearing.
    """

    NEW_REQUEST = "new_request"
    APPRAISER_ASSIGNED = "appraiser_assigned"
    APPRAISAL_SCHEDULED = "appraisal_scheduled"
    APPRAISAL_COMPLETE = "appraisal_complete"
    OFFER_READY = "offer_ready"
    APPROVED_PENDING_ESIGN = "approved_pending_esign"
    ESIGNED_PENDING_PUBLISH = "esigned_pending_publish"
    LISTED = "listed"
    SOLD = "sold"
    DECLINED = "declined"
    # Terminal-via-customer-action: change-request "withdraw" pulls a
    # record out of the pipeline (Phase 2 spec feature 2.4.3).
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class StatusMeta:
    """Per-status metadata. Drives notification routing + admin UI.

    Fields:
        display: Human-readable label used in the customer email subject
            line and (eventually) the admin status picker. Phase 4 admin
            UI reads this to render the dropdown.
        notifies_customer: True → ``record_transition`` enqueues a
            customer-facing status email when this is the destination.
        notifies_sales_rep: True → ``record_transition`` enqueues a
            notification to the assigned sales rep on their preferred
            channel.
        is_terminal: True → no further transitions expected. Informational
            today; Phase 4 admin uses this to grey out the status in
            the change-state UI.
    """

    display: str
    notifies_customer: bool = False
    notifies_sales_rep: bool = False
    is_terminal: bool = False


# Single source of truth. Adding a status = adding a row here.
_REGISTRY: dict[Status, StatusMeta] = {
    Status.NEW_REQUEST: StatusMeta(
        display="New request received",
    ),
    Status.APPRAISER_ASSIGNED: StatusMeta(
        display="An appraiser has been assigned",
    ),
    Status.APPRAISAL_SCHEDULED: StatusMeta(
        display="An appraisal has been scheduled",
        notifies_customer=True,
    ),
    Status.APPRAISAL_COMPLETE: StatusMeta(
        display="Your appraisal is complete",
        notifies_customer=True,
    ),
    Status.OFFER_READY: StatusMeta(
        display="Your offer is ready to review",
        notifies_customer=True,
    ),
    Status.APPROVED_PENDING_ESIGN: StatusMeta(
        display="Approved — ready for eSign",
        notifies_sales_rep=True,
    ),
    Status.ESIGNED_PENDING_PUBLISH: StatusMeta(
        display="Signed — ready to publish",
        notifies_sales_rep=True,
    ),
    Status.LISTED: StatusMeta(
        display="Your equipment is now listed",
        notifies_customer=True,
    ),
    Status.SOLD: StatusMeta(
        display="Your equipment has sold",
        notifies_customer=True,
        is_terminal=True,
    ),
    Status.DECLINED: StatusMeta(
        display="Your submission has been declined",
        notifies_customer=True,
        is_terminal=True,
    ),
    Status.WITHDRAWN: StatusMeta(
        display="Your submission has been withdrawn",
        # No customer email — change_request_service emits its own
        # resolution email that wraps the same context with the
        # request notes.
        notifies_customer=False,
        is_terminal=True,
    ),
}


# Phase 1 chose a denylist policy ("anything not forbidden is allowed")
# so Phase 6 can introduce new workflow paths without code changes here.
# Promoting to an allowlist is safe at any point — start with this set.
FORBIDDEN_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (Status.SOLD.value, Status.NEW_REQUEST.value),
        (Status.DECLINED.value, Status.NEW_REQUEST.value),
        (Status.SOLD.value, Status.LISTED.value),
        (Status.SOLD.value, Status.APPRAISAL_SCHEDULED.value),
    }
)


def all_status_values() -> tuple[str, ...]:
    """Tuple of every legal status value. Used by the migration to
    generate the CHECK constraint and by Phase 4 admin to render the
    status dropdown."""
    return tuple(s.value for s in Status)


def is_known(status: str) -> bool:
    """True if ``status`` is one of the registered statuses. Use at
    integration boundaries (status fields read from external sources,
    not from our own writes)."""
    return status in {s.value for s in Status}


def display_name(status: str) -> str:
    """Human-readable label for ``status``. Falls back to the raw slug
    for unknown statuses so log lines and admin UI never go blank."""
    try:
        return _REGISTRY[Status(status)].display
    except (KeyError, ValueError):
        return status


def notifies_customer(status: str) -> bool:
    """True if a customer-facing email should be enqueued when a record
    transitions INTO ``status``."""
    try:
        return _REGISTRY[Status(status)].notifies_customer
    except (KeyError, ValueError):
        return False


def notifies_sales_rep(status: str) -> bool:
    """True if the assigned sales rep should be notified when a record
    transitions INTO ``status`` (Phase 5 spec features 3.2.1, 3.2.2)."""
    try:
        return _REGISTRY[Status(status)].notifies_sales_rep
    except (KeyError, ValueError):
        return False


def is_terminal(status: str) -> bool:
    """True if no further transitions are expected from ``status``."""
    try:
        return _REGISTRY[Status(status)].is_terminal
    except (KeyError, ValueError):
        return False


def is_forbidden_transition(from_status: str, to_status: str) -> bool:
    """True if the (from, to) edge is explicitly banned. Same denylist
    policy ``equipment_status_service.record_transition`` enforced
    pre-extraction; centralized here so Phase 4 admin can introspect
    the same rules the runtime applies."""
    return (from_status, to_status) in FORBIDDEN_TRANSITIONS
