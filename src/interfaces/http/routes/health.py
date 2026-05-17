"""
📁 File: src/interfaces/http/routes/health.py
Layer: Interfaces (HTTP)
Purpose: Health check endpoints for monitoring and readiness
Depends on: src/shared/config, src/shared/logger
Used by: Load balancers, monitoring systems, Kubernetes

Health check endpoints:
- /health - Basic liveness check
- /health/ready - Readiness check (all dependencies available)
- /health/live - Liveness check (application is running)
"""

import asyncio
import time
import urllib.request
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.database.session import get_async_engine
from src.shared.config import get_settings
from src.shared.logger import get_logger

# Initialize
router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)


async def check_database_health() -> dict[str, Any]:
    """Perform a lightweight database readiness check."""
    started = time.perf_counter()
    try:
        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "backend": str(engine.url),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


async def check_redis_health() -> dict[str, Any]:
    """Check that Redis is reachable over TCP."""
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.REDIS_HOST, settings.REDIS_PORT),
            timeout=2.0,
        )
        writer.close()
        await writer.wait_closed()
        return {
            "status": "healthy",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "endpoint": f"{settings.REDIS_HOST}:{settings.REDIS_PORT}",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "endpoint": f"{settings.REDIS_HOST}:{settings.REDIS_PORT}",
        }


async def check_qdrant_health() -> dict[str, Any]:
    """Check the Qdrant health endpoint over HTTP."""
    started = time.perf_counter()

    def _fetch() -> int:
        with urllib.request.urlopen(f"{settings.qdrant_url}/healthz", timeout=2.0) as response:
            return response.getcode()

    try:
        status_code = await asyncio.to_thread(_fetch)
        return {
            "status": "healthy" if status_code == 200 else "unhealthy",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "endpoint": settings.qdrant_url,
            "http_status": status_code,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "endpoint": settings.qdrant_url,
        }


async def run_dependency_checks() -> dict[str, dict[str, Any]]:
    """Run all readiness checks concurrently."""
    database, redis, qdrant = await asyncio.gather(
        check_database_health(),
        check_redis_health(),
        check_qdrant_health(),
    )
    return {
        "database": database,
        "redis": redis,
        "qdrant": qdrant,
    }


class HealthResponse(BaseModel):
    """Health check response model."""
    
    status: str = Field(..., description="Health status (healthy/unhealthy)")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Deployment environment")


class ReadinessResponse(BaseModel):
    """Readiness check response model with dependency status."""
    
    status: str = Field(..., description="Overall readiness status")
    version: str = Field(..., description="Application version")
    checks: dict[str, Any] = Field(..., description="Individual dependency checks")


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Basic health check endpoint. Returns 200 if application is running.",
)
async def health_check() -> JSONResponse:
    """
    Basic health check endpoint.
    
    This endpoint always returns 200 OK if the application is running.
    Used for basic liveness checks.
    
    Returns:
        JSONResponse with health status
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "healthy",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )


@router.get(
    "/health/live",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Check",
    description="Kubernetes liveness probe. Returns 200 if application process is alive.",
)
async def liveness_check() -> JSONResponse:
    """
    Liveness check for Kubernetes.
    
    Returns 200 OK if the application process is running.
    Does not check external dependencies.
    
    Returns:
        JSONResponse with liveness status
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "alive",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness Check",
    description="Kubernetes readiness probe. Returns 200 if all dependencies are available.",
)
async def readiness_check() -> JSONResponse:
    """
    Readiness check for Kubernetes.
    
    Checks if the application is ready to accept traffic by verifying:
    - Database connection
    - Redis connection
    - Qdrant connection
    - Any other critical dependencies
    
    Returns:
        JSONResponse with readiness status and dependency checks
        
    Note:
        Currently returns basic status. TODO: Add actual dependency checks.
    """
    checks = await run_dependency_checks()
    required_services = ("database",)
    overall_status = "ready"
    status_code = status.HTTP_200_OK

    if any(checks[name]["status"] != "healthy" for name in required_services):
        overall_status = "not_ready"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    optional_degraded = [
        name for name in ("redis", "qdrant")
        if checks[name]["status"] != "healthy"
    ]
    if optional_degraded and overall_status == "ready":
        overall_status = "degraded"
    
    # Log readiness check
    logger.info(
        "readiness_check_completed",
        overall_status=overall_status,
        checks=checks,
    )
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "version": settings.APP_VERSION,
            "checks": checks,
        },
    )
