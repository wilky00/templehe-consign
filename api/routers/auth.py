# ABOUTME: All authentication endpoints — registration, login, 2FA, password management.
# ABOUTME: Route handlers are thin; all business logic lives in services/auth_service.py.
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.base import get_db
from middleware.auth import CurrentUserDep
from middleware.rate_limit import (
    get_client_ip,
    login_email_limiter,
    login_ip_limiter,
    recovery_ip_limiter,
    recovery_partial_token_limiter,
    refresh_ip_limiter,
    register_ip_limiter,
    resend_email_limiter,
    reset_email_limiter,
    reset_ip_limiter,
    totp_ip_limiter,
    totp_partial_token_limiter,
)
from schemas.auth import (
    ChangeEmailRequest,
    CurrentUser,
    LoginRequest,
    MessageResponse,
    MobileLogoutRequest,
    MobileRefreshRequest,
    Partial2FAResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestBody,
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

# Cookie scoped to /api/v1/auth so it is only transmitted on auth endpoints.
_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"

# Phase 5 Sprint 1 — opt-in to body-mode refresh-token transport for
# native iOS clients that can't reliably persist HttpOnly cookies and
# want to store the refresh token in the iOS Keychain instead. The
# header is examined on every token-issuing endpoint; when present,
# the response body carries the refresh token and no Set-Cookie is
# emitted. The web SPA never sets this header → its existing flow
# (cookie + body access_token only) is byte-compatible.
_X_CLIENT_HEADER = "X-Client"
_X_CLIENT_MOBILE_VALUES = frozenset({"ios", "android"})


def _is_mobile_client(request: Request) -> bool:
    return request.headers.get(_X_CLIENT_HEADER, "").lower() in _X_CLIENT_MOBILE_VALUES


def _build_token_response(
    *,
    access_token: str,
    refresh_token: str,
    response: Response,
    is_mobile: bool,
) -> TokenResponse:
    """Branch on transport: web → set HttpOnly cookie + return body
    without ``refresh_token``. Mobile → no cookie + return body with
    ``refresh_token``. Single helper so all four token-issuing endpoints
    stay consistent."""
    if is_mobile:
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path=_REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_expire_days * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(register_ip_limiter),
) -> RegisterResponse:
    user = await auth_service.register_user(
        email=body.email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        tos_version=body.tos_version,
        privacy_version=body.privacy_version,
        db=db,
        base_url=_base_url(request),
        background_tasks=background_tasks,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(resend_email_limiter),
) -> MessageResponse:
    await auth_service.resend_verification(
        body.email, db, _base_url(request), background_tasks=background_tasks
    )
    return MessageResponse(
        message="If an unverified account exists for that email, a new link has been sent."
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/me", response_model=CurrentUser)
async def me(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Return the authenticated user's profile. Phase 2 bootstraps on this."""
    from sqlalchemy import select

    from database.models import Role
    from services import legal_service, user_roles_service

    role_result = await db.execute(select(Role).where(Role.id == current_user.role_id))
    role = role_result.scalar_one_or_none()
    current_tos, current_privacy = await legal_service.get_current_versions(db)
    held_roles = await user_roles_service.role_slugs_for_user(db, user=current_user)
    return CurrentUser(
        id=current_user.id,
        email=current_user.email,
        role=role.slug if role else "customer",
        roles=sorted(held_roles),
        status=current_user.status,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        totp_enabled=current_user.totp_enabled,
        requires_terms_reaccept=legal_service.requires_reaccept(
            current_user, current_tos, current_privacy
        ),
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _rl_ip: None = Depends(login_ip_limiter),
    _rl_email: None = Depends(login_email_limiter),
) -> TokenResponse | Partial2FAResponse:
    result = await auth_service.login(
        email=body.email,
        password=body.password,
        db=db,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        base_url=_base_url(request),
        background_tasks=background_tasks,
    )
    if result.get("requires_2fa"):
        return Partial2FAResponse(partial_token=result["partial_token"])
    return _build_token_response(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        response=response,
        is_mobile=_is_mobile_client(request),
    )


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    body: MobileRefreshRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(refresh_ip_limiter),
) -> TokenResponse:
    """Mobile (X-Client header set) reads the refresh token from the
    body; web reads from the HttpOnly cookie. Either way the response
    rotates the token — mobile in the body, web in a fresh Set-Cookie."""
    is_mobile = _is_mobile_client(request)
    if is_mobile:
        if body is None or not body.refresh_token:
            raise HTTPException(
                status_code=401,
                detail="Refresh token is required in the request body for mobile clients.",
            )
        raw_token = body.refresh_token
    else:
        raw_token = request.cookies.get(_REFRESH_COOKIE_NAME) or ""
    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh token is required.")
    result = await auth_service.refresh_access_token(
        raw_token,
        db,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    return _build_token_response(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        response=response,
        is_mobile=is_mobile,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    current_user: CurrentUserDep,
    body: MobileLogoutRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Mobile (X-Client header set) sends the refresh token to revoke
    in the body; web reads it from the cookie. Both paths revoke the
    token if found, but neither requires it — the access token alone
    is sufficient to consider the user logged out client-side."""
    is_mobile = _is_mobile_client(request)
    raw_token: str | None = None
    if is_mobile:
        raw_token = body.refresh_token if body else None
    else:
        raw_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if raw_token:
        await auth_service.logout(raw_token, db)
    if not is_mobile:
        _clear_refresh_cookie(response)
    return MessageResponse(message="Logged out successfully.")


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------


@router.post("/password-reset-request", response_model=MessageResponse)
async def password_reset_request(
    body: PasswordResetRequestBody,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _rl_ip: None = Depends(reset_ip_limiter),
    _rl_email: None = Depends(reset_email_limiter),
) -> MessageResponse:
    await auth_service.request_password_reset(
        body.email, db, _base_url(request), background_tasks=background_tasks
    )
    return MessageResponse(
        message="If an account exists for that email, a password reset link has been sent."
    )


@router.post("/password-reset-confirm", response_model=MessageResponse)
async def password_reset_confirm(
    body: PasswordResetConfirmRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.confirm_password_reset(
        body.token, body.new_password, db, background_tasks=background_tasks
    )
    return MessageResponse(message="Password updated. You can now log in with your new password.")


@router.post("/change-email", response_model=MessageResponse)
async def change_email(
    body: ChangeEmailRequest,
    request: Request,
    current_user: CurrentUserDep,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.initiate_email_change(
        current_user.id,
        body.new_email,
        body.current_password,
        db,
        _base_url(request),
        background_tasks=background_tasks,
    )
    return MessageResponse(message="A confirmation link has been sent to your new email address.")


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
    codes = await auth_service.confirm_2fa(current_user.id, body.totp_code, body.password, db)
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
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _rl_ip: None = Depends(totp_ip_limiter),
    _rl_token: None = Depends(totp_partial_token_limiter),
) -> TokenResponse:
    result = await auth_service.verify_2fa(body.partial_token, body.totp_code, db)
    return _build_token_response(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        response=response,
        is_mobile=_is_mobile_client(request),
    )


@router.post("/2fa/recovery", response_model=TokenResponse)
async def recover_2fa(
    body: TwoFARecoveryRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _rl_ip: None = Depends(recovery_ip_limiter),
    _rl_token: None = Depends(recovery_partial_token_limiter),
) -> TokenResponse:
    result = await auth_service.recover_2fa(
        body.partial_token, body.recovery_code, db, background_tasks=background_tasks
    )
    return _build_token_response(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        response=response,
        is_mobile=_is_mobile_client(request),
    )


@router.post("/2fa/disable", response_model=MessageResponse)
async def disable_2fa(
    body: TwoFADisableRequest,
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.disable_2fa(current_user.id, body.totp_code, body.password, db)
    return MessageResponse(message="Two-factor authentication has been disabled.")
