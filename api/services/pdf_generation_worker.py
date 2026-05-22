# ABOUTME: Phase 7 — orchestrates PDF generation: data assembly → render → R2 upload → DB row.
# ABOUTME: generate_and_store() is triggered via FastAPI BackgroundTasks on appraisal approval.
"""PDF generation worker.

Called from :func:`approval_service.approve` as a best-effort
``asyncio.create_task``—it never rolls back the approval if it fails.

Workflow:
1. Call :func:`report_data_service.build_report_data`.
2. Run :func:`pdf_render_service.render_pdf` in a thread pool
   (WeasyPrint is blocking I/O; running in-process keeps the
   Cloud Run Job pattern from the spec without a real Pub/Sub bus
   in the POC environment).
3. Upload the PDF bytes to Cloudflare R2 under
   ``reports/{record_id}/{submission_id}.pdf``.
4. Insert/update an ``AppraisalReport`` DB row.
5. Write an ``audit_logs`` entry on failure.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from functools import partial

import boto3
import structlog
from botocore.client import Config as BotoConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import AppraisalReport, AuditLog
from services import pdf_render_service, report_data_service
from services.report_data_service import ReportDataIncompleteError

logger = structlog.get_logger(__name__)

_PRESIGNED_EXPIRY = 900  # 15 minutes


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def _build_storage_key(record_id: uuid.UUID, submission_id: uuid.UUID) -> str:
    return f"reports/{record_id}/{submission_id}.pdf"


def _upload_pdf(pdf_bytes: bytes, storage_key: str) -> None:
    """Synchronous upload — called via asyncio.to_thread."""
    client = _r2_client()
    client.put_object(
        Bucket=settings.r2_bucket_reports,
        Key=storage_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )


def generate_download_url(storage_key: str) -> tuple[str, datetime]:
    """Return (presigned_url, expires_at) for an existing report."""
    client = _r2_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_reports, "Key": storage_key},
        ExpiresIn=_PRESIGNED_EXPIRY,
    )
    expires_at = datetime.now(UTC).replace(microsecond=0)
    from datetime import timedelta

    expires_at = expires_at + timedelta(seconds=_PRESIGNED_EXPIRY)
    return url, expires_at


async def generate_and_store(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
) -> AppraisalReport:
    """Build, render, upload, and record the PDF.

    Raises :exc:`ReportDataIncompleteError` if the submission lacks required data.
    Raises :exc:`LookupError` if the submission is not found.
    All other exceptions propagate to the caller (approval_service catches them).
    """
    report_data = await report_data_service.build_report_data(db, submission_id=submission_id)

    pdf_bytes = await asyncio.to_thread(partial(pdf_render_service.render_pdf, report_data))

    storage_key = _build_storage_key(
        report_data.equipment_record_id,
        report_data.submission_id,
    )

    if settings.r2_access_key_id and settings.r2_secret_access_key:
        await asyncio.to_thread(_upload_pdf, pdf_bytes, storage_key)
        logger.info(
            "pdf_uploaded",
            submission_id=str(submission_id),
            storage_key=storage_key,
            size_bytes=len(pdf_bytes),
        )
    else:
        logger.warning("pdf_r2_not_configured_skipping_upload", submission_id=str(submission_id))

    existing_result = await db.execute(
        select(AppraisalReport).where(AppraisalReport.appraisal_submission_id == submission_id)
    )
    report_row = existing_result.scalar_one_or_none()

    if report_row is not None:
        report_row.gcs_path = storage_key
        report_row.generated_at = datetime.now(UTC)
    else:
        report_row = AppraisalReport(
            equipment_record_id=report_data.equipment_record_id,
            appraisal_submission_id=submission_id,
            gcs_path=storage_key,
            generated_at=datetime.now(UTC),
        )
        db.add(report_row)

    await db.flush()

    logger.info(
        "pdf_report_stored",
        submission_id=str(submission_id),
        report_id=str(report_row.id),
    )

    return report_row


async def generate_and_store_best_effort(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Fire-and-forget wrapper for use in approval_service.approve().

    Logs failures to audit_log but never raises — approval must not be
    rolled back because the PDF worker had a transient error.
    """
    try:
        await generate_and_store(db, submission_id=submission_id)
    except ReportDataIncompleteError as exc:
        logger.warning(
            "pdf_generation_incomplete_data",
            submission_id=str(submission_id),
            detail=str(exc),
        )
        db.add(
            AuditLog(
                event_type="pdf_generation.incomplete_data",
                actor_id=actor_id,
                actor_role="system",
                target_type="appraisal_submission",
                target_id=submission_id,
                before_state={},
                after_state={"error": str(exc)},
            )
        )
        await db.flush()
    except Exception:
        logger.exception(
            "pdf_generation_failed",
            submission_id=str(submission_id),
        )
        db.add(
            AuditLog(
                event_type="pdf_generation.failed",
                actor_id=actor_id,
                actor_role="system",
                target_type="appraisal_submission",
                target_id=submission_id,
                before_state={},
                after_state={"error": "unexpected_error"},
            )
        )
        await db.flush()
