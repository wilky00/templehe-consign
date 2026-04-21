# ABOUTME: Role-based access control dependency factory.
# ABOUTME: Use `Depends(require_roles("admin", "sales"))` in route handlers or router dependencies.
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import Role, User
from middleware.auth import get_current_user


def require_roles(*role_slugs: str):
    """
    Return a FastAPI dependency that enforces role membership.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles("admin"))])
        async def admin_route(user: User = Depends(require_roles("admin", "sales_manager"))):
            ...
    """

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        role_result = await db.execute(select(Role).where(Role.id == current_user.role_id))
        role = role_result.scalar_one_or_none()
        if role is None or role.slug not in role_slugs:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _check
