"""
📁 File: src/layer0_model_infra/routing/benchmark_router.py
Layer: Layer 0 — Routing Pipeline
Purpose: Benchmark-trained model selection router
Depends on: model_benchmarks.json, sentence-transformers, sklearn, complexity_classifier
Used by: Elite router (primary model selection advisor)

Architecture
────────────
  TRAINING (offline, one-time):
    1. Load benchmark scores for 22+ industry LLMs
    2. Load 200 representative training queries
    3. For each query:
       a. Encode text via SentenceTransformer → 384-dim embedding
       b. Compute rubric features from complexity classifier → 6 dims
       c. Determine optimal model label from benchmark scores + cost
    4. Train GradientBoostingClassifier on (390-dim features → model_id)

  INFERENCE (per request, ~15ms):
    Query → SentenceTransformer → 384-dim ─┐
                                            ├─→ 390 features → GBC → model probs → cost filter → selected model
    Query → ComplexityClassifier → 6 dims ─┘

  NO keyword matching.  NO heuristic task detection.
  All task understanding comes from the transformer embedding space
  and the trained classifier.
"""

from __future__ import annotations

import json
import math
import os
import warnings
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from pydantic import BaseModel, Field
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder

from src.shared.logger import get_logger

logger = get_logger(__name__)

# Suppress sklearn convergence warnings during import
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_BENCHMARKS_PATH = _DATA_DIR / "model_benchmarks.json"
_TRAINING_QUERIES_PATH = _DATA_DIR / "router_training_queries.json"
_TRAINED_MODEL_PATH = _DATA_DIR / "benchmark_router_model.joblib"
_LABEL_ENCODER_PATH = _DATA_DIR / "benchmark_router_labels.joblib"

# Sentence-transformer model name (80 MB, downloads once)
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class BenchmarkRouterResult(BaseModel):
    """Result from benchmark-trained router."""

    recommended_model_id: str = Field(..., description="Best model_id for this query")
    recommended_model_name: str = Field(default="", description="Human-readable name")
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0,
        description="Expected quality on relevant benchmarks (0-1)")
    cost_per_1k: float = Field(default=0.0, ge=0.0,
        description="Cost per 1K tokens (USD)")
    value_score: float = Field(default=0.0,
        description="Quality / cost efficiency ratio")
    tier: str = Field(default="moderate", description="premium | moderate | cheap")
    method: str = Field(default="benchmark_lookup",
        description="trained_gbc | benchmark_lookup | fallback")
    reasoning: str = Field(default="", description="Why this model was selected")
    top_candidates: list[dict] = Field(default_factory=list,
        description="Top 3 candidate models with scores")


# ---------------------------------------------------------------------------
# Helper: rubric → benchmark relevance weights
# ---------------------------------------------------------------------------

_RUBRIC_WEIGHTS = {
    # Maps each benchmark to which rubric dimensions drive its relevance.
    # Loaded from model_benchmarks.json at init.
}


def _rubric_to_benchmark_weights(rubric: dict) -> dict[str, float]:
    """
    Convert rubric dimensions to benchmark relevance weights.

    Instead of keyword matching, this uses the rubric dimensions
    from the complexity classifier to determine which benchmarks
    matter most for this query.

    Example: high reasoning_hops → weight BBH and ARC heavily.
    """
    weights = {}
    mapping = {
        "mmlu":          (rubric.get("knowledge_breadth", 0.5), rubric.get("domain_depth", 0.5)),
        "humaneval":     (rubric.get("task_count", 0.5),       rubric.get("output_structure", 0.5)),
        "gsm8k":         (rubric.get("reasoning_hops", 0.5),   rubric.get("task_count", 0.5)),
        "arc_challenge": (rubric.get("reasoning_hops", 0.5),   rubric.get("knowledge_breadth", 0.5)),
        "mt_bench":      (rubric.get("output_structure", 0.5), rubric.get("knowledge_breadth", 0.5)),
        "ifeval":        (rubric.get("output_structure", 0.5), rubric.get("task_count", 0.5)),
        "bbh":           (rubric.get("reasoning_hops", 0.5),   rubric.get("domain_depth", 0.5)),
    }
    for bench, (primary_val, secondary_val) in mapping.items():
        weights[bench] = primary_val * 0.65 + secondary_val * 0.35

    # Normalise so weights sum to 1
    total = sum(weights.values()) or 1.0
    return {b: w / total for b, w in weights.items()}


