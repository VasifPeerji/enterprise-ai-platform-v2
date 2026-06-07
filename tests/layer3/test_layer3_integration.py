"""
Integration tests for the Layer 3 → router.py wiring (3.6).

Uses a fake kNN router so the full router pipeline (L0 fast-path, L1 modality
gate, L2 semantic memory, then the Layer 3 branch + adapter) is exercised
without a live encoder/Qdrant or any LLM call. A fresh legacy ModelRegistry is
injected so the lazy Layer 3 model registration doesn't leak into the global
registry / other tests.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from src.layer0_model_infra.registry import ModelRegistry
from src.layer0_model_infra.routing.layer3_types import (
    HighRiskDomain,
    Modality,
    QueryFeatures,
    RoutingDecision as L3Decision,
    RoutingSource,
)


def _l3_decision(model="llama-3.1-8b-instant-groq", source=RoutingSource.KNN_CORPUS,
                 pq=0.82, confidence="high", high_risk=None):
    return L3Decision(
        request_id="l3x", timestamp=datetime.now(timezone.utc),
        selected_model=model, source=source, predicted_quality=pq,
        prediction_confidence=confidence, estimated_cost_usd=0.0,
        features=QueryFeatures(
            language="en", modality=Modality.TEXT, high_risk_domain=high_risk,
            estimated_input_tokens=20, estimated_output_tokens=400, char_count=80,
        ),
        qualifying_models=[model, "llama-3.3-70b-versatile-groq"],
        feature_cell="text:en:none:normal", quality_floor_base=0.65,
        effective_floor=0.65, latency_ms=42.0,
    )


class _FakeKnn:
    def __init__(self, decision=None, raises=False):
        self._d = decision
        self._raises = raises

    def route(self, query, *, layer1_analysis=None, request_id=None):
        if self._raises:
            raise RuntimeError("knn boom")
        return self._d


@pytest.fixture(scope="module")
def router():
    from src.layer0_model_infra.routing import registry_loader
    saved = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = "test-key"
    registry_loader.reset_layer3_registry()

    from src.layer0_model_infra.router import ModelRouter
    r = ModelRouter()
    r.registry = ModelRegistry()   # isolate Layer 3 registration from the global registry
    # The kNN router is active by default now, so __init__ already registered the
    # Layer 3 models into the previous registry; re-register them into this fresh
    # isolated one so model resolution still finds them.
    r._layer3_models_registered = False
    r._ensure_layer3_models_registered()
    r._layer3_canary = 1.0
    yield r

    if saved is None:
        os.environ.pop("GROQ_API_KEY", None)
    else:
        os.environ["GROQ_API_KEY"] = saved
    registry_loader.reset_layer3_registry()


def test_use_layer3_canary_split(router):
    router._layer3_canary = 0.0
    assert router._use_layer3("req-a") is False     # wired but inactive
    router._layer3_canary = 1.0
    assert router._use_layer3("req-a") is True
    router._layer3_canary = 0.5
    # stable per request_id (no flip on retry)
    assert router._use_layer3("req-x") == router._use_layer3("req-x")
    router._layer3_canary = 1.0


def test_full_route_through_layer3(router):
    router._knn_router = _FakeKnn(decision=_l3_decision())
    router._layer3_canary = 1.0
    d = router.route("explain optimistic vs pessimistic locking in databases in detail")
    assert d.pipeline_metadata["router"] == "layer3_knn"
    assert d.selected_model.model_id == "llama-3.1-8b-instant-groq"
    # the litellm execution name must survive the adapter (gateway needs it)
    assert d.selected_model.model_name == "groq/llama-3.1-8b-instant"
    assert d.pipeline_metadata["layer3_source"] == "knn_corpus"
    assert d.confidence_level == "HIGH"
    assert d.triage_result["synthesized"] is True
    assert d.estimated_cost_usd == 0.0
    assert [m.model_id for m in d.fallback_models] == ["llama-3.3-70b-versatile-groq"]


def test_layer3_failure_returns_none_for_legacy_fallthrough(router):
    router._knn_router = _FakeKnn(raises=True)
    from src.layer0_model_infra.routing.modality_gate import get_modality_gate
    ma = get_modality_gate().analyze("a normal query about something")
    # _route_via_layer3 swallows the failure and returns None so route() can
    # fall through to the legacy pipeline.
    assert router._route_via_layer3("a normal query", ma, None, None, "r1") is None
    router._knn_router = _FakeKnn(decision=_l3_decision())


def test_adapt_carries_audit_trail(router):
    from src.layer0_model_infra.routing.modality_gate import get_modality_gate
    router._ensure_layer3_models_registered()
    md = router.registry.get_model("llama-3.1-8b-instant-groq")
    ma = get_modality_gate().analyze("explain database locking")
    d = router._adapt_layer3_decision(_l3_decision(), md, ma, None, None)
    assert d.pipeline_metadata["layer3_feature_cell"] == "text:en:none:normal"
    assert d.pipeline_metadata["layer3_qualifying_models"] == [
        "llama-3.1-8b-instant-groq", "llama-3.3-70b-versatile-groq"
    ]
    assert d.pipeline_metadata["layer3_effective_floor"] == 0.65
    assert d.uncertainty_score["synthesized"] is True


def test_high_risk_domain_maps_to_triage_domain(router):
    from src.layer0_model_infra.routing.modality_gate import get_modality_gate
    router._ensure_layer3_models_registered()
    md = router.registry.get_model("llama-3.1-8b-instant-groq")
    ma = get_modality_gate().analyze("a medical question")
    d = router._adapt_layer3_decision(
        _l3_decision(high_risk=HighRiskDomain.MEDICAL), md, ma, None, None
    )
    assert d.triage_result["domain"] == "medical"


def test_fallback_source_maps(router):
    from src.layer0_model_infra.routing.modality_gate import get_modality_gate
    router._ensure_layer3_models_registered()
    md = router.registry.get_model("llama-3.1-8b-instant-groq")
    ma = get_modality_gate().analyze("some query")
    l3 = _l3_decision(source=RoutingSource.FALLBACK, pq=None, confidence="low")
    d = router._adapt_layer3_decision(l3, md, ma, None, None)
    assert d.pipeline_metadata["layer3_source"] == "fallback"
    assert d.confidence_level == "MEDIUM"
