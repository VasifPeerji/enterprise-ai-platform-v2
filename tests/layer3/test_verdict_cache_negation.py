"""
Tests for the verdict-cache negation/polarity guard (M3).

Uses a forced-match threshold so the semantic tier always fires, isolating the
guard: with it on, an install-vs-uninstall polarity flip is rejected; with it
off, the same near-duplicate would be served the wrong decision.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.layer0_model_infra.routing.layer3_types import (
    Modality,
    QueryFeatures,
    RoutingDecision,
    RoutingSource,
)
from src.layer0_model_infra.routing.verdict_cache import VerdictCache, _negation_score


def _decision() -> RoutingDecision:
    return RoutingDecision(
        request_id="r", timestamp=datetime.now(timezone.utc),
        selected_model="llama-3.1-8b-instant-groq", source=RoutingSource.KNN_CORPUS,
        estimated_cost_usd=0.0,
        features=QueryFeatures(
            language="en", modality=Modality.TEXT,
            estimated_input_tokens=5, estimated_output_tokens=400,
        ),
    )


def _forced_cache(negation_guard: bool) -> VerdictCache:
    # threshold -1.0 → the single best neighbor always clears it, so the
    # semantic tier fires regardless of the actual cosine.
    return VerdictCache(semantic_threshold=-1.0, enable_negation_guard=negation_guard)


def test_negation_score_distinguishes_polarity():
    assert _negation_score("how do I install the nginx package") < _negation_score(
        "how do I uninstall the nginx package"
    )


def test_guard_rejects_polarity_flip():
    cache = _forced_cache(negation_guard=True)
    if not (cache._embedder and cache._embedder.available):
        pytest.skip("model2vec embedder unavailable")
    cache.put("please install the package now", _decision())
    # Tier-1 misses (different text); Tier-2 would match but polarity flipped.
    assert cache.lookup("please uninstall the package now") is None


def test_without_guard_polarity_flip_hits():
    cache = _forced_cache(negation_guard=False)
    if not (cache._embedder and cache._embedder.available):
        pytest.skip("model2vec embedder unavailable")
    cache.put("please install the package now", _decision())
    hit = cache.lookup("please uninstall the package now")
    assert hit is not None and hit.kind == "semantic"


def test_guard_allows_same_polarity_paraphrase():
    cache = _forced_cache(negation_guard=True)
    if not (cache._embedder and cache._embedder.available):
        pytest.skip("model2vec embedder unavailable")
    cache.put("please install the package now", _decision())
    # same polarity (no negation flip) → guard does not block the semantic hit
    hit = cache.lookup("can you install the package right now")
    assert hit is not None and hit.kind == "semantic"
