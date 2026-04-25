# ABOUTME: Phase 4 pre-work — CHECK constraint enumerating valid equipment_records.status values.
# ABOUTME: Mirrors the runtime registry in services/equipment_status_machine.py; drift caught by a unit test.
"""phase 4 prework — equipment_records.status CHECK constraint

Revision ID: 013
Revises: 012
Create Date: 2026-04-25 21:00:00.000000

The canonical set of equipment record statuses now lives in
``services/equipment_status_machine.py``. This migration installs a
Postgres CHECK constraint enumerating the same set so the database and
the runtime registry can't drift — a write of an unknown status now
fails at the DB layer, not silently downstream.

Additive + reversible. No data backfill needed: every status string in
production is already drawn from the registered set.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# Source of truth lives in api/services/equipment_status_machine.py.
# Duplicated here because alembic migrations can't import application
# code reliably (different Python path at migration time vs. runtime).
# A unit test asserts the two lists stay in sync — drift fails CI
# before it reaches prod.
_VALID_STATUSES: tuple[str, ...] = (
    "new_request",
    "appraiser_assigned",
    "appraisal_scheduled",
    "appraisal_complete",
    "offer_ready",
    "approved_pending_esign",
    "esigned_pending_publish",
    "listed",
    "sold",
    "declined",
    "withdrawn",
)


def upgrade() -> None:
    quoted = ", ".join(f"'{s}'" for s in _VALID_STATUSES)
    op.create_check_constraint(
        "ck_equipment_records_status_valid",
        "equipment_records",
        f"status IN ({quoted})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_equipment_records_status_valid",
        "equipment_records",
        type_="check",
    )
