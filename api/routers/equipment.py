# ABOUTME: Customer-facing equipment intake + list/detail endpoints.
# ABOUTME: /me/equipment/batch is reserved for a future bulk importer and 501s today.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import EquipmentRecord, User
from middleware.rbac import require_roles
from schemas.equipment import EquipmentRecordOut, IntakePhotoOut, IntakeSubmission
from services import equipment_service

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
            )
            for p in sorted(record.intake_photos, key=lambda p: p.display_order)
        ],
    )


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
