# ABOUTME: Email delivery service — SendGrid in production, local SMTP (Mailpit) in development.
# ABOUTME: All calls are wrapped in asyncio.to_thread so the event loop is never blocked.
from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from config import settings

logger = structlog.get_logger(__name__)


async def send_email(to_email: str, subject: str, html_body: str) -> None:
    """Send an email. Routes to SMTP (Mailpit) in dev, SendGrid in production."""
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
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.sendmail(settings.sendgrid_from_email, to_email, msg.as_string())
    except Exception:
        logger.exception("smtp_send_failed", to=to_email, subject=subject)
        raise


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
        raise


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
    Temple Heavy Equipment &mdash; <a href="mailto:support@templehe.com">support@templehe.com</a>
  </p>
</body>
</html>"""


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


async def send_password_changed_email(to_email: str) -> None:
    body = """
    <p>Your TempleHE account password was just changed.</p>
    <p>If this was you, no further action is needed.</p>
    <p>If this wasn't you, <a href="mailto:support@templehe.com">contact support immediately</a>
       or reset your password using the login page.</p>
    """
    await send_email(
        to_email, "Your TempleHE password was changed", _base_html("Password changed", body)
    )


async def send_new_device_email(to_email: str, location: str, device: str) -> None:
    body = f"""
    <p>We detected a new sign-in to your TempleHE account.</p>
    <ul>
      <li><strong>Location:</strong> {location}</li>
      <li><strong>Device:</strong> {device}</li>
    </ul>
    <p>If this was you, no action is needed.</p>
    <p>If this wasn't you,
       <a href="mailto:support@templehe.com">reset your password immediately</a>.</p>
    """
    await send_email(
        to_email,
        "New sign-in to your TempleHE account",
        _base_html("New sign-in detected", body),
    )


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


async def send_email_change_notification(old_email: str, new_email: str) -> None:
    masked = new_email[:3] + "***@" + new_email.split("@")[-1]
    body = f"""
    <p>Your TempleHE account email is being changed to <strong>{masked}</strong>.</p>
    <p>The change will take effect once the new address is confirmed.</p>
    <p>If you didn't request this change,
       <a href="mailto:support@templehe.com">contact support immediately</a>.</p>
    """
    await send_email(
        old_email,
        "Your TempleHE email address is being changed",
        _base_html("Email change requested", body),
    )


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