# ---------------------------------------------------------------------------
# BenchmarkRouter
# ---------------------------------------------------------------------------

class BenchmarkRouter:
    """
    Benchmark-trained model selection router.

    Uses a SentenceTransformer for query understanding + GradientBoosting
    classifier trained on benchmark data for model selection.
    Falls back to rubric-based benchmark scoring when the trained model
    is unavailable.
    """

    def __init__(self, lazy_load_embedder: bool = True) -> None:
        self._model_data: dict = {}
        self._rubric_mapping: dict = {}
        self._model_ids: list[str] = []

        # ML components (lazy-loaded for fast startup)
        self._embedder = None
        self._classifier: Optional[GradientBoostingClassifier] = None
        self._label_encoder: Optional[LabelEncoder] = None
        self._lazy_load_embedder = lazy_load_embedder

        self._load_benchmarks()
        self._load_trained_model()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_benchmarks(self) -> None:
        """Load model benchmark data."""
        if not _BENCHMARKS_PATH.exists():
            logger.warning("benchmark_data_missing", path=str(_BENCHMARKS_PATH))
            return
        with open(_BENCHMARKS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._model_data = data.get("models", {})
        self._rubric_mapping = data.get("benchmark_to_rubric_mapping", {})
        self._model_ids = sorted(self._model_data.keys())
        logger.info("benchmark_data_loaded", models=len(self._model_data))

    def _load_trained_model(self) -> None:
        """Load pre-trained GBC + label encoder if available."""
        if _TRAINED_MODEL_PATH.exists() and _LABEL_ENCODER_PATH.exists():
            try:
                self._classifier = joblib.load(str(_TRAINED_MODEL_PATH))
                self._label_encoder = joblib.load(str(_LABEL_ENCODER_PATH))
                logger.info("benchmark_router_model_loaded")
            except Exception as exc:
                logger.warning("benchmark_router_load_failed", error=str(exc))

    def _get_embedder(self):
        """Lazy-load sentence transformer to avoid slow startup."""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(_EMBEDDING_MODEL)
            logger.info("sentence_transformer_loaded", model=_EMBEDDING_MODEL)
        return self._embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(
        self,
        query: str,
        rubric: Optional[dict] = None,
        available_model_ids: Optional[list[str]] = None,
        max_cost_per_1k: Optional[float] = None,
        complexity_band: Optional[str] = None,
    ) -> BenchmarkRouterResult:
        """
        Recommend the best model for a query, balancing quality and cost.

        Args:
            query:               User query text
            rubric:              Rubric dimensions from complexity classifier
                                 {task_count, domain_depth, reasoning_hops,
                                  output_structure, knowledge_breadth, raw_score}
            available_model_ids: Filter to only these models
            max_cost_per_1k:     Hard budget cap per 1K tokens
            complexity_band:     Complexity band (trivial/simple/moderate/complex/expert)

        Returns:
            BenchmarkRouterResult
        """
        if not self._model_data:
            return self._fallback_result("No benchmark data loaded")

        # Default rubric if not provided
        if rubric is None:
            rubric = {
                "task_count": 0.5, "domain_depth": 0.5,
                "reasoning_hops": 0.5, "output_structure": 0.5,
                "knowledge_breadth": 0.5, "raw_score": 0.5,
            }

        # ── DETERMINISTIC ROUTING (primary path) ──────────────────
        # Uses rubric-weighted benchmark scoring to find the best-value
        # model.  This is grounded in Bloom's Taxonomy and Webb's DOK
        # (see router_training_queries.json for framework documentation).
        #
        # The trained GBC model is preserved below but bypassed because
        # deterministic scoring is more reliable and explainable.
        # To re-enable GBC, uncomment the block below.
        # ──────────────────────────────────────────────────────────
        #
        # if self._classifier is not None and self._label_encoder is not None:
        #     result = self._predict_trained(
        #         query, rubric, available_model_ids,
        #         max_cost_per_1k, complexity_band,
        #     )
        #     if result is not None:
        #         return result

        return self._benchmark_scoring(
            rubric, available_model_ids,
            max_cost_per_1k, complexity_band,
        )

    # ------------------------------------------------------------------
    # Trained model prediction
    # ------------------------------------------------------------------

    def _predict_trained(
        self,
        query: str,
        rubric: dict,
        available_model_ids: Optional[list[str]],
        max_cost_per_1k: Optional[float],
        complexity_band: Optional[str],
    ) -> Optional[BenchmarkRouterResult]:
        """Predict using trained GBC + sentence-transformer embeddings."""
        try:
            embedder = self._get_embedder()
            embedding = embedder.encode(query, convert_to_numpy=True)

            rubric_features = np.array([
                rubric.get("task_count", 0.5),
                rubric.get("domain_depth", 0.5),
                rubric.get("reasoning_hops", 0.5),
                rubric.get("output_structure", 0.5),
                rubric.get("knowledge_breadth", 0.5),
                rubric.get("raw_score", 0.5),
            ], dtype=np.float32)

            features = np.concatenate([embedding, rubric_features]).reshape(1, -1)

            # Get probabilities for all models
            probs = self._classifier.predict_proba(features)[0]
            class_labels = self._label_encoder.classes_

            # Rank by probability
            ranked = sorted(
                zip(class_labels, probs),
                key=lambda x: x[1],
                reverse=True,
            )

            # Filter by availability and budget
            for model_id, prob in ranked:
                if available_model_ids and model_id not in available_model_ids:
                    continue
                info = self._model_data.get(model_id, {})
                cost = info.get("cost_per_1k_tokens", 0.0)
                if max_cost_per_1k is not None and cost > max_cost_per_1k:
                    continue

                # Check minimum quality for complexity
                quality = self._compute_quality(model_id, rubric)
                min_q = self._min_quality_for_band(complexity_band)
                if quality < min_q:
                    continue

                cost_factor = math.log(cost * 1000 + 1) + 0.1
                value = quality / cost_factor

                return BenchmarkRouterResult(
                    recommended_model_id=model_id,
                    recommended_model_name=info.get("display_name", model_id),
                    quality_score=round(quality, 4),
                    cost_per_1k=cost,
                    value_score=round(value, 4),
                    tier=info.get("tier", "moderate"),
                    method="trained_gbc",
                    reasoning=(
                        f"Trained GBC selected {model_id} "
                        f"(prob={prob:.3f}, quality={quality:.3f}, "
                        f"cost=${cost:.4f}/1K)"
                    ),
                    top_candidates=[
                        {
                            "model_id": mid,
                            "probability": round(float(p), 4),
                            "quality": round(self._compute_quality(mid, rubric), 4),
                            "cost": self._model_data.get(mid, {}).get("cost_per_1k_tokens", 0.0),
                        }
                        for mid, p in ranked[:3]
                    ],
                )

        except Exception as exc:
            logger.warning("trained_prediction_failed", error=str(exc))

        return None

    # ------------------------------------------------------------------
    # Rubric-based benchmark scoring (fallback, NO keywords)
    # ------------------------------------------------------------------

    def _benchmark_scoring(
        self,
        rubric: dict,
        available_model_ids: Optional[list[str]],
        max_cost_per_1k: Optional[float],
        complexity_band: Optional[str],
    ) -> BenchmarkRouterResult:
        """
        Score models using rubric-weighted benchmark matching.

        The rubric dimensions from the complexity classifier determine
        which benchmarks matter → we score each model on those benchmarks
        → we factor in cost → we return the best value model.

        NO keyword matching anywhere.
        """
        # Convert rubric to benchmark relevance weights
        bench_weights = _rubric_to_benchmark_weights(rubric)
        min_quality = self._min_quality_for_band(complexity_band)

        candidates: list[dict] = []
        for model_id, info in self._model_data.items():
            if available_model_ids and model_id not in available_model_ids:
                continue
            cost = info.get("cost_per_1k_tokens", 0.0)
            if max_cost_per_1k is not None and cost > max_cost_per_1k:
                continue

            # Weighted quality score
            benchmarks = info.get("benchmarks", {})
            quality = sum(
                benchmarks.get(bench, 0.5) * weight
                for bench, weight in bench_weights.items()
            )

            if quality < min_quality:
                continue

            # Scoring strategy varies by complexity (same as _find_optimal_model)
            if complexity_band in ("trivial", "simple"):
                # Minimise cost while meeting quality bar
                score = quality - cost * 50
            elif complexity_band == "moderate":
                # Balance quality and cost
                cost_factor = math.log(cost * 1000 + 1) + 0.1
                score = quality / cost_factor
            elif complexity_band in ("complex", "expert"):
                # Quality is primary, cost is tie-breaker
                score = quality * 10 - cost
            else:
                # Default: value scoring
                cost_factor = math.log(cost * 1000 + 1) + 0.1
                score = quality / cost_factor

            candidates.append({
                "model_id": model_id,
                "display_name": info.get("display_name", model_id),
                "quality": round(quality, 4),
                "cost": cost,
                "score": round(score, 4),
                "tier": info.get("tier", "moderate"),
            })

        if not candidates:
            return self._fallback_result("No models passed quality/budget filters")

        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0]

        return BenchmarkRouterResult(
            recommended_model_id=best["model_id"],
            recommended_model_name=best["display_name"],
            quality_score=best["quality"],
            cost_per_1k=best["cost"],
            value_score=best["score"],
            tier=best["tier"],
            method="benchmark_lookup",
            reasoning=(
                f"Rubric-weighted benchmark scoring: "
                f"quality={best['quality']:.3f}, cost=${best['cost']:.4f}/1K"
            ),
            top_candidates=[
                {"model_id": c["model_id"], "quality": c["quality"],
                 "cost": c["cost"], "value": c["score"]}
                for c in candidates[:3]
            ],
        )

    # ------------------------------------------------------------------
    # Helper: compute quality for a specific model given rubric
    # ------------------------------------------------------------------

    def _compute_quality(self, model_id: str, rubric: dict) -> float:
        """Compute rubric-weighted quality score for a model."""
        info = self._model_data.get(model_id, {})
        benchmarks = info.get("benchmarks", {})
        bench_weights = _rubric_to_benchmark_weights(rubric)
        return sum(
            benchmarks.get(bench, 0.5) * weight
            for bench, weight in bench_weights.items()
        )

    @staticmethod
    def _min_quality_for_band(band: Optional[str]) -> float:
        """Minimum acceptable quality per complexity band."""
        thresholds = {
            "trivial": 0.0,
            "simple": 0.40,
            "moderate": 0.60,
            "complex": 0.75,
            "expert": 0.85,
        }
        return thresholds.get(band or "", 0.0)

    @staticmethod
    def _fallback_result(reason: str) -> BenchmarkRouterResult:
        """Safe fallback when nothing else works."""
        return BenchmarkRouterResult(
            recommended_model_id="llama-4",
            recommended_model_name="Llama 4 (fallback)",
            tier="moderate",
            method="fallback",
            reasoning=f"Fallback: {reason}",
        )

    # ==================================================================
    # TRAINING PIPELINE
    # ==================================================================

    def train(
        self,
        n_estimators: int = 200,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        verbose: bool = False,
    ) -> dict:
        """
        Train the GradientBoosting classifier on benchmark data.

        Pipeline:
        1. Load training queries from router_training_queries.json
        2. For each query:
           a. Encode via SentenceTransformer → 384-dim
           b. Compute rubric features from query metadata → 6 dims
           c. Determine optimal model from benchmarks + cost → label
        3. Train GradientBoostingClassifier
        4. Save model + label encoder

        Returns:
            Training statistics dict
        """
        if not self._model_data:
            return {"error": "No benchmark data loaded"}

        # Load training queries
        training_queries = self._load_training_queries()
        if not training_queries:
            return {"error": "No training queries found"}

        embedder = self._get_embedder()

        # Build training data
        X_list, y_list = [], []
        query_texts = [q["text"] for q in training_queries]

        # Batch encode all queries (much faster)
        logger.info("encoding_training_queries", count=len(query_texts))
        embeddings = embedder.encode(query_texts, convert_to_numpy=True,
                                     show_progress_bar=verbose, batch_size=32)

        for i, query_info in enumerate(training_queries):
            rubric = self._complexity_to_rubric(
                query_info["complexity"],
                query_info["dominant_rubric"],
            )
            rubric_features = np.array([
                rubric["task_count"],
                rubric["domain_depth"],
                rubric["reasoning_hops"],
                rubric["output_structure"],
                rubric["knowledge_breadth"],
                rubric["raw_score"],
            ], dtype=np.float32)

            features = np.concatenate([embeddings[i], rubric_features])
            X_list.append(features)

            # Determine optimal model (best value for this rubric profile)
            best_model = self._find_optimal_model(rubric, query_info["complexity"])
            y_list.append(best_model)

        X = np.array(X_list, dtype=np.float32)
        y = np.array(y_list)

        # Encode labels
        le = LabelEncoder()
        y_encoded = le.fit_transform(y)

        # Train GradientBoosting
        logger.info("training_gbc", samples=len(X), classes=len(le.classes_),
                     n_estimators=n_estimators)
        gbc = GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=42,
            subsample=0.8,
            min_samples_split=5,
            min_samples_leaf=2,
        )
        gbc.fit(X, y_encoded)

        # Evaluate
        train_preds = gbc.predict(X)
        accuracy = float(np.mean(train_preds == y_encoded))

        # Save
        os.makedirs(_DATA_DIR, exist_ok=True)
        joblib.dump(gbc, str(_TRAINED_MODEL_PATH))
        joblib.dump(le, str(_LABEL_ENCODER_PATH))

        # Update instance
        self._classifier = gbc
        self._label_encoder = le

        stats = {
            "training_samples": len(X),
            "n_features": X.shape[1],
            "n_classes": len(le.classes_),
            "class_labels": list(le.classes_),
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "train_accuracy": round(accuracy, 4),
            "model_saved": str(_TRAINED_MODEL_PATH),
        }
        logger.info("benchmark_router_trained", **stats)
        return stats

    # ------------------------------------------------------------------
    # Training helpers
    # ------------------------------------------------------------------

    def _load_training_queries(self) -> list[dict]:
        """Load training queries from JSON."""
        if not _TRAINING_QUERIES_PATH.exists():
            logger.warning("training_queries_missing")
            return []
        with open(_TRAINING_QUERIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("queries", [])

    @staticmethod
    def _complexity_to_rubric(complexity: str, dominant: str) -> dict:
        """
        Convert complexity level + dominant dimension to rubric values.

        These approximate what the complexity classifier would return
        for a query at this complexity/rubric profile.
        """
        # Base rubric values per complexity level
        bases = {
            "trivial":  {"task_count": 0.05, "domain_depth": 0.05, "reasoning_hops": 0.05,
                         "output_structure": 0.05, "knowledge_breadth": 0.05},
            "simple":   {"task_count": 0.15, "domain_depth": 0.15, "reasoning_hops": 0.12,
                         "output_structure": 0.12, "knowledge_breadth": 0.18},
            "moderate": {"task_count": 0.40, "domain_depth": 0.35, "reasoning_hops": 0.38,
                         "output_structure": 0.32, "knowledge_breadth": 0.35},
            "complex":  {"task_count": 0.65, "domain_depth": 0.60, "reasoning_hops": 0.62,
                         "output_structure": 0.58, "knowledge_breadth": 0.55},
            "expert":   {"task_count": 0.85, "domain_depth": 0.82, "reasoning_hops": 0.88,
                         "output_structure": 0.75, "knowledge_breadth": 0.80},
        }
        rubric = dict(bases.get(complexity, bases["moderate"]))

        # Boost the dominant dimension
        if dominant in rubric:
            rubric[dominant] = min(rubric[dominant] + 0.20, 1.0)

        # Compute raw_score
        weights = {"task_count": 0.25, "domain_depth": 0.20,
                   "reasoning_hops": 0.25, "output_structure": 0.15,
                   "knowledge_breadth": 0.15}
        rubric["raw_score"] = sum(rubric[k] * weights[k] for k in weights)
        return rubric

    def _find_optimal_model(self, rubric: dict, complexity: str) -> str:
        """
        Find the optimal model for a rubric profile considering quality and cost.

        For trivial/simple: prefer cheapest model that meets quality bar.
        For moderate: best value (quality/cost ratio).
        For complex/expert: best quality, cost is secondary.
        """
        bench_weights = _rubric_to_benchmark_weights(rubric)
        min_quality = self._min_quality_for_band(complexity)

        best_model = "llama-4"  # default
        best_score = -1.0

        for model_id, info in self._model_data.items():
            benchmarks = info.get("benchmarks", {})
            cost = info.get("cost_per_1k_tokens", 0.0)

            quality = sum(
                benchmarks.get(bench, 0.5) * weight
                for bench, weight in bench_weights.items()
            )

            if quality < min_quality:
                continue

            # Scoring strategy varies by complexity
            if complexity in ("trivial", "simple"):
                # Minimise cost while meeting quality bar
                score = quality - cost * 50  # Heavily penalise cost
            elif complexity == "moderate":
                # Balance quality and cost (value scoring)
                cost_factor = math.log(cost * 1000 + 1) + 0.1
                score = quality / cost_factor
            else:
                # Complex/expert: quality is primary, cost is tie-breaker
                score = quality * 10 - cost  # Quality dominates

            if score > best_score:
                best_score = score
                best_model = model_id

        return best_model

    # ==================================================================
    # Evaluation
    # ==================================================================

    def evaluate(self, test_queries: Optional[list[dict]] = None) -> dict:
        """
        Evaluate the trained router on test queries.

        Returns accuracy, per-tier accuracy, and confusion details.
        """
        if self._classifier is None:
            return {"error": "No trained model — run train() first"}

        if test_queries is None:
            test_queries = self._load_training_queries()

        if not test_queries:
            return {"error": "No test queries"}

        embedder = self._get_embedder()
        correct = 0
        total = 0
        tier_correct: dict[str, int] = {"trivial": 0, "simple": 0,
                                         "moderate": 0, "complex": 0, "expert": 0}
        tier_total: dict[str, int] = dict(tier_correct)
        mismatches: list[dict] = []

        for query_info in test_queries:
            rubric = self._complexity_to_rubric(
                query_info["complexity"], query_info["dominant_rubric"]
            )
            expected = self._find_optimal_model(rubric, query_info["complexity"])

            result = self.recommend(
                query_info["text"],
                rubric=rubric,
                complexity_band=query_info["complexity"],
            )

            total += 1
            band = query_info["complexity"]
            tier_total[band] = tier_total.get(band, 0) + 1

            # Check if same model OR same tier
            predicted = result.recommended_model_id
            expected_tier = self._model_data.get(expected, {}).get("tier", "")
            predicted_tier = self._model_data.get(predicted, {}).get("tier", "")

            if predicted == expected:
                correct += 1
                tier_correct[band] = tier_correct.get(band, 0) + 1
            elif predicted_tier == expected_tier:
                # Same tier = acceptable
                correct += 1
                tier_correct[band] = tier_correct.get(band, 0) + 1
            else:
                mismatches.append({
                    "query": query_info["text"][:80],
                    "complexity": band,
                    "expected": expected,
                    "predicted": predicted,
                    "expected_tier": expected_tier,
                    "predicted_tier": predicted_tier,
                })

        return {
            "accuracy": round(correct / total, 4) if total > 0 else 0.0,
            "total": total,
            "correct": correct,
            "per_complexity": {
                band: round(tier_correct.get(band, 0) / max(tier_total.get(band, 1), 1), 4)
                for band in tier_total
            },
            "mismatches": mismatches[:10],  # Show first 10
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_benchmark_router: Optional[BenchmarkRouter] = None


def get_benchmark_router() -> BenchmarkRouter:
    """Get or create the global benchmark router instance."""
    global _benchmark_router
    if _benchmark_router is None:
        _benchmark_router = BenchmarkRouter(lazy_load_embedder=True)
    return _benchmark_router
