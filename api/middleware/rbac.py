# ABOUTME: Role-based access control dependency factory.
# ABOUTME: Use `Depends(require_roles("admin", "sales"))` in route handlers or router dependencies.
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.auth import get_current_user
from services import user_roles_service


def require_roles(*role_slugs: str):
    """
    Return a FastAPI dependency that grants access to any user holding
    at least one of the listed roles. Phase 4 pre-work: a user can hold
    multiple roles (sales rep who also covers appraiser shifts), so
    the check is set intersection — not single-role equality.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles("admin"))])
        async def admin_route(user: User = Depends(require_roles("admin", "sales_manager"))):
            ...
    """

    allowed = frozenset(role_slugs)

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        held = await user_roles_service.role_slugs_for_user(db, user=current_user)
        if not allowed & held:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _check
