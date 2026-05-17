"""
📁 File: src/interfaces/http/middleware/request_context.py
Layer: Interfaces (HTTP)
Purpose: Inject trace_id and tenant_id into request context for logging
Depends on: src/shared/logger
Used by: All HTTP requests

This middleware:
1. Generates or extracts trace_id from headers
2. Extracts tenant_id from headers
3. Binds both to logging context
4. Makes them available throughout the request lifecycle
"""

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.shared.config import get_settings
from src.shared.logger import bind_context, clear_context, get_logger

# Initialize
settings = get_settings()
logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to manage request context (trace_id, tenant_id).
    
    Automatically:
    - Generates unique trace_id per request
    - Extracts tenant_id from X-Tenant-ID header
    - Binds context variables to structured logging
    - Adds headers to response
    - Cleans up context after request
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and inject context.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain
            
        Returns:
            HTTP response with context headers
        """
        # Start timing
        start_time = time.time()
        
        # Generate or extract trace_id
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        
        # Extract tenant_id (default to configured default if not provided)
        tenant_id = request.headers.get("X-Tenant-ID") or settings.DEFAULT_TENANT_ID
        
        # Extract user_id if present (from authentication)
        user_id = request.headers.get("X-User-ID")
        
        # Bind context for logging
        context_vars = {
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else "unknown",
        }
        
        if user_id:
            context_vars["user_id"] = user_id
        
        bind_context(**context_vars)
        
        # Store in request state for access in route handlers
        request.state.trace_id = trace_id
        request.state.tenant_id = tenant_id
        request.state.user_id = user_id
        request.state.start_time = start_time
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add context headers to response
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Tenant-ID"] = tenant_id
            
            # Calculate request duration
            duration_ms = (time.time() - start_time) * 1000
            response.headers["X-Request-Duration-Ms"] = f"{duration_ms:.2f}"
            
            return response
            
        finally:
            # Clean up context
            clear_context()
