# ABOUTME: Pure ASGI middleware that emits one structured JSON log line per request via structlog.
# ABOUTME: Captures method, path, status_code, latency_ms, user_id (JWT, no DB call).
from __future__ import annotations

import time

import jwt
import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config import settings

logger = structlog.get_logger(__name__)


def _extract_user_id(scope: Scope) -> str | None:
    headers = dict(scope.get("headers", []))
    auth = headers.get(b"authorization", b"").decode()
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


class StructuredLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        user_id = _extract_user_id(scope)
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
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "request",
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                user_id=user_id,
            )
