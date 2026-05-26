"""
Tests for the aggregate-scores prior.

Validates:
  • Loading the bundled model_aggregate_scores.json
  • prior_quality() honours modality-specific weights
  • Models missing entirely fall back to default
  • Per-modality benchmark relevance maps make sense
  • Missing benchmarks within a model don't crash
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.layer0_model_infra.routing.aggregate_scores import (
    AggregateScores,
    DEFAULT_FALLBACK_VALUE,
    RELEVANCE_WEIGHTS,
)
from src.layer0_model_infra.routing.layer3_types import Modality


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLED_SCORES = REPO_ROOT / "src/layer0_model_infra/data/model_aggregate_scores.json"


@pytest.fixture
def synthetic_scores(tmp_path):
    """Tiny synthetic aggregate_scores.json for deterministic unit tests."""
    payload = {
        "_meta": {"schema_version": "1.0", "last_refresh": "test"},
        "models": {
            "best_coder": {
                "humaneval": 0.95,
                "humaneval_plus": 0.90,
                "mbpp": 0.92,
                "livecodebench": 0.85,
                "livebench_coding": 0.80,
                "arena_elo_normalised": 0.85,
            },
            "best_mather": {
                "humaneval": 0.55,         # weak on code
                "humaneval_plus": 0.50,
                "mbpp": 0.55,
                "livecodebench": 0.45,
                "livebench_coding": 0.40,
                "math_hard": 0.95,         # strong on math
                "gsm8k": 0.98,
                "gpqa_diamond": 0.75,
                "bbh": 0.85,
                "arena_elo_normalised": 0.90,
            },
            "weak_model": {
                "humaneval": 0.30,
                "math_hard": 0.20,
                "mmlu_pro": 0.40,
                "arena_elo_normalised": 0.50,
            },
            "elo_only": {
                "arena_elo_normalised": 0.80,
            },
        },
    }
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(payload))
    return path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_bundled_scores_load_cleanly():
    """The shipped JSON parses + populates."""
    scores = AggregateScores(BUNDLED_SCORES)
    assert len(scores._scores) >= 20, "expected ~22 models in the bundled scores"


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        AggregateScores(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# prior_quality semantics
# ---------------------------------------------------------------------------


def test_coding_query_prefers_best_coder(synthetic_scores):
    scores = AggregateScores(synthetic_scores)
    q_coder = scores.prior_quality("best_coder", Modality.CODE)
    q_mather = scores.prior_quality("best_mather", Modality.CODE)
    assert q_coder > q_mather, "for CODE modality, code benchmarks should dominate"


def test_math_query_prefers_best_mather(synthetic_scores):
    scores = AggregateScores(synthetic_scores)
    q_coder = scores.prior_quality("best_coder", Modality.MATH)
    q_mather = scores.prior_quality("best_mather", Modality.MATH)
    assert q_mather > q_coder, "for MATH modality, math benchmarks should dominate"


def test_text_modality_uses_text_weights(synthetic_scores):
    scores = AggregateScores(synthetic_scores)
    # weak_model has only mmlu_pro + arena. text weights heavily weight mmlu_pro.
    q = scores.prior_quality("weak_model", Modality.TEXT)
    # Should be between 0.40 (mmlu_pro) and 0.50 (arena) blended.
    assert 0.35 < q < 0.55


def test_unknown_model_returns_fallback(synthetic_scores):
    scores = AggregateScores(synthetic_scores)
    q = scores.prior_quality("totally-unknown-model", Modality.TEXT)
    assert q == DEFAULT_FALLBACK_VALUE


def test_model_with_only_arena_elo_falls_to_arena(synthetic_scores):
    """elo_only model only has arena_elo_normalised. For CODE modality, no
    code benchmarks are present, so the function should fall through to
    arena_elo_normalised."""
    scores = AggregateScores(synthetic_scores)
    q = scores.prior_quality("elo_only", Modality.CODE)
    # elo_only weights: arena_elo_normalised has weight 0.05 in CODE; only it
    # is present, so prior = 0.80*0.05/0.05 = 0.80
    assert q == pytest.approx(0.80, abs=0.05)


def test_string_modality_accepted(synthetic_scores):
    """Modality can be passed as string or enum."""
    scores = AggregateScores(synthetic_scores)
    q_enum = scores.prior_quality("best_coder", Modality.CODE)
    q_str = scores.prior_quality("best_coder", "code")
    assert q_enum == q_str


def test_unknown_modality_falls_to_text_weights(synthetic_scores):
    scores = AggregateScores(synthetic_scores)
    # Pass a bogus modality string — should silently use TEXT weights
    q_unknown = scores.prior_quality("best_coder", "totally_made_up")
    q_text = scores.prior_quality("best_coder", Modality.TEXT)
    assert q_unknown == q_text


# ---------------------------------------------------------------------------
# Relevance weights sanity
# ---------------------------------------------------------------------------


def test_relevance_weights_sum_to_one_per_modality():
    """Each modality's weights should sum to 1.0 (so prior is a proper
    weighted average when all benchmarks are present)."""
    for modality, weights in RELEVANCE_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, (
            f"RELEVANCE_WEIGHTS[{modality!r}] sums to {total}, not 1.0"
        )


def test_all_modalities_have_arena_elo():
    """Every modality should include arena_elo_normalised as a fallback when
    no specific benchmark data is available."""
    for modality, weights in RELEVANCE_WEIGHTS.items():
        assert "arena_elo_normalised" in weights, (
            f"modality {modality!r} doesn't include arena_elo_normalised — "
            f"the fallback path will break for that modality"
        )


# ---------------------------------------------------------------------------
# Bundled scores: per-model sanity
# ---------------------------------------------------------------------------


def test_frontier_models_score_higher_than_cheap_models_on_code():
    """Sanity: Claude Opus 4.5 + Sonnet 4.5 should score higher than Haiku
    on coding-weighted aggregate."""
    scores = AggregateScores(BUNDLED_SCORES)
    if scores.has("claude-opus-4-5") and scores.has("claude-3-5-haiku"):
        q_opus = scores.prior_quality("claude-opus-4-5", Modality.CODE)
        q_haiku = scores.prior_quality("claude-3-5-haiku", Modality.CODE)
        assert q_opus > q_haiku, (
            f"Claude Opus prior ({q_opus:.3f}) should beat Claude Haiku ({q_haiku:.3f}) on code"
        )


def test_dedicated_coder_beats_general_model_on_code():
    """Sanity: Qwen 2.5 Coder should score higher on CODE than a general
    Llama model."""
    scores = AggregateScores(BUNDLED_SCORES)
    if scores.has("qwen-2.5-coder-32b-openrouter-free") and scores.has("llama-3.1-8b-instant-groq"):
        q_coder = scores.prior_quality("qwen-2.5-coder-32b-openrouter-free", Modality.CODE)
        q_general = scores.prior_quality("llama-3.1-8b-instant-groq", Modality.CODE)
        assert q_coder > q_general, (
            f"Qwen Coder prior ({q_coder:.3f}) should beat Llama 8B ({q_general:.3f}) on code"
        )
