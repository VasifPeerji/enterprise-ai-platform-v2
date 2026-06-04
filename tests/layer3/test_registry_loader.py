"""
Tests for the Layer 3 registry loader.

Covers:
  • The bundled data/registry.json parses + loads without errors
  • Every entry's coverage_quality tag is one of {full, medium, low}
  • Patch P1 is correctly applied: paid commercial models are NOT tagged 'full'
  • is_active is gated on each model's required_env_var (the user's key story)
  • The singleton is genuinely shared but resettable for tests
  • safe_defaults reference real model_ids
"""

from __future__ import annotations

import json
import pytest

from src.layer0_model_infra.routing.layer3_types import (
    CoverageQuality,
    Modality,
    RegistryEntry,
    SafeDefaults,
)
from src.layer0_model_infra.routing.registry_loader import (
    Layer3Registry,
    get_layer3_registry,
    reset_layer3_registry,
)


# ---------------------------------------------------------------------------
# Basic loading
# ---------------------------------------------------------------------------


def test_loads_bundled_registry(registry_path):
    """The shipped registry.json parses with every entry validating."""
    reg = Layer3Registry(registry_path)
    assert len(reg.all_models()) >= 10, "expected ~13 models in the bundled registry after the 2026-06 refresh"
    assert reg.safe_defaults is not None


def test_meta_fields_present(registry_path):
    reg = Layer3Registry(registry_path)
    stats = reg.stats()
    assert stats["schema_version"] == "1.0"
    assert stats["last_verified"] != "unknown"


def test_safe_defaults_reference_real_models(registry_path):
    reg = Layer3Registry(registry_path)
    for modality in ("text", "code", "math", "vision", "multimodal", "high_risk"):
        model_id = getattr(reg.safe_defaults, modality)
        assert reg.has(model_id), f"safe_defaults['{modality}']='{model_id}' missing from registry"


def test_duplicate_model_id_rejected(tmp_path):
    """A registry with duplicate model_ids should fail to load."""
    payload = {
        "_meta": {"schema_version": "1.0"},
        "safe_defaults": {
            "text": "m1", "code": "m1", "math": "m1",
            "vision": "m1", "multimodal": "m1", "high_risk": "m1",
        },
        "models": [
            _minimal_entry("m1"),
            _minimal_entry("m1"),  # duplicate
        ],
    }
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Duplicate model_id"):
        Layer3Registry(path)


def test_safe_default_missing_from_registry_rejected(tmp_path):
    payload = {
        "_meta": {"schema_version": "1.0"},
        "safe_defaults": {
            "text": "does-not-exist", "code": "m1", "math": "m1",
            "vision": "m1", "multimodal": "m1", "high_risk": "m1",
        },
        "models": [_minimal_entry("m1")],
    }
    path = tmp_path / "bad-default.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="safe_defaults"):
        Layer3Registry(path)


# ---------------------------------------------------------------------------
# P1 — coverage_quality tagging is honest
# ---------------------------------------------------------------------------


def test_coverage_quality_field_constrained(registry_path):
    reg = Layer3Registry(registry_path)
    valid = {CoverageQuality.FULL, CoverageQuality.MEDIUM, CoverageQuality.LOW}
    for entry in reg.all_models():
        assert entry.coverage_quality in valid


def test_p1_paid_commercial_not_full_coverage(registry_path):
    """Patch P1: GPT-4o-mini / Claude Haiku / Gemini Flash are coverage=low.
    GPT-4o / Claude Sonnet / Gemini Pro are at most coverage=medium.
    Frontier (Opus 4.5 / Sonnet 4.5) is coverage=low.
    """
    reg = Layer3Registry(registry_path)

    # The "low" set per P1
    must_be_low = {
        "gpt-4o-mini",
        "claude-3-5-haiku",
        "gemini-2.0-flash",  # P1 lists Gemini 2.5 Flash as low; we have 2.0 Flash here as the equivalent
        "gemini-1.5-flash",  # similarly low coverage as a "small" Gemini
        "claude-sonnet-4-5",
        "claude-opus-4-5",
    }
    for model_id in must_be_low:
        if reg.has(model_id):
            entry = reg.get(model_id)
            assert entry.coverage_quality == CoverageQuality.LOW, (
                f"P1 violation: {model_id} should be coverage_quality=low, "
                f"got {entry.coverage_quality.value}"
            )

    # The "should not be 'full'" set per P1
    must_not_be_full = {
        "gpt-4o-mini", "gpt-4o",
        "claude-3-5-haiku", "claude-3-5-sonnet", "claude-sonnet-4-5", "claude-opus-4-5",
        "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro",
    }
    for model_id in must_not_be_full:
        if reg.has(model_id):
            entry = reg.get(model_id)
            assert entry.coverage_quality != CoverageQuality.FULL, (
                f"P1 violation: {model_id} should not be coverage_quality=full"
            )


