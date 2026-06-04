"""
Tests for the Stage C kNN router.

The selection logic (floor application, low-coverage penalty, high-risk floor,
cost minimization, ε-exploration, warmup gating) is unit-tested with injected
synthetic dependencies — no live encoder or Qdrant needed. Prediction
(kNN-weighted vs aggregate prior) is tested against a synthetic outcome store.
A single guarded end-to-end test exercises the real encoder + live Qdrant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.layer0_model_infra.routing.aggregate_scores import get_aggregate_scores
from src.layer0_model_infra.routing.calibration_store import CalibrationStore
from src.layer0_model_infra.routing.feature_extractor import FeatureExtractor
from src.layer0_model_infra.routing.knn_router import (
    KnnRouter,
    length_adjusted_similarity,
    make_feature_cell,
)
from src.layer0_model_infra.routing.layer3_types import (
    HighRiskDomain,
    Modality,
    QueryFeatures,
    RoutingDecision,
    RoutingSource,
)
from src.layer0_model_infra.routing.outcome_store import OutcomeStore
from src.layer0_model_infra.routing.registry_loader import get_layer3_registry


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _SeqRng:
    """Deterministic stand-in for random.Random: random() yields a fixed
    sequence (repeating the last value), choice() picks a fixed index."""

    def __init__(self, randoms=None, choice_index: int = 0) -> None:
        self._randoms = list(randoms) if randoms else [1.0]
        self._i = 0
        self._ci = choice_index

    def random(self) -> float:
        v = self._randoms[min(self._i, len(self._randoms) - 1)]
        self._i += 1
        return v

    def choice(self, seq):
        seq = list(seq)
        return seq[self._ci % len(seq)]


def _neighbors(qids, score: float = 0.8, text: str = "x" * 100):
    return [
        SimpleNamespace(score=score, payload={"question_global_id": q, "question_text": text})
        for q in qids
    ]


def _features(modality: Modality = Modality.TEXT, high_risk=None, char_count: int = 100) -> QueryFeatures:
    return QueryFeatures(
        language="en",
        modality=modality,
        high_risk_domain=high_risk,
        estimated_input_tokens=50,
        estimated_output_tokens=400,
        char_count=char_count,
    )


@pytest.fixture
def synthetic_outcomes(tmp_path: Path) -> Path:
    now = datetime.now(timezone.utc)
    qids = ["livebench:n1", "livebench:n2", "livebench:n3", "livebench:n4", "livebench:n5"]
    rows_qid, rows_model, rows_outcome = [], [], []

    def add(model, pairs):
        for q, o in pairs:
            rows_qid.append(q)
            rows_model.append(model)
            rows_outcome.append(o)

    # full-coverage model with 4 outcomes on the neighbor set → uses kNN
    add("llama-3.3-70b-versatile-groq", [(qids[0], 1.0), (qids[1], 1.0), (qids[2], 0.0), (qids[3], 1.0)])
    # full-coverage model with only 2 outcomes → falls to prior
    add("llama-3.1-8b-instant-groq", [(qids[0], 1.0), (qids[1], 1.0)])
    # low-coverage model with 5 outcomes → STILL prior (coverage_quality=low)
    add("claude-opus-4-5", [(q, 1.0) for q in qids])

    table = pa.table(
        {
            "question_global_id": rows_qid,
            "model_id": rows_model,
            "outcome": rows_outcome,
            "source_url": ["https://livebench.ai"] * len(rows_qid),
            "ingested_at": [now] * len(rows_qid),
        },
        schema=pa.schema([
            ("question_global_id", pa.string()),
            ("model_id", pa.string()),
            ("outcome", pa.float32()),
            ("source_url", pa.string()),
            ("ingested_at", pa.timestamp("us", tz="UTC")),
        ]),
    )
    path = tmp_path / "outcomes.parquet"
    pq.write_table(table, path, compression="zstd")
    return path


def _router(tmp_path, *, outcomes=None, rng=None, cooldown=None) -> KnnRouter:
    from src.layer0_model_infra.routing.rate_limit_cooldown import RateLimitCooldown
    return KnnRouter(
        registry=get_layer3_registry(),
        outcome_store=OutcomeStore(outcomes) if outcomes else None,
        aggregate_scores=get_aggregate_scores(),
        calibration_store=CalibrationStore(tmp_path / "calibration.parquet"),
        cooldown=cooldown or RateLimitCooldown(),  # fresh, no singleton leakage
        rng=rng or _SeqRng([1.0]),
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_make_feature_cell():
    f = _features(Modality.CODE, high_risk=HighRiskDomain.MEDICAL)
    assert make_feature_cell(f) == "code:en:medical:normal"
    assert make_feature_cell(_features(Modality.TEXT)) == "text:en:none:normal"


def test_length_adjusted_similarity():
    # equal lengths → score unchanged
    assert length_adjusted_similarity(100, 100, 0.8, 0.7, 0.3) == pytest.approx(0.8)
    # very different lengths → discounted toward score * base
    assert length_adjusted_similarity(10, 1000, 0.8, 0.7, 0.3) == pytest.approx(0.8 * (0.7 + 0.3 * 0.01))
    # zero length guard
    assert length_adjusted_similarity(0, 100, 0.8, 0.7, 0.3) == pytest.approx(0.8 * 0.7)


# ---------------------------------------------------------------------------
# _predict_qualities — kNN vs prior
# ---------------------------------------------------------------------------


def test_predict_uses_knn_when_enough_outcomes(all_keys_set, reset_registry, synthetic_outcomes, tmp_path):
    router = _router(tmp_path, outcomes=synthetic_outcomes)
    feats = _features(Modality.TEXT)
    qids = ["livebench:n1", "livebench:n2", "livebench:n3", "livebench:n4", "livebench:n5"]
    neighbors = _neighbors(qids)
    cell = make_feature_cell(feats)

    qualities, confidence, prior_used = router._predict_qualities(feats, neighbors, cell)

    # 4 equal-similarity outcomes [1,1,0,1] → weighted mean 0.75
    assert qualities["llama-3.3-70b-versatile-groq"] == pytest.approx(0.75, abs=1e-3)
    assert confidence["llama-3.3-70b-versatile-groq"] == "high"
    assert prior_used["llama-3.3-70b-versatile-groq"] is False


def test_predict_falls_to_prior_below_min_outcomes(all_keys_set, reset_registry, synthetic_outcomes, tmp_path):
    router = _router(tmp_path, outcomes=synthetic_outcomes)
    feats = _features(Modality.TEXT)
    neighbors = _neighbors(["livebench:n1", "livebench:n2", "livebench:n3", "livebench:n4", "livebench:n5"])
    cell = make_feature_cell(feats)
    qualities, confidence, prior_used = router._predict_qualities(feats, neighbors, cell)

    # only 2 outcomes → prior
    assert prior_used["llama-3.1-8b-instant-groq"] is True
    assert confidence["llama-3.1-8b-instant-groq"] == "low"
    expected = get_aggregate_scores().prior_quality("llama-3.1-8b-instant-groq", Modality.TEXT)
    assert qualities["llama-3.1-8b-instant-groq"] == pytest.approx(expected, abs=1e-6)


def test_predict_low_coverage_always_uses_prior(all_keys_set, reset_registry, synthetic_outcomes, tmp_path):
    router = _router(tmp_path, outcomes=synthetic_outcomes)
    feats = _features(Modality.TEXT)
    neighbors = _neighbors(["livebench:n1", "livebench:n2", "livebench:n3", "livebench:n4", "livebench:n5"])
    cell = make_feature_cell(feats)
    qualities, confidence, prior_used = router._predict_qualities(feats, neighbors, cell)

    # claude-opus-4-5 has 5 outcomes but coverage_quality=low → prior, not kNN
    assert prior_used["claude-opus-4-5"] is True


# ---------------------------------------------------------------------------
# _choose — floor, penalty, cost-min
# ---------------------------------------------------------------------------


def test_cost_minimization_picks_cheapest_qualifier(all_keys_set, reset_registry, tmp_path):
    router = _router(tmp_path)
    feats = _features(Modality.TEXT)
    qualities = {
        "llama-3.1-8b-instant-groq": 0.70,    # free
        "gemini-2.5-flash": 0.90,               # paid
        "gpt-4o": 0.95,                       # paid, pricier
    }
    confidence = {k: "high" for k in qualities}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert decision.source == RoutingSource.KNN_CORPUS
    assert decision.selected_model == "llama-3.1-8b-instant-groq"  # cheapest above floor
    assert set(decision.qualifying_models) == set(qualities)       # all cleared 0.65


def test_below_floor_models_excluded(all_keys_set, reset_registry, tmp_path):
    router = _router(tmp_path)
    feats = _features(Modality.TEXT)
    qualities = {"llama-3.1-8b-instant-groq": 0.50, "gemini-2.5-flash": 0.90}  # 0.50 < 0.65
    confidence = {k: "high" for k in qualities}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert decision.selected_model == "gemini-2.5-flash"
    assert "llama-3.1-8b-instant-groq" not in decision.qualifying_models


def test_low_coverage_penalty_blocks_frontier_on_prior(all_keys_set, reset_registry, tmp_path):
    # claude-opus-4-5 is coverage_quality=low → effective floor 0.65 + 0.10 = 0.75.
    # A 0.70 prediction clears the default floor but NOT the penalized one.
    router = _router(tmp_path)
    feats = _features(Modality.TEXT)
    qualities = {"claude-opus-4-5": 0.70, "llama-3.1-8b-instant-groq": 0.66}
    confidence = {k: "high" for k in qualities}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert "claude-opus-4-5" not in decision.qualifying_models
    assert decision.selected_model == "llama-3.1-8b-instant-groq"


def test_no_qualifier_falls_back(all_keys_set, reset_registry, tmp_path):
    router = _router(tmp_path)
    feats = _features(Modality.TEXT)
    qualities = {"claude-opus-4-5": 0.70}  # below penalized floor 0.75, nothing else
    confidence = {"claude-opus-4-5": "low"}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert decision.source == RoutingSource.FALLBACK
    assert decision.fallback_reason == "no_model_above_floor"


def test_high_risk_raises_floor(all_keys_set, reset_registry, tmp_path):
    router = _router(tmp_path)
    feats = _features(Modality.TEXT, high_risk=HighRiskDomain.MEDICAL)  # base floor 0.75
    # llama-3.1-8b is full-coverage → effective floor is the 0.75 base; 0.70 misses it.
    # gemini-2.5-flash is low-coverage → effective floor 0.75 + 0.10 penalty = 0.85, so it
    # needs 0.90 to qualify (a re-tag to medium/full would only lower that bar).
    qualities = {"llama-3.1-8b-instant-groq": 0.70, "gemini-2.5-flash": 0.90}
    confidence = {k: "high" for k in qualities}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert decision.quality_floor_base == 0.75
    assert "llama-3.1-8b-instant-groq" not in decision.qualifying_models  # 0.70 < 0.75
    assert decision.selected_model == "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# _choose — exploration & warmup
# ---------------------------------------------------------------------------


def test_exploration_forces_borderline_model(all_keys_set, reset_registry, tmp_path):
    # rng.random()=0.0 → always explore. 0.62 is within [floor-band, floor) = [0.60, 0.65).
    router = _router(tmp_path, rng=_SeqRng([0.0]))
    feats = _features(Modality.TEXT)
    qualities = {"llama-3.1-8b-instant-groq": 0.62, "gemini-2.5-flash": 0.90}
    confidence = {k: "high" for k in qualities}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert decision.source == RoutingSource.EXPLORATION
    assert decision.selected_model == "llama-3.1-8b-instant-groq"
    assert decision.predicted_quality == pytest.approx(0.62)


def test_warmup_does_not_fire_for_established_models(all_keys_set, reset_registry, tmp_path):
    # Both models here were added 2026-04-01 (well past max_age_days), so even
    # when the dice say "warm up" the warmup pool is empty → normal cost-min.
    # gpt-4o is paid, so the free llama stays cheapest.
    # randoms: skip exploration (0.99), would-fire warmup (0.0).
    router = _router(tmp_path, rng=_SeqRng([0.99, 0.0]))
    feats = _features(Modality.TEXT)
    qualities = {"llama-3.1-8b-instant-groq": 0.80, "gpt-4o": 0.95}
    confidence = {k: "high" for k in qualities}
    decision = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert decision.source == RoutingSource.KNN_CORPUS
    assert decision.selected_model == "llama-3.1-8b-instant-groq"


def test_is_in_warmup_logic(all_keys_set, reset_registry, tmp_path):
    router = _router(tmp_path)
    reg = get_layer3_registry()
    established = reg.get("llama-3.1-8b-instant-groq")  # added 2026-04-01
    # "now" far in the future → aged out
    assert router._is_in_warmup(established, now=datetime(2026, 12, 1, tzinfo=timezone.utc)) is False
    # a freshly-added model with no observations → in warmup
    fresh = established.model_copy(update={"added_at": datetime(2026, 5, 29, tzinfo=timezone.utc)})
    assert router._is_in_warmup(fresh, now=datetime(2026, 5, 30, tzinfo=timezone.utc)) is True


# ---------------------------------------------------------------------------
# Unsupported modality → Stage D before search
# ---------------------------------------------------------------------------


def test_vision_modality_routes_to_fallback_without_search(all_keys_set, reset_registry, tmp_path):
    # No encoder/qdrant injected → if route() tried to search it would crash.
    # Vision must short-circuit to fallback first.
    router = _router(tmp_path)
    # Force the extractor to report VISION by passing a layer1-like object.
    analysis = SimpleNamespace(
        language="en", primary_modality=SimpleNamespace(value="image"),
        requires_vision=True, requires_audio=False, requires_code_model=False, token_count=20,
    )
    decision = router.route("what is in this picture?", layer1_analysis=analysis)
    assert decision.source == RoutingSource.FALLBACK
    assert decision.fallback_reason == "unsupported_modality_no_coverage"
    assert decision.latency_ms >= 0


# ---------------------------------------------------------------------------
# End-to-end over the live encoder + Qdrant (guarded)
# ---------------------------------------------------------------------------


def _live_qdrant_ok() -> bool:
    try:
        from qdrant_client import QdrantClient
        from src.shared.config import get_settings
        s = get_settings()
        # Honor the configured QDRANT_HOST (not a hardcoded "localhost", which
        # resolves to IPv6 ::1 on this Windows + Docker Desktop host and isn't
        # forwarded by the port-proxy).
        c = QdrantClient(host=s.QDRANT_HOST, port=s.QDRANT_PORT, timeout=3.0)
        return c.get_collection("layer3_benchmark_corpus").points_count > 0
    except Exception:
        return False


@pytest.mark.skipif(not _live_qdrant_ok(), reason="live Qdrant collection unavailable")
def test_route_end_to_end_real(all_keys_set, reset_registry):
    router = KnnRouter()  # real encoder + qdrant + stores
    decision = router.route("How do I deploy a Python web service with Docker and nginx?")
    reg = get_layer3_registry()
    assert reg.has(decision.selected_model)
    assert decision.source in {
        RoutingSource.KNN_CORPUS, RoutingSource.EXPLORATION,
        RoutingSource.WARMUP, RoutingSource.FALLBACK,
    }
    assert decision.latency_ms > 0
    # A code/text query is covered by the corpus → should not be the
    # "unsupported modality" fallback.
    assert decision.fallback_reason != "unsupported_modality_no_coverage"


# ---------------------------------------------------------------------------
# Robustness: graceful degradation, cache policy, context window (S2/S3/M1/M6)
# ---------------------------------------------------------------------------


class _FakeEncoder:
    def encode(self, text, **kw):
        import numpy as np
        return np.ones(384, dtype=np.float32)


class _BoomEncoder:
    def encode(self, *a, **k):
        raise RuntimeError("encoder boom")


class _FakeQdrant:
    def __init__(self, points):
        self._points = points

    def query_points(self, **kw):
        return SimpleNamespace(points=list(self._points))

    def get_collections(self):
        return SimpleNamespace(collections=[])


class _BoomQdrant:
    def query_points(self, **kw):
        raise RuntimeError("qdrant down")

    def get_collections(self):
        return SimpleNamespace(collections=[])


def _route_router(tmp_path, neighbors, *, encoder=None, qdrant=None, cache=None,
                  cache_enabled=False, rng=None):
    from src.layer0_model_infra.config.routing_config import get_routing_config
    base = get_routing_config().layer3
    config = base.model_copy(update={
        "verdict_cache": base.verdict_cache.model_copy(update={"enable": cache_enabled}),
    })
    return KnnRouter(
        config=config,
        registry=get_layer3_registry(),
        aggregate_scores=get_aggregate_scores(),
        calibration_store=CalibrationStore(tmp_path / "cal.parquet"),
        verdict_cache=cache,
        # Regex-only extractor: keeps the high-risk Tier-2 model out of the
        # route-level unit tests (the dedicated high_risk tests cover Tier-2).
        feature_extractor=FeatureExtractor(high_risk_tier2_mode="off"),
        encoder=encoder if encoder is not None else _FakeEncoder(),
        qdrant_client=qdrant if qdrant is not None else _FakeQdrant(neighbors),
        rng=rng or _SeqRng([1.0]),
    )


def test_is_cacheable_policy():
    def mk(source, reason=None):
        return RoutingDecision(
            request_id="r", timestamp=datetime.now(timezone.utc), selected_model="m",
            source=source, estimated_cost_usd=0.0, features=_features(), fallback_reason=reason,
        )
    assert KnnRouter._is_cacheable(mk(RoutingSource.KNN_CORPUS)) is True
    assert KnnRouter._is_cacheable(mk(RoutingSource.FALLBACK, "insufficient_neighbors")) is True
    assert KnnRouter._is_cacheable(mk(RoutingSource.EXPLORATION)) is False
    assert KnnRouter._is_cacheable(mk(RoutingSource.WARMUP)) is False
    assert KnnRouter._is_cacheable(mk(RoutingSource.FORCED)) is False
    assert KnnRouter._is_cacheable(mk(RoutingSource.FALLBACK, "search_error")) is False


def test_encoder_error_degrades_to_fallback(all_keys_set, reset_registry, tmp_path):
    router = _route_router(tmp_path, _neighbors([f"livebench:n{i}" for i in range(5)]), encoder=_BoomEncoder())
    d = router.route("a normal text question about geography")
    assert d.source == RoutingSource.FALLBACK
    assert d.fallback_reason == "search_error"


def test_qdrant_error_degrades_to_fallback(all_keys_set, reset_registry, tmp_path):
    router = _route_router(tmp_path, [], qdrant=_BoomQdrant())
    d = router.route("a normal text question about geography")
    assert d.source == RoutingSource.FALLBACK
    assert d.fallback_reason == "search_error"


def test_cache_hit_replays_on_identical_query(all_keys_set, reset_registry, tmp_path):
    from src.layer0_model_infra.routing.verdict_cache import VerdictCache
    cache = VerdictCache(enable_semantic_tier=False)
    neighbors = _neighbors([f"livebench:n{i}" for i in range(5)])
    router = _route_router(tmp_path, neighbors, cache=cache, cache_enabled=True)
    d1 = router.route("how do i deploy a service")
    d2 = router.route("how do i deploy a service")
    assert d1.source == RoutingSource.KNN_CORPUS
    assert d2.source == RoutingSource.CACHE_HIT
    assert d2.cache_hit_kind == "exact"
    assert d2.selected_model == d1.selected_model


def test_cache_skips_inactive_cached_model(only_groq_set, reset_registry, tmp_path):
    from src.layer0_model_infra.routing.verdict_cache import VerdictCache
    cache = VerdictCache(enable_semantic_tier=False)
    seed = RoutingDecision(
        request_id="seed", timestamp=datetime.now(timezone.utc),
        selected_model="gemini-2.5-flash",  # inactive when only GROQ is set
        source=RoutingSource.KNN_CORPUS, predicted_quality=0.9, estimated_cost_usd=0.0,
        features=_features(),
    )
    cache.put("revalidate this query", seed)
    neighbors = _neighbors([f"livebench:n{i}" for i in range(5)])
    router = _route_router(tmp_path, neighbors, cache=cache, cache_enabled=True)
    d = router.route("revalidate this query")
    assert d.source != RoutingSource.CACHE_HIT          # stale entry rejected
    assert get_layer3_registry().get(d.selected_model).is_active


def test_context_window_excludes_too_small_models(all_keys_set, reset_registry, tmp_path):
    router = _router(tmp_path)
    feats = QueryFeatures(
        language="en", modality=Modality.TEXT,
        estimated_input_tokens=500_000, estimated_output_tokens=400, char_count=100,
    )
    qualities = {"llama-3.1-8b-instant-groq": 0.9, "gemini-2.5-flash": 0.9}  # 8k ctx vs 2M ctx
    confidence = {k: "high" for k in qualities}
    d = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert "llama-3.1-8b-instant-groq" not in d.qualifying_models
    assert d.selected_model == "gemini-2.5-flash"


def test_cost_min_skips_rate_limited_model(all_keys_set, reset_registry, tmp_path):
    from src.layer0_model_infra.routing.rate_limit_cooldown import RateLimitCooldown
    cooldown = RateLimitCooldown()
    cooldown.mark("llama-3.1-8b-instant-groq", 100)  # cheapest free model on cooldown
    router = _router(tmp_path, cooldown=cooldown)
    feats = _features(Modality.TEXT)
    qualities = {"llama-3.1-8b-instant-groq": 0.9, "llama-3.3-70b-versatile-groq": 0.9}
    confidence = {k: "high" for k in qualities}
    d = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert "llama-3.1-8b-instant-groq" not in d.qualifying_models
    assert d.selected_model == "llama-3.3-70b-versatile-groq"


def test_all_qualifying_rate_limited_falls_back(all_keys_set, reset_registry, tmp_path):
    from src.layer0_model_infra.routing.rate_limit_cooldown import RateLimitCooldown
    cooldown = RateLimitCooldown()
    cooldown.mark("llama-3.1-8b-instant-groq", 100)
    router = _router(tmp_path, cooldown=cooldown)
    feats = _features(Modality.TEXT)
    qualities = {"llama-3.1-8b-instant-groq": 0.9}  # only floor-clearer, but cooling
    confidence = {"llama-3.1-8b-instant-groq": "high"}
    d = router._choose("q", feats, qualities, confidence, [], "rid", make_feature_cell(feats))
    assert d.source == RoutingSource.FALLBACK
    assert d.fallback_reason == "all_qualifying_rate_limited"
