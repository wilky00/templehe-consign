# ABOUTME: Phase 5 Sprint 5 — seeds photo_gps_radius_tolerance_meters AppConfig key and
# ABOUTME: ios_required_photos_<slug> keys from existing category_photo_slots rows.
"""Phase 5 Sprint 5 — seed photo AppConfig keys

Revision ID: 027
Revises: 026
Create Date: 2026-05-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        INSERT INTO app_config (key, value)
        VALUES ('photo_gps_radius_tolerance_meters', '{"meters": 5000}')
        ON CONFLICT (key) DO NOTHING
    """)
    )

    # One row per active category: labels = list of required, active slot labels
    # ordered by display_order. Categories with no required slots get [].
    op.execute(
        sa.text("""
        INSERT INTO app_config (key, value)
        SELECT
            'ios_required_photos_' || ec.slug,
            jsonb_build_object(
                'labels',
                COALESCE(
                    jsonb_agg(cps.label ORDER BY cps.display_order)
                        FILTER (WHERE cps.required AND cps.active),
                    '[]'::jsonb
                )
            )
        FROM equipment_categories ec
        LEFT JOIN category_photo_slots cps ON cps.category_id = ec.id
        WHERE ec.status = 'active'
        GROUP BY ec.id, ec.slug
        ON CONFLICT (key) DO NOTHING
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM app_config WHERE key = 'photo_gps_radius_tolerance_meters'"))
    op.execute(sa.text("DELETE FROM app_config WHERE key LIKE 'ios_required_photos_%'"))
