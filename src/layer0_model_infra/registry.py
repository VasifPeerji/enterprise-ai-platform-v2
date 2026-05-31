"""
📁 File: src/layer0_model_infra/registry.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Central registry of all available models
Depends on: src/layer0_model_infra/models
Used by: Model router, gateway

The registry is the single source of truth for:
- Which models are available
- Model capabilities and pricing
- Compliance and performance characteristics
"""

import os
from typing import Optional

from src.layer0_model_infra.models import (
    ComplianceDomain,
    ModelCapability,
    ModelDefinition,
    ModelLatency,
    ModelPricing,
    ModelProvider,
    ModelRoutingTier,
    ModelType,
)
from src.shared.config import get_settings
from src.shared.errors import ModelNotFoundError
from src.shared.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class ModelRegistry:
    """
    Central registry for all models.
    
    This class maintains the catalog of available models and provides
    query methods for model selection.
    """
    
    def __init__(self) -> None:
        """Initialize the registry with default models."""
        self._models: dict[str, ModelDefinition] = {}
        self._aliases: dict[str, str] = {}
        self._initialize_default_models()
        self._register_2026_eval_models()

    def _refresh_dynamic_activation(self) -> None:
        """Refresh provider-backed model availability from the live process environment."""
        dynamic_activation_rules = {
            "gemini-2.0-flash-lite-free": bool(os.getenv("GEMINI_API_KEY")),
            "gemini-2.0-flash-free": bool(os.getenv("GEMINI_API_KEY")),
            "groq-llama-3.1-8b-free": bool(os.getenv("GROQ_API_KEY")),
            "groq-llama-3.3-70b-free": bool(os.getenv("GROQ_API_KEY")),
            "openrouter-free-router": bool(os.getenv("OPENROUTER_API_KEY")),
            "huggingface-qwen2.5-7b-experimental": bool(
                os.getenv("HUGGINGFACE_API_KEY") and os.getenv("HUGGINGFACE_API_BASE")
            ),
        }
        for model_id, is_active in dynamic_activation_rules.items():
            model = self._models.get(model_id)
            if model is not None:
                model.is_active = is_active
                if model.provider in {ModelProvider.GOOGLE, ModelProvider.GROQ}:
                    model.is_recommended = is_active
    
    def _initialize_default_models(self) -> None:
        """Initialize registry with commonly used models."""
        
        # ==========================================
        # OPENAI MODELS
        # ==========================================
        
        # GPT-4 Turbo
        self.register_model(
            ModelDefinition(
                model_id="gpt-4-turbo",
                model_name="gpt-4-turbo-preview",
                provider=ModelProvider.OPENAI,
                display_name="GPT-4 Turbo",
                description="Most capable GPT-4 model with 128k context",
                model_type=ModelType.TEXT,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                    ModelCapability.JSON_MODE,
                ],
                max_tokens=128000,
                supports_streaming=True,
                supports_function_calling=True,
                supports_json_mode=True,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.01,
                    output_cost_per_1k_tokens=0.03,
                ),
                latency=ModelLatency(
                    p50_ms=2000,
                    p95_ms=5000,
                    p99_ms=8000,
                    time_to_first_token_ms=500,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,
            )
        )
        
        # GPT-4 Vision
        self.register_model(
            ModelDefinition(
                model_id="gpt-4-vision",
                model_name="gpt-4-vision-preview",
                provider=ModelProvider.OPENAI,
                display_name="GPT-4 Vision",
                description="GPT-4 with vision capabilities",
                model_type=ModelType.MULTIMODAL,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.VISION,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=128000,
                supports_streaming=True,
                supports_function_calling=True,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.01,
                    output_cost_per_1k_tokens=0.03,
                    image_cost=0.01,
                ),
                latency=ModelLatency(
                    p50_ms=3000,
                    p95_ms=7000,
                    p99_ms=10000,
                    time_to_first_token_ms=800,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
            )
        )
        
        # GPT-3.5 Turbo (cost-effective)
        self.register_model(
            ModelDefinition(
                model_id="gpt-3.5-turbo",
                model_name="gpt-3.5-turbo",
                provider=ModelProvider.OPENAI,
                display_name="GPT-3.5 Turbo",
                description="Fast and cost-effective model",
                model_type=ModelType.TEXT,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                    ModelCapability.JSON_MODE,
                ],
                max_tokens=16385,
                supports_streaming=True,
                supports_function_calling=True,
                supports_json_mode=True,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0005,
                    output_cost_per_1k_tokens=0.0015,
                ),
                latency=ModelLatency(
                    p50_ms=800,
                    p95_ms=2000,
                    p99_ms=3000,
                    time_to_first_token_ms=200,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
            )
        )
        
        # ==========================================
        # ANTHROPIC MODELS
        # ==========================================
        
        # Claude Sonnet 4
        self.register_model(
            ModelDefinition(
                model_id="claude-sonnet-4",
                model_name="claude-sonnet-4-20250514",
                provider=ModelProvider.ANTHROPIC,
                display_name="Claude Sonnet 4",
                description="Anthropic's most balanced model",
                model_type=ModelType.TEXT,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=200000,
                supports_streaming=True,
                supports_function_calling=True,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.003,
                    output_cost_per_1k_tokens=0.015,
                ),
                latency=ModelLatency(
                    p50_ms=1500,
                    p95_ms=4000,
                    p99_ms=6000,
                    time_to_first_token_ms=400,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,
            )
        )
        
        # Claude Opus 4
        self.register_model(
            ModelDefinition(
                model_id="claude-opus-4",
                model_name="claude-opus-4-20250514",
                provider=ModelProvider.ANTHROPIC,
                display_name="Claude Opus 4",
                description="Anthropic's most capable model",
                model_type=ModelType.TEXT,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=200000,
                supports_streaming=True,
                supports_function_calling=True,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.015,
                    output_cost_per_1k_tokens=0.075,
                ),
                latency=ModelLatency(
                    p50_ms=2500,
                    p95_ms=6000,
                    p99_ms=9000,
                    time_to_first_token_ms=600,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
            )
        )

        # ==========================================
        # FREE / LOW-COST API MODELS
        # ==========================================
        self._register_free_api_models()
        
        # ==========================================
        # EMBEDDING MODELS
        # ==========================================
        
        # OpenAI Embeddings
        self.register_model(
            ModelDefinition(
                model_id="text-embedding-3-small",
                model_name="text-embedding-3-small",
                provider=ModelProvider.OPENAI,
                display_name="OpenAI Embedding Small",
                description="Fast and cost-effective embeddings",
                model_type=ModelType.EMBEDDING,
                capabilities=[],
                max_tokens=8191,
                supports_streaming=False,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.00002,
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=100,
                    p95_ms=300,
                    p99_ms=500,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,
            )
        )
        
        self.register_model(
            ModelDefinition(
                model_id="text-embedding-3-large",
                model_name="text-embedding-3-large",
                provider=ModelProvider.OPENAI,
                display_name="OpenAI Embedding Large",
                description="High-quality embeddings for better retrieval",
                model_type=ModelType.EMBEDDING,
                capabilities=[],
                max_tokens=8191,
                supports_streaming=False,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.00013,
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=150,
                    p95_ms=400,
                    p99_ms=600,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
            )
        )
        
        # ==========================================
        # OLLAMA MODELS (Local, Cost-Effective)
        # ==========================================
        
        # Llama 3.1 8B (Fast, local, free)
        self.register_model(
            ModelDefinition(
                model_id="ollama-llama3.1-8b",
                model_name="ollama/llama3.1:8b",
                provider=ModelProvider.LOCAL,
                display_name="Llama 3.1 8B (Ollama)",
                description="Fast local model, zero API costs",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.CHEAP,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=8192,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,  # FREE - local
                    output_cost_per_1k_tokens=0.0,  # FREE - local
                ),
                latency=ModelLatency(
                    p50_ms=500,
                    p95_ms=1500,
                    p99_ms=3000,
                    time_to_first_token_ms=200,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,  # Recommended for simple queries
            )
        )
        
        # Mistral 7B (Balanced local model)
        self.register_model(
            ModelDefinition(
                model_id="ollama-mistral-7b",
                model_name="ollama/mistral:7b",
                provider=ModelProvider.LOCAL,
                display_name="Mistral 7B (Ollama)",
                description="Balanced local model with good reasoning",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.MID,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=8192,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,  # FREE - local
                    output_cost_per_1k_tokens=0.0,  # FREE - local
                ),
                latency=ModelLatency(
                    p50_ms=600,
                    p95_ms=1800,
                    p99_ms=3500,
                    time_to_first_token_ms=250,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
            )
        )
        
        # Phi-3 Mini (Ultra-fast local model)
        self.register_model(
            ModelDefinition(
                model_id="ollama-phi3-mini",
                model_name="ollama/phi3:mini",
                provider=ModelProvider.LOCAL,
                display_name="Phi-3 Mini (Ollama)",
                description="Ultra-fast local model for simple tasks",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.CHEAP,
                capabilities=[
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=4096,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,  # FREE - local
                    output_cost_per_1k_tokens=0.0,  # FREE - local
                ),
                latency=ModelLatency(
                    p50_ms=300,
                    p95_ms=800,
                    p99_ms=1500,
                    time_to_first_token_ms=100,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,  # Recommended for very simple queries
            )
        )
        
        # ==========================================
        # 2026 BEST-IN-CLASS MODELS
        # ==========================================
        
        # Qwen3 Embedding 0.6B (2026 leader for multilingual embeddings)
        self.register_model(
            ModelDefinition(
                model_id="qwen3-embedding-0.6b",
                model_name="ollama/qwen3-embedding:0.6b",
                provider=ModelProvider.LOCAL,
                display_name="Qwen3 Embedding 0.6B",
                description="2026 leader for multilingual, instruction-aware embeddings",
                model_type=ModelType.EMBEDDING,
                capabilities=[],
                max_tokens=8192,
                supports_streaming=False,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,  # FREE - local
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=80,
                    p95_ms=200,
                    p99_ms=400,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,
            )
        )
        
        # Llama 4 Scout 3B (Agentic monitoring specialist)
        self.register_model(
            ModelDefinition(
                model_id="llama4-scout-3b",
                model_name="ollama/llama4-scout:3b",
                provider=ModelProvider.LOCAL,
                display_name="Llama 4 Scout 3B",
                description="Agentic monitoring and rubric grading specialist",
                model_type=ModelType.TEXT,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=8192,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=True,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,  # FREE - local
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=400,
                    p95_ms=1000,
                    p99_ms=2000,
                    time_to_first_token_ms=150,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
                is_recommended=True,
            )
        )
        
        # DeepSeek R1 Distill 1.5B (Thinking-enabled reward scoring)
        self.register_model(
            ModelDefinition(
                model_id="deepseek-r1-distill-1.5b",
                model_name="deepseek/deepseek-r1-distill:1.5b",
                provider=ModelProvider.LOCAL,
                display_name="DeepSeek R1 Distill 1.5B",
                description="Thinking-enabled reward scoring for bandit optimization",
                model_type=ModelType.TEXT,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=8192,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=True,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,  # FREE - local
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=300,
                    p95_ms=800,
                    p99_ms=1500,
                    time_to_first_token_ms=120,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=True,
            )
        )

        # NOTE: model-id aliases were intentionally removed. They mapped names
        # like "gpt-4o" and "claude-3-5-sonnet" to *different* local models
        # (claude-sonnet-4 / ollama-phi3-mini), which silently misroutes once the
        # Layer 3 registry — whose real model_ids are exactly "gpt-4o" /
        # "claude-3-5-sonnet" — is wired into execution. If a genuine alias is
        # ever needed, add it explicitly; register_alias now refuses any alias
        # that shadows a registered model_id.
        
        logger.info(
            "model_registry_initialized",
            total_models=len(self._models),
            providers=list(set(m.provider for m in self._models.values())),
        )

    def _register_2026_eval_models(self) -> None:
        """Register missing 2026 models for robust evaluation routing."""
        
        # Phi-4 3.8B
        self.register_model(ModelDefinition(
            model_id="ollama/phi4:3.8b",
            model_name="ollama/phi4:3.8b",
            provider=ModelProvider.LOCAL,
            display_name="Phi-4 3.8B",
            description="Fast triage model",
            model_type=ModelType.TEXT,
            routing_tier=ModelRoutingTier.MID,
            capabilities=[ModelCapability.STREAMING],
            max_tokens=8192,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=200, p95_ms=500, p99_ms=1000, time_to_first_token_ms=50),
            is_active=True,
        ))
        
        # DeepSeek R1 7B
        self.register_model(ModelDefinition(
            model_id="ollama/deepseek-r1:7b",
            model_name="ollama/deepseek-r1:7b",
            provider=ModelProvider.LOCAL,
            display_name="DeepSeek R1 7B",
            description="Deep reasoning judge",
            model_type=ModelType.TEXT,
            routing_tier=ModelRoutingTier.PREMIUM,
            capabilities=[ModelCapability.REASONING, ModelCapability.STREAMING],
            max_tokens=16000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=400, p95_ms=1200, p99_ms=2500, time_to_first_token_ms=150),
            is_active=True,
        ))

        # Qwen3 8B
        self.register_model(ModelDefinition(
            model_id="ollama-qwen3-8b",
            model_name="ollama/qwen3:8b",
            provider=ModelProvider.LOCAL,
            display_name="Qwen3 8B",
            description="Best overall <=8B local model for general chat, coding, and structured reasoning",
            model_type=ModelType.TEXT,
            routing_tier=ModelRoutingTier.MID,
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
            ],
            max_tokens=40000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=450, p95_ms=1200, p99_ms=2400, time_to_first_token_ms=130),
            is_active=True,
            is_recommended=True,
        ))

        # Phi-4 Mini Reasoning 3.8B
        self.register_model(ModelDefinition(
            model_id="ollama-phi4-mini-reasoning-3.8b",
            model_name="ollama/phi4-mini-reasoning:3.8b",
            provider=ModelProvider.LOCAL,
            display_name="Phi-4 Mini Reasoning 3.8B",
            description="Small, high-quality step-by-step reasoning model for math and logic-heavy evaluation",
            model_type=ModelType.TEXT,
            routing_tier=ModelRoutingTier.MID,
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
            ],
            max_tokens=32000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=350, p95_ms=900, p99_ms=1800, time_to_first_token_ms=110),
            is_active=True,
        ))

        # Gemma 3 4B
        self.register_model(ModelDefinition(
            model_id="ollama-gemma3-4b",
            model_name="ollama/gemma3:4b",
            provider=ModelProvider.LOCAL,
            display_name="Gemma 3 4B",
            description="Compact multimodal-capable local model for high-quality small-footprint generation",
            model_type=ModelType.MULTIMODAL,
            routing_tier=ModelRoutingTier.PREMIUM,
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
            ],
            max_tokens=128000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=500, p95_ms=1300, p99_ms=2600, time_to_first_token_ms=140),
            is_active=True,
        ))

        # Qwen 2.5 VL 3B
        self.register_model(ModelDefinition(
            model_id="ollama/qwen2.5-vl:3b",
            model_name="ollama/qwen2.5-vl:3b",
            provider=ModelProvider.LOCAL,
            display_name="Qwen 2.5 VL 3B",
            description="Fast multimodal gate",
            model_type=ModelType.MULTIMODAL,
            routing_tier=ModelRoutingTier.CHEAP,
            capabilities=[ModelCapability.VISION, ModelCapability.STREAMING],
            max_tokens=8192,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=300, p95_ms=900, p99_ms=1500, time_to_first_token_ms=100),
            is_active=True,
        ))
        
        # Qwen 3 VL 7B
        self.register_model(ModelDefinition(
            model_id="qwen/qwen3-vl-7b",
            model_name="qwen/qwen3-vl-7b",
            provider=ModelProvider.LOCAL,
            display_name="Qwen 3 VL 7B",
            description="High fidelity multimodal",
            model_type=ModelType.MULTIMODAL,
            capabilities=[ModelCapability.VISION, ModelCapability.STREAMING],
            max_tokens=32000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.0, output_cost_per_1k_tokens=0.0),
            latency=ModelLatency(p50_ms=600, p95_ms=1500, p99_ms=2500, time_to_first_token_ms=200),
            is_active=True,
        ))

        # Gemma 3 12B
        self.register_model(ModelDefinition(
            model_id="google/gemma-3-12b",
            model_name="google/gemma-3-12b",
            provider=ModelProvider.GOOGLE,
            display_name="Gemma 3 12B",
            description="Production fast triage",
            model_type=ModelType.TEXT,
            capabilities=[ModelCapability.STREAMING],
            max_tokens=8192,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.001, output_cost_per_1k_tokens=0.002),
            latency=ModelLatency(p50_ms=300, p95_ms=800, p99_ms=1500, time_to_first_token_ms=80),
            is_active=True,
        ))
        
        # DeepSeek R1 70B
        self.register_model(ModelDefinition(
            model_id="deepseek/deepseek-r1-70b",
            model_name="deepseek/deepseek-r1-70b",
            provider=ModelProvider.LOCAL,
            display_name="DeepSeek R1 70B",
            description="Production Deep reasoning",
            model_type=ModelType.TEXT,
            capabilities=[ModelCapability.REASONING, ModelCapability.CODING, ModelCapability.STREAMING],
            max_tokens=32000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.004, output_cost_per_1k_tokens=0.01),
            latency=ModelLatency(p50_ms=1500, p95_ms=3500, p99_ms=6000, time_to_first_token_ms=400),
            is_active=True,
        ))
        
        # Llama 4 Scout 17B
        self.register_model(ModelDefinition(
            model_id="meta/llama-4-scout-17b",
            model_name="meta/llama-4-scout-17b",
            provider=ModelProvider.LOCAL,
            display_name="Llama 4 Scout 17B",
            description="Production Quality Evaluation",
            model_type=ModelType.TEXT,
            capabilities=[ModelCapability.REASONING, ModelCapability.STREAMING],
            max_tokens=16000,
            pricing=ModelPricing(input_cost_per_1k_tokens=0.002, output_cost_per_1k_tokens=0.004),
            latency=ModelLatency(p50_ms=600, p95_ms=1500, p99_ms=2500, time_to_first_token_ms=150),
            is_active=True,
        ))

    def _register_free_api_models(self) -> None:
        """Register free-tier or developer-friendly API models when keys exist."""
        self.register_model(
            ModelDefinition(
                model_id="gemini-2.0-flash-lite-free",
                model_name="gemini/gemini-2.0-flash-lite",
                provider=ModelProvider.GOOGLE,
                display_name="Gemini 2.0 Flash-Lite (Free Tier)",
                description="Google AI Studio free-tier fast path and triage model",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.CHEAP,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=1_000_000,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0001,
                    output_cost_per_1k_tokens=0.0004,
                ),
                latency=ModelLatency(
                    p50_ms=500,
                    p95_ms=1200,
                    p99_ms=2500,
                    time_to_first_token_ms=180,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=bool(settings.GEMINI_API_KEY),
                is_recommended=bool(settings.GEMINI_API_KEY),
            )
        )

        self.register_model(
            ModelDefinition(
                model_id="gemini-2.0-flash-free",
                model_name="gemini/gemini-2.0-flash",
                provider=ModelProvider.GOOGLE,
                display_name="Gemini 2.0 Flash (Free Tier)",
                description="Higher quality free-tier Google model for general chat and code",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.MID,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                    ModelCapability.JSON_MODE,
                ],
                max_tokens=1_000_000,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=True,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0001,
                    output_cost_per_1k_tokens=0.0004,
                ),
                latency=ModelLatency(
                    p50_ms=800,
                    p95_ms=1800,
                    p99_ms=3200,
                    time_to_first_token_ms=220,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=bool(settings.GEMINI_API_KEY),
            )
        )

        self.register_model(
            ModelDefinition(
                model_id="groq-llama-3.1-8b-free",
                model_name="groq/llama-3.1-8b-instant",
                provider=ModelProvider.GROQ,
                display_name="Groq Llama 3.1 8B Instant (Free Key)",
                description="Very fast free-key Groq model for short answers and routing tasks",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.CHEAP,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=131072,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0001,
                    output_cost_per_1k_tokens=0.0001,
                ),
                latency=ModelLatency(
                    p50_ms=250,
                    p95_ms=700,
                    p99_ms=1200,
                    time_to_first_token_ms=90,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=bool(settings.GROQ_API_KEY),
                is_recommended=bool(settings.GROQ_API_KEY),
            )
        )

        self.register_model(
            ModelDefinition(
                model_id="groq-llama-3.3-70b-free",
                model_name="groq/llama-3.3-70b-versatile",
                provider=ModelProvider.GROQ,
                display_name="Groq Llama 3.3 70B Versatile (Free Key)",
                description="Higher-quality Groq option for reasoning and coding",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.PREMIUM,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=131072,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0006,
                    output_cost_per_1k_tokens=0.0008,
                ),
                latency=ModelLatency(
                    p50_ms=450,
                    p95_ms=1100,
                    p99_ms=1800,
                    time_to_first_token_ms=120,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=bool(settings.GROQ_API_KEY),
            )
        )

        self.register_model(
            ModelDefinition(
                model_id="openrouter-free-router",
                model_name="openrouter/openrouter/free",
                provider=ModelProvider.OPENROUTER,
                display_name="OpenRouter Free Router",
                description="OpenRouter free router for opportunistic no-cost model access",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.CHEAP,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                ],
                max_tokens=131072,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=1000,
                    p95_ms=2500,
                    p99_ms=5000,
                    time_to_first_token_ms=250,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=bool(settings.OPENROUTER_API_KEY),
            )
        )

        self.register_model(
            ModelDefinition(
                model_id="huggingface-qwen2.5-7b-experimental",
                model_name="huggingface/Qwen/Qwen2.5-7B-Instruct",
                provider=ModelProvider.HUGGINGFACE,
                display_name="Hugging Face Qwen2.5 7B (Experimental)",
                description="Experimental Hugging Face inference path; enable only if you have a compatible HF endpoint/base URL",
                model_type=ModelType.TEXT,
                routing_tier=ModelRoutingTier.MID,
                capabilities=[
                    ModelCapability.REASONING,
                    ModelCapability.CODING,
                    ModelCapability.STREAMING,
                    ModelCapability.JSON_MODE,
                ],
                max_tokens=131072,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=True,
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,
                    output_cost_per_1k_tokens=0.0,
                ),
                latency=ModelLatency(
                    p50_ms=1200,
                    p95_ms=3000,
                    p99_ms=6000,
                    time_to_first_token_ms=300,
                ),
                compliance_domains=[ComplianceDomain.GENERAL],
                is_active=bool(settings.HUGGINGFACE_API_KEY and settings.HUGGINGFACE_API_BASE),
            )
        )
    
    def register_model(self, model: ModelDefinition) -> None:
        """
        Register a new model in the registry.
        
        Args:
            model: Model definition to register
        """
        self._models[model.model_id] = model
        logger.debug("model_registered", model_id=model.model_id, model_name=model.model_name)

    def register_alias(self, alias_id: str, target_model_id: str) -> None:
        """Register a compatibility alias to an existing model id.

        Refuses to register an alias that shadows a real model_id — that's how
        the old "gpt-4o" -> "claude-sonnet-4" misroute happened, and it must
        never recur once the Layer 3 registry's ids are executable.
        """
        if alias_id in self._models:
            logger.warning(
                "model_alias_shadows_model",
                alias_id=alias_id,
                note="alias collides with a registered model_id; skipping to avoid misroute",
            )
            return
        self._aliases[alias_id] = target_model_id
        logger.debug("model_alias_registered", alias_id=alias_id, target_model_id=target_model_id)
    
    def get_model(self, model_id: str) -> ModelDefinition:
        """
        Get a model by its ID.
        
        Args:
            model_id: Model identifier
            
        Returns:
            Model definition
            
        Raises:
            ModelNotFoundError: If model not found in registry
        """
        resolved_model_id = self._aliases.get(model_id, model_id)
        self._refresh_dynamic_activation()

        if resolved_model_id not in self._models:
            raise ModelNotFoundError(model_id)
        
        model = self._models[resolved_model_id]
        
        if not model.is_active:
            logger.warning("inactive_model_requested", model_id=resolved_model_id)
        
        return model

    def resolve_model_id(self, model_id: str) -> str:
        """Return the canonical model id for a model or alias."""
        return self._aliases.get(model_id, model_id)
    
    def get_model_by_name(self, model_name: str) -> ModelDefinition:
        """
        Get a model by its official name.
        
        Args:
            model_name: Official model name (e.g., 'gpt-4-turbo-preview')
            
        Returns:
            Model definition
            
        Raises:
            ModelNotFoundError: If model not found in registry
        """
        for model in self._models.values():
            if model.model_name == model_name:
                return model
        
        raise ModelNotFoundError(model_name)
    
    def list_models(
        self,
        model_type: Optional[ModelType] = None,
        provider: Optional[ModelProvider] = None,
        capability: Optional[ModelCapability] = None,
        compliance_domain: Optional[ComplianceDomain] = None,
        only_active: bool = True,
        only_recommended: bool = False,
    ) -> list[ModelDefinition]:
        """
        List models matching criteria.
        
        Args:
            model_type: Filter by model type
            provider: Filter by provider
            capability: Filter by capability
            compliance_domain: Filter by compliance domain
            only_active: Only return active models
            only_recommended: Only return recommended models
            
        Returns:
            List of matching models
        """
        self._refresh_dynamic_activation()
        models = list(self._models.values())
        
        # Apply filters
        if model_type:
            models = [m for m in models if m.model_type == model_type]
        
        if provider:
            models = [m for m in models if m.provider == provider]
        
        if capability:
            models = [m for m in models if m.supports_capability(capability)]
        
        if compliance_domain:
            models = [m for m in models if m.is_compliant_for(compliance_domain)]
        
        if only_active:
            models = [m for m in models if m.is_active]
        
        if only_recommended:
            models = [m for m in models if m.is_recommended]
        
        return models
    
    def get_recommended_model(
        self, model_type: ModelType = ModelType.TEXT
    ) -> ModelDefinition:
        """
        Get the recommended model for a given type.
        
        Args:
            model_type: Type of model needed
            
        Returns:
            Recommended model definition
            
        Raises:
            ModelNotFoundError: If no recommended model found
        """
        recommended = self.list_models(
            model_type=model_type,
            only_active=True,
            only_recommended=True,
        )
        
        if not recommended:
            raise ModelNotFoundError(
                f"No recommended model found for type: {model_type}"
            )
        
        return recommended[0]


# Global registry instance
_registry: Optional[ModelRegistry] = None


def get_registry() -> ModelRegistry:
    """
    Get the global model registry instance.
    
    Returns:
        Model registry singleton
    """
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
