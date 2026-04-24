# ABOUTME: Authenticated customer-profile endpoints (GET/PATCH /me/profile, email prefs).
# ABOUTME: All routes require an active customer-role user; admins use their own surface.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.customer import CustomerProfileRead, CustomerProfileUpdate, EmailPrefs
from services import customer_service

router = APIRouter(prefix="/me", tags=["customer"])

_require_customer = require_roles("customer")


def _serialize(customer, prefs: EmailPrefs) -> CustomerProfileRead:
    return CustomerProfileRead(
        id=customer.id,
        user_id=customer.user_id,
        business_name=customer.business_name,
        submitter_name=customer.submitter_name,
        title=customer.title,
        address_street=customer.address_street,
        address_city=customer.address_city,
        address_state=customer.address_state,
        address_zip=customer.address_zip,
        business_phone=customer.business_phone,
        business_phone_ext=customer.business_phone_ext,
        cell_phone=customer.cell_phone,
        email_prefs=prefs,
    )


@router.get("/profile", response_model=CustomerProfileRead)
async def get_profile(
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> CustomerProfileRead:
    customer, prefs = await customer_service.get_profile(db, current_user)
    return _serialize(customer, prefs)


@router.patch("/profile", response_model=CustomerProfileRead)
async def patch_profile(
    body: CustomerProfileUpdate,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> CustomerProfileRead:
    customer, prefs = await customer_service.update_profile(db, current_user, body)
    return _serialize(customer, prefs)


@router.get("/email-prefs", response_model=EmailPrefs)
async def get_email_prefs(
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> EmailPrefs:
    _, prefs = await customer_service.get_profile(db, current_user)
    return prefs


@router.patch("/email-prefs", response_model=EmailPrefs)
async def patch_email_prefs(
    body: EmailPrefs,
    current_user: User = Depends(_require_customer),
    db: AsyncSession = Depends(get_db),
) -> EmailPrefs:
    return await customer_service.update_email_prefs(db, current_user, body)
