# ABOUTME: FastAPI application entry point — registers middleware, routers, and startup handlers.
# ABOUTME: All API routes are prefixed with /api/v1.
from __future__ import annotations

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from middleware.body_size import MaxBodySizeMiddleware
from middleware.request_id import RequestIDMiddleware
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.structured_logging import StructuredLoggingMiddleware
from routers import account as account_router
from routers import admin as admin_router
from routers import admin_categories as admin_categories_router
from routers import admin_config as admin_config_router
from routers import admin_credentials as admin_credentials_router
from routers import admin_health as admin_health_router
from routers import admin_routing as admin_routing_router
from routers import admin_templates as admin_templates_router
from routers import auth as auth_router
from routers import calendar as calendar_router
from routers import customers as customers_router
from routers import equipment as equipment_router
from routers import health as health_router
from routers import ios_config as ios_config_router
from routers import legal as legal_router
from routers import me_device_tokens as me_device_tokens_router
from routers import me_notifications as me_notifications_router
from routers import record_locks as record_locks_router
from routers import sales as sales_router

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
# Desired order: RequestID → StructuredLogging → SecurityHeaders → MaxBodySize →
# CORS → route handler. Body-size check sits inside CORS so preflights are cheap.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(MaxBodySizeMiddleware, max_bytes=1024 * 1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Client"],
)


app.include_router(account_router.router, prefix="/api/v1")
app.include_router(admin_router.router, prefix="/api/v1")
app.include_router(admin_categories_router.router, prefix="/api/v1")
app.include_router(admin_config_router.router, prefix="/api/v1")
app.include_router(admin_credentials_router.router, prefix="/api/v1")
app.include_router(admin_health_router.router, prefix="/api/v1")
app.include_router(admin_routing_router.router, prefix="/api/v1")
app.include_router(admin_templates_router.router, prefix="/api/v1")
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(calendar_router.router, prefix="/api/v1")
app.include_router(customers_router.router, prefix="/api/v1")
app.include_router(equipment_router.router, prefix="/api/v1")
app.include_router(health_router.router, prefix="/api/v1")
app.include_router(ios_config_router.router, prefix="/api/v1")
app.include_router(legal_router.router, prefix="/api/v1")
app.include_router(me_device_tokens_router.router, prefix="/api/v1")
app.include_router(me_notifications_router.router, prefix="/api/v1")
app.include_router(record_locks_router.router, prefix="/api/v1")
app.include_router(sales_router.router, prefix="/api/v1")
