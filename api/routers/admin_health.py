# ABOUTME: Phase 4 Sprint 7 — admin health dashboard read endpoints.
# ABOUTME: GET /admin/health returns the persisted snapshot; refresh re-runs the probe.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.admin import HealthSnapshotResponse, HealthStateRow
from services import health_check_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/health", tags=["admin-health"])

_require_admin = require_roles("admin")

_STALE_AFTER = timedelta(seconds=health_check_service._STALE_AFTER_SECONDS)


def _row_to_schema(row) -> HealthStateRow:  # type: ignore[no-untyped-def]
    return HealthStateRow(
        service_name=row.service_name,
        status=row.status,
        last_checked_at=row.last_checked_at,
        last_alerted_at=row.last_alerted_at,
        error_detail=row.error_detail,
        latency_ms=row.latency_ms,
    )


@router.get("", response_model=HealthSnapshotResponse)
async def get_health_snapshot(
    refresh: bool = Query(default=False),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> HealthSnapshotResponse:
    """Return the persisted snapshot.

    Pass ``?refresh=true`` to force a fresh probe (admin's "refresh
    now" button). Without it, the snapshot is served as-is and the
    background poller refreshes it every 30s. If the snapshot is older
    than 30 seconds AND there's no row at all, run a probe so the
    first admin to land on /admin/health doesn't see an empty grid.
    """
    rows = await health_check_service.list_state(db)
    if refresh or not rows:
        rows = await health_check_service.run_all(db)
    elif rows[0].last_checked_at is not None and (
        datetime.now(UTC) - rows[0].last_checked_at > _STALE_AFTER
    ):
        rows = await health_check_service.run_all(db)
    return HealthSnapshotResponse(
        services=[_row_to_schema(r) for r in rows],
        snapshot_at=datetime.now(UTC),
    )
