# ABOUTME: Pure ASGI middleware that rejects request bodies larger than max_bytes.
# ABOUTME: Caps the cheap CPU-burning vectors (e.g., megabytes of form data + bcrypt).
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class MaxBodySizeMiddleware:
    """Reject requests with bodies larger than ``max_bytes`` with a 413.

    Checks Content-Length up front; falls back to counting bytes as they arrive
    when the client didn't advertise one (chunked transfer). The Phase 1 default
    is 1 MB because no Phase 1 endpoint legitimately accepts more — photo
    uploads (larger) land in Phase 2 and should bump the limit per-route.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = 1024 * 1024) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                declared = 0
            if declared > self.max_bytes:
                await _send_413(send)
                return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Drain any remaining chunks so the client doesn't block
                    # on backpressure while we send the 413.
                    while message.get("more_body", False):
                        message = await receive()
                    await _send_413(send)
                    # Signal EOF to the app by swallowing further chunks.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        await self.app(scope, counting_receive, send)


async def _send_413(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"detail":"Request body too large."}',
            "more_body": False,
        }
    )
