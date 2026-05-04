# ABOUTME: Phase 6 Sprint 3 — adds proposed_consignment_price to change_requests.
# ABOUTME: Enables PriceChangeService to evaluate re-approval threshold against the approved price.
"""Phase 6 Sprint 3 — proposed_consignment_price on change_requests

Revision ID: 030
Revises: 029
Create Date: 2026-05-03 00:00:00.000000

Adds one nullable column to change_requests:
  - proposed_consignment_price DECIMAL(12,2): the customer's counter-offer price;
    NULL for request types that don't carry a price (withdraw, edit_details, etc.)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE change_requests
            ADD COLUMN proposed_consignment_price DECIMAL(12,2)
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE change_requests
            DROP COLUMN IF EXISTS proposed_consignment_price
    """)
    )
