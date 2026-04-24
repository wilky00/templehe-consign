# ABOUTME: Public ToS/Privacy document fetch + authenticated re-accept endpoint.
# ABOUTME: Drives the sign-up consent checkbox and the version-bump interstitial.
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from middleware.auth import CurrentUserDep
from middleware.rate_limit import get_client_ip
from schemas.auth import MessageResponse
from schemas.legal import AcceptTermsRequest, ConsentStatus, LegalDocument
from services import legal_service

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/tos", response_model=LegalDocument)
async def get_tos(db: AsyncSession = Depends(get_db)) -> LegalDocument:
    current_tos, _ = await legal_service.get_current_versions(db)
    return LegalDocument(
        document_type="tos",
        version=current_tos,
        body_markdown=legal_service.load_document("tos", current_tos),
    )


@router.get("/privacy", response_model=LegalDocument)
async def get_privacy(db: AsyncSession = Depends(get_db)) -> LegalDocument:
    _, current_privacy = await legal_service.get_current_versions(db)
    return LegalDocument(
        document_type="privacy",
        version=current_privacy,
        body_markdown=legal_service.load_document("privacy", current_privacy),
    )


@router.get("/consent-status", response_model=ConsentStatus)
async def consent_status(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> ConsentStatus:
    current_tos, current_privacy = await legal_service.get_current_versions(db)
    return ConsentStatus(
        tos_current_version=current_tos,
        privacy_current_version=current_privacy,
        tos_accepted_version=current_user.tos_version,
        privacy_accepted_version=current_user.privacy_version,
        requires_reaccept=legal_service.requires_reaccept(
            current_user, current_tos, current_privacy
        ),
    )


@router.post("/accept", response_model=MessageResponse)
async def accept_terms(
    body: AcceptTermsRequest,
    request: Request,
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await legal_service.accept_current_versions(
        db=db,
        user=current_user,
        submitted_tos=body.tos_version,
        submitted_privacy=body.privacy_version,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Terms acceptance recorded.")
