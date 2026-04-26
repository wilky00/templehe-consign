# ABOUTME: Phase 4 Sprint 2 — admin-created walk-in customers w/ no user account yet.
# ABOUTME: customers.user_id becomes nullable + new invite_email field; CHECK requires one or the other.
"""phase 4 sprint 2 — walk-in customers + invite_email

Revision ID: 016
Revises: 015
Create Date: 2026-04-26 18:30:00.000000

Phase 4 admin needs to create customer records for people who haven't
registered yet — a sales rep meets a customer at an event, takes their
details on paper, and the admin enters them into the system later. The
customer doesn't have (and may never need) a user account.

Schema changes:

- ``customers.user_id`` becomes NULLABLE. The existing UNIQUE on
  ``user_id`` is replaced with a partial unique index that only applies
  when ``user_id IS NOT NULL`` so multiple walk-in records can coexist
  with NULL.

- ``customers.invite_email`` (String, nullable) — the email address an
  admin types when creating a walk-in. Holds the address the
  registration invite will be sent to when the admin clicks "Send
  Portal Invite". Once an invite is accepted and a User account
  created, ``user_id`` is set and ``invite_email`` can be cleared (or
  retained for audit).

- CHECK ``ck_customers_user_or_invite``: every customer row must have
  either a ``user_id`` (registered) or an ``invite_email`` (walk-in).
  Prevents accidentally inserting a customer with no way to ever reach
  them.

Reversible: downgrade restores the unique constraint, drops the column,
drops the CHECK. Walk-in rows without a user_id would fail the
NOT NULL re-imposition, so the downgrade also asserts there are none
before tightening the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | None = "015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1) Drop the old NOT NULL + UNIQUE on user_id.
    op.alter_column("customers", "user_id", nullable=True)
    # The UNIQUE was created via column-level `unique=True`, which
    # generates a constraint named after Postgres' default policy.
    # Explicitly drop both the constraint and any backing index by name
    # so re-runs against fresh DBs that didn't get the constraint don't
    # error — IF EXISTS makes it idempotent.
    op.execute(sa.text("ALTER TABLE customers DROP CONSTRAINT IF EXISTS customers_user_id_key"))
    op.execute(sa.text("DROP INDEX IF EXISTS customers_user_id_key"))

    # 2) Replace with a partial unique index — only enforced when the
    # user_id is set, so multiple NULL walk-ins coexist freely.
    op.create_index(
        "uq_customers_user_id_when_set",
        "customers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # 3) New nullable column for the walk-in invite address.
    op.add_column(
        "customers",
        sa.Column("invite_email", sa.String(length=255), nullable=True),
    )

    # 4) CHECK: at least one of (user_id, invite_email) must be present.
    op.create_check_constraint(
        "ck_customers_user_or_invite",
        "customers",
        "(user_id IS NOT NULL) OR (invite_email IS NOT NULL)",
    )


def downgrade() -> None:
    # Refuse to downgrade if any walk-in rows exist; restoring NOT NULL
    # would silently fail otherwise.
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM customers WHERE user_id IS NULL) THEN
                    RAISE EXCEPTION
                        'Cannot downgrade 016: walk-in customers (user_id IS NULL) exist. '
                        'Either register them as users or delete them first.';
                END IF;
            END$$
            """
        )
    )

    op.drop_constraint("ck_customers_user_or_invite", "customers", type_="check")
    op.drop_column("customers", "invite_email")
    op.drop_index("uq_customers_user_id_when_set", table_name="customers")
    op.alter_column("customers", "user_id", nullable=False)
    op.create_unique_constraint("customers_user_id_key", "customers", ["user_id"])
