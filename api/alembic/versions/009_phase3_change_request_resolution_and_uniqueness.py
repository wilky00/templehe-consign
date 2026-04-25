# ABOUTME: Phase 3 Sprint 1 — change-request resolution tracking + one-pending-per-record uniqueness.
# ABOUTME: Record-locks table is already complete from Phase 1; no columns changed here.
"""phase 3 change request resolution and uniqueness

Revision ID: 009
Revises: 008
Create Date: 2026-04-24 16:00:00.000000

Adds:
- change_requests.resolved_by — FK to users, nullable; set when a sales
  rep or manager resolves or rejects the request via Sprint 2's
  PATCH /api/v1/sales/change-requests/{id}. ``resolved_at`` and
  ``resolution_notes`` already exist from Phase 1 — this only adds the
  actor reference.
- Partial UNIQUE index ``ux_change_requests_one_pending_per_record`` on
  ``change_requests(equipment_record_id)`` WHERE status='pending'. This
  enforces the Phase 2 Feature 2.4.1 rule ("customer cannot submit a
  second change request while one is already pending for the same
  record") at the database boundary, not just the service layer. A second
  INSERT with status='pending' while an existing pending row exists
  raises UniqueViolation which the service maps to 409.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_requests",
        sa.Column(
            "resolved_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ux_change_requests_one_pending_per_record
        ON change_requests (equipment_record_id)
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_change_requests_one_pending_per_record")
    op.drop_column("change_requests", "resolved_by")
