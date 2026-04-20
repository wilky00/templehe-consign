# ABOUTME: FastAPI application entry point — registers middleware, routers, and startup handlers.
# ABOUTME: All API routes are prefixed with /api/v1.
from __future__ import annotations

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

logger = structlog.get_logger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
    )

app = FastAPI(
    title="TempleHE API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", tags=["system"])
async def health() -> dict:
    """Basic liveness check. Full health check (DB + R2) is in routers/health.py (Sprint 4)."""
    return {"status": "ok"}
