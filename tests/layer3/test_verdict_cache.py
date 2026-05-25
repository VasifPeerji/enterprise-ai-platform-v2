"""
Tests for the Stage A verdict cache.

Two tiers to cover:
  • Tier 1 — exact-match (SHA256 of normalised query)
  • Tier 2 — semantic near-duplicate (Model2Vec ANN ≥ 0.93)

Also tests TTL staleness, schema-version invalidation, LRU eviction, and the
"don't cache cache_hits" guard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.layer0_model_infra.routing.feature_extractor import (
    FeatureExtractor,
)
from src.layer0_model_infra.routing.layer3_types import (
    LAYER3_SCHEMA_VERSION,
    Modality,
    RoutingDecision,
    RoutingSource,
)
from src.layer0_model_infra.routing.verdict_cache import (
    VerdictCache,
    VerdictCacheHit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def extractor() -> FeatureExtractor:
    return FeatureExtractor()


@pytest.fixture
def cache() -> VerdictCache:
    return VerdictCache(
        ttl_seconds=3600.0,
        max_entries=100,
        semantic_threshold=0.93,
    )


def _make_decision(
    *,
    extractor: FeatureExtractor,
    query: str,
    model_id: str = "llama-3.3-70b-versatile-groq",
    source: RoutingSource = RoutingSource.KNN_CORPUS,
    predicted_quality: float = 0.85,
) -> RoutingDecision:
    return RoutingDecision(
        request_id="test-req-1",
        timestamp=datetime.now(timezone.utc),
        selected_model=model_id,
        source=source,
        predicted_quality=predicted_quality,
        prediction_confidence="high",
        estimated_cost_usd=0.0,
        features=extractor.extract(query),
    )


# ---------------------------------------------------------------------------
# Tier 1 — exact match
# ---------------------------------------------------------------------------


def test_miss_on_empty_cache(cache, extractor):
    hit = cache.lookup("How do I deploy nginx?")
    assert hit is None


def test_exact_hit_after_put(cache, extractor):
    query = "How do I deploy nginx as a reverse proxy?"
    decision = _make_decision(extractor=extractor, query=query)
    cache.put(query, decision)
    hit = cache.lookup(query)
    assert hit is not None
    assert isinstance(hit, VerdictCacheHit)
    assert hit.kind == "exact"
    assert hit.decision.selected_model == decision.selected_model


def test_hit_is_case_and_whitespace_insensitive(cache, extractor):
    query = "How do I deploy nginx as a reverse proxy?"
    cache.put(query, _make_decision(extractor=extractor, query=query))

    hit = cache.lookup("HOW DO I DEPLOY NGINX AS A REVERSE PROXY?")
    assert hit is not None and hit.kind == "exact"

    hit2 = cache.lookup("How  do   I deploy nginx as a reverse proxy?")
    assert hit2 is not None and hit2.kind == "exact"


def test_different_queries_dont_collide(cache, extractor):
    q1 = "How do I deploy nginx?"
    q2 = "How do I deploy apache?"
    cache.put(q1, _make_decision(extractor=extractor, query=q1, model_id="model-a"))
    cache.put(q2, _make_decision(extractor=extractor, query=q2, model_id="model-b"))

    hit1 = cache.lookup(q1)
    hit2 = cache.lookup(q2)
    assert hit1.decision.selected_model == "model-a"
    assert hit2.decision.selected_model == "model-b"


def test_cache_hit_decisions_not_re_cached(cache, extractor):
    """Don't store decisions that came from the cache — circular."""
    query = "How do I deploy nginx?"
    decision = _make_decision(
        extractor=extractor, query=query, source=RoutingSource.CACHE_HIT
    )
    cache.put(query, decision)
    assert cache.lookup(query) is None


def test_empty_query_is_miss_not_crash(cache):
    assert cache.lookup("") is None
    assert cache.lookup("   ") is None


# ---------------------------------------------------------------------------
# Hit counting + LRU ordering
# ---------------------------------------------------------------------------


def test_hit_count_increments(cache, extractor):
    query = "What is Kubernetes?"
    cache.put(query, _make_decision(extractor=extractor, query=query))
    cache.lookup(query)
    cache.lookup(query)
    cache.lookup(query)
    stats = cache.stats()
    assert stats["hits_exact"] == 3


