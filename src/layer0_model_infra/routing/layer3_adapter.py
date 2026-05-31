"""
📁 File: src/layer0_model_infra/routing/layer3_adapter.py
Layer: Layer 0 — Layer 3 redesign (integration bridge for Batch 3.6)
Purpose: Make the new Layer 3 registry's models executable by the legacy
         gateway, by converting a RegistryEntry into the legacy ModelDefinition.
Depends on: src/layer0_model_infra/models, routing/layer3_types
Used by: router.py (registers Layer 3 models at startup; adapts decisions)

The two registries are intentionally separate during the retrofit:
  • Layer 3 routes over ``data/registry.json`` (Layer3Registry) — cloud free-tier
    models with coverage tags, env-gated activation, etc.
  • The legacy gateway executes via the in-code ModelRegistry, keyed by model_id,
    using ``ModelDefinition.model_name`` (the litellm string) + provider.

So once Layer 3 selects, say, ``llama-3.3-70b-versatile-groq``, the gateway must
be able to resolve that id. We do NOT round-trip through the legacy registry's
aliases (those were removed precisely because ``gpt-4o`` → ``claude-sonnet-4``
silently misroutes). Instead we build a faithful ModelDefinition straight from
the RegistryEntry — carrying the real litellm_model_name + provider — and
register it.

Pricing note: the Layer 3 registry quotes USD per **1M** tokens; ModelDefinition
quotes per **1k**. The conversion divides by 1000 — getting this wrong makes
every cost 1000× off, so it's unit-tested.
"""

from __future__ import annotations

from src.layer0_model_infra.models import (
    ComplianceDomain,
    ModelCapability,
    ModelDefinition,
    ModelLatency,
    ModelPricing,
    ModelProvider,
    ModelType,
)
from src.layer0_model_infra.routing.layer3_types import RegistryEntry
from src.shared.logger import get_logger

logger = get_logger(__name__)


_CAPABILITY_MAP: dict[str, ModelCapability] = {
    "reasoning": ModelCapability.REASONING,
    "coding": ModelCapability.CODING,
    "vision": ModelCapability.VISION,
    "audio": ModelCapability.AUDIO,
    "function_calling": ModelCapability.FUNCTION_CALLING,
    "streaming": ModelCapability.STREAMING,
    "json_mode": ModelCapability.JSON_MODE,
}

# The new registry tracks no latency; the legacy ModelDefinition requires it but
# it's advisory metadata only (it never influences the Layer 3 decision — that's
# already made). Neutral mid-tier placeholder.
_SYNTHETIC_LATENCY = ModelLatency(p50_ms=600, p95_ms=1800, p99_ms=3500, time_to_first_token_ms=200)


def registry_entry_to_model_definition(entry: RegistryEntry) -> ModelDefinition:
    """Build a legacy ModelDefinition from a Layer 3 RegistryEntry.

    The litellm execution string and provider come straight from the entry, so
    the gateway calls the right model. Pricing is converted per-1M → per-1k.
    """
    try:
        provider = ModelProvider(entry.provider)
    except ValueError as exc:  # unknown provider — fail loudly, don't misroute
        raise ValueError(
            f"RegistryEntry '{entry.model_id}' has provider '{entry.provider}' "
            f"that is not a known ModelProvider"
        ) from exc

    capabilities = [_CAPABILITY_MAP[c] for c in entry.capabilities if c in _CAPABILITY_MAP]

    return ModelDefinition(
        model_id=entry.model_id,
        model_name=entry.litellm_model_name,
        provider=provider,
        display_name=entry.display_name,
        description=entry.description or entry.display_name,
        model_type=ModelType(entry.model_type),
        capabilities=capabilities,
        routing_tier=None,  # Layer 3 already chose the model; no tier filtering
        max_tokens=entry.context_window,
        supports_streaming="streaming" in entry.capabilities,
        supports_function_calling="function_calling" in entry.capabilities,
        supports_json_mode="json_mode" in entry.capabilities,
        pricing=ModelPricing(
            input_cost_per_1k_tokens=entry.pricing.input_per_1m_usd / 1000.0,
            output_cost_per_1k_tokens=entry.pricing.output_per_1m_usd / 1000.0,
        ),
        latency=_SYNTHETIC_LATENCY,
        compliance_domains=[ComplianceDomain.GENERAL],
        is_active=entry.is_active,
        is_recommended=entry.is_recommended,
    )


def register_layer3_models(legacy_registry, layer3_registry) -> int:
    """Register every Layer 3 model into the legacy registry so the gateway can
    execute them by model_id. Skips ids already present (never overwrites a
    legacy model). Returns the number newly registered.
    """
    registered = 0
    skipped: list[str] = []
    for entry in layer3_registry.all_models():
        if entry.model_id in legacy_registry._models:  # already known to gateway
            skipped.append(entry.model_id)
            continue
        try:
            legacy_registry.register_model(registry_entry_to_model_definition(entry))
            registered += 1
        except Exception as exc:  # one bad entry shouldn't break startup
            logger.error("layer3_model_register_failed", model_id=entry.model_id, reason=str(exc))
    logger.info(
        "layer3_models_registered_into_legacy",
        registered=registered,
        skipped=len(skipped),
    )
    return registered
