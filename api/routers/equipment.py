# ABOUTME: Customer-facing equipment intake, photo upload, change requests, and timeline views.
# ABOUTME: /me/equipment/batch is reserved for a future bulk importer and 501s today.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import EquipmentRecord, User
from middleware.rbac import require_roles
from schemas.change_request import ChangeRequestCreate, ChangeRequestOut
from schemas.equipment import (
    EquipmentRecordOut,
    IntakePhotoOut,
    IntakeSubmission,
    StatusEventOut,
)
from schemas.photo import FinalizePhotoRequest, UploadUrlRequest, UploadUrlResponse
from services import (
    change_request_service,
    equipment_service,
    photo_upload_service,
)

router = APIRouter(prefix="/me/equipment", tags=["customer"])

_require_customer = require_roles("customer")


def _serialize(record: EquipmentRecord) -> EquipmentRecordOut:
    return EquipmentRecordOut(
        id=record.id,
        reference_number=record.reference_number or "",
        status=record.status,
        category_id=record.category_id,
        make=record.customer_make,
        model=record.customer_model,
        year=record.customer_year,
        serial_number=record.customer_serial_number,
        hours=record.customer_hours,
        running_status=record.customer_running_status,
        ownership_type=record.customer_ownership_type,
        location_text=record.customer_location_text,
        description=record.customer_description,
        submitted_at=record.customer_submitted_at,
        created_at=record.created_at,
        photos=[
            IntakePhotoOut(
                id=p.id,
                storage_key=p.storage_key,
                caption=p.caption,
                display_order=p.display_order,
                uploaded_at=p.uploaded_at,
                scan_status=p.scan_status,
                content_type=p.content_type,
            )
            for p in sorted(record.intake_photos, key=lambda p: p.display_order)
        ],
        status_events=[
            StatusEventOut(
                id=e.id,
                from_status=e.from_status,
                to_status=e.to_status,
                note=e.note,
                created_at=e.created_at,
            )
            for e in sorted(record.status_events, key=lambda e: e.created_at)
        ],
    )


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


@router.post("", response_model=EquipmentRecordOut, status_code=201)
async def submit_intake(
    body: IntakeSubmission,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> EquipmentRecordOut:
    record = await equipment_service.submit_intake(db=db, user=current_user, payload=body)
    return _serialize(record)


@router.post("/batch", status_code=501)
async def submit_intake_batch(
    current_user: User = Depends(_require_customer),
) -> None:
    """Bulk importer placeholder. Not implemented in Phase 2.

    Reserved for the Phase 4/5 power-user flow where sales reps or an
    admin-side importer ingest a list of customer equipment at once.
    Stubbed as 501 so the URL is owned and clients know the shape exists.
    """
    raise HTTPException(
        status_code=501,
        detail="Bulk intake is not implemented yet. POST one item at a time.",
    )


@router.get("", response_model=list[EquipmentRecordOut])
async def list_equipment(
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> list[EquipmentRecordOut]:
    records = await equipment_service.list_records_for_user(db, current_user)
    return [_serialize(r) for r in records]


@router.get("/{record_id}", response_model=EquipmentRecordOut)
async def get_equipment(
    record_id: uuid.UUID,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> EquipmentRecordOut:
    record = await equipment_service.get_record_for_user(db, current_user, record_id)
    return _serialize(record)


# ---------------------------------------------------------------------------
# Photo upload (signed URL + finalize)
# ---------------------------------------------------------------------------


@router.post("/{record_id}/photos/upload-url", response_model=UploadUrlResponse)
async def request_photo_upload_url(
    record_id: uuid.UUID,
    body: UploadUrlRequest,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> UploadUrlResponse:
    # Ownership check — reusing get_record_for_user guarantees 404 on
    # cross-customer access before we issue a presigned URL.
    record = await equipment_service.get_record_for_user(db, current_user, record_id)
    intent = photo_upload_service.generate_upload_intent(
        equipment_record_id=record.id,
        filename=body.filename,
        content_type=body.content_type,
    )
    return UploadUrlResponse(
        upload_url=intent.upload_url,
        storage_key=intent.storage_key,
        expires_in=intent.expires_in,
    )


@router.post("/{record_id}/photos", response_model=IntakePhotoOut, status_code=201)
async def finalize_photo(
    record_id: uuid.UUID,
    body: FinalizePhotoRequest,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> IntakePhotoOut:
    record = await equipment_service.get_record_for_user(db, current_user, record_id)
    photo_upload_service.validate_finalize_inputs(
        storage_key=body.storage_key,
        equipment_record_id=record.id,
        content_type=body.content_type,
        sha256=body.sha256,
    )
    photo = await equipment_service.finalize_intake_photo(
        db=db,
        record=record,
        storage_key=body.storage_key,
        content_type=body.content_type,
        caption=body.caption,
        display_order=body.display_order,
        sha256=body.sha256,
    )
    return IntakePhotoOut(
        id=photo.id,
        storage_key=photo.storage_key,
        caption=photo.caption,
        display_order=photo.display_order,
        uploaded_at=photo.uploaded_at,
        scan_status=photo.scan_status,
        content_type=photo.content_type,
    )


# ---------------------------------------------------------------------------
# Change requests
# ---------------------------------------------------------------------------


@router.post(
    "/{record_id}/change-requests",
    response_model=ChangeRequestOut,
    status_code=201,
)
async def create_change_request(
    record_id: uuid.UUID,
    body: ChangeRequestCreate,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> ChangeRequestOut:
    record = await equipment_service.get_record_for_user(db, current_user, record_id)
    change = await change_request_service.submit_change_request(
        db=db,
        customer_user=current_user,
        record=record,
        request_type=body.request_type,
        customer_notes=body.customer_notes,
    )
    return ChangeRequestOut.model_validate(change)


@router.get(
    "/{record_id}/change-requests",
    response_model=list[ChangeRequestOut],
)
async def list_change_requests(
    record_id: uuid.UUID,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> list[ChangeRequestOut]:
    # Ownership check ensures a customer can't list another customer's changes.
    record = await equipment_service.get_record_for_user(db, current_user, record_id)
    rows = await change_request_service.list_change_requests_for_record(db, record.id)
    return [ChangeRequestOut.model_validate(r) for r in rows]
