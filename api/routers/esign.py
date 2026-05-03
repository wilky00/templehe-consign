# ABOUTME: Phase 6 Sprint 3 — eSign endpoints: signing redirect, webhook handler, stub preview.
# ABOUTME: Webhook HMAC-validated; stub endpoints allow end-to-end testing without a real provider.
"""eSign router.

Public endpoints:

- ``GET  /esign/sign/{envelope_id}`` — redirect to the signing URL.
- ``GET  /esign/stub-preview/{envelope_id}`` — stub signing page (HTML).
- ``POST /esign/stub-sign/{envelope_id}`` — trigger a synthetic signed event.
- ``POST /esign/webhook`` — receive provider callbacks (HMAC-validated).
"""

from __future__ import annotations

import hashlib
import hmac
import textwrap
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.base import get_db
from database.models import AuditLog, ConsignmentContract, EquipmentRecord
from services import equipment_status_service
from services.equipment_status_machine import Status
from services.signing_service import get_signing_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/esign", tags=["esign"])

_STUB_PAGE_TEMPLATE = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Consignment Agreement — Temple Heavy Equipment</title>
      <style>
        body {{ font-family: system-ui, sans-serif; max-width: 640px;
                margin: 4rem auto; padding: 0 1rem; }}
        .notice {{ background: #fef9c3; border: 1px solid #fde047;
                   padding: 1rem; border-radius: 6px; margin-bottom: 1.5rem; }}
        button {{ background: #1d4ed8; color: #fff; border: none; padding: .75rem 2rem;
                  font-size: 1rem; border-radius: 6px; cursor: pointer; }}
        button:hover {{ background: #1e40af; }}
      </style>
    </head>
    <body>
      <div class="notice">[Stub] This is where the consignment agreement would be signed.</div>
      <h1>Consignment Agreement</h1>
      <p>Envelope ID: <code>{envelope_id}</code></p>
      <p>Review the agreement and click Sign Now to complete the process.</p>
      <form method="POST" action="/api/v1/esign/stub-sign/{envelope_id}">
        <button type="submit">Sign Now</button>
      </form>
    </body>
    </html>
""")


async def _fetch_contract(db: AsyncSession, envelope_id: str) -> ConsignmentContract:
    result = await db.execute(
        select(ConsignmentContract).where(ConsignmentContract.envelope_id == envelope_id)
    )
    contract = result.scalar_one_or_none()
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Envelope {envelope_id} not found")
    return contract


@router.get("/sign/{envelope_id}", include_in_schema=False)
async def signing_redirect(
    envelope_id: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Redirect to the signing URL for the given envelope."""
    await _fetch_contract(db, envelope_id)
    svc = get_signing_service()
    return_url = f"{settings.base_url}/portal" if hasattr(settings, "base_url") else "/portal"
    signing_url = await svc.get_signing_url(envelope_id, return_url)
    return RedirectResponse(url=signing_url, status_code=302)


@router.get("/stub-preview/{envelope_id}", response_class=HTMLResponse, include_in_schema=False)
async def stub_preview(
    envelope_id: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render the stub signing page."""
    await _fetch_contract(db, envelope_id)
    html = _STUB_PAGE_TEMPLATE.format(envelope_id=envelope_id)
    return HTMLResponse(content=html)


@router.post("/stub-sign/{envelope_id}", include_in_schema=False)
async def stub_sign(
    envelope_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Simulate a signed event for the stub provider.

    Triggers the same logic as a real ``envelope_completed`` webhook so that
    tests and manual QA can walk the full workflow without a real eSign account.
    """
    await _handle_envelope_completed(db, envelope_id=envelope_id)
    return {"status": "signed", "envelope_id": envelope_id}


@router.post("/webhook")
async def esign_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive eSign provider webhooks.

    Validates the HMAC-SHA256 signature from the ``X-ESign-Signature``
    header against ``settings.esign_webhook_secret``. Unknown events are
    silently ignored so new event types don't break production.
    """
    raw_body = await request.body()

    secret = getattr(settings, "esign_webhook_secret", "")
    if secret:
        sig_header = request.headers.get("x-esign-signature", "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig_header):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    import json  # noqa: PLC0415 — deferred to avoid import at module level for tests
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    event = payload.get("event", "")
    envelope_id = payload.get("envelope_id", "")

    logger.info("esign_webhook_received", webhook_event=event, envelope_id=envelope_id)

    if event == "envelope_completed":
        await _handle_envelope_completed(db, envelope_id=envelope_id)
    elif event == "envelope_declined":
        await _handle_envelope_declined(db, envelope_id=envelope_id)
    else:
        logger.info("esign_webhook_unknown_event", webhook_event=event)

    return {"received": True}


async def _handle_envelope_completed(db: AsyncSession, *, envelope_id: str) -> None:
    contract = await _fetch_contract(db, envelope_id)

    # Idempotency — ignore duplicate events.
    if contract.status == "completed":
        logger.info("esign_already_completed", envelope_id=envelope_id)
        return

    contract.status = "completed"
    contract.signed_at = datetime.now(UTC)
    await db.flush()

    record = await db.get(EquipmentRecord, contract.equipment_record_id)
    if record is None:
        logger.error("esign_record_missing", envelope_id=envelope_id)
        return

    await equipment_status_service.record_transition(
        db,
        record=record,
        to_status=Status.ESIGNED_PENDING_PUBLISH.value,
        changed_by=None,
        note="Customer signed consignment agreement.",
    )

    db.add(
        AuditLog(
            event_type="consignment_contract.signed",
            actor_id=None,
            actor_role="system",
            target_type="consignment_contract",
            target_id=contract.id,
            after_state={
                "envelope_id": envelope_id,
                "signed_at": contract.signed_at.isoformat(),
                "equipment_record_id": str(contract.equipment_record_id),
            },
        )
    )
    await db.flush()

    logger.info(
        "esign_envelope_completed",
        envelope_id=envelope_id,
        record_id=str(record.id),
    )


async def _handle_envelope_declined(db: AsyncSession, *, envelope_id: str) -> None:
    contract = await _fetch_contract(db, envelope_id)

    if contract.status == "declined":
        logger.info("esign_already_declined", envelope_id=envelope_id)
        return

    contract.status = "declined"
    await db.flush()

    record = await db.get(EquipmentRecord, contract.equipment_record_id)
    if record is None:
        logger.error("esign_record_missing_on_decline", envelope_id=envelope_id)
        return

    # Revert to approved_pending_esign so the Sales Rep can re-trigger eSign.
    # Guard: if the record is already there (dispatch doesn't advance the status),
    # skip the transition — record_transition 409s on same-state moves.
    if record.status != Status.APPROVED_PENDING_ESIGN.value:
        await equipment_status_service.record_transition(
            db,
            record=record,
            to_status=Status.APPROVED_PENDING_ESIGN.value,
            changed_by=None,
            note="Customer declined consignment agreement — ready to re-send.",
        )

    db.add(
        AuditLog(
            event_type="consignment_contract.declined",
            actor_id=None,
            actor_role="system",
            target_type="consignment_contract",
            target_id=contract.id,
            after_state={"envelope_id": envelope_id},
        )
    )
    await db.flush()

    logger.info(
        "esign_envelope_declined",
        envelope_id=envelope_id,
        record_id=str(record.id),
    )