def test_lru_eviction_at_capacity(extractor):
    cache = VerdictCache(ttl_seconds=3600.0, max_entries=3, enable_semantic_tier=False)
    for i in range(5):
        q = f"Query number {i}"
        cache.put(q, _make_decision(extractor=extractor, query=q, model_id=f"m{i}"))
    stats = cache.stats()
    assert stats["size"] == 3
    assert stats["lru_evictions"] == 2

    # The two oldest entries should be gone
    assert cache.lookup("Query number 0") is None
    assert cache.lookup("Query number 1") is None
    # Most-recently put should still be there
    assert cache.lookup("Query number 4") is not None


def test_lookup_promotes_entry_to_mru(extractor):
    cache = VerdictCache(ttl_seconds=3600.0, max_entries=3, enable_semantic_tier=False)
    for i in range(3):
        q = f"Query number {i}"
        cache.put(q, _make_decision(extractor=extractor, query=q, model_id=f"m{i}"))

    # Touch query 0 → now it's the MRU
    cache.lookup("Query number 0")

    # Insert a new one → query 1 should be evicted (oldest non-touched)
    cache.put("Query number 3", _make_decision(extractor=extractor, query="Query number 3", model_id="m3"))

    assert cache.lookup("Query number 0") is not None
    assert cache.lookup("Query number 1") is None
    assert cache.lookup("Query number 2") is not None
    assert cache.lookup("Query number 3") is not None


# ---------------------------------------------------------------------------
# TTL + schema-version staleness
# ---------------------------------------------------------------------------


def test_stale_entry_evicted_on_lookup(extractor):
    cache = VerdictCache(ttl_seconds=0.01, max_entries=100, enable_semantic_tier=False)
    query = "Stale me"
    cache.put(query, _make_decision(extractor=extractor, query=query))
    # Force the entry to be old
    cache._entries[next(iter(cache._entries))].cached_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert cache.lookup(query) is None
    assert cache.stats()["stale_evictions"] >= 1


def test_schema_version_mismatch_invalidates(extractor):
    cache = VerdictCache(ttl_seconds=3600.0, max_entries=100, enable_semantic_tier=False)
    query = "Schema-version test"
    cache.put(query, _make_decision(extractor=extractor, query=query))
    # Force the stored decision to a stale schema version
    entry = next(iter(cache._entries.values()))
    entry.decision = entry.decision.model_copy(update={"version": "0.0.0-pre-release"})
    assert cache.lookup(query) is None
    assert cache.stats()["stale_evictions"] >= 1


# ---------------------------------------------------------------------------
# Tier 2 — semantic near-duplicate (skipped if model2vec unavailable)
# ---------------------------------------------------------------------------


def _semantic_tier_available() -> bool:
    cache = VerdictCache(ttl_seconds=3600.0, max_entries=100)
    return cache.stats()["embedder_available"]


@pytest.mark.skipif(not _semantic_tier_available(), reason="model2vec not installed")
def test_near_duplicate_hits_via_semantic_tier(extractor):
    cache = VerdictCache(
        ttl_seconds=3600.0,
        max_entries=100,
        semantic_threshold=0.80,  # relaxed for the test corpus
    )
    cached_query = "How do I configure nginx as a reverse proxy"
    cache.put(cached_query, _make_decision(extractor=extractor, query=cached_query))

    # A near-duplicate that won't match on exact signature
    hit = cache.lookup("how do i set up nginx as a reverse proxy please")
    assert hit is not None
    assert hit.kind == "semantic"
    assert hit.similarity >= 0.80


@pytest.mark.skipif(not _semantic_tier_available(), reason="model2vec not installed")
def test_dissimilar_query_misses_even_with_semantic_tier(extractor):
    cache = VerdictCache(
        ttl_seconds=3600.0,
        max_entries=100,
        semantic_threshold=0.93,
    )
    cache.put("How do I configure nginx?", _make_decision(
        extractor=extractor, query="How do I configure nginx?"))

    # Totally different topic — must not hit
    hit = cache.lookup("What is the cosmological constant?")
    assert hit is None


# ---------------------------------------------------------------------------
# Invalidation + clear
# ---------------------------------------------------------------------------


def test_invalidate_drops_specific_entry(cache, extractor):
    q1 = "Keep this one"
    q2 = "Drop this one"
    cache.put(q1, _make_decision(extractor=extractor, query=q1))
    cache.put(q2, _make_decision(extractor=extractor, query=q2))

    assert cache.invalidate(q2) is True
    assert cache.lookup(q1) is not None
    assert cache.lookup(q2) is None
    assert cache.invalidate(q2) is False  # already gone


def test_clear_drops_everything(cache, extractor):
    cache.put("x", _make_decision(extractor=extractor, query="x"))
    cache.put("y", _make_decision(extractor=extractor, query="y"))
    cache.clear()
    assert cache.stats()["size"] == 0
    assert cache.lookup("x") is None
