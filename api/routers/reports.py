# ABOUTME: Phase 7 — PDF report download endpoint for equipment records.
# ABOUTME: Returns a signed R2 URL (15-min expiry) or 202 if the report is still generating.
"""PDF report download router.

``GET /api/v1/equipment-records/{id}/report/pdf``

- Customer: may only fetch their own record's report.
- Sales, Manager, Admin: may fetch any record's report.
- If the report exists → 200 + signed URL.
- If the report is generating → 202 + status message.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.base import get_db
from database.models import AppraisalReport, Customer, EquipmentRecord, User
from middleware.rbac import require_roles
from schemas.report import ReportDownloadResponse, ReportGeneratingResponse
from services import pdf_generation_worker

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/equipment-records", tags=["reports"])

_require_any = require_roles("customer", "sales", "sales_manager", "admin", "appraiser")


@router.get(
    "/{record_id}/report/pdf",
    status_code=200,
)
async def get_report_download(
    record_id: uuid.UUID,
    current_user: User = Depends(_require_any),
    db: AsyncSession = Depends(get_db),
):
    """Return a signed download URL for the appraisal PDF report.

    Returns 202 with a status payload if the report is still generating.
    Returns 404 if the record does not exist or the user cannot access it.
    """
    record = await db.get(EquipmentRecord, record_id)
    if record is None or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Equipment record not found")

    # Ownership check: customers can only access their own records
    from services import user_roles_service

    roles = await user_roles_service.role_slugs_for_user(db, user=current_user)
    non_staff = "admin" not in roles and "sales" not in roles and "sales_manager" not in roles
    if "customer" in roles and non_staff:
        customer_result = await db.execute(
            select(Customer).where(Customer.user_id == current_user.id)
        )
        customer_profile = customer_result.scalar_one_or_none()
        if customer_profile is None or record.customer_id != customer_profile.id:
            raise HTTPException(status_code=403, detail="Access denied")

    report_result = await db.execute(
        select(AppraisalReport).where(AppraisalReport.equipment_record_id == record_id)
    )
    report = report_result.scalar_one_or_none()

    if report is None:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=202,
            content=ReportGeneratingResponse().model_dump(),
        )

    if not (settings.r2_access_key_id and settings.r2_secret_access_key):
        raise HTTPException(
            status_code=503,
            detail="Report storage is not configured. Contact support.",
        )

    try:
        download_url, expires_at = pdf_generation_worker.generate_download_url(report.gcs_path)
    except Exception as exc:
        logger.exception("report_presign_failed", record_id=str(record_id))
        raise HTTPException(
            status_code=503,
            detail="Could not generate download link. Try again shortly.",
        ) from exc

    return ReportDownloadResponse(download_url=download_url, expires_at=expires_at)
