"""fix set_updated_at trigger to use clock_timestamp

Revision ID: 002
Revises: 001
Create Date: 2026-04-20 12:18:15.527755

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: str | None = '001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOW() returns transaction start time; clock_timestamp() returns wall clock.
    # Tests that INSERT then UPDATE within one transaction need the wall clock to observe a change.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
