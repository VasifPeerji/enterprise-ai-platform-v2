"""
📁 File: src/interfaces/http/middleware/logging_middleware.py
Layer: Interfaces (HTTP)
Purpose: Log all HTTP requests and responses with timing and status
Depends on: src/shared/logger
Used by: All HTTP requests

This middleware logs:
- Request method, path, headers
- Response status code
- Request duration
- Any errors that occur
"""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.shared.logger import get_logger

# Initialize
logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses.
    
    Logs include:
    - Request details (method, path, client IP)
    - Response status code
    - Request duration in milliseconds
    - Query parameters (if any)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Log request and response details.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain
            
        Returns:
            HTTP response
        """
        # Get start time (should be set by RequestContextMiddleware)
        start_time = getattr(request.state, "start_time", time.time())
        
        # Extract request details
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params) if request.query_params else None
        
        # Log request
        logger.info(
            "http_request_received",
            method=method,
            path=path,
            query_params=query_params,
        )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log response
            logger.info(
                "http_request_completed",
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            
            return response
            
        except Exception as e:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log error
            logger.error(
                "http_request_failed",
                method=method,
                path=path,
                duration_ms=round(duration_ms, 2),
                error=str(e),
                error_type=type(e).__name__,
            )
            
            # Re-raise to let error handler middleware catch it
            raise
