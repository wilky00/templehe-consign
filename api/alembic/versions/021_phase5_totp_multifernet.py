# ABOUTME: Phase 5 Sprint 0 — TOTP MultiFernet rotation marker (no DDL).
# ABOUTME: Existing totp_secret_enc rows decrypt unchanged with the same key.
"""phase 5 sprint 0 — totp multifernet rotation marker

Revision ID: 021
Revises: 020
Create Date: 2026-04-28 09:00:00.000000

Phase 5 Sprint 0 swaps ``auth_service._fernet()`` from a single
``Fernet`` to a ``MultiFernet`` keyed off a comma-separated
``totp_encryption_keys`` setting (the legacy ``totp_encryption_key`` is
still honored as a fallback so existing dev / test envs don't need a
re-key). The wire format on disk is unchanged — `MultiFernet` produces
tokens that any underlying `Fernet` can read, and existing rows
encrypted under the lone-key path decrypt cleanly with the same key
re-listed in the new variable.

This migration ships only a revision-id bump so the alembic head
advances in step with the code change. No DDL — `users.totp_secret_enc`
is byte-identical before and after.

To rotate later: prepend a new key to ``TOTP_ENCRYPTION_KEYS``, redeploy,
and let users naturally re-encrypt their secrets the next time they
disable + re-enable 2FA. Old keys can be removed once every active row
has been re-encrypted (operational call — not enforced here).
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: the field semantics changed at the application layer; the
    encrypted-bytes column is byte-identical before and after."""


def downgrade() -> None:
    """No-op: nothing to undo on the database side."""
