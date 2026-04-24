# ABOUTME: GDPR-lite data export — gathers customer-owned rows, zips to R2, emails a signed URL.
# ABOUTME: Processed synchronously on POST; data_export_jobs row captures the audit trail.
"""Data export service.

On ``POST /me/account/data-export`` the service:

1. Writes a ``data_export_jobs`` row (status='processing').
2. Gathers every customer-owned entity the user can see in the portal:
   profile, consent history, equipment records (with intake photo
   metadata + status timeline), change requests, notification-job
   audit trail of emails/SMS sent to them.
3. Serializes the collection to JSON, zips it (one file per entity
   kind + a ``manifest.txt``), uploads to R2 at
   ``exports/{user_id}/{export_id}.zip``.
4. Generates a 7-day presigned GET URL and stores it on the job row.
5. Enqueues a NotificationService email with the download link.
6. Marks the job complete and returns the row for the router.

If any step fails the job row is marked failed with the error message;
the router surfaces that to the caller.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import boto3
import structlog
from botocore.client import Config as BotoConfig
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database.models import (
    ChangeRequest,
    Customer,
    CustomerIntakePhoto,
    DataExportJob,
    EquipmentRecord,
    NotificationJob,
    StatusEvent,
    User,
    UserConsentVersion,
)
from services import notification_service

logger = structlog.get_logger(__name__)

_URL_VALID_SECONDS = 7 * 24 * 60 * 60  # 7 days — generous; export is one-shot.


def _r2_client():
    if not (settings.r2_access_key_id and settings.r2_secret_access_key):
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured. Contact support.",
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


async def _gather_user_data(db: AsyncSession, user: User) -> dict:
    """Collect every customer-owned row into a plain dict tree."""
    # User profile + consent + notification audit
    consent_rows = await db.execute(
        select(UserConsentVersion)
        .where(UserConsentVersion.user_id == user.id)
        .order_by(UserConsentVersion.accepted_at)
    )
    notif_rows = await db.execute(
        select(NotificationJob)
        .where(NotificationJob.user_id == user.id)
        .order_by(NotificationJob.created_at)
    )

    # Customer + equipment records + photos + events + change requests
    customer_row = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = customer_row.scalar_one_or_none()

    records_data: list[dict] = []
    change_data: list[dict] = []
    if customer is not None:
        rec_result = await db.execute(
            select(EquipmentRecord)
            .options(
                selectinload(EquipmentRecord.intake_photos),
                selectinload(EquipmentRecord.status_events),
                selectinload(EquipmentRecord.change_requests),
            )
            .where(EquipmentRecord.customer_id == customer.id)
            .order_by(EquipmentRecord.created_at)
        )
        for rec in rec_result.scalars().all():
            records_data.append(_serialize_record(rec))
            for ch in rec.change_requests:
                change_data.append(_serialize_change(ch))

    return {
        "user": _serialize_user(user),
        "customer": _serialize_customer(customer) if customer else None,
        "consent_versions": [_serialize_consent(c) for c in consent_rows.scalars().all()],
        "equipment_records": records_data,
        "change_requests": change_data,
        "notifications_sent": [_serialize_notification(n) for n in notif_rows.scalars().all()],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _serialize_user(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": user.status,
        "totp_enabled": user.totp_enabled,
        "tos_accepted_at": _iso(user.tos_accepted_at),
        "tos_version": user.tos_version,
        "privacy_accepted_at": _iso(user.privacy_accepted_at),
        "privacy_version": user.privacy_version,
        "created_at": _iso(user.created_at),
    }


def _serialize_customer(customer: Customer) -> dict:
    return {
        "id": str(customer.id),
        "business_name": customer.business_name,
        "submitter_name": customer.submitter_name,
        "title": customer.title,
        "address_street": customer.address_street,
        "address_city": customer.address_city,
        "address_state": customer.address_state,
        "address_zip": customer.address_zip,
        "business_phone": customer.business_phone,
        "business_phone_ext": customer.business_phone_ext,
        "cell_phone": customer.cell_phone,
        "communication_prefs": customer.communication_prefs,
        "created_at": _iso(customer.created_at),
    }


def _serialize_consent(row: UserConsentVersion) -> dict:
    return {
        "consent_type": row.consent_type,
        "version": row.version,
        "accepted_at": _iso(row.accepted_at),
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
    }


def _serialize_record(rec: EquipmentRecord) -> dict:
    return {
        "id": str(rec.id),
        "reference_number": rec.reference_number,
        "status": rec.status,
        "category_id": str(rec.category_id) if rec.category_id else None,
        "make": rec.customer_make,
        "model": rec.customer_model,
        "year": rec.customer_year,
        "serial_number": rec.customer_serial_number,
        "hours": rec.customer_hours,
        "running_status": rec.customer_running_status,
        "ownership_type": rec.customer_ownership_type,
        "location_text": rec.customer_location_text,
        "description": rec.customer_description,
        "submitted_at": _iso(rec.customer_submitted_at),
        "created_at": _iso(rec.created_at),
        "photos": [_serialize_photo(p) for p in rec.intake_photos],
        "status_events": [_serialize_status_event(e) for e in rec.status_events],
    }


def _serialize_photo(p: CustomerIntakePhoto) -> dict:
    return {
        "id": str(p.id),
        "storage_key": p.storage_key,
        "caption": p.caption,
        "display_order": p.display_order,
        "scan_status": p.scan_status,
        "content_type": p.content_type,
        "uploaded_at": _iso(p.uploaded_at),
    }


def _serialize_status_event(e: StatusEvent) -> dict:
    return {
        "from_status": e.from_status,
        "to_status": e.to_status,
        "note": e.note,
        "created_at": _iso(e.created_at),
    }


def _serialize_change(ch: ChangeRequest) -> dict:
    return {
        "id": str(ch.id),
        "equipment_record_id": str(ch.equipment_record_id),
        "request_type": ch.request_type,
        "customer_notes": ch.customer_notes,
        "status": ch.status,
        "submitted_at": _iso(ch.submitted_at),
        "resolved_at": _iso(ch.resolved_at),
    }


def _serialize_notification(n: NotificationJob) -> dict:
    # Payload may contain html bodies — include them so the user has the
    # content of every email sent to them, which is the GDPR point.
    return {
        "id": str(n.id),
        "channel": n.channel,
        "template": n.template,
        "status": n.status,
        "scheduled_for": _iso(n.scheduled_for),
        "processed_at": _iso(n.processed_at),
        "payload": n.payload,
    }


def _build_zip(payload: dict) -> bytes:
    """Serialize the payload dict into a zip with per-entity JSON files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.txt", _manifest_text(payload))
        zf.writestr("user.json", json.dumps(payload["user"], indent=2))
        if payload["customer"] is not None:
            zf.writestr("customer.json", json.dumps(payload["customer"], indent=2))
        zf.writestr(
            "consent_versions.json",
            json.dumps(payload["consent_versions"], indent=2),
        )
        zf.writestr(
            "equipment_records.json",
            json.dumps(payload["equipment_records"], indent=2),
        )
        zf.writestr(
            "change_requests.json",
            json.dumps(payload["change_requests"], indent=2),
        )
        zf.writestr(
            "notifications_sent.json",
            json.dumps(payload["notifications_sent"], indent=2),
        )
    return buf.getvalue()


