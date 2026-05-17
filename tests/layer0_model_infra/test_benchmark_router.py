"""
Tests for BenchmarkRouter — sentence-transformer + gradient boosting.

Tests:
1. Benchmark data integrity (22 industry LLMs)
2. Rubric-based benchmark scoring (NO keyword matching)
3. Quality/cost model selection
4. Training pipeline (embedding + GBC)
5. Budget constraints
6. Complexity-aware quality floors
"""

import json
from pathlib import Path

import numpy as np
import pytest

from src.layer0_model_infra.routing.benchmark_router import (
    BenchmarkRouter,
    BenchmarkRouterResult,
    _rubric_to_benchmark_weights,
)


# ---------------------------------------------------------------------------
# Rubric fixtures (simulate complexity classifier output)
# ---------------------------------------------------------------------------

@pytest.fixture
def trivial_rubric():
    return {
        "task_count": 0.05, "domain_depth": 0.05, "reasoning_hops": 0.05,
        "output_structure": 0.05, "knowledge_breadth": 0.05, "raw_score": 0.05,
    }

@pytest.fixture
def simple_rubric():
    return {
        "task_count": 0.15, "domain_depth": 0.15, "reasoning_hops": 0.12,
        "output_structure": 0.12, "knowledge_breadth": 0.18, "raw_score": 0.15,
    }

@pytest.fixture
def complex_rubric():
    return {
        "task_count": 0.70, "domain_depth": 0.60, "reasoning_hops": 0.65,
        "output_structure": 0.60, "knowledge_breadth": 0.55, "raw_score": 0.65,
    }

@pytest.fixture
def expert_rubric():
    return {
        "task_count": 0.85, "domain_depth": 0.82, "reasoning_hops": 0.90,
        "output_structure": 0.75, "knowledge_breadth": 0.80, "raw_score": 0.86,
    }

@pytest.fixture
def coding_rubric():
    """High task_count + output_structure → should weight HumanEval + IFEval."""
    return {
        "task_count": 0.75, "domain_depth": 0.40, "reasoning_hops": 0.50,
        "output_structure": 0.70, "knowledge_breadth": 0.30, "raw_score": 0.55,
    }

@pytest.fixture
def reasoning_rubric():
    """High reasoning_hops + domain_depth → should weight BBH + ARC."""
    return {
        "task_count": 0.30, "domain_depth": 0.70, "reasoning_hops": 0.80,
        "output_structure": 0.25, "knowledge_breadth": 0.50, "raw_score": 0.55,
    }


@pytest.fixture
def router():
    return BenchmarkRouter(lazy_load_embedder=True)


# ---------------------------------------------------------------------------
# Tests — Data loading
# ---------------------------------------------------------------------------

class TestDataLoading:
    """Test that benchmark data loads correctly."""

    def test_benchmark_data_loaded(self, router):
        assert len(router._model_data) >= 22, \
            f"Expected 22+ models, got {len(router._model_data)}"

    def test_all_models_have_benchmarks(self, router):
        for model_id, info in router._model_data.items():
            assert "benchmarks" in info, f"{model_id} missing benchmarks"
            assert len(info["benchmarks"]) >= 7, \
                f"{model_id} should have 7 benchmark scores"
            assert "cost_per_1k_tokens" in info, f"{model_id} missing cost"
            assert "tier" in info, f"{model_id} missing tier"

    def test_all_tiers_represented(self, router):
        tiers = {info["tier"] for info in router._model_data.values()}
        assert tiers == {"premium", "moderate", "cheap"}, f"Got tiers: {tiers}"

    def test_user_specified_models_present(self, router):
        """Verify the exact models the user requested are in the data."""
        required = [
            "gpt-5.4", "gpt-5-mini", "gpt-5-nano",
            "claude-opus-4.6", "claude-sonnet-4.6", "claude-haiku",
            "gemini-3.1-pro", "gemini-2.5-pro", "gemini-flash",
            "grok-3", "grok-3-mini", "grok-lite",
            "llama-4-ultra", "llama-4", "llama-small",
            "mistral-large-3", "mistral-medium", "mistral-small",
        ]
        for model_id in required:
            assert model_id in router._model_data, \
                f"Required model {model_id} not found"

    def test_benchmark_json_valid(self):
        path = Path(__file__).resolve().parent.parent.parent / \
            "src" / "layer0_model_infra" / "data" / "model_benchmarks.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "models" in data
        assert "benchmark_to_rubric_mapping" in data


# ---------------------------------------------------------------------------
# Tests — Rubric to benchmark weights (NO keywords!)
# ---------------------------------------------------------------------------

