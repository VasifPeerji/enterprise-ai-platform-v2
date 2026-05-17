"""
📁 File: src/layer0_model_infra/models.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Model definitions and capability specifications
Depends on: pydantic
Used by: Model registry, router

Defines:
- Model types and capabilities
- Pricing information
- Latency characteristics
- Compliance eligibility
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ModelType(str, Enum):
    """Types of models available in the platform."""
    
    TEXT = "text"
    VISION = "vision"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"
    EMBEDDING = "embedding"


class ModelCapability(str, Enum):
    """Capabilities that models can have."""
    
    REASONING = "reasoning"
    CODING = "coding"
    VISION = "vision"
    AUDIO = "audio"
    FUNCTION_CALLING = "function_calling"
    STREAMING = "streaming"
    JSON_MODE = "json_mode"
    DETERMINISTIC = "deterministic"


class ModelProvider(str, Enum):
    """LLM providers supported by the platform."""
    
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    GOOGLE = "google"
    OPENROUTER = "openrouter"
    GROQ = "groq"
    HUGGINGFACE = "huggingface"
    COHERE = "cohere"
    MISTRAL = "mistral"
    LOCAL = "local"


class ComplianceDomain(str, Enum):
    """Compliance domains for regulated industries."""
    
    BANKING = "banking"
    HEALTHCARE = "healthcare"
    GOVERNMENT = "government"
    GENERAL = "general"


class ModelRoutingTier(str, Enum):
    """Presentation/runtime quality tier used by the router."""

    CHEAP = "cheap"
    MID = "mid"
    PREMIUM = "premium"


class ModelPricing(BaseModel):
    """Pricing information for a model."""
    
    input_cost_per_1k_tokens: float = Field(
        ..., description="Cost per 1,000 input tokens in USD"
    )
    output_cost_per_1k_tokens: float = Field(
        ..., description="Cost per 1,000 output tokens in USD"
    )
    image_cost: Optional[float] = Field(
        None, description="Cost per image in USD (for vision models)"
    )
    audio_cost_per_minute: Optional[float] = Field(
        None, description="Cost per minute of audio in USD"
    )


class ModelLatency(BaseModel):
    """Expected latency characteristics."""
    
    p50_ms: int = Field(..., description="50th percentile latency in milliseconds")
    p95_ms: int = Field(..., description="95th percentile latency in milliseconds")
    p99_ms: int = Field(..., description="99th percentile latency in milliseconds")
    time_to_first_token_ms: Optional[int] = Field(
        None, description="Time to first token for streaming (milliseconds)"
    )


class ModelDefinition(BaseModel):
    """
    Complete definition of a model in the registry.
    
    This is the source of truth for all model metadata.
    """
    
    # Identity
    model_id: str = Field(..., description="Unique identifier for internal use")
    model_name: str = Field(..., description="Official model name (e.g., 'gpt-4-turbo')")
    provider: ModelProvider = Field(..., description="Model provider")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Model description")
    
    # Classification
    model_type: ModelType = Field(..., description="Primary model type")
    capabilities: list[ModelCapability] = Field(
        default_factory=list, description="Model capabilities"
    )
    routing_tier: Optional[ModelRoutingTier] = Field(
        default=None,
        description="Explicit router tier for stable cheap/mid/premium selection",
    )
    
    # Technical Specs
    max_tokens: int = Field(..., description="Maximum context window size")
    supports_streaming: bool = Field(default=True, description="Supports streaming")
    supports_function_calling: bool = Field(
        default=False, description="Supports function/tool calling"
    )
    supports_json_mode: bool = Field(default=False, description="Supports JSON mode")
    
    # Performance
    pricing: ModelPricing = Field(..., description="Pricing information")
    latency: ModelLatency = Field(..., description="Expected latency")
    
    # Compliance
    compliance_domains: list[ComplianceDomain] = Field(
        default_factory=lambda: [ComplianceDomain.GENERAL],
        description="Approved compliance domains",
    )
    data_residency: Optional[str] = Field(
        None, description="Data residency region (e.g., 'US', 'EU')"
    )
    
    # Status
    is_active: bool = Field(default=True, description="Is model currently active")
    is_recommended: bool = Field(
        default=False, description="Is this a recommended default"
    )
    deprecation_date: Optional[str] = Field(
        None, description="Deprecation date if applicable (ISO 8601)"
    )
    
    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate total cost for a request.
        
        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Total cost in USD
        """
        input_cost = (input_tokens / 1000) * self.pricing.input_cost_per_1k_tokens
        output_cost = (output_tokens / 1000) * self.pricing.output_cost_per_1k_tokens
        return input_cost + output_cost
    
    def supports_capability(self, capability: ModelCapability) -> bool:
        """
        Check if model supports a specific capability.
        
        Args:
            capability: Capability to check
            
        Returns:
            True if supported, False otherwise
        """
        return capability in self.capabilities
    
    def is_compliant_for(self, domain: ComplianceDomain) -> bool:
        """
        Check if model is compliant for a specific domain.
        
        Args:
            domain: Compliance domain to check
            
        Returns:
            True if compliant, False otherwise
        """
        return domain in self.compliance_domains
