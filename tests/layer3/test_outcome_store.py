"""
Tests for the DuckDB-backed outcome store.

Uses a tiny synthetic parquet so tests run in <1s and don't depend on the
real benchmark corpus existing on the filesystem.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.layer0_model_infra.routing.outcome_store import OutcomeStore


@pytest.fixture
def synthetic_parquet(tmp_path: Path) -> Path:
    """Build a tiny outcomes.parquet for unit tests."""
    now = datetime.now(timezone.utc)
    table = pa.table(
        {
            "question_global_id": [
                "livebench:q1", "livebench:q1", "livebench:q1",
                "livebench:q2", "livebench:q2",
                "mmlu_pro:q1",
            ],
            "model_id": [
                "llama-3.3-70b-versatile-groq",
                "deepseek-v3-openrouter-free",
                "claude-3-5-sonnet",
                "llama-3.3-70b-versatile-groq",
                "deepseek-v3-openrouter-free",
                "llama-3.3-70b-versatile-groq",
            ],
            "outcome": [1.0, 1.0, 0.85, 0.0, 1.0, 0.7],
            "source_url": ["https://livebench.ai"] * 5 + ["https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro"],
            "ingested_at": [now] * 6,
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


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def test_lookup_batch_returns_present_outcomes(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    result = store.lookup_batch(
        "llama-3.3-70b-versatile-groq",
        ["livebench:q1", "livebench:q2", "mmlu_pro:q1", "nonexistent:q"],
    )
    # Float32 → float64 roundtrip through Parquet introduces tiny precision
    # noise (0.7 ≈ 0.699999988079...). Compare with tolerance.
    assert set(result.keys()) == {"livebench:q1", "livebench:q2", "mmlu_pro:q1"}
    assert result["livebench:q1"] == pytest.approx(1.0, abs=1e-5)
    assert result["livebench:q2"] == pytest.approx(0.0, abs=1e-5)
    assert result["mmlu_pro:q1"] == pytest.approx(0.7, abs=1e-5)
    assert "nonexistent:q" not in result


def test_lookup_batch_for_unknown_model_returns_empty(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    result = store.lookup_batch("gpt-99-future", ["livebench:q1"])
    assert result == {}


def _matches(actual: dict, expected: dict, tol: float = 1e-5) -> bool:
    """Float-tolerant dict comparison for parquet roundtrip noise."""
    if set(actual.keys()) != set(expected.keys()):
        return False
    return all(abs(actual[k] - expected[k]) < tol for k in expected)


def test_lookup_batch_empty_question_list(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    result = store.lookup_batch("llama-3.3-70b-versatile-groq", [])
    assert result == {}


def test_lookup_for_all_models_returns_per_model_dict(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    result = store.lookup_for_all_models(
        ["livebench:q1", "livebench:q2"],
        ["llama-3.3-70b-versatile-groq", "deepseek-v3-openrouter-free", "gpt-4o"],
    )
    assert set(result.keys()) == {
        "llama-3.3-70b-versatile-groq",
        "deepseek-v3-openrouter-free",
        "gpt-4o",
    }
    assert _matches(result["llama-3.3-70b-versatile-groq"], {"livebench:q1": 1.0, "livebench:q2": 0.0})
    assert _matches(result["deepseek-v3-openrouter-free"], {"livebench:q1": 1.0, "livebench:q2": 1.0})
    assert result["gpt-4o"] == {}  # unknown model


# ---------------------------------------------------------------------------
# Coverage analytics
# ---------------------------------------------------------------------------


def test_coverage_for_model(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    cov = store.coverage_for_model("llama-3.3-70b-versatile-groq")
    assert cov["n_outcomes"] == 3
    assert cov["n_unique_questions"] == 3
    # Mean of [1.0, 0.0, 0.7] = 0.5667
    assert abs(cov["mean_outcome"] - 0.5667) < 0.01


def test_coverage_for_unknown_model(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    cov = store.coverage_for_model("gpt-99-future")
    assert cov["n_outcomes"] == 0
    assert cov["n_unique_questions"] == 0
    assert cov["mean_outcome"] is None


def test_coverage_by_source(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    by_source = store.coverage_by_source()
    sources = {row["source_url"] for row in by_source}
    assert "https://livebench.ai" in sources
    assert "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro" in sources


def test_coverage_by_source_with_prefix(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    filtered = store.coverage_by_source("https://livebench.ai")
    assert len(filtered) == 1
    assert filtered[0]["n"] == 5


def test_stats(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    s = store.stats()
    assert s["rows"] == 6
    assert s["unique_models"] == 3
    assert s["unique_questions"] == 3


def test_all_models(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    models = store.all_models()
    assert set(models) == {
        "llama-3.3-70b-versatile-groq",
        "deepseek-v3-openrouter-free",
        "claude-3-5-sonnet",
    }


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_missing_parquet_raises(tmp_path):
    store = OutcomeStore(tmp_path / "does_not_exist.parquet")
    with pytest.raises(FileNotFoundError):
        store.lookup_batch("any", ["any"])


def test_close_then_reload(synthetic_parquet):
    store = OutcomeStore(synthetic_parquet)
    _ = store.stats()
    store.close()
    # Re-querying should re-init the connection transparently
    s = store.stats()
    assert s["rows"] == 6
