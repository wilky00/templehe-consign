# ABOUTME: FastAPI application entry point — registers middleware, routers, and startup handlers.
# ABOUTME: All API routes are prefixed with /api/v1.
from __future__ import annotations

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from middleware.request_id import RequestIDMiddleware
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.structured_logging import StructuredLoggingMiddleware
from routers import auth as auth_router
from routers import health as health_router

logger = structlog.get_logger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release or None,
        traces_sample_rate=0.1,
    )

app = FastAPI(
    title="TempleHE API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# Middleware is applied in reverse registration order (last registered = outermost).
# Desired order: RequestID → StructuredLogging → SecurityHeaders → CORS → route handler
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(health_router.router, prefix="/api/v1")
