"""
📁 File: src/layer0_model_infra/gateway.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Unified gateway for all LLM API calls via LiteLLM
Depends on: litellm, src/layer0_model_infra/registry, src/shared/config
Used by: Layer 1 (Intelligence), Layer 2 (Orchestrator)

This gateway:
- Abstracts all LLM provider APIs
- Handles authentication
- Implements retry logic
- Tracks costs and tokens
- Provides fallback mechanisms
"""

import time
from typing import Any, AsyncIterator, Optional

import litellm
from litellm import acompletion, aembedding
from pydantic import BaseModel, Field

from src.layer0_model_infra.models import ModelProvider, ModelRoutingTier, ModelType
from src.layer0_model_infra.registry import get_registry
from src.shared.config import get_settings
from src.shared.errors import ModelError, ModelRateLimitError, ModelTimeoutError
from src.shared.logger import get_logger, log_model_call

# Initialize
settings = get_settings()
logger = get_logger(__name__)
registry = get_registry()

# Configure LiteLLM
litellm.telemetry = settings.LITELLM_TELEMETRY
litellm.drop_params = settings.LITELLM_DROP_PARAMS
litellm.set_verbose = settings.LOG_LEVEL == "DEBUG"


class LLMRequest(BaseModel):
    """Request for LLM completion."""
    
    model_id: str = Field(..., description="Model ID from registry")
    messages: list[dict[str, str]] = Field(..., description="Chat messages")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, description="Max output tokens")
    stream: bool = Field(default=False, description="Enable streaming")
    functions: Optional[list[dict[str, Any]]] = Field(
        default=None, description="Function definitions"
    )
    function_call: Optional[str] = Field(
        default=None, description="Force function call"
    )
    response_format: Optional[dict[str, str]] = Field(
        default=None, description="Response format (e.g., {'type': 'json_object'})"
    )


class LLMResponse(BaseModel):
    """Response from LLM completion."""
    
    content: str = Field(..., description="Generated text")
    model_id: str = Field(..., description="Model used")
    input_tokens: int = Field(..., description="Input tokens consumed")
    output_tokens: int = Field(..., description="Output tokens generated")
    total_tokens: int = Field(..., description="Total tokens")
    cost_usd: float = Field(..., description="Estimated cost in USD")
    latency_ms: float = Field(..., description="Request latency in milliseconds")
    finish_reason: Optional[str] = Field(None, description="Why generation stopped")
    function_call: Optional[dict[str, Any]] = Field(
        None, description="Function call if present"
    )


class EmbeddingRequest(BaseModel):
    """Request for embedding generation."""
    
    model_id: str = Field(..., description="Embedding model ID from registry")
    texts: list[str] = Field(..., description="Texts to embed", min_length=1)


class EmbeddingResponse(BaseModel):
    """Response from embedding generation."""
    
    embeddings: list[list[float]] = Field(..., description="Generated embeddings")
    model_id: str = Field(..., description="Model used")
    total_tokens: int = Field(..., description="Total tokens processed")
    cost_usd: float = Field(..., description="Estimated cost in USD")
    latency_ms: float = Field(..., description="Request latency in milliseconds")


