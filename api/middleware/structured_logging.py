# ABOUTME: Pure ASGI middleware that emits one structured JSON log line per request.
# ABOUTME: Reads user_id from request.state (set by auth dep) — never re-verifies the JWT here.
from __future__ import annotations

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


class StructuredLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500
        path = scope.get("path", "")
        method = scope.get("method", "")

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        except Exception as exc:
            # Uncaught exception propagating past the app layer. Sentry picks it up,
            # but add a structured log line so request-level tooling can correlate.
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.exception(
                "request_uncaught_exception",
                method=method,
                path=path,
                latency_ms=latency_ms,
                user_id=_user_id_from_scope(scope),
                exception=exc.__class__.__name__,
            )
            raise

        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        log_method = logger.error if status_code >= 500 else logger.info
        log_method(
            "request",
            method=method,
            path=path,
            status_code=status_code,
            latency_ms=latency_ms,
            user_id=_user_id_from_scope(scope),
        )


def _user_id_from_scope(scope: Scope) -> str | None:
    """Read the user_id stashed by middleware.auth.get_current_user, if any."""
    state = scope.get("state") or {}
    return state.get("user_id")
