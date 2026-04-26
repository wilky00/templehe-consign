# ABOUTME: Phase 4 Sprint 4 — UNIQUE(rule_type, priority) on lead_routing_rules + dedup backfill.
# ABOUTME: Drag-to-reorder UX assumes priorities are dense + unique inside each rule_type bucket.
"""phase 4 sprint 4 — routing priority uniqueness

Revision ID: 017
Revises: 016
Create Date: 2026-04-26 22:00:00.000000

Phase 3 Sprint 3 modeled ``lead_routing_rules.priority`` as a free
integer with no uniqueness constraint. The runtime sorts by ascending
priority and picks the first match, so duplicates were tolerable —
ties broke by primary key in practice. Phase 4's drag-to-reorder UI
needs the priorities to be dense + unique per ``rule_type`` so the
admin can swap two rows without ambiguity (and so the optimistic
re-render matches the persisted order on refresh).

Schema changes:

- Backfill: for each ``rule_type`` bucket, find any duplicate priorities
  and renumber the older rows up by 1, 2, ... so the first row keeps
  its priority and the rest get unique values. Deterministic ordering:
  ``(rule_type, priority, created_at)``. Soft-deleted rows are skipped
  (the partial index below also excludes them).
- ``CREATE UNIQUE INDEX uq_lead_routing_rules_type_priority`` on
  ``(rule_type, priority)`` ``WHERE deleted_at IS NULL``. Partial so
  soft-deleted rules don't block re-use of their priority slot.

Reversible: downgrade drops the index. The backfilled priority
renumbering is *not* reverted (no way to recover the original duplicate
state, and there's no semantic reason to want to).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | None = "016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1) Deterministic backfill. For every (rule_type, priority) bucket
    # with > 1 active row, sort the rows by created_at and bump each one
    # past the prior so all priorities become unique. Window over the
    # ROW_NUMBER() means the offset is the per-bucket position.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    rule_type,
                    priority,
                    ROW_NUMBER() OVER (
                        PARTITION BY rule_type, priority
                        ORDER BY created_at, id
                    ) - 1 AS dup_offset
                FROM lead_routing_rules
                WHERE deleted_at IS NULL
            )
            UPDATE lead_routing_rules AS r
            SET priority = r.priority + ranked.dup_offset
            FROM ranked
            WHERE r.id = ranked.id
              AND ranked.dup_offset > 0
            """
        )
    )

    # 2) Enforce uniqueness going forward. Partial index — soft-deleted
    # rows don't conflict, so admin can deactivate then re-create at the
    # same slot.
    op.create_index(
        "uq_lead_routing_rules_type_priority",
        "lead_routing_rules",
        ["rule_type", "priority"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_lead_routing_rules_type_priority",
        table_name="lead_routing_rules",
    )
