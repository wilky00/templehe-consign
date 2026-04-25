# ABOUTME: Phase 3 Sprint 4 — drive_time_cache + geocode_cache tables (Postgres POC stand-in for Redis SETEX).
# ABOUTME: Both keyed by SHA-256 hash, 6h TTL swept by fn_sweep_retention(); seeds drive_time_fallback_minutes.
"""phase 3 drive time + geocode caches

Revision ID: 011
Revises: 010
Create Date: 2026-04-25 14:00:00.000000

Adds:
- drive_time_cache(origin_hash, dest_hash, duration_seconds, fetched_at, expires_at)
  Composite PK (origin_hash, dest_hash). 6h TTL — Redis-swap target is `SETEX 21600`.
- geocode_cache(address_hash, lat, lon, fetched_at, expires_at)
  PK (address_hash). 30d TTL — addresses rarely move; longer cache reduces API calls.
- AppConfig key `drive_time_fallback_minutes` seeded to 60 — used when the Distance
  Matrix call fails or no API key is configured.

Both caches are read-through: services check the cache first, hit the API only on
miss, then write the result back. The retention sweeper drops expired rows hourly.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE drive_time_cache (
                origin_hash       VARCHAR(64) NOT NULL,
                dest_hash         VARCHAR(64) NOT NULL,
                duration_seconds  INTEGER NOT NULL,
                fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at        TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (origin_hash, dest_hash)
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_drive_time_cache_expires ON drive_time_cache(expires_at)"))

    op.execute(
        sa.text(
            """
            CREATE TABLE geocode_cache (
                address_hash  VARCHAR(64) PRIMARY KEY,
                lat           DOUBLE PRECISION NOT NULL,
                lon           DOUBLE PRECISION NOT NULL,
                fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at    TIMESTAMPTZ NOT NULL
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_geocode_cache_expires ON geocode_cache(expires_at)"))

    # Seed the drive-time fallback. Idempotent — safe on re-runs.
    op.execute(
        sa.text(
            """
            INSERT INTO app_config (key, value, category, field_type)
            VALUES (
                'drive_time_fallback_minutes',
                '{"minutes": 60}'::jsonb,
                'scheduling',
                'integer'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_config WHERE key = 'drive_time_fallback_minutes'")
    op.execute("DROP INDEX IF EXISTS ix_geocode_cache_expires")
    op.execute("DROP TABLE IF EXISTS geocode_cache")
    op.execute("DROP INDEX IF EXISTS ix_drive_time_cache_expires")
    op.execute("DROP TABLE IF EXISTS drive_time_cache")
