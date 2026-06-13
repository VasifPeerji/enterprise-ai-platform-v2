"""
📁 File: src/layer0_model_infra/routing/knn_router.py
Layer: Layer 0 — Layer 3 redesign (Stage C orchestrator — the core)
Purpose: Benchmark-grounded kNN router. Predicts per-model quality from public
         benchmark outcomes and selects the cheapest model that clears a floor.
Depends on: verdict_cache, feature_extractor, outcome_store, aggregate_scores,
            calibration_store, registry_loader, fallback_router, qdrant, an encoder
Used by: router.py (Batch 3.6 integration), the dashboard, the validation harness

Pipeline (see docs/layers/LAYER_3_RESEARCH.md for the full rationale):

  Stage A  verdict cache         exact + semantic; sub-ms short-circuit
  Stage B  feature extraction    reuse Layer 1's ModalityAnalysis when present
  Stage C  kNN over the corpus   encode → Qdrant ANN → per-model quality:
              • neighbors with ≥ min_outcomes outcomes → similarity-weighted
                average (length-adjusted similarity, P3)
              • otherwise / coverage_quality=low        → aggregate prior
              • × online calibration multiplier
            then: quality floor (+0.10 low-coverage penalty, 0.75 high-risk),
            ε-exploration (P2), warmup forcing (P4), cost minimization.
  Stage D  fallback              off-distribution / nothing clears the floor

Anti-over-routing is structural: cost minimization runs INSIDE the qualifying
set. A model below its floor can never win, however cheap. Anti-under-routing is
the floor itself (+ Layer 7 quality eval + Layer 8 escalation downstream).

No model training anywhere. The only thing that "learns" is the calibration EMA
(calibration_store), updated post-Layer-7 from observed quality.

Every external dependency is injectable so the selection logic can be unit-tested
without a live encoder or Qdrant; production wiring uses the module singletons.
"""

from __future__ import annotations

import random
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.layer0_model_infra.routing.fallback_router import (
    FallbackRouter,
    REASON_ALL_RATE_LIMITED,
    REASON_INSUFFICIENT_NEIGHBORS,
    REASON_NO_MODEL_ABOVE_FLOOR,
    REASON_SEARCH_ERROR,
    REASON_UNSUPPORTED_MODALITY,
)
from src.layer0_model_infra.routing.layer3_types import (
    CoverageQuality,
    Modality,
    QueryFeatures,
    RoutingDecision,
    RoutingSource,
)
from src.shared.config import get_settings
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.layer0_model_infra.routing.modality_gate import ModalityAnalysis

logger = get_logger(__name__)


# Modalities the benchmark corpus actually covers (measured: text/math/code).
# Vision / multimodal queries are routed to Stage D before any search, since a
# kNN hit would necessarily be a different-modality question.
_CORPUS_MODALITIES = frozenset({Modality.TEXT, Modality.CODE, Modality.MATH})

# Param-count proxy (the "<N>b" in a model name) used to break cost ties among
# equally-priced (free) models — see KnnRouter._model_compute_cost.
_MODEL_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def _as_modality(value) -> Modality:
    return value if isinstance(value, Modality) else Modality(value)


def make_feature_cell(features: QueryFeatures) -> str:
    """Calibration cell key: '{modality}:{language}:{high_risk}:{difficulty}'."""
    modality = _as_modality(features.modality).value
    high_risk = features.high_risk_domain.value if features.high_risk_domain else "none"
    difficulty = (
        features.difficulty_signal.value
        if hasattr(features.difficulty_signal, "value")
        else str(features.difficulty_signal)
    )
    return f"{modality}:{features.language}:{high_risk}:{difficulty}"


def length_adjusted_similarity(
    query_len: int,
    neighbor_len: int,
    score: float,
    base: float,
    span: float,
) -> float:
    """P3 — re-weight a raw cosine score by how close the query and neighbor are
    in length. ``adjusted = score · (base + span · length_ratio)`` where
    length_ratio = min/max of the two lengths. Identical lengths leave the score
    untouched; very different lengths discount it down to ``score · base``.
    """
    if query_len <= 0 or neighbor_len <= 0:
        ratio = 0.0
    else:
        ratio = min(query_len, neighbor_len) / max(query_len, neighbor_len)
    return score * (base + span * ratio)


