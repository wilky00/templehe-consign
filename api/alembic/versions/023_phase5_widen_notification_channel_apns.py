"""phase5: widen notification_jobs.channel CHECK to include 'apns'

Revision ID: 023
Revises: 022
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "023"
down_revision: str = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 4 Sprint 7 widened from ('email','sms') → ('email','sms','slack').
    # Sprint 2 adds 'apns' for iOS push dispatch.
    op.execute(sa.text("ALTER TABLE notification_jobs DROP CONSTRAINT chk_notification_channel"))
    op.execute(
        sa.text(
            "ALTER TABLE notification_jobs ADD CONSTRAINT chk_notification_channel "
            "CHECK (channel IN ('email', 'sms', 'slack', 'apns'))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE notification_jobs DROP CONSTRAINT chk_notification_channel"))
    op.execute(
        sa.text(
            "ALTER TABLE notification_jobs ADD CONSTRAINT chk_notification_channel "
            "CHECK (channel IN ('email', 'sms', 'slack'))"
        )
    )