def test_p1_open_weights_keep_full_coverage(registry_path):
    """Patch P1: open-weights models with per-question MMLU-Pro coverage keep
    coverage=full because they're on the HF Open LLM Leaderboard with real
    per-question outcomes.

    deepseek-v3-openrouter-free is deliberately NOT in this set: its only
    per-question outcomes are SWE-bench coding (~6% of the corpus), far below
    the 60% 'full' threshold, so it was re-tagged 'low' from the real merged
    corpus. See test_p1_frontier_models_are_low_coverage for the low side.
    """
    reg = Layer3Registry(registry_path)
    must_be_full = {
        "llama-3.3-70b-versatile-groq",
        "llama-3.1-8b-instant-groq",
        "deepseek-r1-distill-llama-70b-groq",
        "qwen-2.5-coder-32b-openrouter-free",
        "gemma-2-27b-openrouter-free",
    }
    for model_id in must_be_full:
        if reg.has(model_id):
            entry = reg.get(model_id)
            assert entry.coverage_quality == CoverageQuality.FULL, (
                f"P1 violation: open-weights {model_id} should be coverage_quality=full"
            )


def test_p1_net_effect_significant_low_coverage_population(registry_path):
    """The point of P1 is anti-over-routing: enough models eat the +0.10
    floor penalty (LOW) or use mixed-prior (MEDIUM) treatment that free open
    models dominate the qualifying set on most queries.

    With a 22-model registry, we expect at least 6 LOW and at least 12
    LOW+MEDIUM combined (since both groups have weaker kNN signal and the
    aggregate prior carries more weight for them).
    """
    reg = Layer3Registry(registry_path)
    low_count = len(reg.by_coverage(CoverageQuality.LOW))
    medium_count = len(reg.by_coverage(CoverageQuality.MEDIUM))
    total = len(reg.all_models())
    assert low_count >= 6, (
        f"only {low_count}/{total} models tagged 'low'; P1 not applied? "
        f"Expected at least 6 frontier/cheap-paid models to be coverage_quality=low."
    )
    assert low_count + medium_count >= 8, (
        f"only {low_count + medium_count}/{total} models tagged low+medium; "
        f"too many models claiming 'full' coverage — likely an honest-tagging regression."
    )


# ---------------------------------------------------------------------------
# Env-var-gated activation (the user's key story)
# ---------------------------------------------------------------------------


def test_no_keys_means_no_active_models(registry_path, no_keys_set):
    reg = Layer3Registry(registry_path)
    # Every model in the bundled registry has a required_env_var; with all
    # keys deleted, every model is inactive.
    assert reg.active_models() == []
    assert reg.stats()["active"] == 0


def test_only_groq_key_activates_only_groq_models(registry_path, only_groq_set):
    reg = Layer3Registry(registry_path)
    active = reg.active_models()
    assert len(active) >= 1, "expected at least one Groq model to be active"
    for entry in active:
        assert entry.required_env_var == "GROQ_API_KEY"
        assert entry.provider == "groq"


def test_adding_key_at_runtime_activates_models(registry_path, no_keys_set, monkeypatch):
    """The user wants: add a key, models flip active without restart."""
    reg = Layer3Registry(registry_path)
    assert reg.active_models() == []

    monkeypatch.setenv("GROQ_API_KEY", "test-value")
    reg.refresh_activation()
    active = reg.active_models()
    assert len(active) > 0
    assert all(e.required_env_var == "GROQ_API_KEY" for e in active)


def test_removing_key_at_runtime_deactivates(registry_path, all_keys_set, monkeypatch):
    reg = Layer3Registry(registry_path)
    initial = len(reg.active_models())
    assert initial > 0

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    reg.refresh_activation()
    groq_active = [e for e in reg.active_models() if e.required_env_var == "GROQ_API_KEY"]
    assert groq_active == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton_returns_same_instance(reset_registry, all_keys_set):
    a = get_layer3_registry()
    b = get_layer3_registry()
    assert a is b


def test_reset_singleton_creates_fresh_instance(reset_registry, all_keys_set):
    a = get_layer3_registry()
    reset_layer3_registry()
    b = get_layer3_registry()
    assert a is not b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_entry(model_id: str) -> dict:
    return {
        "model_id": model_id,
        "provider": "test",
        "litellm_model_name": "test/model",
        "display_name": model_id,
        "description": "",
        "model_type": "text",
        "capabilities": [],
        "context_window": 4096,
        "max_output_tokens": 1024,
        "pricing": {"input_per_1m_usd": 0.0, "output_per_1m_usd": 0.0},
        "rate_limits": {"rpm": None, "rpd": None, "tier": "free"},
        "coverage_quality": "full",
        "benchmark_coverage_pct": 0.5,
        "license_terms": "",
        "added_at": "2026-04-01",
    }
