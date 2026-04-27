# ABOUTME: Phase 4 Sprint 7 — admin endpoints for the integration credentials vault.
# ABOUTME: GET list, PUT store, POST reveal (step-up), POST test. All admin-only.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.admin import (
    IntegrationListResponse,
    IntegrationOut,
    IntegrationRevealRequest,
    IntegrationRevealResponse,
    IntegrationStoreRequest,
    IntegrationTestRequest,
    IntegrationTestResponse,
)
from services import admin_credentials_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/integrations", tags=["admin-integrations"])

_require_admin = require_roles("admin")


def _to_out(meta: admin_credentials_service.IntegrationMetadata) -> IntegrationOut:
    return IntegrationOut(
        name=meta.name,
        is_set=meta.is_set,
        set_by=meta.set_by,
        set_at=meta.set_at,
        last_tested_at=meta.last_tested_at,
        last_test_status=meta.last_test_status,  # type: ignore[arg-type]
        last_test_detail=meta.last_test_detail,
        last_test_latency_ms=meta.last_test_latency_ms,
    )


@router.get("", response_model=IntegrationListResponse)
async def list_integrations(
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> IntegrationListResponse:
    metas = await admin_credentials_service.list_metadata(db)
    return IntegrationListResponse(integrations=[_to_out(m) for m in metas])


@router.put("/{name}", response_model=IntegrationOut)
async def store_integration(
    name: str,
    payload: IntegrationStoreRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> IntegrationOut:
    try:
        meta = await admin_credentials_service.store(
            db, name=name, plaintext=payload.plaintext, actor=admin
        )
    except admin_credentials_service.UnknownIntegration:
        raise HTTPException(status_code=404, detail=f"unknown integration: {name}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(meta)


@router.post("/{name}/reveal", response_model=IntegrationRevealResponse)
async def reveal_integration(
    name: str,
    payload: IntegrationRevealRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRevealResponse:
    try:
        result = await admin_credentials_service.reveal(
            db,
            name=name,
            actor=admin,
            password=payload.password,
            totp_code=payload.totp_code,
        )
    except admin_credentials_service.StepUpRateLimited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="reveal rate limit exceeded — try again in an hour",
        ) from None
    except admin_credentials_service.StepUpFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except admin_credentials_service.CredentialNotFound:
        raise HTTPException(status_code=404, detail=f"credential not set: {name}") from None
    except admin_credentials_service.UnknownIntegration:
        raise HTTPException(status_code=404, detail=f"unknown integration: {name}") from None
    return IntegrationRevealResponse(
        name=result.name,
        plaintext=result.plaintext,
        revealed_at=result.revealed_at,
    )


@router.post("/{name}/test", response_model=IntegrationTestResponse)
async def test_integration(
    name: str,
    payload: IntegrationTestRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> IntegrationTestResponse:
    try:
        result = await admin_credentials_service.test_credential(
            db,
            name=name,
            actor=admin,
            extra_args=payload.extra_args,
        )
    except admin_credentials_service.UnknownIntegration:
        raise HTTPException(status_code=404, detail=f"unknown integration: {name}") from None
    except admin_credentials_service.CredentialNotFound:
        raise HTTPException(status_code=404, detail=f"credential not set: {name}") from None
    return IntegrationTestResponse(
        name=name,
        success=result.success,
        status=result.status,  # type: ignore[arg-type]
        detail=result.detail,
        latency_ms=result.latency_ms,
    )
