"""
📁 File: src/database/session.py
Layer: Database (Infrastructure)
Purpose: Database connection and session management
Depends on: sqlmodel, asyncpg
Used by: All database operations

Provides:
- Async database engine
- Session factory
- Dependency injection for FastAPI
"""

from functools import lru_cache
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from src.database.connection import get_fallback_async_database_url
from src.shared.config import get_settings
from src.shared.logger import get_logger

# Initialize
settings = get_settings()
logger = get_logger(__name__)


@lru_cache
def get_async_engine():
    """Build the shared async engine, falling back to SQLite for demo safety."""
    database_url = settings.database_url_computed
    try:
        return create_async_engine(
            database_url,
            echo=settings.DATABASE_ECHO,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    except Exception as exc:
        fallback_url = get_fallback_async_database_url()
        logger.warning(
            "async_engine_init_failed_fallback_sqlite",
            database_url=database_url,
            fallback_url=fallback_url,
            error=str(exc),
        )
        return create_async_engine(
            fallback_url,
            echo=False,
            pool_pre_ping=True,
        )


@lru_cache
def get_async_session_maker():
    """Return a cached async session factory bound to the shared engine."""
    return sessionmaker(
        get_async_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def init_db() -> None:
    """
    Initialize database by creating all tables.
    
    This should be called on application startup.
    Only creates tables if they don't exist.
    """
    logger.info("initializing_database")
    
    try:
        async with get_async_engine().begin() as conn:
            # Import the full models module so all SQLModel tables are registered.
            from src.database import models as _models  # noqa: F401

            # Create all tables
            await conn.run_sync(SQLModel.metadata.create_all)

            # Verify basic connectivity after startup wiring.
            await conn.execute(text("SELECT 1"))
            
        logger.info("database_initialized_successfully")
    
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session for dependency injection.
    
    Usage in FastAPI:
        @app.get("/users")
        async def get_users(session: AsyncSession = Depends(get_session)):
            result = await session.execute(select(User))
            return result.scalars().all()
    
    Yields:
        AsyncSession: Database session
    """
    async with get_async_session_maker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """
    Close database connections.
    
    This should be called on application shutdown.
    """
    logger.info("closing_database_connections")
    
    try:
        await get_async_engine().dispose()
        logger.info("database_connections_closed")
    
    except Exception as e:
        logger.error("error_closing_database", error=str(e))
        raise