class KnnRouter:
    """Stage C orchestrator. Construct via get_knn_router() in production; pass
    explicit dependencies in tests."""

    def __init__(
        self,
        *,
        config=None,
        settings=None,
        registry=None,
        outcome_store=None,
        aggregate_scores=None,
        calibration_store=None,
        verdict_cache=None,
        feature_extractor=None,
        fallback_router=None,
        encoder=None,
        qdrant_client=None,
        rng=None,
        cooldown=None,
        quality_head=None,
    ) -> None:
        self._config = config or get_routing_config().layer3
        self._settings = settings or get_settings()

        # Light dependencies — injected or lazily resolved via the singletons.
        self._registry = registry
        self._outcome_store = outcome_store
        self._aggregate_scores = aggregate_scores
        self._calibration = calibration_store
        self._verdict_cache = verdict_cache
        self._feature_extractor = feature_extractor
        self._fallback = fallback_router
        self._cooldown = cooldown
        self._quality_head = quality_head

        # Heavy / external dependencies — lazily built.
        self._encoder = encoder
        self._encoder_device: Optional[str] = None
        self._encoder_lock = threading.Lock()
        self._qdrant = qdrant_client

        self._rng = rng or random.Random()

        # Resolve the effective quality floors once (env override → config).
        qf = self._config.quality_floor
        self._floor_default = (
            self._settings.LAYER3_QUALITY_FLOOR_DEFAULT
            if self._settings.LAYER3_QUALITY_FLOOR_DEFAULT is not None
            else qf.default
        )
        self._floor_high_risk = (
            self._settings.LAYER3_QUALITY_FLOOR_HIGH_RISK
            if self._settings.LAYER3_QUALITY_FLOOR_HIGH_RISK is not None
            else qf.high_risk
        )

    # ------------------------------------------------------------------
    # Lazy dependency accessors
    # ------------------------------------------------------------------

    @property
    def registry(self):
        if self._registry is None:
            from src.layer0_model_infra.routing.registry_loader import get_layer3_registry
            self._registry = get_layer3_registry()
        return self._registry

    @property
    def outcome_store(self):
        if self._outcome_store is None:
            from src.layer0_model_infra.routing.outcome_store import get_outcome_store
            self._outcome_store = get_outcome_store()
        return self._outcome_store

    @property
    def aggregate_scores(self):
        if self._aggregate_scores is None:
            from src.layer0_model_infra.routing.aggregate_scores import get_aggregate_scores
            self._aggregate_scores = get_aggregate_scores()
        return self._aggregate_scores

    @property
    def calibration(self):
        if self._calibration is None:
            from src.layer0_model_infra.routing.calibration_store import get_calibration_store
            self._calibration = get_calibration_store()
        return self._calibration

    @property
    def verdict_cache(self):
        if self._verdict_cache is None:
            from src.layer0_model_infra.routing.verdict_cache import get_verdict_cache
            self._verdict_cache = get_verdict_cache()
        return self._verdict_cache

    @property
    def feature_extractor(self):
        if self._feature_extractor is None:
            from src.layer0_model_infra.routing.feature_extractor import get_feature_extractor
            self._feature_extractor = get_feature_extractor()
        return self._feature_extractor

    @property
    def fallback(self) -> FallbackRouter:
        if self._fallback is None:
            # Share the router's registry so activation state is consistent.
            self._fallback = FallbackRouter(registry=self.registry)
        return self._fallback

    @property
    def cooldown(self):
        if self._cooldown is None:
            from src.layer0_model_infra.routing.rate_limit_cooldown import get_rate_limit_cooldown
            self._cooldown = get_rate_limit_cooldown()
        return self._cooldown

    @property
    def quality_head(self):
        if self._quality_head is None:
            from src.layer0_model_infra.routing.quality_head import get_quality_head
            self._quality_head = get_quality_head()
        return self._quality_head

    # ------------------------------------------------------------------
    # Encoder (P11 — GPU FP16 primary, CPU fallback)
    # ------------------------------------------------------------------

    def _resolve_device(self) -> str:
        pref = self._settings.LAYER3_ENCODER_DEVICE
        if pref in ("cuda", "cpu"):
            return pref
        # "auto"
        try:
            import torch  # type: ignore
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    @property
    def encoder(self):
        if self._encoder is None:
            with self._encoder_lock:
                if self._encoder is None:
                    from sentence_transformers import SentenceTransformer  # type: ignore
                    device = self._resolve_device()
                    try:
                        model = SentenceTransformer(self._config.encoder.model_name, device=device)
                        if device == "cuda":
                            # Match how the corpus was embedded (embed_corpus.py
                            # used FP16 on CUDA) so query/corpus vectors share a
                            # space.
                            model = model.half()
                    except Exception as exc:
                        if device == "cpu":
                            raise
                        # CUDA load/OOM (e.g. VRAM exhausted by another process)
                        # — degrade to CPU rather than fail every route.
                        logger.warning(
                            "layer3_encoder_device_fallback",
                            failed_device=device, reason=str(exc), fallback="cpu",
                        )
                        model = SentenceTransformer(self._config.encoder.model_name, device="cpu")
                        device = "cpu"
                    self._encoder = model
                    self._encoder_device = device
                    logger.info(
                        "layer3_encoder_loaded",
                        model=self._config.encoder.model_name,
                        device=device,
                    )
        return self._encoder

    @property
    def qdrant(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            self._qdrant = QdrantClient(
                host=self._settings.QDRANT_HOST,
                port=self._settings.QDRANT_PORT,
                timeout=10.0,
            )
        return self._qdrant

    def warmup(self) -> None:
        """Pre-load every dependency so the first real request doesn't pay the
        cold-start cost (the encoder alone is ~20s on first load, and the
        DuckDB / JSON / Parquet stores each lazy-load on first touch). Without
        this the first route() can take 20-25s; after it, routes are ~50-150ms.
        Best-effort — a failure here only means the cost is paid on first use.
        """
        try:
            _ = self.registry.active_models()
            # extract() warms lingua + (if enabled) the high-risk Tier-2 model.
            self.feature_extractor.extract("warm up the feature extractor")
            _ = self.aggregate_scores
            _ = self.calibration
            _ = self.verdict_cache
            self.outcome_store.stats()         # triggers the DuckDB view build
            _ = self.encoder
            self._encode("warmup")             # JIT the CUDA kernels
            _ = self.qdrant.get_collections()  # open the HTTP connection
            logger.info("layer3_knn_router_warmed_up", device=self._encoder_device)
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("layer3_knn_router_warmup_failed", reason=str(exc))

    def _encode(self, text: str):
        return self.encoder.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def _search_neighbors(self, embedding, features: QueryFeatures) -> list[Any]:
        from qdrant_client.http import models as qmodels

        conditions = []
        modality = _as_modality(features.modality)
        if self._config.knn.filter_by_modality and modality in _CORPUS_MODALITIES:
            conditions.append(
                qmodels.FieldCondition(key="modality", match=qmodels.MatchValue(value=modality.value))
            )
        if self._config.knn.filter_by_language and features.language:
            conditions.append(
                qmodels.FieldCondition(key="language", match=qmodels.MatchValue(value=features.language))
            )
        query_filter = qmodels.Filter(must=conditions) if conditions else None

        response = self.qdrant.query_points(
            collection_name=self._config.encoder.qdrant_collection,
            query=embedding.tolist(),
            query_filter=query_filter,
            limit=self._config.knn.knn_k,
            score_threshold=self._config.knn.min_similarity,
            with_payload=True,
        )
        return list(response.points)

    # ------------------------------------------------------------------
    # Per-model quality prediction
    # ------------------------------------------------------------------

    def _predict_qualities(
        self,
        features: QueryFeatures,
        neighbors: list[Any],
        feature_cell: str,
        embedding=None,
    ) -> tuple[dict[str, float], dict[str, str], dict[str, bool], dict[str, float]]:
        """Return (qualities, confidence, prior_used, confidence_scores) for every
        model. confidence_scores is a 0-1 calibrated confidence in each per-model
        prediction, built from the neighbours the kNN already fetched (coverage +
        agreement + proximity). It is the free, data-grounded signal the risk-aware
        selector uses to escalate an uncertain cheap pick — no model call."""
        # Consider the FULL catalog (active + inactive) so the decision is
        # benchmark-driven across every registered model — including premium
        # models without a key. When a keyless model wins, execution falls back
        # to a free model (gateway fallback); the DECISION still reflects the
        # benchmark-optimal pick.
        models = self.registry.all_models()
        model_ids = [m.model_id for m in models]
        qids = [n.payload["question_global_id"] for n in neighbors]
        lookup = self.outcome_store.lookup_for_all_models(qids, model_ids)

        knn_cfg = self._config.knn
        unc_cfg = self._config.uncertainty
        # Learned quality head (prior path): query-aware predictions that replace
        # the flat prior for the models it covers. Inert / no embedding -> {} ->
        # the flat prior is used, so this never changes the kNN-grounded path.
        qh_cfg = self._config.quality_head
        head_preds: dict[str, float] = {}
        qh_confidence = unc_cfg.prior_confidence
        if qh_cfg.enable and embedding is not None:
            try:
                head_preds = self.quality_head.predict_all(embedding)
                if head_preds:
                    qh_confidence = qh_cfg.confidence
            except Exception as exc:  # the head must never break routing
                logger.warning("layer3_quality_head_predict_failed", reason=str(exc))
                head_preds = {}
        query_len = features.char_count or 0
        # Pre-compute the length-adjusted similarity for each neighbor once.
        neighbor_sims: list[tuple[str, float]] = []
        for n in neighbors:
            qid = n.payload["question_global_id"]
            neighbor_len = len(n.payload.get("question_text", "") or "")
            adj = length_adjusted_similarity(
                query_len, neighbor_len, float(n.score),
                knn_cfg.length_adjustment_base, knn_cfg.length_adjustment_range,
            )
            neighbor_sims.append((qid, adj))

        # Query-level proximity: how close the single nearest neighbour is, scaled
        # above the search threshold so it spans 0-1. Shared across all models.
        top_sim = max((float(n.score) for n in neighbors), default=0.0)
        prox_denom = max(1e-9, 1.0 - knn_cfg.min_similarity)
        proximity = max(0.0, min(1.0, (top_sim - knn_cfg.min_similarity) / prox_denom))
        wsum = (unc_cfg.weight_coverage + unc_cfg.weight_agreement
                + unc_cfg.weight_proximity) or 1.0

        qualities: dict[str, float] = {}
        confidence: dict[str, str] = {}
        prior_used: dict[str, bool] = {}
        confidence_scores: dict[str, float] = {}

        for model in models:
            mid = model.model_id
            model_outcomes = lookup.get(mid, {})
            pairs = [(adj, model_outcomes[qid]) for qid, adj in neighbor_sims if qid in model_outcomes]

            # Use real per-question neighbour outcomes whenever we have enough of
            # them (>= min_outcomes), EVEN for low-coverage models. The +0.10
            # low-coverage floor penalty (applied later) is the safety for those
            # — not a blanket prior fallback. This is what lets freshly-generated
            # conversational outcomes actually drive routing instead of being
            # ignored because the model's *global* coverage is still low.
            sim_sum = sum(s for s, _ in pairs)
            if len(pairs) < knn_cfg.min_outcomes_per_model or sim_sum <= 0:
                # No local neighbour evidence. Prefer the learned head's
                # query-aware prediction for the models it covers; otherwise fall
                # back to the flat (query-independent) benchmark prior. Either way
                # this is the non-kNN path, low-confidence by construction.
                head_q = head_preds.get(mid)
                if head_q is not None:
                    raw = head_q
                    conf_score = qh_confidence
                else:
                    raw = self.aggregate_scores.prior_quality(mid, features.modality)
                    conf_score = unc_cfg.prior_confidence
                confidence[mid] = "low"
                prior_used[mid] = True
            else:
                raw = sum(s * o for s, o in pairs) / sim_sum
                confidence[mid] = "high"
                prior_used[mid] = False
                # Confidence from the neighbours: more outcomes (coverage), tighter
                # agreement (low dispersion), and a closer nearest neighbour all
                # raise it. Every term is free — already computed for the average.
                coverage = min(len(pairs) / unc_cfg.full_confidence_neighbors, 1.0)
                variance = sum(s * (o - raw) ** 2 for s, o in pairs) / sim_sum
                agreement = max(0.0, 1.0 - 2.0 * (variance ** 0.5))
                conf_score = (
                    unc_cfg.weight_coverage * coverage
                    + unc_cfg.weight_agreement * agreement
                    + unc_cfg.weight_proximity * proximity
                ) / wsum

            multiplier = self.calibration.get_multiplier(mid, feature_cell)
            qualities[mid] = max(0.0, min(1.0, raw * multiplier))
            confidence_scores[mid] = max(0.0, min(1.0, conf_score))

        return qualities, confidence, prior_used, confidence_scores

    # ------------------------------------------------------------------
    # Floors / cost / warmup
    # ------------------------------------------------------------------

    def _base_floor(self, features: QueryFeatures) -> float:
        base = (
            self._floor_high_risk
            if features.high_risk_domain is not None
            else self._floor_default
        )
        # Hard/complex queries demand higher predicted quality: a model that's
        # only good on average shouldn't qualify, so the bar rises toward the
        # strongest models (where Claude wins complex coding). The difficulty
        # signal is a coarse hint, so the bump is modest and capped.
        difficulty = getattr(features.difficulty_signal, "value", str(features.difficulty_signal))
        if difficulty == "hard":
            qf = self._config.quality_floor
            base = min(base + qf.hard_difficulty_penalty, qf.floor_ceiling)
        return base

    def _effective_floor(self, model, base_floor: float) -> float:
        # The low-coverage penalty exists to stop a model winning on an INFLATED,
        # untrusted aggregate prior. Once a model has a measured realism factor
        # (aggregate_scores), its prior is debiased onto observed outcomes and is
        # trustworthy, so adding the penalty on top would double-count the same
        # correction — skip it for measured models, keep it only for the still-
        # unverified ones (e.g. keyless premium with estimate-only priors).
        if (
            model.coverage_quality == CoverageQuality.LOW
            and not self.aggregate_scores.has_realism(model.model_id)
        ):
            qf = self._config.quality_floor
            return min(base_floor + qf.low_coverage_penalty, qf.floor_ceiling)
        return base_floor

    def _estimate_cost(self, model_id: str, features: QueryFeatures) -> float:
        entry = self.registry.get(model_id)
        return entry.total_cost_per_1k(
            features.estimated_input_tokens, features.estimated_output_tokens
        )

    def _model_compute_cost(self, model_id: str) -> float:
        """Compute-cost proxy (≈ params in billions) for breaking cost ties.
        When several models cost the same USD — the all-free pool, where dollar
        cost is 0 for everyone — "cheapest" should mean the SMALLEST model that
        still clears the floor (cheaper compute, lower latency), not the biggest
        free one. Parsed from the model name; 'lite/nano/mini' and 'flash/haiku/
        small' get small defaults and unknown frontier names a large one."""
        try:
            entry = self.registry.get(model_id)
        except KeyError:
            return 100.0
        name = f"{entry.model_id} {entry.litellm_model_name}".lower()
        m = _MODEL_SIZE_RE.search(name)
        if m:
            return float(m.group(1))
        if any(k in name for k in ("lite", "nano", "mini")):
            return 8.0
        if any(k in name for k in ("flash", "haiku", "small")):
            return 15.0
        return 150.0  # unknown / frontier name → treat as expensive compute

    @staticmethod
    def _supports_vision(model) -> bool:
        """Whether a model can actually serve an image/multimodal query."""
        return "vision" in getattr(model, "capabilities", []) or getattr(
            model, "model_type", "text"
        ) in {"multimodal", "vision"}

    def _is_in_warmup(self, model, now: Optional[datetime] = None) -> bool:
        """A model is in warmup until it ages past max_age_days OR accumulates
        min_observations_to_exit calibration observations — whichever first."""
        now = now or datetime.now(timezone.utc)
        warm = self._config.warmup
        added = model.added_at
        if added.tzinfo is None:
            added = added.replace(tzinfo=timezone.utc)
        age_days = (now - added).days
        if age_days > warm.max_age_days:
            return False
        if self.calibration.total_observations(model.model_id) >= warm.min_observations_to_exit:
            return False
        return True

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _choose(
        self,
        query: str,
        features: QueryFeatures,
        qualities: dict[str, float],
        confidence: dict[str, str],
        neighbors: list[Any],
        request_id: str,
        feature_cell: str,
        *,
        knn_grounded: bool = True,
        confidence_scores: Optional[dict[str, float]] = None,
    ) -> RoutingDecision:
        confidence_scores = confidence_scores or {}
        base_floor = self._base_floor(features)
        # KNN_CORPUS when the prediction is backed by per-question neighbor
        # outcomes; PRIOR when it's the benchmark aggregate prior (no neighbors).
        # Both are benchmark-DATA-driven — neither is a hard-coded default.
        base_source = RoutingSource.KNN_CORPUS if knn_grounded else RoutingSource.PRIOR

        effective_floors: dict[str, float] = {}
        eligible: list[str] = []           # passed the context-window check
        qualifying: dict[str, float] = {}  # cleared the floor and not cooling down
        any_cleared_floor = False
        for mid, q in qualities.items():
            try:
                model = self.registry.get(mid)
            except KeyError:
                continue
            # Vision / multimodal queries need a vision-capable model — a text
            # model can't serve them however high its text prior.
            if (
                _as_modality(features.modality) not in _CORPUS_MODALITIES
                and not self._supports_vision(model)
            ):
                continue
            # S3 — a model whose context window can't hold the input can't serve
            # the query; exclude it before it can win on cost.
            if model.context_window < features.estimated_input_tokens:
                continue
            eligible.append(mid)
            floor = self._effective_floor(model, base_floor)
            effective_floors[mid] = floor
            if q >= floor:
                any_cleared_floor = True
                # M4 — skip models that just rate-limited (429); they clear the
                # floor but can't serve right now. (Inactive models are never
                # cooling — they simply fall back at execution time.)
                if not self.cooldown.is_cooling_down(mid):
                    qualifying[mid] = q

        if not qualifying:
            # Floor-clearers exist but every one is rate-limited right now →
            # genuinely unavailable; fall back rather than hammer a cooling model.
            if any_cleared_floor:
                return self.fallback.route(
                    features, request_id, REASON_ALL_RATE_LIMITED, query=query
                )
            # Nothing cleared the floor: stay benchmark-driven — route to the
            # highest-predicted NON-cooling model (cheapest among ties) rather
            # than a hard-coded safe default. Layer 7/8 are the downstream net.
            pool = [mid for mid in eligible if not self.cooldown.is_cooling_down(mid)]
            if pool:
                best_q = max(qualities[mid] for mid in pool)
                contenders = [mid for mid in pool if qualities[mid] >= best_q - 1e-9]
                selected = min(
                    contenders,
                    key=lambda mid: (self._estimate_cost(mid, features), self._model_compute_cost(mid)),
                )
                order = sorted(
                    pool,
                    key=lambda mid: (
                        self._estimate_cost(mid, features),
                        self._model_compute_cost(mid),
                        -qualities[mid],
                    ),
                )
                return self._build_decision(
                    selected=selected, source=base_source, features=features,
                    qualities=qualities, confidence=confidence, candidates_sorted=order,
                    effective_floors=effective_floors, base_floor=base_floor,
                    feature_cell=feature_cell, neighbors=neighbors, request_id=request_id,
                    confidence_score=confidence_scores.get(selected),
                )
            return self.fallback.route(
                features, request_id, REASON_NO_MODEL_ABOVE_FLOOR, query=query
            )

        candidates_sorted = sorted(
            qualifying,
            key=lambda mid: (
                self._estimate_cost(mid, features),
                self._model_compute_cost(mid),
                -qualities[mid],
            ),
        )

        # P2/P4 — exploration + warmup are LEARNING mechanisms: only meaningful
        # for grounded routing over executable (active) models. Skip them on the
        # prior-only path and never force an inactive (keyless) model.
        if knn_grounded:
            active_ids = {m.model_id for m in self.registry.active_models()}

            # P2 — ε-exploration of borderline models (just below the floor) that
            # haven't yet accumulated enough calibration observations.
            if self._rng.random() < self._config.exploration.rate:
                band = self._config.exploration.borderline_band
                max_obs = self._config.exploration.max_observations_for_borderline
                borderline = sorted(
                    mid for mid, q in qualities.items()
                    if mid in effective_floors and mid in active_ids
                    and (effective_floors[mid] - band) <= q < effective_floors[mid]
                    and self.calibration.observations(mid, feature_cell) < max_obs
                    and not self.cooldown.is_cooling_down(mid)
                )
                if borderline:
                    selected = self._rng.choice(borderline)
                    logger.info("layer3_exploration_route", model_id=selected, feature_cell=feature_cell)
                    return self._build_decision(
                        selected=selected, source=RoutingSource.EXPLORATION, features=features,
                        qualities=qualities, confidence=confidence, candidates_sorted=candidates_sorted,
                        effective_floors=effective_floors, base_floor=base_floor,
                        feature_cell=feature_cell, neighbors=neighbors, request_id=request_id,
                        confidence_score=confidence_scores.get(selected),
                    )

            # P4 — warmup forcing, restricted to qualifying ACTIVE models.
            warmup_pool = sorted(
                (m for m in self.registry.active_models()
                 if m.model_id in qualifying and self._is_in_warmup(m)),
                key=lambda m: m.model_id,
            )
            if warmup_pool and self._rng.random() < self._config.warmup.forced_selection_rate:
                forced = self._rng.choice(warmup_pool)
                logger.info("layer3_warmup_route", model_id=forced.model_id, feature_cell=feature_cell)
                return self._build_decision(
                    selected=forced.model_id, source=RoutingSource.WARMUP, features=features,
                    qualities=qualities, confidence=confidence, candidates_sorted=candidates_sorted,
                    effective_floors=effective_floors, base_floor=base_floor,
                    feature_cell=feature_cell, neighbors=neighbors, request_id=request_id,
                    confidence_score=confidence_scores.get(forced.model_id),
                )

        # Cost minimization inside the qualifying set (the anti-over-routing core),
        # then risk-aware escalation: if the cheapest qualifier's prediction is
        # low-confidence (few / disagreeing / far neighbours), don't gamble on the
        # cheap pick — escalate to the strongest qualifier (highest predicted
        # quality). The confidence comes free from the neighbours; measured
        # selective over a random escalation of the same budget.
        #
        # Gated to the GROUNDED path: on the prior path every prediction carries
        # the same placeholder confidence (prior_confidence, ~0.20) because there
        # are no neighbours, so the "< escalate_below_confidence" test would fire
        # on EVERY off-distribution query and silently escalate the cheapest free
        # pick to the strongest (often paid / unverified) model — defeating cost
        # minimization for no benefit. Escalation only means something when the
        # confidence is a real, per-query neighbour signal.
        selected = candidates_sorted[0]
        escalated = False
        unc = self._config.uncertainty
        if (
            knn_grounded
            and unc.enable
            and unc.escalate_below_confidence > 0.0
            and len(candidates_sorted) > 1
            and confidence_scores.get(selected, 1.0) < unc.escalate_below_confidence
        ):
            # Escalate to the strongest EXECUTABLE (active) qualifier: routing an
            # uncertain query to a keyless model would just fall back to a free one
            # and deliver no upgrade, so the safety escalation must target a model
            # that actually runs, and only when it is genuinely stronger.
            active_qualifiers = [
                mid for mid in candidates_sorted if self.registry.get(mid).is_active
            ]
            if active_qualifiers:
                strongest = max(active_qualifiers, key=lambda mid: qualities.get(mid, 0.0))
                if qualities.get(strongest, 0.0) > qualities.get(selected, 0.0):
                    selected = strongest
                    escalated = True
        return self._build_decision(
            selected=selected, source=base_source, features=features,
            qualities=qualities, confidence=confidence, candidates_sorted=candidates_sorted,
            effective_floors=effective_floors, base_floor=base_floor,
            feature_cell=feature_cell, neighbors=neighbors, request_id=request_id,
            confidence_score=confidence_scores.get(selected), escalated=escalated,
        )

    def _build_decision(
        self,
        *,
        selected: str,
        source: RoutingSource,
        features: QueryFeatures,
        qualities: dict[str, float],
        confidence: dict[str, str],
        candidates_sorted: list[str],
        effective_floors: dict[str, float],
        base_floor: float,
        feature_cell: str,
        neighbors: list[Any],
        request_id: str,
        confidence_score: Optional[float] = None,
        escalated: bool = False,
    ) -> RoutingDecision:
        return RoutingDecision(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            selected_model=selected,
            source=source,
            predicted_quality=qualities.get(selected),
            prediction_confidence=confidence.get(selected, "low"),
            prediction_confidence_score=confidence_score,
            uncertainty_escalated=escalated,
            estimated_cost_usd=self._estimate_cost(selected, features),
            quality_floor_base=base_floor,
            effective_floor=effective_floors.get(selected),
            features=features,
            neighbors_used=[
                (n.payload["question_global_id"], float(n.score)) for n in neighbors[:10]
            ],
            all_model_qualities=qualities,
            qualifying_models=candidates_sorted,
            calibration_multiplier_applied=self.calibration.get_multiplier(selected, feature_cell),
            feature_cell=feature_cell,
        )

    def _forced_decision(self, force_model_id: str, features: QueryFeatures, request_id: str) -> RoutingDecision:
        if self.registry.has(force_model_id) and self.registry.get(force_model_id).is_active:
            return RoutingDecision(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc),
                selected_model=force_model_id,
                source=RoutingSource.FORCED,
                predicted_quality=None,
                prediction_confidence="low",
                estimated_cost_usd=self._estimate_cost(force_model_id, features),
                features=features,
                qualifying_models=[force_model_id],
                feature_cell=make_feature_cell(features),
            )
        logger.warning("layer3_forced_model_invalid", model_id=force_model_id)
        return self.fallback.route(features, request_id, REASON_NO_MODEL_ABOVE_FLOOR, query="")

    @staticmethod
    def _is_cacheable(decision: RoutingDecision) -> bool:
        """Only stable, on-policy decisions belong in the verdict cache.
        Exploration / warmup / forced are deliberately off-policy — caching one
        would replay it to every near-duplicate query and blow past the intended
        rates — and a search-error fallback is transient (the encoder/Qdrant may
        be back on the next request).
        """
        if decision.source in (
            RoutingSource.CACHE_HIT,
            RoutingSource.EXPLORATION,
            RoutingSource.WARMUP,
            RoutingSource.FORCED,
        ):
            return False
        if decision.source == RoutingSource.FALLBACK and decision.fallback_reason == REASON_SEARCH_ERROR:
            return False
        return True

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def route(
        self,
        query: str,
        *,
        layer1_analysis: "Optional[ModalityAnalysis]" = None,
        force_model_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> RoutingDecision:
        """Route a query through Stages A→D and return a RoutingDecision."""
        t0 = time.monotonic()
        request_id = request_id or uuid.uuid4().hex
        query = query or ""

        # Stage A — verdict cache (skipped on forced overrides).
        if force_model_id is None and self._config.verdict_cache.enable:
            hit = self.verdict_cache.lookup(query)
            if hit is not None:
                cached = hit.decision
                # M6 — don't replay a cached decision whose model has since gone
                # inactive (e.g. a provider key was removed); drop it + recompute.
                if self.registry.has(cached.selected_model) and self.registry.get(
                    cached.selected_model
                ).is_active:
                    return cached.model_copy(update={
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc),
                        "source": RoutingSource.CACHE_HIT,
                        "cache_hit_kind": hit.kind,
                        "latency_ms": (time.monotonic() - t0) * 1000.0,
                    })
                self.verdict_cache.invalidate(query)

        # Stage B — features (reuse Layer 1's analysis when the caller has it).
        if layer1_analysis is not None:
            features = self.feature_extractor.extract_from_layer1(layer1_analysis, query)
        else:
            features = self.feature_extractor.extract(query)

        if force_model_id is not None:
            decision = self._forced_decision(force_model_id, features, request_id)
        elif _as_modality(features.modality) not in _CORPUS_MODALITIES:
            # Vision / multimodal — no corpus neighbours, but still route by
            # benchmark DATA (vision priors: MMMU / MathVista) over the
            # vision-capable models, not a hard-coded default.
            feature_cell = make_feature_cell(features)
            qualities, confidence, _p, conf_scores = self._predict_qualities(features, [], feature_cell)
            decision = self._choose(
                query, features, qualities, confidence, [], request_id,
                feature_cell, knn_grounded=False, confidence_scores=conf_scores,
            )
        else:
            # Stage C — encode + ANN search. Any encoder/Qdrant failure must
            # degrade to Stage D rather than crash routing (S2).
            try:
                embedding = self._encode(query)
                neighbors = self._search_neighbors(embedding, features)
            except Exception as exc:
                logger.warning(
                    "layer3_stage_c_failed",
                    reason=str(exc), error_type=type(exc).__name__,
                )
                decision = self.fallback.route(features, request_id, REASON_SEARCH_ERROR, query=query)
            else:
                feature_cell = make_feature_cell(features)
                if len(neighbors) < self._config.knn.min_neighbors_for_trust:
                    # No per-question corpus evidence for THIS query — but still
                    # route by benchmark DATA (aggregate priors over the full
                    # catalog), not a hard-coded default. Source = PRIOR.
                    qualities, confidence, _prior, conf_scores = self._predict_qualities(
                        features, [], feature_cell, embedding=embedding
                    )
                    decision = self._choose(
                        query, features, qualities, confidence, [], request_id,
                        feature_cell, knn_grounded=False, confidence_scores=conf_scores,
                    )
                else:
                    qualities, confidence, _prior, conf_scores = self._predict_qualities(
                        features, neighbors, feature_cell, embedding=embedding
                    )
                    decision = self._choose(
                        query, features, qualities, confidence, neighbors, request_id,
                        feature_cell, knn_grounded=True, confidence_scores=conf_scores,
                    )

        decision.latency_ms = (time.monotonic() - t0) * 1000.0

        # Cache only stable, on-policy decisions (M1) — never an off-policy
        # exploration/warmup/forced shot or a transient error fallback.
        if (
            self._config.verdict_cache.enable
            and force_model_id is None
            and self._is_cacheable(decision)
        ):
            self.verdict_cache.put(query, decision)

        return decision


# ============================================================================
# Singleton
# ============================================================================

_knn_router: Optional[KnnRouter] = None
_knn_router_lock = threading.Lock()


def get_knn_router() -> KnnRouter:
    """Process-wide KnnRouter wired to the production singletons."""
    global _knn_router
    if _knn_router is None:
        with _knn_router_lock:
            if _knn_router is None:
                _knn_router = KnnRouter()
    return _knn_router


def reset_knn_router() -> None:
    """Test helper — drop the singleton."""
    global _knn_router
    with _knn_router_lock:
        _knn_router = None
