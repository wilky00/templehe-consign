# ABOUTME: All authentication endpoints — registration, login, 2FA, password management.
# ABOUTME: Route handlers are thin; all business logic lives in services/auth_service.py.
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from middleware.auth import CurrentUserDep
from middleware.rate_limit import (
    login_email_limiter,
    login_ip_limiter,
    refresh_ip_limiter,
    register_ip_limiter,
    resend_email_limiter,
    reset_email_limiter,
    reset_ip_limiter,
    totp_ip_limiter,
)
from schemas.auth import (
    ChangeEmailRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    Partial2FAResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestBody,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    TokenResponse,
    TwoFAConfirmRequest,
    TwoFAConfirmResponse,
    TwoFADisableRequest,
    TwoFARecoveryRequest,
    TwoFASetupResponse,
    TwoFAVerifyRequest,
)
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _ip(request: Request) -> str | None:
    # Honour X-Forwarded-For when behind Fly proxy / Cloudflare
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(register_ip_limiter),
) -> RegisterResponse:
    user = await auth_service.register_user(
        email=body.email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        db=db,
        base_url=_base_url(request),
    )
    return RegisterResponse(
        id=user.id,
        email=user.email,
        message="Registration successful. Please check your email to verify your account.",
    )


@router.get("/verify-email", response_model=MessageResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    await auth_service.verify_email(token, db)
    return MessageResponse(message="Email verified. You can now log in.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(resend_email_limiter),
) -> MessageResponse:
    await auth_service.resend_verification(body.email, db, _base_url(request))
    return MessageResponse(
        message="If an unverified account exists for that email, a new link has been sent."
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rl_ip: None = Depends(login_ip_limiter),
    _rl_email: None = Depends(login_email_limiter),
) -> TokenResponse | Partial2FAResponse:
    result = await auth_service.login(
        email=body.email,
        password=body.password,
        db=db,
        ip_address=_ip(request),
        user_agent=request.headers.get("User-Agent"),
        base_url=_base_url(request),
    )
    if result.get("requires_2fa"):
        return Partial2FAResponse(partial_token=result["partial_token"])
    return TokenResponse(access_token=result["access_token"])


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(refresh_ip_limiter),
) -> TokenResponse:
    result = await auth_service.refresh_access_token(
        body.refresh_token, db,
        ip_address=_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    return TokenResponse(access_token=result["access_token"])


@router.post("/logout", response_model=MessageResponse)
async def logout(
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.logout(body.refresh_token, db)
    return MessageResponse(message="Logged out successfully.")


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------


@router.post("/password-reset-request", response_model=MessageResponse)
async def password_reset_request(
    body: PasswordResetRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rl_ip: None = Depends(reset_ip_limiter),
    _rl_email: None = Depends(reset_email_limiter),
) -> MessageResponse:
    await auth_service.request_password_reset(body.email, db, _base_url(request))
    return MessageResponse(
        message="If an account exists for that email, a password reset link has been sent."
    )


@router.post("/password-reset-confirm", response_model=MessageResponse)
async def password_reset_confirm(
    body: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.confirm_password_reset(body.token, body.new_password, db)
    return MessageResponse(message="Password updated. You can now log in with your new password.")


@router.post("/change-email", response_model=MessageResponse)
async def change_email(
    body: ChangeEmailRequest,
    request: Request,
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.initiate_email_change(
        current_user.id, body.new_email, body.current_password, db, _base_url(request)
    )
    return MessageResponse(
        message="A confirmation link has been sent to your new email address."
    )


@router.get("/change-email/confirm", response_model=MessageResponse)
async def change_email_confirm(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.confirm_email_change(token, db)
    return MessageResponse(message="Email address updated successfully.")


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------


@router.post("/2fa/setup", response_model=TwoFASetupResponse)
async def setup_2fa(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> TwoFASetupResponse:
    result = await auth_service.setup_2fa(current_user.id, db)
    return TwoFASetupResponse(
        secret=result["secret"],
        qr_uri=result["qr_uri"],
        message="Scan the QR code with your authenticator app, then confirm with a code.",
    )


@router.post("/2fa/confirm", response_model=TwoFAConfirmResponse)
async def confirm_2fa(
    body: TwoFAConfirmRequest,
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> TwoFAConfirmResponse:
    codes = await auth_service.confirm_2fa(current_user.id, body.totp_code, db)
    return TwoFAConfirmResponse(
        recovery_codes=codes,
        message=(
            "Two-factor authentication enabled. Save these recovery codes"
            " — they will not be shown again."
        ),
    )


@router.post("/2fa/verify", response_model=TokenResponse)
async def verify_2fa(
    body: TwoFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(totp_ip_limiter),
) -> TokenResponse:
    result = await auth_service.verify_2fa(body.partial_token, body.totp_code, db)
    return TokenResponse(access_token=result["access_token"])


@router.post("/2fa/recovery", response_model=TokenResponse)
async def recover_2fa(
    body: TwoFARecoveryRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await auth_service.recover_2fa(body.partial_token, body.recovery_code, db)
    return TokenResponse(access_token=result["access_token"])


@router.post("/2fa/disable", response_model=MessageResponse)
async def disable_2fa(
    body: TwoFADisableRequest,
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.disable_2fa(current_user.id, body.totp_code, db)
    return MessageResponse(message="Two-factor authentication has been disabled.")