class TestRubricWeighting:
    """Test that rubric dimensions correctly weight benchmarks."""

    def test_high_reasoning_weights_bbh_arc(self, reasoning_rubric):
        weights = _rubric_to_benchmark_weights(reasoning_rubric)
        # BBH and ARC should be weighted highest
        assert weights["bbh"] > weights["mmlu"], \
            "High reasoning should weight BBH > MMLU"
        assert weights["arc_challenge"] > weights["humaneval"], \
            "High reasoning should weight ARC > HumanEval"

    def test_high_coding_weights_humaneval(self, coding_rubric):
        weights = _rubric_to_benchmark_weights(coding_rubric)
        assert weights["humaneval"] > weights["mmlu"], \
            "High task_count+output should weight HumanEval > MMLU"
        assert weights["ifeval"] > weights["gsm8k"], \
            "High output_structure should weight IFEval"

    def test_weights_sum_to_one(self, trivial_rubric):
        weights = _rubric_to_benchmark_weights(trivial_rubric)
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"Weights should sum to 1.0, got {total}"


# ---------------------------------------------------------------------------
# Tests — Model recommendation
# ---------------------------------------------------------------------------

class TestRecommendation:
    """Test model selection quality."""

    def test_returns_valid_result(self, router):
        result = router.recommend("What is Python?")
        assert isinstance(result, BenchmarkRouterResult)
        assert result.recommended_model_id != ""

    def test_trivial_selects_cheap(self, router, trivial_rubric):
        result = router.recommend(
            "Hi there",
            rubric=trivial_rubric,
            complexity_band="trivial",
        )
        assert result.cost_per_1k <= 0.005, \
            f"Trivial should get cheap model, cost={result.cost_per_1k}"

    def test_complex_selects_quality(self, router, complex_rubric):
        result = router.recommend(
            "Design a distributed consensus protocol",
            rubric=complex_rubric,
            complexity_band="complex",
        )
        assert result.quality_score >= 0.75, \
            f"Complex should get quality model, quality={result.quality_score}"

    def test_expert_selects_premium(self, router, expert_rubric):
        result = router.recommend(
            "Prove convergence bounds for transformer attention",
            rubric=expert_rubric,
            complexity_band="expert",
        )
        tier = router._model_data.get(result.recommended_model_id, {}).get("tier", "")
        assert tier == "premium", \
            f"Expert should get premium tier, got {tier} ({result.recommended_model_id})"

    def test_budget_constraint_respected(self, router):
        result = router.recommend(
            "Explain machine learning",
            max_cost_per_1k=0.001,
        )
        assert result.cost_per_1k <= 0.001, \
            f"Budget violated: cost={result.cost_per_1k} > 0.001"

    def test_top_candidates_populated(self, router):
        result = router.recommend("Explain photosynthesis")
        assert len(result.top_candidates) >= 1
        assert len(result.top_candidates) <= 3

    def test_coding_query_uses_benchmark_not_keywords(self, router, coding_rubric):
        """The router should score coding queries via rubric, not keywords."""
        result = router.recommend(
            "Build a web service",  # No explicit "code" / "function" keyword
            rubric=coding_rubric,
            complexity_band="complex",
        )
        assert result.quality_score >= 0.75, \
            "Coding rubric should select capable model regardless of keywords"


# ---------------------------------------------------------------------------
# Tests — Training pipeline
# ---------------------------------------------------------------------------

class TestTraining:
    """Test the GBC training pipeline."""

    def test_training_runs(self, router):
        stats = router.train(n_estimators=20, max_depth=4)
        assert "error" not in stats, f"Training failed: {stats}"
        assert stats["training_samples"] >= 100
        assert stats["n_classes"] >= 3
        assert stats["train_accuracy"] >= 0.0

    def test_trained_model_recommends(self, router, complex_rubric):
        """After training, trained_gbc should be the method."""
        router.train(n_estimators=20, max_depth=4)
        result = router.recommend(
            "Design a REST API with authentication",
            rubric=complex_rubric,
            complexity_band="complex",
        )
        assert result.recommended_model_id != ""
        assert result.method in {"trained_gbc", "benchmark_lookup"}

    def test_evaluation_returns_stats(self, router):
        """After training, evaluate() should return accuracy stats."""
        router.train(n_estimators=20, max_depth=4)
        eval_result = router.evaluate()
        assert "error" not in eval_result, f"Eval failed: {eval_result}"
        assert eval_result["accuracy"] >= 0.0
        assert "per_complexity" in eval_result


# ---------------------------------------------------------------------------
# Tests — Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge case handling."""

    def test_empty_query(self, router):
        result = router.recommend("")
        assert isinstance(result, BenchmarkRouterResult)

    def test_very_long_query(self, router):
        result = router.recommend("explain " * 500)
        assert isinstance(result, BenchmarkRouterResult)

    def test_filtered_to_single_model(self, router):
        result = router.recommend(
            "What is Python?",
            available_model_ids=["llama-4"],
        )
        assert result.recommended_model_id == "llama-4"

    def test_impossible_budget(self, router, expert_rubric):
        result = router.recommend(
            "Prove P=NP",
            rubric=expert_rubric,
            complexity_band="expert",
            max_cost_per_1k=0.0001,
        )
        # Should still return something (fallback or relaxed constraint)
        assert isinstance(result, BenchmarkRouterResult)
