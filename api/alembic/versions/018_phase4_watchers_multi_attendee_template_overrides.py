# ABOUTME: Phase 4 Sprint 5 — equipment record watchers + calendar multi-attendee + template overrides.
# ABOUTME: Backfills calendar_event_attendees from existing appraiser_id rows; mirror invariant follows.
"""phase 4 sprint 5 — watchers + multi-attendee + template overrides

Revision ID: 018
Revises: 017
Create Date: 2026-04-26 23:30:00.000000

Three additive tables, all PK on join columns + cascade-on-parent-delete:

1. ``equipment_record_watchers`` (Architectural Debt #9) — secondary
   followers for an equipment record. Notification dispatch widens to
   include watchers; primary owner stays in
   ``equipment_records.assigned_sales_rep_id`` for landing-page logic.

2. ``calendar_event_attendees`` (Architectural Debt #11) — multi-
   attendee calendar events. ``role`` slot lets us mark
   "primary appraiser" vs "co-attendee". Mirrors the multi-role
   pattern from PR #33: ``calendar_events.appraiser_id`` stays as the
   primary attendee for back-compat; the join table is the live
   source for "who's coming." Backfill inserts one row per existing
   event using the current appraiser_id so the mirror invariant
   holds the moment migration completes.

3. ``notification_template_overrides`` (Architectural Debt #1, #16) —
   admin "edit email copy" stores its overrides here. One row per
   template name; missing row → render uses the code default.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | None = "017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1) equipment_record_watchers
    op.create_table(
        "equipment_record_watchers",
        sa.Column(
            "record_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "added_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["record_id"], ["equipment_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("record_id", "user_id"),
    )
    op.create_index(
        "ix_equipment_record_watchers_record_id",
        "equipment_record_watchers",
        ["record_id"],
    )
    op.create_index(
        "ix_equipment_record_watchers_user_id",
        "equipment_record_watchers",
        ["user_id"],
    )

    # 2) calendar_event_attendees + backfill from existing appraiser_id.
    op.create_table(
        "calendar_event_attendees",
        sa.Column(
            "event_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # "primary" for the appraiser_id-mirror row, "attendee" for
        # everyone else added later. Schema doesn't enforce one primary
        # per event — the mirror invariant in code is the source of truth.
        sa.Column("role", sa.String(length=20), nullable=False, server_default="attendee"),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["event_id"], ["calendar_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id", "user_id"),
    )
    op.create_index(
        "ix_calendar_event_attendees_event_id",
        "calendar_event_attendees",
        ["event_id"],
    )
    op.create_index(
        "ix_calendar_event_attendees_user_id",
        "calendar_event_attendees",
        ["user_id"],
    )
    # Backfill: every existing event gets the appraiser_id mirrored
    # into the join table as the "primary" attendee. Idempotent on
    # re-run (PK conflict → no-op).
    op.execute(
        sa.text(
            """
            INSERT INTO calendar_event_attendees (event_id, user_id, role, added_at)
            SELECT id, appraiser_id, 'primary', NOW()
            FROM calendar_events
            ON CONFLICT (event_id, user_id) DO NOTHING
            """
        )
    )

    # 3) notification_template_overrides
    op.create_table(
        "notification_template_overrides",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("subject_md", sa.Text(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "updated_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_notification_template_overrides_name"),
    )
    # Reuse the existing set_updated_at trigger.
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_set_updated_at_notification_template_overrides
                BEFORE UPDATE ON notification_template_overrides
                FOR EACH ROW EXECUTE FUNCTION set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_set_updated_at_notification_template_overrides "
            "ON notification_template_overrides"
        )
    )
    op.drop_table("notification_template_overrides")
    op.drop_index(
        "ix_calendar_event_attendees_user_id",
        table_name="calendar_event_attendees",
    )
    op.drop_index(
        "ix_calendar_event_attendees_event_id",
        table_name="calendar_event_attendees",
    )
    op.drop_table("calendar_event_attendees")
    op.drop_index(
        "ix_equipment_record_watchers_user_id",
        table_name="equipment_record_watchers",
    )
    op.drop_index(
        "ix_equipment_record_watchers_record_id",
        table_name="equipment_record_watchers",
    )
    op.drop_table("equipment_record_watchers")
