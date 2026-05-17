"""
📁 File: src/shared/errors.py
Layer: Shared (Cross-cutting)
Purpose: Custom exception hierarchy for the entire platform
Depends on: None (foundation)
Used by: All layers

Custom exceptions provide:
1. Structured error information
2. HTTP status code mapping
3. Client-safe error messages
4. Detailed logging context
"""

from typing import Any, Optional


class PlatformError(Exception):
    """
    Base exception for all platform errors.
    
    All custom exceptions should inherit from this class to ensure
    consistent error handling across the platform.
    
    Attributes:
        message: Human-readable error message
        error_code: Unique error code for tracking
        details: Additional context (never exposed to client)
        status_code: HTTP status code for API responses
    """
    
    def __init__(
        self,
        message: str,
        error_code: str,
        details: Optional[dict[str, Any]] = None,
        status_code: int = 500,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "status_code": self.status_code,
        }


# ==========================================
# LAYER 0 - MODEL INFRASTRUCTURE ERRORS
# ==========================================

class ModelError(PlatformError):
    """Base error for model-related issues."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "MODEL_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details, status_code=500)


class ModelNotFoundError(ModelError):
    """Requested model is not available in registry."""
    
    def __init__(self, model_name: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(
            message=f"Model '{model_name}' not found in registry",
            error_code="MODEL_NOT_FOUND",
            details=details or {"model_name": model_name},
        )


class ModelTimeoutError(ModelError):
    """Model inference exceeded timeout."""
    
    def __init__(self, model_name: str, timeout: float) -> None:
        super().__init__(
            message=f"Model '{model_name}' timeout after {timeout}s",
            error_code="MODEL_TIMEOUT",
            details={"model_name": model_name, "timeout": timeout},
        )


class ModelRateLimitError(ModelError):
    """Model rate limit exceeded."""
    
    def __init__(self, model_name: str, retry_after: Optional[int] = None) -> None:
        super().__init__(
            message=f"Rate limit exceeded for model '{model_name}'",
            error_code="MODEL_RATE_LIMIT",
            details={"model_name": model_name, "retry_after": retry_after},
        )


# ==========================================
# LAYER 1 - COGNITIVE ERRORS
# ==========================================

class CognitiveError(PlatformError):
    """Base error for cognitive layer issues."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "COGNITIVE_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details, status_code=500)


class IntentClassificationError(CognitiveError):
    """Failed to classify user intent."""
    
    def __init__(self, user_input: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(
            message="Unable to classify user intent",
            error_code="INTENT_CLASSIFICATION_FAILED",
            details=details or {"user_input": user_input[:100]},  # Truncate for safety
        )


class RAGError(CognitiveError):
    """Base error for RAG operations."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "RAG_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)


class NoRelevantContextError(RAGError):
    """No relevant context found for query."""
    
    def __init__(self, query: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(
            message="No relevant knowledge found for query",
            error_code="NO_RELEVANT_CONTEXT",
            details=details or {"query": query[:100]},
        )


class EmbeddingError(RAGError):
    """Failed to generate embeddings."""
    
    def __init__(self, text: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(
            message="Failed to generate embeddings",
            error_code="EMBEDDING_FAILED",
            details=details or {"text_length": len(text)},
        )


# ==========================================
# LAYER 2 - ORCHESTRATOR / TRANSACTION ERRORS
# ==========================================

class OrchestratorError(PlatformError):
    """Base error for orchestration issues."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "ORCHESTRATOR_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details, status_code=500)


class TransactionError(OrchestratorError):
    """Base error for transactional operations."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "TRANSACTION_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details)


class UnauthorizedActionError(TransactionError):
    """User not authorized to perform action."""
    
    def __init__(
        self,
        action: str,
        user_id: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=f"User not authorized to perform action: {action}",
            error_code="UNAUTHORIZED_ACTION",
            details=details or {"action": action, "user_id": user_id},
        )
        self.status_code = 403


class IdempotencyError(TransactionError):
    """Idempotency key conflict detected."""
    
    def __init__(
        self,
        idempotency_key: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=f"Duplicate operation detected: {idempotency_key}",
            error_code="IDEMPOTENCY_CONFLICT",
            details=details or {"idempotency_key": idempotency_key},
        )
        self.status_code = 409


class WorkflowExecutionError(OrchestratorError):
    """Workflow execution failed."""
    
    def __init__(
        self,
        workflow_id: str,
        step: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=f"Workflow '{workflow_id}' failed at step '{step}'",
            error_code="WORKFLOW_EXECUTION_FAILED",
            details=details or {"workflow_id": workflow_id, "step": step},
        )


# ==========================================
# LAYER 3 - DOMAIN ERRORS
# ==========================================

class DomainError(PlatformError):
    """Base error for domain-specific issues."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "DOMAIN_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details, status_code=400)


class InvalidDomainError(DomainError):
    """Requested domain does not exist."""
    
    def __init__(self, domain_name: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(
            message=f"Domain '{domain_name}' not found",
            error_code="INVALID_DOMAIN",
            details=details or {"domain_name": domain_name},
        )
        self.status_code = 404


class DataValidationError(DomainError):
    """Domain data failed validation."""
    
    def __init__(
        self,
        field: str,
        value: Any,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=f"Validation failed for field '{field}'",
            error_code="DATA_VALIDATION_FAILED",
            details=details or {"field": field, "value": str(value)[:100]},
        )


class DocumentParsingError(DomainError):
    """Document parsing failed or no parser was available."""

    def __init__(
        self,
        source_name: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=f"Failed to parse document '{source_name}'",
            error_code="DOCUMENT_PARSING_FAILED",
            details=details or {"source_name": source_name},
        )


# ==========================================
# LAYER 4 - PLATFORM / MULTI-TENANCY ERRORS
# ==========================================

class PlatformTenantError(PlatformError):
    """Base error for multi-tenancy issues."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "TENANT_ERROR",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, details, status_code=400)


class TenantNotFoundError(PlatformTenantError):
    """Tenant does not exist."""
    
    def __init__(self, tenant_id: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(
            message=f"Tenant '{tenant_id}' not found",
            error_code="TENANT_NOT_FOUND",
            details=details or {"tenant_id": tenant_id},
        )
        self.status_code = 404


class TenantIsolationError(PlatformTenantError):
    """Tenant isolation boundary violated."""
    
    def __init__(
        self,
        accessing_tenant: str,
        target_tenant: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message="Tenant isolation violation detected",
            error_code="TENANT_ISOLATION_VIOLATION",
            details=details
            or {"accessing_tenant": accessing_tenant, "target_tenant": target_tenant},
        )
        self.status_code = 403


# ==========================================
# VALIDATION & INPUT ERRORS
# ==========================================

class ValidationError(PlatformError):
    """Input validation failed."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        error_details = details or {}
        if field:
            error_details["field"] = field
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details=error_details,
            status_code=422,
        )


# ==========================================
# CONFIGURATION ERRORS
# ==========================================

class ConfigurationError(PlatformError):
    """Configuration is invalid or missing."""
    
    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        error_details = details or {}
        if config_key:
            error_details["config_key"] = config_key
        super().__init__(
            message=message,
            error_code="CONFIGURATION_ERROR",
            details=error_details,
            status_code=500,
        )
