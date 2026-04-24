# ABOUTME: Account-level customer endpoints — deletion request/cancel + data export.
# ABOUTME: Uses CurrentUserDep; `pending_deletion` users must reach /delete/cancel.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from middleware.auth import CurrentUserDep
from schemas.account import DataExportOut, DeletionRequestResponse
from services import account_deletion_service, data_export_service

router = APIRouter(prefix="/me/account", tags=["customer"])


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------


@router.post("/delete", response_model=DeletionRequestResponse)
async def request_account_deletion(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> DeletionRequestResponse:
    user = await account_deletion_service.request_deletion(db, current_user)
    return DeletionRequestResponse(
        status=user.status,
        deletion_grace_until=user.deletion_grace_until,
        message=(
            f"Account scheduled for deletion. You can cancel any time before "
            f"{user.deletion_grace_until.date().isoformat()}."
            if user.deletion_grace_until
            else "Account scheduled for deletion."
        ),
    )


@router.post("/delete/cancel", response_model=DeletionRequestResponse)
async def cancel_account_deletion(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> DeletionRequestResponse:
    user = await account_deletion_service.cancel_deletion(db, current_user)
    return DeletionRequestResponse(
        status=user.status,
        deletion_grace_until=user.deletion_grace_until,
        message="Account deletion cancelled.",
    )


# ---------------------------------------------------------------------------
# Data export
# ---------------------------------------------------------------------------


@router.post("/data-export", response_model=DataExportOut, status_code=201)
async def request_data_export(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> DataExportOut:
    job = await data_export_service.request_export(db, current_user)
    return DataExportOut.model_validate(job)


@router.get("/data-exports", response_model=list[DataExportOut])
async def list_data_exports(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> list[DataExportOut]:
    jobs = await data_export_service.list_exports_for_user(db, current_user)
    return [DataExportOut.model_validate(j) for j in jobs]
