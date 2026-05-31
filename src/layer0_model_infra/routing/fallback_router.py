"""
📁 File: src/layer0_model_infra/routing/fallback_router.py
Layer: Layer 0 — Layer 3 redesign (Stage D)
Purpose: Off-distribution / no-confident-choice safe-default dispatch.
Depends on: src/layer0_model_infra/routing/layer3_types, registry_loader
Used by: knn_router (Stage C calls this when it can't make a grounded decision)

Stage D is the floor of the router: whenever Stage C can't make a benchmark-
grounded choice, we hand off to a per-modality safe default rather than guessing.
It fires when:

  • fewer than ``min_neighbors_for_trust`` kNN neighbors clear the similarity
    threshold (the query is off-distribution — we have no comparable benchmark
    questions),                                    → 'insufficient_neighbors'
  • no active model clears its effective quality floor,
                                                   → 'no_model_above_floor'
  • every qualifying model is currently rate-limited,
                                                   → 'all_qualifying_rate_limited'
  • the query modality has zero benchmark coverage in the corpus (vision /
    multimodal — see the measured distribution: the corpus is text/code/math
    only, so a kNN result would be a different-modality red herring),
                                                   → 'unsupported_modality_no_coverage'

Robustness: ``safe_defaults`` in registry.json points most modalities at
gemini-1.5-pro, which is INACTIVE without a GEMINI_API_KEY. A dead default is
useless, so select_model() verifies the configured default is active and, if
not, walks to the cheapest active model that can plausibly serve the modality
(vision/multimodal need a vision-capable model). Only when the registry has zero
active models at all do we return the configured (inactive) default as a marker
— at that point routing can't run anyway and the caller surfaces the error.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from src.layer0_model_infra.routing.layer3_types import (
    Modality,
    QueryFeatures,
    RegistryEntry,
    RoutingDecision,
    RoutingSource,
)
from src.layer0_model_infra.routing.registry_loader import Layer3Registry, get_layer3_registry
from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Fallback reason constants (stored verbatim in RoutingDecision.fallback_reason)
# ============================================================================

REASON_INSUFFICIENT_NEIGHBORS = "insufficient_neighbors"
REASON_NO_MODEL_ABOVE_FLOOR = "no_model_above_floor"
REASON_ALL_RATE_LIMITED = "all_qualifying_rate_limited"
REASON_UNSUPPORTED_MODALITY = "unsupported_modality_no_coverage"
REASON_NO_ACTIVE_MODELS = "no_active_models"
REASON_SEARCH_ERROR = "search_error"  # transient encoder/Qdrant failure (S2)

# Modalities the benchmark corpus has zero coverage for — routing these through
# kNN would match against text/code/math questions, so they go straight here.
_NO_COVERAGE_MODALITIES = frozenset({Modality.VISION, Modality.MULTIMODAL})


def _as_modality(value) -> Modality:
    """QueryFeatures.modality is normally a Modality enum, but a frozen-model
    round-trip can surface it as a bare string — coerce defensively."""
    return value if isinstance(value, Modality) else Modality(value)


def _estimate_cost(entry: RegistryEntry, features: QueryFeatures) -> float:
    """USD estimate for serving this query shape with this model."""
    return entry.total_cost_per_1k(
        features.estimated_input_tokens,
        features.estimated_output_tokens,
    )


def _is_vision_capable(entry: RegistryEntry) -> bool:
    return "vision" in entry.capabilities or entry.model_type in {"multimodal", "vision"}


# ============================================================================
# Fallback router
# ============================================================================


class FallbackRouter:
    """Stage D dispatcher. Stateless given a registry; safe to share."""

    def __init__(self, registry: Optional[Layer3Registry] = None) -> None:
        self._registry = registry

    @property
    def registry(self) -> Layer3Registry:
        if self._registry is None:
            self._registry = get_layer3_registry()
        return self._registry

    def select_model(self, features: QueryFeatures) -> Optional[RegistryEntry]:
        """Pick the safe-default model for these features, guaranteeing the
        result is active. Returns None only when the registry has no active
        models at all.
        """
        reg = self.registry
        preferred_id = reg.safe_defaults.for_features(features)

        # 1) Configured safe default, if it's active.
        if reg.has(preferred_id):
            entry = reg.get(preferred_id)
            if entry.is_active:
                return entry
            logger.warning(
                "layer3_fallback_default_inactive",
                model_id=preferred_id,
                reason="required_env_var missing; walking to an active alternative",
            )

        actives = reg.active_models()
        if not actives:
            return None

        # 2) Capability-aware pool: vision/multimodal need a vision-capable model.
        if _as_modality(features.modality) in _NO_COVERAGE_MODALITIES:
            vision_pool = [m for m in actives if _is_vision_capable(m)]
            pool = vision_pool or actives
        else:
            pool = actives

        # 3) Cheapest first; tie-break toward recommended, then higher arena Elo.
        pool.sort(
            key=lambda m: (
                _estimate_cost(m, features),
                0 if m.is_recommended else 1,
                -(m.arena_elo_normalised or 0.0),
            )
        )
        return pool[0]

    def route(
        self,
        features: QueryFeatures,
        request_id: str,
        reason: str,
        query: str = "",
    ) -> RoutingDecision:
        """Build a FALLBACK RoutingDecision. ``predicted_quality`` is None —
        off-distribution means a quality prediction would be dishonest."""
        entry = self.select_model(features)

        if entry is None:
            preferred_id = self.registry.safe_defaults.for_features(features)
            logger.error(
                "layer3_fallback_no_active_models",
                configured_default=preferred_id,
                hint="no provider keys are set; the gateway's own fallback must handle execution",
            )
            return RoutingDecision(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc),
                selected_model=preferred_id,
                source=RoutingSource.FALLBACK,
                predicted_quality=None,
                prediction_confidence="low",
                estimated_cost_usd=0.0,
                features=features,
                qualifying_models=[preferred_id],
                fallback_reason=REASON_NO_ACTIVE_MODELS,
            )

        cost = _estimate_cost(entry, features)
        logger.info(
            "layer3_fallback_route",
            model_id=entry.model_id,
            reason=reason,
            modality=_as_modality(features.modality).value,
            high_risk=features.high_risk_domain.value if features.high_risk_domain else None,
        )
        return RoutingDecision(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            selected_model=entry.model_id,
            source=RoutingSource.FALLBACK,
            predicted_quality=None,
            prediction_confidence="low",
            estimated_cost_usd=cost,
            features=features,
            qualifying_models=[entry.model_id],
            fallback_reason=reason,
        )


# ============================================================================
# Singleton
# ============================================================================

_fallback_router: Optional[FallbackRouter] = None
_fallback_lock = threading.Lock()


def get_fallback_router() -> FallbackRouter:
    """Process-wide FallbackRouter bound to the Layer 3 registry singleton."""
    global _fallback_router
    if _fallback_router is None:
        with _fallback_lock:
            if _fallback_router is None:
                _fallback_router = FallbackRouter()
    return _fallback_router


def reset_fallback_router() -> None:
    """Test helper — drop the singleton."""
    global _fallback_router
    with _fallback_lock:
        _fallback_router = None
