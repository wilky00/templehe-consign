# ABOUTME: Health check router — verifies DB reachability, migration version, and R2 connectivity.
# ABOUTME: Returns 200 OK if healthy, 503 Service Unavailable if any required check fails.
from __future__ import annotations

import asyncio

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.base import get_db

router = APIRouter(tags=["system"])

_EXPECTED_MIGRATION_HEAD = "002"


async def _check_database(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


async def _check_migrations(db: AsyncSession) -> str:
    try:
        result = await db.execute(
            text("SELECT version_num FROM alembic_version")
        )
        version = result.scalar_one_or_none()
        return "ok" if version == _EXPECTED_MIGRATION_HEAD else "error"
    except Exception:
        return "error"


async def _check_r2() -> str:
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        return "unconfigured"
    try:
        def _head() -> None:
            client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )
            client.head_bucket(Bucket=settings.r2_bucket_photos)

        await asyncio.to_thread(_head)
        return "ok"
    except (BotoCoreError, ClientError):
        return "error"
    except Exception:
        return "error"


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    db_status = await _check_database(db)
    migration_status = await _check_migrations(db)
    r2_status = await _check_r2()

    checks = {
        "database": db_status,
        "migrations": migration_status,
        "r2": r2_status,
    }

    # r2 is allowed to be unconfigured in non-production environments
    required_ok = db_status == "ok" and migration_status == "ok"
    overall = "ok" if required_ok else "degraded"

    body = {
        "status": overall,
        "version": "0.1.0",
        "checks": checks,
    }
    return JSONResponse(content=body, status_code=200 if required_ok else 503)
