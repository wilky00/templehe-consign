# ABOUTME: Serves ToS / Privacy documents from files and records user acceptances.
# ABOUTME: Current versions live in app_config; text bodies under api/content/<type>/v<N>.md.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, UserConsentVersion
from services import app_config_registry

logger = structlog.get_logger(__name__)

_VALID_TYPES = frozenset({"tos", "privacy"})
_CONTENT_ROOT = Path(__file__).resolve().parent.parent / "content"


def _content_path(doc_type: str, version: str) -> Path:
    # Defense-in-depth: version is also validated by a regex below, so a
    # path-traversal attempt like "../../../etc/passwd" would already fail
    # there before we build the path.
    return _CONTENT_ROOT / doc_type / f"v{version}.md"


def load_document(doc_type: str, version: str) -> str:
    if doc_type not in _VALID_TYPES:
        raise HTTPException(status_code=404, detail="Unknown document type.")
    # Only digits — prevents any path-like version string from being accepted.
    if not version.isdigit():
        raise HTTPException(status_code=404, detail="Invalid version.")
    path = _content_path(doc_type, version)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document version not found.")
    return path.read_text(encoding="utf-8")


async def _read_app_config_version(db: AsyncSession, key: str) -> str:
    """Read a non-empty version string for ``key`` via the AppConfig
    registry. Missing or malformed seeds surface as 500 — legal versions
    are load-bearing for ToS gating and silent defaults would be worse
    than a loud failure."""
    version = await app_config_registry.get_typed(db, key)
    if not version:
        raise HTTPException(
            status_code=500,
            detail=f"Legal configuration missing or malformed ({key}). Contact support.",
        )
    return str(version)


async def get_current_versions(db: AsyncSession) -> tuple[str, str]:
    tos = await _read_app_config_version(db, app_config_registry.TOS_CURRENT_VERSION.name)
    privacy = await _read_app_config_version(db, app_config_registry.PRIVACY_CURRENT_VERSION.name)
    return tos, privacy


async def record_acceptance(
    db: AsyncSession,
    user: User,
    tos_version: str,
    privacy_version: str,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Write to the archive + update the user's current accepted version."""
    now = datetime.now(UTC)
    db.add(
        UserConsentVersion(
            user_id=user.id,
            consent_type="tos",
            version=tos_version,
            accepted_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.add(
        UserConsentVersion(
            user_id=user.id,
            consent_type="privacy",
            version=privacy_version,
            accepted_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    user.tos_version = tos_version
    user.tos_accepted_at = now
    user.privacy_version = privacy_version
    user.privacy_accepted_at = now
    db.add(user)
    await db.flush()


async def accept_current_versions(
    db: AsyncSession,
    user: User,
    submitted_tos: str,
    submitted_privacy: str,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Interstitial re-accept path. Both submitted versions must match the
    server's current versions exactly — a stale client must refresh."""
    current_tos, current_privacy = await get_current_versions(db)
    if submitted_tos != current_tos or submitted_privacy != current_privacy:
        raise HTTPException(
            status_code=409,
            detail="Terms have been updated. Please refresh and review the latest versions.",
        )
    await record_acceptance(
        db=db,
        user=user,
        tos_version=current_tos,
        privacy_version=current_privacy,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def requires_reaccept(user: User, current_tos: str, current_privacy: str) -> bool:
    return user.tos_version != current_tos or user.privacy_version != current_privacy