def _manifest_text(payload: dict) -> str:
    return (
        "Temple Heavy Equipment — Data Export\n"
        f"Generated: {payload['generated_at']}\n"
        f"User ID: {payload['user']['id']}\n"
        f"Equipment records: {len(payload['equipment_records'])}\n"
        f"Change requests: {len(payload['change_requests'])}\n"
        f"Consent records: {len(payload['consent_versions'])}\n"
        f"Notifications sent: {len(payload['notifications_sent'])}\n\n"
        "Files:\n"
        "  user.json               — your profile\n"
        "  customer.json           — your customer profile (optional)\n"
        "  consent_versions.json   — every ToS / Privacy acceptance\n"
        "  equipment_records.json  — submissions, photos, and timeline\n"
        "  change_requests.json    — change requests you filed\n"
        "  notifications_sent.json — emails and SMS sent to you\n"
    )


async def _upload_zip(
    *, zip_bytes: bytes, user_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[str, str, datetime]:
    storage_key = f"exports/{user_id}/{job_id}.zip"
    client = _r2_client()
    client.put_object(
        Bucket=settings.r2_bucket_photos,
        Key=storage_key,
        Body=zip_bytes,
        ContentType="application/zip",
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_photos, "Key": storage_key},
        ExpiresIn=_URL_VALID_SECONDS,
        HttpMethod="GET",
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=_URL_VALID_SECONDS)
    return storage_key, url, expires_at


async def request_export(db: AsyncSession, user: User) -> DataExportJob:
    """Create the job row, run the generator, and return the completed job.

    Synchronous — the user gets a fully populated response. Any failure
    is captured on the job row so a follow-up GET can see what happened.
    """
    job = DataExportJob(
        user_id=user.id,
        status="processing",
    )
    db.add(job)
    await db.flush()

    try:
        payload = await _gather_user_data(db, user)
        zip_bytes = _build_zip(payload)
        storage_key, url, expires_at = await _upload_zip(
            zip_bytes=zip_bytes, user_id=user.id, job_id=job.id
        )
    except HTTPException:
        job.status = "failed"
        job.error = "object storage unavailable"
        await db.flush()
        raise
    except Exception as exc:
        logger.exception("data_export_failed", user_id=str(user.id))
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"[:1000]
        await db.flush()
        raise HTTPException(
            status_code=500,
            detail="Data export failed. Please try again or contact support.",
        ) from exc

    job.status = "complete"
    job.storage_key = storage_key
    job.download_url = url
    job.url_expires_at = expires_at
    job.completed_at = datetime.now(UTC)
    await db.flush()

    # Email the link even though we return it inline — the email is the
    # archival record the user can come back to later.
    await notification_service.enqueue(
        db,
        idempotency_key=f"data_export:{job.id}",
        user_id=user.id,
        channel="email",
        template="data_export_ready",
        payload={
            "to_email": user.email,
            "subject": "Your Temple Heavy Equipment data export is ready",
            "html_body": (
                f"<p>Hi {user.first_name},</p>"
                f"<p>Your data export is ready. The download link below is "
                f"valid for 7 days:</p>"
                f'<p><a href="{url}">Download your data</a></p>'
                "<p>If you did not request this export, contact support immediately.</p>"
                "<p>— The Temple Heavy Equipment team</p>"
            ),
            "download_url": url,
        },
    )
    return job


async def list_exports_for_user(
    db: AsyncSession, user: User, *, limit: int = 20
) -> list[DataExportJob]:
    result = await db.execute(
        select(DataExportJob)
        .where(DataExportJob.user_id == user.id)
        .order_by(DataExportJob.requested_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
