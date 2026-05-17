"""
📁 File: src/interfaces/http/routes/models.py
Layer: Interfaces (HTTP)
Purpose: API endpoints for model registry and testing
Depends on: src/layer0_model_infra
Used by: Clients, testing

Endpoints:
- GET /models - List all available models
- GET /models/{model_id} - Get model details
- POST /models/test - Test a model with a simple prompt
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.layer0_model_infra.gateway import LLMRequest, get_gateway
from src.layer0_model_infra.models import ModelCapability, ModelProvider, ModelType
from src.layer0_model_infra.registry import get_registry
from src.shared.errors import ModelNotFoundError
from src.shared.logger import get_logger

# Initialize
router = APIRouter(prefix="/models", tags=["Models"])
logger = get_logger(__name__)
registry = get_registry()
gateway = get_gateway()


class ModelListResponse(BaseModel):
    """Response for listing models."""
    
    models: list[dict] = Field(..., description="List of available models")
    total_count: int = Field(..., description="Total number of models")


class TestModelRequest(BaseModel):
    """Request to test a model."""
    
    model_id: str = Field(..., description="Model ID to test")
    prompt: str = Field(..., description="Test prompt", min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=100, description="Max output tokens")


@router.get(
    "",
    response_model=ModelListResponse,
    summary="List Models",
    description="Get list of all available models with optional filtering",
)
async def list_models(
    model_type: Optional[ModelType] = None,
    provider: Optional[ModelProvider] = None,
    capability: Optional[ModelCapability] = None,
    only_active: bool = True,
    only_recommended: bool = False,
) -> ModelListResponse:
    """
    List all available models with optional filters.
    
    Args:
        model_type: Filter by model type
        provider: Filter by provider
        capability: Filter by capability
        only_active: Only return active models
        only_recommended: Only return recommended models
        
    Returns:
        List of models with metadata
    """
    logger.info(
        "list_models_requested",
        model_type=model_type,
        provider=provider,
        capability=capability,
    )
    
    models = registry.list_models(
        model_type=model_type,
        provider=provider,
        capability=capability,
        only_active=only_active,
        only_recommended=only_recommended,
    )
    
    # Convert to dict for response
    models_data = [
        {
            "model_id": m.model_id,
            "model_name": m.model_name,
            "provider": m.provider,
            "display_name": m.display_name,
            "description": m.description,
            "model_type": m.model_type,
            "capabilities": m.capabilities,
            "max_tokens": m.max_tokens,
            "pricing": {
                "input_cost_per_1k": m.pricing.input_cost_per_1k_tokens,
                "output_cost_per_1k": m.pricing.output_cost_per_1k_tokens,
            },
            "is_recommended": m.is_recommended,
        }
        for m in models
    ]
    
    return ModelListResponse(models=models_data, total_count=len(models_data))


@router.get(
    "/{model_id}",
    summary="Get Model Details",
    description="Get detailed information about a specific model",
)
async def get_model_details(model_id: str) -> dict:
    """
    Get detailed information about a specific model.
    
    Args:
        model_id: Model identifier
        
    Returns:
        Complete model definition
        
    Raises:
        HTTPException: If model not found
    """
    logger.info("get_model_details_requested", model_id=model_id)
    
    try:
        model = registry.get_model(model_id)
        return model.dict()
    except ModelNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found",
        )


@router.post(
    "/test",
    summary="Test Model",
    description="Test a model with a simple prompt (for development/debugging)",
)
async def test_model(request: TestModelRequest) -> dict:
    """
    Test a model with a simple prompt.
    
    This endpoint is for testing and debugging only.
    
    Args:
        request: Test request with model_id and prompt
        
    Returns:
        Model response with generated text and metadata
        
    Raises:
        HTTPException: If model not found or call fails
    """
    logger.info(
        "test_model_requested",
        model_id=request.model_id,
        prompt_length=len(request.prompt),
    )
    
    try:
        # Create LLM request
        llm_request = LLMRequest(
            model_id=request.model_id,
            messages=[{"role": "user", "content": request.prompt}],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        
        # Call the model
        response = await gateway.complete(llm_request)
        
        return {
            "success": True,
            "model_id": response.model_id,
            "response": response.content,
            "metadata": {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "cost_usd": response.cost_usd,
                "latency_ms": response.latency_ms,
                "finish_reason": response.finish_reason,
            },
        }
    
    except ModelNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e.message),
        )
    
    except Exception as e:
        logger.error(
            "test_model_failed",
            model_id=request.model_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Model test failed: {str(e)}",
        )
