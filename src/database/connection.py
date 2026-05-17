"""
Database connection helpers for synchronous SQLModel access.

This module exists for components that run in background threads (bandit
state persistence, routing telemetry) and therefore need a sync engine.
"""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)
FALLBACK_DB_PATH = Path("./enterprise_ai_fallback.db").resolve()
FALLBACK_SYNC_SQLITE_URL = f"sqlite:///{FALLBACK_DB_PATH.as_posix()}"
FALLBACK_ASYNC_SQLITE_URL = f"sqlite+aiosqlite:///{FALLBACK_DB_PATH.as_posix()}"


def _to_sync_database_url(url: str) -> str:
    """
    Convert an async SQLAlchemy URL to a sync URL when needed.

    Examples:
    - postgresql+asyncpg://... -> postgresql+psycopg2://...
    - sqlite+aiosqlite:///...  -> sqlite:///...
    """
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    return url


def get_fallback_sync_database_url() -> str:
    """Return the shared fallback SQLite URL for sync code paths."""
    return FALLBACK_SYNC_SQLITE_URL


def get_fallback_async_database_url() -> str:
    """Return the shared fallback SQLite URL for async code paths."""
    return FALLBACK_ASYNC_SQLITE_URL


@lru_cache
def get_engine() -> Engine:
    """Return a cached synchronous SQLAlchemy engine."""
    settings = get_settings()
    sync_url = _to_sync_database_url(settings.database_url_computed)
    try:
        return create_engine(sync_url, echo=settings.DATABASE_ECHO, pool_pre_ping=True)
    except Exception as exc:
        logger.warning(
            "sync_engine_init_failed_fallback_sqlite",
            sync_url=sync_url,
            error=str(exc),
            fallback_url=FALLBACK_SYNC_SQLITE_URL,
        )
        return create_engine(FALLBACK_SYNC_SQLITE_URL, echo=False)
