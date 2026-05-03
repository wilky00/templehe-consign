# ABOUTME: eSign service interface and stub implementation for Phase 6.
# ABOUTME: Real provider (DocuSign, Dropbox Sign) swaps in by implementing SigningService and updating esign_provider AppConfig.
"""Signing service — abstract interface + stub implementation.

The active implementation is selected by the ``esign_provider`` AppConfig key
(currently only "stub" is supported). Phase 7 will add a real provider class.

Usage::

    svc = get_signing_service()
    envelope_id = await svc.create_envelope(...)
    url = await svc.get_signing_url(envelope_id, return_url)
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from enum import StrEnum

import structlog

logger = structlog.get_logger(__name__)


class EnvelopeStatus(StrEnum):
    SENT = "sent"
    COMPLETED = "completed"
    DECLINED = "declined"
    VOIDED = "voided"


class SigningService(ABC):
    @abstractmethod
    async def create_envelope(
        self,
        *,
        record_id: uuid.UUID,
        customer_email: str,
        customer_name: str,
        document_data: str,
    ) -> str:
        """Create a signing envelope and return the envelope_id."""

    @abstractmethod
    async def get_envelope_status(self, envelope_id: str) -> EnvelopeStatus:
        """Return the current status of an envelope."""

    @abstractmethod
    async def void_envelope(self, envelope_id: str, reason: str) -> bool:
        """Void an in-progress envelope. Returns True on success."""

    @abstractmethod
    async def get_signing_url(self, envelope_id: str, return_url: str) -> str:
        """Return an embedded signing URL for the given envelope."""


class StubSigningService(SigningService):
    """Returns deterministic mock data for all operations.

    The stub signing URL points to ``GET /api/v1/esign/stub-preview/{envelope_id}``,
    which renders a simple HTML page. Clicking "Sign Now" on that page calls
    ``POST /api/v1/esign/stub-sign/{envelope_id}``, which fires the webhook
    handler with a synthetic ``envelope_completed`` event.
    """

    async def create_envelope(
        self,
        *,
        record_id: uuid.UUID,
        customer_email: str,
        customer_name: str,
        document_data: str,
    ) -> str:
        envelope_id = f"stub-{uuid.uuid4()}"
        logger.info(
            "stub_signing_service.create_envelope",
            envelope_id=envelope_id,
            record_id=str(record_id),
            customer_email=customer_email,
        )
        return envelope_id

    async def get_envelope_status(self, envelope_id: str) -> EnvelopeStatus:
        return EnvelopeStatus.SENT

    async def void_envelope(self, envelope_id: str, reason: str) -> bool:
        logger.info("stub_signing_service.void_envelope", envelope_id=envelope_id, reason=reason)
        return True

    async def get_signing_url(self, envelope_id: str, return_url: str) -> str:
        return f"/api/v1/esign/stub-preview/{envelope_id}"


def get_signing_service() -> SigningService:
    """Return the active signing service implementation.

    Currently always returns StubSigningService. When a real provider is
    configured via AppConfig('esign_provider'), add a branch here.
    """
    return StubSigningService()