class ModelGateway:
    """
    Gateway for all LLM and embedding operations.
    
    Provides a unified interface for:
    - Text completion
    - Streaming completion
    - Embedding generation
    - Cost tracking
    - Error handling
    """
    
    def __init__(self) -> None:
        """Initialize the gateway."""
        self.registry = get_registry()

    def _build_litellm_params(self, request: LLMRequest, model_def) -> dict[str, Any]:
        """Build provider-aware LiteLLM request params."""
        litellm_params: dict[str, Any] = {
            "model": model_def.model_name,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": request.stream,
        }

        if request.max_tokens:
            litellm_params["max_tokens"] = request.max_tokens

        if request.functions:
            litellm_params["functions"] = request.functions

        if request.function_call:
            litellm_params["function_call"] = request.function_call

        if request.response_format:
            litellm_params["response_format"] = request.response_format

        if model_def.provider == ModelProvider.LOCAL:
            litellm_params["api_base"] = settings.OLLAMA_BASE_URL
        elif model_def.provider == ModelProvider.OPENAI and settings.OPENAI_API_KEY:
            litellm_params["api_key"] = settings.OPENAI_API_KEY
        elif model_def.provider == ModelProvider.ANTHROPIC and settings.ANTHROPIC_API_KEY:
            litellm_params["api_key"] = settings.ANTHROPIC_API_KEY
        elif model_def.provider == ModelProvider.GOOGLE and settings.GEMINI_API_KEY:
            litellm_params["api_key"] = settings.GEMINI_API_KEY
        elif model_def.provider == ModelProvider.GROQ and settings.GROQ_API_KEY:
            litellm_params["api_key"] = settings.GROQ_API_KEY
        elif model_def.provider == ModelProvider.OPENROUTER and settings.OPENROUTER_API_KEY:
            litellm_params["api_key"] = settings.OPENROUTER_API_KEY
            litellm_params["extra_headers"] = {
                "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                "X-Title": settings.OPENROUTER_APP_NAME,
            }
        elif model_def.provider == ModelProvider.HUGGINGFACE and settings.HUGGINGFACE_API_KEY:
            litellm_params["api_key"] = settings.HUGGINGFACE_API_KEY
            if settings.HUGGINGFACE_API_BASE:
                litellm_params["api_base"] = settings.HUGGINGFACE_API_BASE
        elif model_def.provider == ModelProvider.COHERE and settings.COHERE_API_KEY:
            litellm_params["api_key"] = settings.COHERE_API_KEY
        elif model_def.provider == ModelProvider.AZURE_OPENAI and settings.AZURE_OPENAI_API_KEY:
            litellm_params["api_key"] = settings.AZURE_OPENAI_API_KEY
            if settings.AZURE_OPENAI_ENDPOINT:
                litellm_params["api_base"] = settings.AZURE_OPENAI_ENDPOINT
            litellm_params["api_version"] = settings.AZURE_OPENAI_API_VERSION

        return litellm_params

    def _fallback_model_id_for(self, model_def) -> Optional[str]:
        """Pick a reliable free cloud model to retry on when a free-API model
        fails (rate-limit / transient error). Local Ollama is no longer a fallback
        target — it isn't reliably running and was hard-failing every retry.
        Returns None when fallback is off, the model is local, or the model is
        already the fallback target (prevents a self-loop)."""
        if not settings.ENABLE_FREE_API_FALLBACK:
            return None
        if model_def.provider == ModelProvider.LOCAL:
            return None
        if model_def.model_type == ModelType.MULTIMODAL:
            fb = "gemini-2.5-flash"
        else:
            fb = "llama-3.1-8b-instant-groq"
        if fb == model_def.model_id:
            # The model that failed IS the fallback — try a different provider.
            fb = "qwen-2.5-72b-huggingface"
        return fb

    async def _try_local_fallback(
        self,
        request: LLMRequest,
        failed_model_def,
        failure_reason: str,
    ) -> Optional[LLMResponse]:
        """Retry a failed free API request on a local model."""
        fallback_model_id = self._fallback_model_id_for(failed_model_def)
        if not fallback_model_id:
            return None

        logger.warning(
            "free_api_fallback_triggered",
            failed_model=failed_model_def.model_id,
            fallback_model=fallback_model_id,
            reason=failure_reason,
        )

        try:
            fallback_request = request.model_copy(update={"model_id": fallback_model_id})
            return await self.complete(fallback_request, _allow_fallback=False)
        except Exception as fallback_error:
            logger.error(
                "free_api_fallback_failed",
                failed_model=failed_model_def.model_id,
                fallback_model=fallback_model_id,
                error=str(fallback_error),
            )
            return None
    
    async def complete(self, request: LLMRequest, *, _allow_fallback: bool = True) -> LLMResponse:
        """
        Generate a completion from an LLM.

        Args:
            request: LLM request parameters
            _allow_fallback: internal — False on the fallback retry itself so a
                failing fallback can't recurse into another fallback.
            
        Returns:
            LLM response with content and metadata
            
        Raises:
            ModelError: If model call fails
            ModelTimeoutError: If request times out
            ModelRateLimitError: If rate limit is hit
        """
        start_time = time.time()
        
        # Get model definition
        model_def = self.registry.get_model(request.model_id)
        
        logger.info(
            "llm_request_started",
            model_id=request.model_id,
            model_name=model_def.model_name,
            message_count=len(request.messages),
            stream=request.stream,
        )
        
        try:
            litellm_params = self._build_litellm_params(request, model_def)
            litellm_params["stream"] = False
            
            # Make API call
            response = await acompletion(**litellm_params)
            
            # Extract response data
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
            function_call = (
                choice.message.function_call.dict()
                if hasattr(choice.message, "function_call")
                and choice.message.function_call
                else None
            )
            
            # Extract token usage
            usage = response.usage
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens
            
            # Calculate cost
            cost_usd = model_def.calculate_cost(input_tokens, output_tokens)
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            # Log completion
            log_model_call(
                logger=logger,
                model_name=model_def.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
            
            return LLMResponse(
                content=content,
                model_id=request.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                function_call=function_call,
            )
        
        except litellm.Timeout as e:
            fallback = await self._try_local_fallback(request, model_def, "timeout") if _allow_fallback else None
            if fallback is not None:
                return fallback
            logger.error(
                "llm_request_timeout",
                model_id=request.model_id,
                error=str(e),
            )
            raise ModelTimeoutError(model_def.model_name, timeout=60.0)
        
        except litellm.RateLimitError as e:
            fallback = await self._try_local_fallback(request, model_def, "rate_limit") if _allow_fallback else None
            if fallback is not None:
                return fallback
            logger.error(
                "llm_rate_limit_exceeded",
                model_id=request.model_id,
                error=str(e),
            )
            raise ModelRateLimitError(model_def.model_name)
        
        except Exception as e:
            fallback = await self._try_local_fallback(request, model_def, type(e).__name__) if _allow_fallback else None
            if fallback is not None:
                return fallback
            logger.error(
                "llm_request_failed",
                model_id=request.model_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise ModelError(
                message=f"LLM request failed: {str(e)}",
                details={"model_id": request.model_id, "error_type": type(e).__name__},
            )
    
    async def complete_stream(
        self, request: LLMRequest
    ) -> AsyncIterator[str]:
        """
        Generate a streaming completion from an LLM.
        
        Args:
            request: LLM request parameters (stream will be forced to True)
            
        Yields:
            Content chunks as they arrive
            
        Raises:
            ModelError: If model call fails
        """
        start_time = time.time()
        
        # Get model definition
        model_def = self.registry.get_model(request.model_id)
        
        logger.info(
            "llm_stream_request_started",
            model_id=request.model_id,
            model_name=model_def.model_name,
        )
        
        try:
            litellm_params = self._build_litellm_params(request, model_def)
            litellm_params["stream"] = True
            
            # Make streaming API call
            response = await acompletion(**litellm_params)
            
            total_chunks = 0
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    total_chunks += 1
                    yield content
            
            latency_ms = (time.time() - start_time) * 1000
            
            logger.info(
                "llm_stream_completed",
                model_id=request.model_id,
                total_chunks=total_chunks,
                latency_ms=round(latency_ms, 2),
            )
        
        except Exception as e:
            logger.error(
                "llm_stream_failed",
                model_id=request.model_id,
                error=str(e),
            )
            raise ModelError(
                message=f"LLM streaming failed: {str(e)}",
                details={"model_id": request.model_id},
            )
    
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        Generate embeddings for texts.
        
        Args:
            request: Embedding request parameters
            
        Returns:
            Embedding response with vectors and metadata
            
        Raises:
            ModelError: If embedding generation fails
        """
        start_time = time.time()
        
        # Get model definition
        model_def = self.registry.get_model(request.model_id)
        
        logger.info(
            "embedding_request_started",
            model_id=request.model_id,
            model_name=model_def.model_name,
            text_count=len(request.texts),
        )
        
        try:
            # Make API call
            response = await aembedding(
                model=model_def.model_name,
                input=request.texts,
            )
            
            # Extract embeddings
            embeddings = [item["embedding"] for item in response.data]
            
            # Extract token usage
            total_tokens = response.usage.total_tokens
            
            # Calculate cost
            cost_usd = model_def.calculate_cost(total_tokens, 0)
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            logger.info(
                "embedding_completed",
                model_id=request.model_id,
                text_count=len(request.texts),
                total_tokens=total_tokens,
                latency_ms=round(latency_ms, 2),
                cost_usd=cost_usd,
            )
            
            return EmbeddingResponse(
                embeddings=embeddings,
                model_id=request.model_id,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        
        except Exception as e:
            logger.error(
                "embedding_failed",
                model_id=request.model_id,
                error=str(e),
            )
            raise ModelError(
                message=f"Embedding generation failed: {str(e)}",
                details={"model_id": request.model_id},
            )


# Global gateway instance
_gateway: Optional[ModelGateway] = None


def get_gateway() -> ModelGateway:
    """
    Get the global model gateway instance.
    
    Returns:
        Model gateway singleton
    """
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway()
    return _gateway
