"""
📁 File: src/layer0_model_infra/routing/aggregate_scores.py
Layer: Layer 0 — Layer 3 redesign
Purpose: prior_quality(model, features) — the kNN fallback path.
Depends on: src/layer0_model_infra/data/model_aggregate_scores.json
Used by: knn_router (next batch), validation scripts

When a query has fewer than the minimum number of kNN neighbor outcomes for
a model (coverage_quality='low' OR neighbor outcomes < 3), the per-model
quality prediction falls back to a modality-weighted aggregate of that model's
public benchmark scores. This module computes that aggregate.

The mapping ``RELEVANCE_WEIGHTS`` says: for a query of modality M, which
benchmarks predict performance best? E.g. for CODE, weight HumanEval + MBPP +
LiveCodeBench heavily; for MATH, weight MATH-Hard + GSM8K + GPQA; for VISION,
weight MMMU + MathVista.

The weights are derived from the cited papers on benchmark-modality
correlation (RouteLLM, BenchLM analyses) — not invented. They're documented in
``docs/layer3/aggregate_scores.md``.

Missing benchmarks are not penalised: the weighted sum normalises against the
benchmarks that ARE present, so a model without a HumanEval score still gets
a sensible aggregate from its other benchmarks.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from src.layer0_model_infra.routing.layer3_types import Modality
from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Modality → benchmark relevance weights
# ============================================================================
#
# Each modality maps to a dict of (benchmark_key → weight). When predicting
# quality for a model on a query of that modality:
#
#   prior = Σ (benchmark_score[bench] × weight[bench])  /  Σ weight[bench]
#                                                          for benchmarks present
#
# Weights ARE configuration — moving them affects every prior_quality() call.
# Document and version any changes in docs/layer3/aggregate_scores.md.

RELEVANCE_WEIGHTS: dict[str, dict[str, float]] = {
    "code": {
        "humaneval": 0.20,
        "humaneval_plus": 0.15,
        "mbpp": 0.15,
        "livecodebench": 0.20,
        "swe_bench_verified": 0.10,
        "livebench_coding": 0.15,
        "arena_elo_normalised": 0.05,
    },
    "math": {
        "math_hard": 0.30,
        "gsm8k": 0.15,
        "gpqa_diamond": 0.20,
        "bbh": 0.15,
        "livebench_reasoning": 0.15,
        "arena_elo_normalised": 0.05,
    },
    "vision": {
        "mmmu": 0.50,
        "mathvista": 0.25,
        "arena_elo_normalised": 0.25,
    },
    "multimodal": {
        "mmmu": 0.35,
        "mathvista": 0.15,
        "livebench_reasoning": 0.20,
        "mmlu_pro": 0.15,
        "arena_elo_normalised": 0.15,
    },
    "text": {
        "mmlu_pro": 0.25,
        "ifeval": 0.20,
        "livebench_reasoning": 0.15,
        "bbh": 0.15,
        "gpqa_diamond": 0.10,
        "arena_elo_normalised": 0.15,
    },
}

# Fallback when a modality is missing from RELEVANCE_WEIGHTS
DEFAULT_FALLBACK_BENCH = "arena_elo_normalised"
DEFAULT_FALLBACK_VALUE = 0.50  # used only when the model has zero benchmarks scored


# ============================================================================
# Loader
# ============================================================================


class AggregateScores:
    """Wrapper around model_aggregate_scores.json."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.is_absolute():
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            self._path = (repo_root / self._path).resolve()
        self._lock = threading.RLock()
        self._scores: dict[str, dict[str, float]] = {}
        self._meta: dict = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                raise FileNotFoundError(
                    f"model_aggregate_scores.json not found at {self._path}"
                )
            with self._path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            self._meta = payload.get("_meta", {})
            self._scores = payload.get("models", {})
            logger.info(
                "layer3_aggregate_scores_loaded",
                path=str(self._path),
                models=len(self._scores),
                last_refresh=self._meta.get("last_refresh", "unknown"),
            )

    def has(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._scores

    def scores_for(self, model_id: str) -> dict[str, float]:
        with self._lock:
            return dict(self._scores.get(model_id, {}))

    def prior_quality(self, model_id: str, modality: Modality | str) -> float:
        """Compute the modality-weighted aggregate quality prior for a model.

        Returns 0.0–1.0. Missing models or modalities fall through to
        arena_elo_normalised; missing that too returns ``DEFAULT_FALLBACK_VALUE``.
        """
        modality_key = modality.value if isinstance(modality, Modality) else str(modality)
        with self._lock:
            scores = self._scores.get(model_id, {})
            if not scores:
                # No benchmark data at all for this model.
                logger.debug("aggregate_scores_no_data", model_id=model_id)
                return DEFAULT_FALLBACK_VALUE

            weights = RELEVANCE_WEIGHTS.get(modality_key, RELEVANCE_WEIGHTS["text"])

            total_score = 0.0
            total_weight = 0.0
            for benchmark, weight in weights.items():
                if benchmark in scores:
                    total_score += scores[benchmark] * weight
                    total_weight += weight

            if total_weight == 0.0:
                # None of the modality-relevant benchmarks are scored — fall
                # back to arena Elo as a last resort.
                return float(scores.get(DEFAULT_FALLBACK_BENCH, DEFAULT_FALLBACK_VALUE))

            return total_score / total_weight

    def coverage_summary(self) -> dict:
        """Per-model summary: which benchmarks they have, how many, mean score.
        Useful for build-time sanity checks.
        """
        with self._lock:
            out = {}
            for model_id, benchmarks in self._scores.items():
                values = list(benchmarks.values())
                out[model_id] = {
                    "n_benchmarks": len(benchmarks),
                    "benchmarks": sorted(benchmarks.keys()),
                    "mean": sum(values) / len(values) if values else 0.0,
                }
            return out


# ============================================================================
# Singleton
# ============================================================================

_scores: Optional[AggregateScores] = None
_scores_lock = threading.Lock()


def get_aggregate_scores() -> AggregateScores:
    """Process-wide aggregate-scores singleton."""
    global _scores
    if _scores is None:
        with _scores_lock:
            if _scores is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                cfg = get_routing_config()
                _scores = AggregateScores(cfg.layer3.aggregate_scores_path)
    return _scores


def reset_aggregate_scores() -> None:
    """Test helper."""
    global _scores
    with _scores_lock:
        _scores = None
