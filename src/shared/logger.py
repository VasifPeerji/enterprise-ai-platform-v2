"""
📁 File: src/shared/logger.py
Layer: Shared (Cross-cutting)
Purpose: Structured, JSON-based logging with trace_id and tenant_id support
Depends on: structlog, python-json-logger
Used by: All layers

Logging requirements:
- JSON format for machine parsing
- Automatic trace_id injection
- Automatic tenant_id injection
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Context propagation
- Safe PII handling
"""

import logging
import sys
from typing import Any, Callable, Optional

import structlog
try:
    from structlog.types import EventDict, Processor
except Exception:
    EventDict = dict[str, Any]
    Processor = Callable[..., Any]

from src.shared.config import get_settings

# Get settings
settings = get_settings()


def add_app_context(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """
    Add application-wide context to every log entry.
    
    Args:
        logger: Python logger instance
        method_name: Name of the logging method
        event_dict: Current event dictionary
        
    Returns:
        Updated event dictionary with app context
    """
    event_dict["app_name"] = settings.APP_NAME
    event_dict["environment"] = settings.ENVIRONMENT
    event_dict["app_version"] = settings.APP_VERSION
    return event_dict


def censor_sensitive_data(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """
    Censor sensitive data from logs to prevent leaking PII or secrets.
    
    Args:
        logger: Python logger instance
        method_name: Name of the logging method
        event_dict: Current event dictionary
        
    Returns:
        Event dictionary with sensitive data censored
    """
    sensitive_keys = {
        "password",
        "api_key",
        "secret",
        "token",
        "authorization",
        "ssn",
        "credit_card",
        "cvv",
    }
    
    for key, value in event_dict.items():
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            event_dict[key] = "***REDACTED***"
    
    return event_dict


def configure_logging() -> None:
    """
    Configure structlog with JSON output and context processors.
    
    This should be called once at application startup.
    """
    # Choose processors based on environment
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        add_app_context,
        censor_sensitive_data,
    ]
    
    if settings.LOG_FORMAT == "json":
        # Production: JSON format
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Pretty console output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper()),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.
    
    Args:
        name: Logger name (typically __name__ of the module)
        
    Returns:
        Configured structlog logger
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("user_logged_in", user_id="123", tenant_id="acme")
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind context variables that will be included in all subsequent logs.
    
    This is useful for adding trace_id, tenant_id, user_id, etc.
    to all logs in a request context.
    
    Args:
        **kwargs: Key-value pairs to bind to the logging context
        
    Example:
        >>> bind_context(trace_id="abc-123", tenant_id="acme", user_id="user_456")
        >>> logger.info("processing_request")
        # Output includes trace_id, tenant_id, user_id automatically
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """
    Remove specific keys from the logging context.
    
    Args:
        *keys: Keys to remove from context
        
    Example:
        >>> unbind_context("trace_id", "user_id")
    """
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """
    Clear all bound context variables.
    
    This should typically be called at the end of a request.
    """
    structlog.contextvars.clear_contextvars()


# ==========================================
# CONVENIENCE FUNCTIONS FOR SPECIFIC LAYERS
# ==========================================

def log_model_call(
    logger: structlog.stdlib.BoundLogger,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    cost_usd: Optional[float] = None,
) -> None:
    """
    Log model inference call with standard metrics.
    
    Args:
        logger: Logger instance
        model_name: Name of the model
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Latency in milliseconds
        cost_usd: Cost in USD (optional)
    """
    logger.info(
        "model_inference_completed",
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        layer="layer0_model_infra",
    )


def log_rag_retrieval(
    logger: structlog.stdlib.BoundLogger,
    query: str,
    num_results: int,
    top_score: float,
    latency_ms: float,
) -> None:
    """
    Log RAG retrieval operation.
    
    Args:
        logger: Logger instance
        query: Search query (truncated)
        num_results: Number of results retrieved
        top_score: Highest similarity score
        latency_ms: Retrieval latency in milliseconds
    """
    logger.info(
        "rag_retrieval_completed",
        query=query[:100],  # Truncate for safety
        num_results=num_results,
        top_score=top_score,
        latency_ms=latency_ms,
        layer="layer1_intelligence",
    )


def log_transaction(
    logger: structlog.stdlib.BoundLogger,
    transaction_type: str,
    status: str,
    idempotency_key: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """
    Log transaction execution.
    
    Args:
        logger: Logger instance
        transaction_type: Type of transaction
        status: Transaction status (success, failed, pending)
        idempotency_key: Idempotency key (optional)
        error: Error message if failed (optional)
    """
    logger.info(
        "transaction_executed",
        transaction_type=transaction_type,
        status=status,
        idempotency_key=idempotency_key,
        error=error,
        layer="layer2_orchestrator",
    )


def log_intent_classification(
    logger: structlog.stdlib.BoundLogger,
    user_input: str,
    predicted_intent: str,
    confidence: float,
    intent_type: str,
) -> None:
    """
    Log intent classification result.
    
    Args:
        logger: Logger instance
        user_input: User's input (truncated)
        predicted_intent: Classified intent
        confidence: Confidence score
        intent_type: Intent type (cognitive/transactional/hybrid)
    """
    logger.info(
        "intent_classified",
        user_input=user_input[:100],
        predicted_intent=predicted_intent,
        confidence=confidence,
        intent_type=intent_type,
        layer="layer1_intelligence",
    )


# Initialize logging on module import
configure_logging()
