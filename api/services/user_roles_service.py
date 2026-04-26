# ABOUTME: Grant/revoke + slug lookups for the user_roles join table.
# ABOUTME: Keeps the primary role (users.role_id) mirrored into the join table.
"""User role grant/revoke service.

Phase 1 / 2 / 3 enforced one role per user via ``users.role_id``. Phase
4 ships an admin UI that grants additional roles; the live source of
truth for ``require_roles()`` checks is now the ``user_roles`` join
table.

Public surface:

- ``role_slugs_for_user(db, user)`` — every role slug the user holds.
  Used by ``middleware.rbac.require_roles`` and the ``CurrentUser``
  schema. Hits the join table; the primary role is included via the
  backfill / mirror invariant.
- ``grant(db, user, role_slug, granted_by)`` — idempotent insert into
  the join table. No-op if the user already has the role.
- ``revoke(db, user, role_slug)`` — idempotent delete from the join
  table. Refuses to revoke the user's *primary* role to keep the
  ``users.role_id`` invariant intact (Phase 4 admin "change primary
  role" is a separate operation that updates ``users.role_id`` and
  the join table together).
- ``set_primary_role(db, user, role_slug, granted_by)`` — flips
  ``users.role_id`` and ensures the join row exists.

Mirror invariant: the role identified by ``users.role_id`` MUST always
have a corresponding ``user_roles`` row. The seeders, the Phase 4
admin grant path, and ``set_primary_role`` all enforce this; the join
table backfill in migration 015 establishes it for existing users.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Role, User, UserRole


async def role_slugs_for_user(db: AsyncSession, *, user: User) -> set[str]:
    """Every role slug the user currently holds. Reads from the join
    table directly so a stale ``user.roles`` relationship doesn't
    silently miss a recent grant."""
    stmt = (
        select(Role.slug)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    result = await db.execute(stmt)
    return {slug for (slug,) in result.all()}


async def _resolve_role_id(db: AsyncSession, slug: str) -> uuid.UUID:
    role_id = (await db.execute(select(Role.id).where(Role.slug == slug))).scalar_one_or_none()
    if role_id is None:
        raise HTTPException(status_code=404, detail=f"Unknown role slug: {slug}")
    return role_id


async def grant(
    db: AsyncSession,
    *,
    user: User,
    role_slug: str,
    granted_by: uuid.UUID | None,
) -> None:
    """Idempotent role grant. ``granted_by`` is the admin's user ID;
    None for migrations / seeders."""
    role_id = await _resolve_role_id(db, role_slug)
    stmt = (
        pg_insert(UserRole)
        .values(user_id=user.id, role_id=role_id, granted_by=granted_by)
        .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
    )
    await db.execute(stmt)
    await db.flush()


async def revoke(db: AsyncSession, *, user: User, role_slug: str) -> None:
    """Idempotent revoke. Refuses to revoke the user's primary role;
    Phase 4 admin "change primary" is ``set_primary_role``, not a
    revoke + grant."""
    role_id = await _resolve_role_id(db, role_slug)
    if role_id == user.role_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot revoke '{role_slug}' — it is the user's primary role. "
                "Change the primary role first."
            ),
        )
    grant_row = (
        await db.execute(
            select(UserRole).where((UserRole.user_id == user.id) & (UserRole.role_id == role_id))
        )
    ).scalar_one_or_none()
    if grant_row is None:
        return
    await db.delete(grant_row)
    await db.flush()


async def set_primary_role(
    db: AsyncSession,
    *,
    user: User,
    role_slug: str,
    granted_by: uuid.UUID | None,
) -> None:
    """Update ``users.role_id`` to the named role and ensure the join
    table mirrors it. Used by Phase 4 admin's "change primary role"
    action and by the registration path."""
    role_id = await _resolve_role_id(db, role_slug)
    user.role_id = role_id
    db.add(user)
    await grant(db, user=user, role_slug=role_slug, granted_by=granted_by)
