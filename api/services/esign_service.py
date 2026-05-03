# ABOUTME: eSign contract dispatch service — creates ConsignmentContract and sends signing envelope.
# ABOUTME: Called by approval_service.approve() after status transitions to approved_pending_esign.
"""eSign contract dispatch service.

Triggered when an equipment record transitions to ``approved_pending_esign``.
Creates the ``consignment_contracts`` row and dispatches a signing envelope
via the active ``SigningService`` implementation (currently stub).

The customer receives an email with a link to the signing flow at
``GET /api/v1/esign/sign/{envelope_id}``.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AppraisalSubmission, ConsignmentContract, Customer, EquipmentRecord, User
from services import notification_service
from services.signing_service import get_signing_service

logger = structlog.get_logger(__name__)

_CONTRACT_STUB_TEXT = (
    "CONSIGNMENT AGREEMENT\n\n"
    "This agreement is entered into between Temple Heavy Equipment and the customer "
    "identified below for the consignment of the described equipment.\n\n"
    "Equipment: {make} {model} ({year})\n"
    "Reference Number: {reference_number}\n"
    "Approved Purchase Offer: ${purchase_offer}\n"
    "Consignment Price: ${consignment_price}\n\n"
    "By signing this agreement the customer authorizes Temple Heavy Equipment to list "
    "and sell the described equipment on their behalf under the terms discussed.\n\n"
    "[Signature block]\n"
)


async def dispatch_contract(
    db: AsyncSession,
    *,
    equipment_record: EquipmentRecord,
) -> ConsignmentContract | None:
    """Create and send a consignment signing envelope for an approved record.

    Idempotent: if a ConsignmentContract already exists for this record
    (status != declined), returns it unchanged.

    Returns None if no approved appraisal submission is found (should not
    happen in normal flow but guards against data races).
    """
    existing = await db.execute(
        select(ConsignmentContract).where(
            ConsignmentContract.equipment_record_id == equipment_record.id
        )
    )
    contract = existing.scalar_one_or_none()
    if contract is not None and contract.status != "declined":
        logger.info(
            "esign_contract_already_exists",
            record_id=str(equipment_record.id),
            envelope_id=contract.envelope_id,
            status=contract.status,
        )
        return contract

    # Resolve the approved submission for pricing data.
    submission_result = await db.execute(
        select(AppraisalSubmission).where(
            AppraisalSubmission.equipment_record_id == equipment_record.id,
            AppraisalSubmission.status == "approved",
        )
    )
    submission = submission_result.scalar_one_or_none()
    if submission is None:
        logger.warning(
            "esign_no_approved_submission",
            record_id=str(equipment_record.id),
        )
        return None

    # Resolve the customer user for email + name.
    customer_result = await db.execute(
        select(Customer).where(Customer.id == equipment_record.customer_id)
    )
    customer = customer_result.scalar_one_or_none()
    if customer is None:
        logger.warning("esign_no_customer", record_id=str(equipment_record.id))
        return None

    user_result = await db.execute(select(User).where(User.id == customer.user_id))
    customer_user = user_result.scalar_one_or_none()
    if customer_user is None:
        logger.warning("esign_no_customer_user", record_id=str(equipment_record.id))
        return None

    document_data = _CONTRACT_STUB_TEXT.format(
        make=submission.make or "",
        model=submission.model or "",
        year=submission.year or "",
        reference_number=equipment_record.reference_number or str(equipment_record.id),
        purchase_offer=submission.approved_purchase_offer or 0,
        consignment_price=submission.suggested_consignment_price or 0,
    )

    svc = get_signing_service()
    envelope_id = await svc.create_envelope(
        record_id=equipment_record.id,
        customer_email=customer_user.email,
        customer_name=f"{customer_user.first_name} {customer_user.last_name}".strip(),
        document_data=document_data,
    )

    if contract is not None:
        # Declined contract — reuse the row, reset envelope.
        contract.envelope_id = envelope_id
        contract.status = "sent"
        contract.signed_at = None
    else:
        contract = ConsignmentContract(
            equipment_record_id=equipment_record.id,
            envelope_id=envelope_id,
            status="sent",
        )
        db.add(contract)

    await db.flush()

    ref = equipment_record.reference_number or str(equipment_record.id)
    make_model = f"{submission.make or ''} {submission.model or ''}".strip()

    await notification_service.enqueue(
        db,
        idempotency_key=f"esign_dispatch:{envelope_id}",
        user_id=customer_user.id,
        channel="email",
        template="customer_esign_ready",
        payload={
            "to_email": customer_user.email,
            "first_name": customer_user.first_name,
            "reference_number": ref,
            "make_model": make_model,
            "envelope_id": envelope_id,
        },
    )

    logger.info(
        "esign_contract_dispatched",
        record_id=str(equipment_record.id),
        envelope_id=envelope_id,
        customer_email=customer_user.email,
    )
    return contract
