# ABOUTME: Email delivery service — SendGrid in production, local SMTP (Mailpit) in development.
# ABOUTME: Send failures are logged and swallowed so callers can schedule via BackgroundTasks.
from __future__ import annotations

import asyncio
import functools
import html
import smtplib
from collections.abc import Awaitable, Callable
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from config import settings

logger = structlog.get_logger(__name__)


def _safe_send(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Wrap an email-send helper so any exception is logged and swallowed.

    These helpers are dispatched through FastAPI BackgroundTasks (fire and
    forget). An uncaught exception there kills the task silently and can
    surface as a 500 on the originating request, which we never want — the
    point of BackgroundTasks is that email is best-effort.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            await func(*args, **kwargs)
        except Exception:
            logger.exception(f"{func.__name__}_failed")

    return wrapper


async def send_email(to_email: str, subject: str, html_body: str) -> None:
    """Send an email. Routes to SMTP (Mailpit) in dev, SendGrid in production.

    Failures are logged but never re-raised — auth flows scheduling this via
    BackgroundTasks must not 500 the originating request when SendGrid hiccups.
    """
    if settings.use_smtp_local:
        await asyncio.to_thread(_send_smtp, to_email, subject, html_body)
    else:
        await asyncio.to_thread(_send_sendgrid, to_email, subject, html_body)


def _send_smtp(to_email: str, subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.sendgrid_from_name} <{settings.sendgrid_from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    # local_hostname is passed explicitly so smtplib doesn't call
    # socket.getfqdn(), which hangs ~35s on macOS when mDNS goes looking for
    # a .local FQDN the network doesn't answer for. timeout=10 bounds any
    # other slowness (e.g. if Mailpit is slow to greet).
    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            local_hostname="localhost",
            timeout=10,
        ) as server:
            server.sendmail(settings.sendgrid_from_email, to_email, msg.as_string())
    except Exception:
        logger.exception("smtp_send_failed", to=to_email, subject=subject)


def _send_sendgrid(to_email: str, subject: str, html_body: str) -> None:
    import sendgrid as sg_module
    from sendgrid.helpers.mail import Mail

    client = sg_module.SendGridAPIClient(api_key=settings.sendgrid_api_key)
    message = Mail(
        from_email=(settings.sendgrid_from_email, settings.sendgrid_from_name),
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )
    try:
        client.send(message)
    except Exception:
        logger.exception("sendgrid_send_failed", to=to_email, subject=subject)


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------


def _base_html(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#1a1a1a;">{title}</h2>
  {body_html}
  <hr style="margin-top:32px;border:none;border-top:1px solid #eee;">
  <p style="font-size:12px;color:#666;">
    Temple Heavy Equipment &mdash; <a href="mailto:support@saltrun.net">support@saltrun.net</a>
  </p>
</body>
</html>"""


@_safe_send
async def send_verification_email(to_email: str, verify_url: str) -> None:
    body = f"""
    <p>Thanks for registering with Temple Heavy Equipment.</p>
    <p>Please verify your email address by clicking the link below.
       This link expires in 24 hours.</p>
    <p><a href="{verify_url}" style="background:#1a1a1a;color:#fff;padding:12px 24px;
       text-decoration:none;border-radius:4px;display:inline-block;">Verify Email</a></p>
    <p>If you did not create an account, you can ignore this email.</p>
    """
    await send_email(
        to_email, "Verify your TempleHE account", _base_html("Verify your email", body)
    )


@_safe_send
async def send_password_reset_email(to_email: str, reset_url: str) -> None:
    body = f"""
    <p>We received a request to reset the password for your TempleHE account.</p>
    <p>Click the link below to choose a new password. This link expires in 30 minutes.</p>
    <p><a href="{reset_url}" style="background:#1a1a1a;color:#fff;padding:12px 24px;
       text-decoration:none;border-radius:4px;display:inline-block;">Reset Password</a></p>
    <p>If you didn't request a password reset, you can ignore this email.
       Your password has not changed.</p>
    """
    await send_email(
        to_email, "Reset your TempleHE password", _base_html("Reset your password", body)
    )


@_safe_send
async def send_password_changed_email(to_email: str) -> None:
    body = """
    <p>Your TempleHE account password was just changed.</p>
    <p>If this was you, no further action is needed.</p>
    <p>If this wasn't you, <a href="mailto:support@saltrun.net">contact support immediately</a>
       or reset your password using the login page.</p>
    """
    await send_email(
        to_email, "Your TempleHE password was changed", _base_html("Password changed", body)
    )


@_safe_send
async def send_new_device_email(to_email: str, location: str, device: str) -> None:
    # location (IP) and device (user-agent) are user-controlled — escape before HTML.
    safe_location = html.escape(location)
    safe_device = html.escape(device)
    body = f"""
    <p>We detected a new sign-in to your TempleHE account.</p>
    <ul>
      <li><strong>Location:</strong> {safe_location}</li>
      <li><strong>Device:</strong> {safe_device}</li>
    </ul>
    <p>If this was you, no action is needed.</p>
    <p>If this wasn't you,
       <a href="mailto:support@saltrun.net">reset your password immediately</a>.</p>
    """
    await send_email(
        to_email,
        "New sign-in to your TempleHE account",
        _base_html("New sign-in detected", body),
    )


@_safe_send
async def send_email_change_verification(new_email: str, verify_url: str) -> None:
    body = f"""
    <p>A request was made to change your TempleHE account email to this address.</p>
    <p>Click the link below to confirm the change. This link expires in 1 hour.</p>
    <p><a href="{verify_url}" style="background:#1a1a1a;color:#fff;padding:12px 24px;
       text-decoration:none;border-radius:4px;display:inline-block;">Confirm new email</a></p>
    <p>If you didn't request this change, you can ignore this email.</p>
    """
    await send_email(
        new_email,
        "Confirm your new TempleHE email address",
        _base_html("Confirm email change", body),
    )


@_safe_send
async def send_email_change_notification(old_email: str, new_email: str) -> None:
    # new_email is user-submitted; the masked variant is derived from it.
    masked = html.escape(new_email[:3] + "***@" + new_email.split("@")[-1])
    body = f"""
    <p>Your TempleHE account email is being changed to <strong>{masked}</strong>.</p>
    <p>The change will take effect once the new address is confirmed.</p>
    <p>If you didn't request this change,
       <a href="mailto:support@saltrun.net">contact support immediately</a>.</p>
    """
    await send_email(
        old_email,
        "Your TempleHE email address is being changed",
        _base_html("Email change requested", body),
    )


@_safe_send
async def send_2fa_warning_email(to_email: str, remaining: int) -> None:
    body = f"""
    <p>You have only <strong>{remaining}</strong> two-factor authentication
       recovery code(s) remaining.</p>
    <p>Log in to your account and generate new recovery codes before you run out.</p>
    """
    await send_email(
        to_email,
        "Low on 2FA recovery codes — action needed",
        _base_html("2FA recovery codes running low", body),
    )


@_safe_send
async def send_walkin_invite_email(
    to_email: str, register_url: str, customer_name: str, inviter_name: str
) -> None:
    """Phase 4 Sprint 2 — admin clicks "Send Portal Invite" on a walk-in
    customer record. Email links to /register pre-seeded with the
    invite_email so the customer keeps the same email address the admin
    typed."""
    button_style = (
        "background:#1a1a1a;color:#fff;padding:12px 24px;"
        "text-decoration:none;border-radius:4px;display:inline-block;"
    )
    body = f"""
    <p>Hi {customer_name},</p>
    <p>{inviter_name} from Temple Heavy Equipment created a customer
       account for you and invited you to set up portal access so you
       can track your equipment submissions online.</p>
    <p><a href="{register_url}" style="{button_style}">Set up your portal account</a></p>
    <p>This invite was sent to <strong>{to_email}</strong>. If you didn't expect this,
       feel free to ignore the message.</p>
    """
    await send_email(
        to_email,
        "You're invited to the Temple Heavy Equipment customer portal",
        _base_html("Set up your TempleHE portal account", body),
    )
