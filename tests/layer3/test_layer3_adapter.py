"""
Tests for the Layer 3 → legacy execution bridge (3.6).

Verifies the RegistryEntry → ModelDefinition conversion (litellm name, provider,
per-1M → per-1k pricing, capabilities), registration into the legacy registry,
and — importantly — that the removed aliases no longer misroute (gpt-4o now
resolves to the real OpenAI model, not the old claude-sonnet-4 alias target).
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.models import ModelCapability, ModelProvider, ModelType
from src.layer0_model_infra.registry import ModelRegistry
from src.layer0_model_infra.routing.layer3_adapter import (
    register_layer3_models,
    registry_entry_to_model_definition,
)
from src.layer0_model_infra.routing.registry_loader import get_layer3_registry


def test_pricing_converted_per_1m_to_per_1k(all_keys_set, reset_registry):
    entry = get_layer3_registry().get("gemini-2.5-flash")  # 0.30 / 2.50 per 1M
    md = registry_entry_to_model_definition(entry)
    assert md.model_id == "gemini-2.5-flash"
    assert md.model_name == "gemini/gemini-2.5-flash"  # litellm string for the gateway
    assert md.provider == ModelProvider.GOOGLE
    assert md.model_type == ModelType.MULTIMODAL
    assert md.pricing.input_cost_per_1k_tokens == pytest.approx(0.0003)
    assert md.pricing.output_cost_per_1k_tokens == pytest.approx(0.0025)
    assert md.max_tokens == entry.context_window
    assert md.is_active is True


def test_capabilities_and_flags_mapped(all_keys_set, reset_registry):
    md = registry_entry_to_model_definition(
        get_layer3_registry().get("llama-3.3-70b-versatile-groq")
    )
    assert ModelCapability.CODING in md.capabilities
    assert md.supports_streaming is True
    assert md.provider == ModelProvider.GROQ


def test_register_makes_models_gateway_resolvable(all_keys_set, reset_registry):
    legacy = ModelRegistry()
    registered = register_layer3_models(legacy, get_layer3_registry())
    assert registered > 0
    md = legacy.get_model("llama-3.3-70b-versatile-groq")
    assert md.model_name == "groq/llama-3.3-70b-versatile"
    assert md.provider == ModelProvider.GROQ


def test_removed_alias_no_longer_misroutes(all_keys_set, reset_registry):
    # Before the I1 fix, get_model("gpt-4o") resolved the alias -> claude-sonnet-4.
    # Now gpt-4o must resolve to the real OpenAI model registered from Layer 3.
    legacy = ModelRegistry()
    register_layer3_models(legacy, get_layer3_registry())
    md = legacy.get_model("gpt-4o")
    assert md.model_name == "openai/gpt-4o"
    assert md.provider == ModelProvider.OPENAI


def test_register_is_idempotent(all_keys_set, reset_registry):
    legacy = ModelRegistry()
    register_layer3_models(legacy, get_layer3_registry())
    # second pass finds everything already present
    assert register_layer3_models(legacy, get_layer3_registry()) == 0
