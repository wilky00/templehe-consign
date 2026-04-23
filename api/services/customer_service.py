# ABOUTME: Customer profile + email-preference read/update logic.
# ABOUTME: Called by api/routers/customers.py; never talks to HTTP directly.
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Customer, User
from schemas.customer import CustomerProfileUpdate, EmailPrefs

_DEFAULT_PREFS = EmailPrefs().model_dump()


async def ensure_profile_for_user(db: AsyncSession, user: User) -> Customer:
    """Return the Customer row for a user, creating one on first access.

    The `customers` row is paired 1:1 with a customer-role `users` row, but
    registration intentionally does not create it — only customers that
    actually reach the portal get a profile row. Callers should check the
    user's role before invoking this.
    """
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = result.scalar_one_or_none()
    if customer is not None:
        return customer

    customer = Customer(
        user_id=user.id,
        submitter_name=f"{user.first_name} {user.last_name}".strip(),
        communication_prefs=_DEFAULT_PREFS,
    )
    db.add(customer)
    await db.flush()
    return customer


def _read_prefs(customer: Customer) -> EmailPrefs:
    stored = customer.communication_prefs or {}
    merged = {**_DEFAULT_PREFS, **stored}
    return EmailPrefs(**merged)


async def get_profile(db: AsyncSession, user: User) -> tuple[Customer, EmailPrefs]:
    customer = await ensure_profile_for_user(db, user)
    return customer, _read_prefs(customer)


async def update_profile(
    db: AsyncSession,
    user: User,
    patch: CustomerProfileUpdate,
) -> tuple[Customer, EmailPrefs]:
    customer = await ensure_profile_for_user(db, user)
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        return customer, _read_prefs(customer)

    # submitter_name is NOT NULL on the table — protect against explicit null.
    if "submitter_name" in updates and not updates["submitter_name"]:
        raise HTTPException(status_code=422, detail="submitter_name cannot be empty.")

    for field, value in updates.items():
        setattr(customer, field, value)
    db.add(customer)
    await db.flush()
    return customer, _read_prefs(customer)


async def update_email_prefs(
    db: AsyncSession,
    user: User,
    prefs: EmailPrefs,
) -> EmailPrefs:
    customer = await ensure_profile_for_user(db, user)
    customer.communication_prefs = prefs.model_dump()
    db.add(customer)
    await db.flush()
    return prefs
