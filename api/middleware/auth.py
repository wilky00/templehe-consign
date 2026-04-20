# ABOUTME: JWT authentication dependency — decodes Bearer tokens and provides get_current_user.
# ABOUTME: Inject `current_user: CurrentUserDep` in route handlers to require authentication.
from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.base import get_db
from database.models import Role, User

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the Bearer JWT and return the authenticated User. Raises 401 on any failure."""
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=401,
            detail="Token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Token is invalid.")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
    user = result.scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Account not found or inactive.")

    return user


async def require_roles(*role_slugs: str):
    """
    Factory that returns a FastAPI dependency enforcing role membership.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles("admin"))])
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


# Convenience type alias for route handler signatures
CurrentUserDep = Annotated[User, Depends(get_current_user)]
