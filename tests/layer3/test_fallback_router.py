"""
Tests for Stage D (fallback_router).

Exercises safe-default dispatch per modality, the high-risk default, the
"configured default is inactive → walk to an active model" path, and the
no-active-models marker. Uses the env-key fixtures from conftest so model
activation reflects which provider keys are present.
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.routing.fallback_router import (
    FallbackRouter,
    REASON_INSUFFICIENT_NEIGHBORS,
    REASON_NO_ACTIVE_MODELS,
    REASON_UNSUPPORTED_MODALITY,
)
from src.layer0_model_infra.routing.layer3_types import (
    HighRiskDomain,
    Modality,
    QueryFeatures,
    RoutingSource,
)
from src.layer0_model_infra.routing.registry_loader import get_layer3_registry


def _features(modality: Modality = Modality.TEXT, high_risk=None) -> QueryFeatures:
    return QueryFeatures(
        language="en",
        modality=modality,
        high_risk_domain=high_risk,
        estimated_input_tokens=50,
        estimated_output_tokens=400,
    )


def _router() -> FallbackRouter:
    # Bind the freshly-activated registry (reset_registry + an env fixture run first).
    return FallbackRouter(registry=get_layer3_registry())


# ---------------------------------------------------------------------------
# Safe-default dispatch (all keys present → configured defaults are active)
# ---------------------------------------------------------------------------


def test_text_modality_uses_text_default(all_keys_set, reset_registry):
    decision = _router().route(_features(Modality.TEXT), "rid-1", REASON_INSUFFICIENT_NEIGHBORS)
    assert decision.selected_model == "gemini-1.5-pro"
    assert decision.source == RoutingSource.FALLBACK
    assert decision.predicted_quality is None
    assert decision.prediction_confidence == "low"
    assert decision.fallback_reason == REASON_INSUFFICIENT_NEIGHBORS
    assert decision.qualifying_models == ["gemini-1.5-pro"]
    assert decision.estimated_cost_usd > 0  # gemini-1.5-pro is paid


def test_code_modality_uses_code_default(all_keys_set, reset_registry):
    decision = _router().route(_features(Modality.CODE), "rid-2", REASON_INSUFFICIENT_NEIGHBORS)
    assert decision.selected_model == "qwen-2.5-coder-32b-openrouter-free"


def test_math_modality_uses_math_default(all_keys_set, reset_registry):
    decision = _router().route(_features(Modality.MATH), "rid-3", REASON_INSUFFICIENT_NEIGHBORS)
    assert decision.selected_model == "deepseek-r1-distill-llama-70b-groq"


def test_high_risk_overrides_modality_default(all_keys_set, reset_registry):
    decision = _router().route(
        _features(Modality.TEXT, high_risk=HighRiskDomain.MEDICAL), "rid-4", REASON_INSUFFICIENT_NEIGHBORS
    )
    assert decision.selected_model == "gemini-1.5-pro"  # high_risk default


def test_vision_modality_uses_vision_default(all_keys_set, reset_registry):
    decision = _router().route(_features(Modality.VISION), "rid-5", REASON_UNSUPPORTED_MODALITY)
    assert decision.selected_model == "gemini-1.5-pro"
    assert decision.fallback_reason == REASON_UNSUPPORTED_MODALITY


# ---------------------------------------------------------------------------
# Inactive default → walk to an active model
# ---------------------------------------------------------------------------


def test_inactive_default_walks_to_active_model(only_groq_set, reset_registry):
    # gemini-1.5-pro (text default) requires GEMINI_API_KEY which is absent here.
    decision = _router().route(_features(Modality.TEXT), "rid-6", REASON_INSUFFICIENT_NEIGHBORS)
    assert decision.selected_model != "gemini-1.5-pro"
    chosen = get_layer3_registry().get(decision.selected_model)
    assert chosen.is_active is True
    assert chosen.provider == "groq"  # only groq keys are set


def test_vision_under_partial_keys_returns_active_model(only_groq_set, reset_registry):
    # No vision-capable active model exists with only groq — must still return
    # an active model rather than the dead gemini default.
    decision = _router().route(_features(Modality.VISION), "rid-7", REASON_UNSUPPORTED_MODALITY)
    chosen = get_layer3_registry().get(decision.selected_model)
    assert chosen.is_active is True


# ---------------------------------------------------------------------------
# No active models at all → return the configured default as a marker
# ---------------------------------------------------------------------------


def test_no_active_models_returns_marker(no_keys_set, reset_registry):
    decision = _router().route(_features(Modality.TEXT), "rid-8", REASON_INSUFFICIENT_NEIGHBORS)
    assert decision.selected_model == "gemini-1.5-pro"  # configured default, inactive
    assert decision.fallback_reason == REASON_NO_ACTIVE_MODELS
    assert decision.source == RoutingSource.FALLBACK


# ---------------------------------------------------------------------------
# select_model directly
# ---------------------------------------------------------------------------


def test_select_model_none_when_no_active(no_keys_set, reset_registry):
    assert _router().select_model(_features(Modality.TEXT)) is None


def test_select_model_returns_active_entry(all_keys_set, reset_registry):
    entry = _router().select_model(_features(Modality.CODE))
    assert entry is not None
    assert entry.model_id == "qwen-2.5-coder-32b-openrouter-free"
    assert entry.is_active is True
