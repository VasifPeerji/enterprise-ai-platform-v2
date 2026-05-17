"""
📁 File: src/interfaces/http/main.py
Layer: Interfaces (HTTP)
Purpose: Main FastAPI application entry point
Depends on: src/shared/config, src/shared/logger, src/shared/errors
Used by: uvicorn server

This is the main application that:
- Configures FastAPI with all middleware
- Registers all routes
- Sets up CORS
- Configures OpenAPI documentation
- Initializes logging and tracing
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from src.database.session import close_db, init_db
from src.interfaces.http.middleware.error_handler import ErrorHandlerMiddleware
from src.interfaces.http.middleware.logging_middleware import LoggingMiddleware
from src.interfaces.http.middleware.request_context import RequestContextMiddleware
from src.interfaces.http.routes.health import run_dependency_checks
from src.interfaces.http.routes import (
    chat,
    grounded_documents,
    health,
    models,
    rag_citations_demo,
    tenants,
)
from src.shared.config import get_settings
from src.shared.logger import get_logger

# Initialize
settings = get_settings()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    
    Handles startup and shutdown events:
    - Startup: Initialize connections, validate config
    - Shutdown: Close connections, cleanup resources
    
    Args:
        app: FastAPI application instance
        
    Yields:
        None during application runtime
    """
    # Startup
    logger.info(
        "application_starting",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        python_version=settings.model_config.get("python_version", "unknown"),
    )
    
    # Validate production configuration
    if settings.is_production():
        logger.info("validating_production_configuration")
        settings.validate_required_for_production()
    
    # Initialize database
    logger.info("initializing_database")
    await init_db()

    dependency_checks = await run_dependency_checks()
    app.state.dependency_checks = dependency_checks
    logger.info("startup_dependency_checks_completed", checks=dependency_checks)
    
    logger.info("application_started_successfully")
    
    yield
    
    # Shutdown
    logger.info("application_shutting_down")
    
    # Close database connections
    await close_db()
    app.state.dependency_checks = {}
    
    logger.info("application_shutdown_complete")


def create_application() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    This factory function:
    1. Creates FastAPI instance with metadata
    2. Adds all middleware in correct order
    3. Registers all route handlers
    4. Configures CORS
    5. Sets up exception handlers
    
    Returns:
        Configured FastAPI application instance
    """
    # Create FastAPI app
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Composable Enterprise AI Assistant Platform - Production-grade, multi-tenant, domain-agnostic AI system",
        docs_url="/docs" if settings.ENABLE_API_DOCS else None,
        redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
        openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
        lifespan=lifespan,
    )
    
    # ==========================================
    # MIDDLEWARE (Order matters!)
    # ==========================================
    
    # 1. CORS - Must be first
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 2. GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # 3. Request context (trace_id, tenant_id)
    app.add_middleware(RequestContextMiddleware)
    
    # 4. Logging middleware
    app.add_middleware(LoggingMiddleware)
    
    # 5. Error handler - Must be last
    app.add_middleware(ErrorHandlerMiddleware)
    
    # ==========================================
    # ROUTES
    # ==========================================
    
    # Health check routes (no prefix)
    app.include_router(health.router, tags=["Health"])
    
    # Model registry and testing routes
    app.include_router(models.router, tags=["Models"])
    
    # Smart chat with intelligent routing
    app.include_router(chat.router, tags=["Chat"])

    # Grounded document QA
    app.include_router(grounded_documents.router, tags=["Grounded Documents"])

    # Dedicated showcase for grounded RAG with page proof
    app.include_router(rag_citations_demo.router, tags=["RAG Citations Demo"])
    
    # Tenant management
    app.include_router(tenants.router, tags=["Tenants"])
    
    # TODO: Add API v1 routes
    # app.include_router(api_v1.router, prefix="/api/v1", tags=["API v1"])
    
    # ==========================================
    # ROOT ENDPOINT
    # ==========================================
    
    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        """Root endpoint with API information."""
        return JSONResponse(
            content={
                "name": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "environment": settings.ENVIRONMENT,
                "docs": "/docs" if settings.ENABLE_API_DOCS else None,
                "health": "/health",
            }
        )
    
    logger.info(
        "fastapi_application_created",
        routes_count=len(app.routes),
        middleware_count=len(app.user_middleware),
    )
    
    return app


# Create application instance
app = create_application()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.interfaces.http.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )
