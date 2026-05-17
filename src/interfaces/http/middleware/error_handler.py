"""
📁 File: src/interfaces/http/middleware/error_handler.py
Layer: Interfaces (HTTP)
Purpose: Global error handling for all HTTP requests
Depends on: src/shared/errors, src/shared/logger
Used by: All HTTP requests

This middleware:
1. Catches all exceptions
2. Maps custom exceptions to proper HTTP responses
3. Logs errors with full context
4. Returns safe error messages to clients
5. Never exposes internal details in production
"""

import traceback
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.shared.config import get_settings
from src.shared.errors import PlatformError, ValidationError
from src.shared.logger import get_logger

# Initialize
settings = get_settings()
logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Global error handler middleware.
    
    Catches all exceptions and converts them to proper HTTP responses.
    Ensures consistent error format across the API.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Catch and handle all exceptions.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain
            
        Returns:
            HTTP response (normal or error response)
        """
        try:
            # Process request normally
            response = await call_next(request)
            return response
            
        except PlatformError as e:
            # Handle custom platform errors
            return await self._handle_platform_error(request, e)
            
        except ValidationError as e:
            # Handle validation errors
            return await self._handle_validation_error(request, e)
            
        except Exception as e:
            # Handle unexpected errors
            return await self._handle_unexpected_error(request, e)
    
    async def _handle_platform_error(
        self, request: Request, error: PlatformError
    ) -> JSONResponse:
        """
        Handle custom platform errors.
        
        Args:
            request: HTTP request
            error: Platform error instance
            
        Returns:
            JSON error response
        """
        # Log the error
        logger.error(
            "platform_error_occurred",
            error_code=error.error_code,
            message=error.message,
            details=error.details,
            status_code=error.status_code,
            path=request.url.path,
        )
        
        # Build response
        error_response = {
            "error": {
                "code": error.error_code,
                "message": error.message,
                "trace_id": getattr(request.state, "trace_id", None),
            }
        }
        
        # Include details only in development
        if settings.DEBUG and error.details:
            error_response["error"]["details"] = error.details
        
        return JSONResponse(
            status_code=error.status_code,
            content=error_response,
        )
    
    async def _handle_validation_error(
        self, request: Request, error: ValidationError
    ) -> JSONResponse:
        """
        Handle validation errors.
        
        Args:
            request: HTTP request
            error: Validation error instance
            
        Returns:
            JSON error response
        """
        # Log the error
        logger.warning(
            "validation_error_occurred",
            message=error.message,
            details=error.details,
            path=request.url.path,
        )
        
        # Build response
        error_response = {
            "error": {
                "code": error.error_code,
                "message": error.message,
                "trace_id": getattr(request.state, "trace_id", None),
            }
        }
        
        # Always include validation details
        if error.details:
            error_response["error"]["details"] = error.details
        
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_response,
        )
    
    async def _handle_unexpected_error(
        self, request: Request, error: Exception
    ) -> JSONResponse:
        """
        Handle unexpected errors (not caught by application).
        
        Args:
            request: HTTP request
            error: Exception instance
            
        Returns:
            JSON error response
        """
        # Get trace_id for debugging
        trace_id = getattr(request.state, "trace_id", "unknown")
        
        # Log the full error with stack trace
        logger.error(
            "unexpected_error_occurred",
            error_type=type(error).__name__,
            error_message=str(error),
            traceback=traceback.format_exc(),
            path=request.url.path,
            method=request.method,
        )
        
        # Build safe response (don't expose internal details in production)
        if settings.is_production():
            error_response = {
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An internal error occurred. Please contact support.",
                    "trace_id": trace_id,
                }
            }
        else:
            # In development, include more details
            error_response = {
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": str(error),
                    "trace_id": trace_id,
                    "type": type(error).__name__,
                    "traceback": traceback.format_exc().split("\n"),
                }
            }
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )
