# ABOUTME: Pure ASGI middleware that sets all required security response headers on every response.
# ABOUTME: Header values come from security baseline §3. CSP report-uri appended when config is set.
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config import settings

_CSP_BASE = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://*.r2.cloudflarestorage.com https://temple-he-photos.saltrun.net; "
    "connect-src 'self' https://sentry.io; "
    "frame-ancestors 'none'"
)

_SECURITY_HEADERS = [
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
]


def _csp_header() -> tuple[bytes, bytes]:
    csp = _CSP_BASE
    if settings.sentry_csp_report_uri:
        csp = f"{csp}; report-uri {settings.sentry_csp_report_uri}"
    return (b"content-security-policy", csp.encode())


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._extra_headers = _SECURITY_HEADERS + [_csp_header()]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._extra_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
