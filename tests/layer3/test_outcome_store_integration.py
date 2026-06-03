"""
Integration tests for OutcomeStore — these exercise the REAL outcomes.parquet
built by ``scripts/layer3/build_outcomes_corpus.py``. Skipped if the corpus
hasn't been built yet (CI / first-time checkout).

Catches the kinds of issues that synthetic-data unit tests don't:
  • Real parquet schema matches what OutcomeStore expects
  • DuckDB can scan the real-world row count without OOM
  • The model_id values in the corpus actually match the registry
  • Per-source coverage is plausible (LiveBench rows dominate)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.layer0_model_infra.routing.outcome_store import OutcomeStore
from src.layer0_model_infra.routing.registry_loader import get_layer3_registry


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTCOMES_PARQUET = REPO_ROOT / "data/processed/outcomes.parquet"


pytestmark = pytest.mark.skipif(
    not OUTCOMES_PARQUET.exists() or OUTCOMES_PARQUET.stat().st_size < 1000,
    reason="outcomes.parquet not built yet; run scripts/layer3/build_outcomes_corpus.py",
)


@pytest.fixture(scope="module")
def store() -> OutcomeStore:
    return OutcomeStore(OUTCOMES_PARQUET)


def test_real_corpus_has_outcomes(store):
    s = store.stats()
    assert s["rows"] > 0, "outcomes.parquet exists but has zero rows"
    assert s["unique_models"] > 0
    assert s["unique_questions"] > 0


def test_real_corpus_models_are_in_registry(store, all_keys_set):
    """Every model_id in the corpus must resolve to a registry entry —
    otherwise the kNN router has no way to use those outcomes for routing
    decisions. Mis-mapped IDs would silently waste corpus data.
    """
    from src.layer0_model_infra.routing.registry_loader import reset_layer3_registry
    reset_layer3_registry()
    registry = get_layer3_registry()
    registry_models = {e.model_id for e in registry.all_models()}

    corpus_models = set(store.all_models())
    unknown = corpus_models - registry_models
    assert not unknown, (
        f"Corpus has model_ids unknown to registry: {sorted(unknown)} — "
        f"either add them to data/registry.json or remove their mapping "
        f"from data/model_id_mapping.json"
    )


def test_real_corpus_outcomes_in_unit_interval(store):
    """Outcomes must be in [0, 1]."""
    s = store._conn.execute(  # type: ignore[union-attr]
        "SELECT MIN(outcome) AS lo, MAX(outcome) AS hi FROM outcomes"
    ).fetchone()
    store._ensure_loaded()
    lo, hi = s
    assert 0.0 <= float(lo) <= 1.0
    assert 0.0 <= float(hi) <= 1.0


def test_real_corpus_coverage_by_source(store):
    """MMLU-Pro (Open LLM Leaderboard) is the primary outcome source after the
    benchmark harvest; LiveBench and SWE-bench are smaller secondary sources."""
    by_source = store.coverage_by_source()
    sources = {row["source_url"]: row["n"] for row in by_source}
    # Every source must be a real URL (HF dataset / leaderboard / SWE-bench repo).
    for url in sources:
        assert url.startswith("https://"), f"non-URL source: {url!r}"
    total = sum(sources.values())
    # MMLU-Pro (harvested from the Open LLM Leaderboard) dominates the corpus.
    mmlu_rows = sum(n for url, n in sources.items() if "open-llm-leaderboard" in url.lower())
    assert mmlu_rows / total > 0.5, (
        f"MMLU-Pro is only {mmlu_rows}/{total} rows; expected the harvested "
        f"MMLU-Pro outcomes to dominate. Sources: {sources}"
    )
    # LiveBench remains present as the original seed outcome source.
    livebench_rows = sum(n for url, n in sources.items() if "livebench" in url.lower())
    assert livebench_rows > 0, f"LiveBench outcomes missing entirely. Sources: {sources}"


def test_real_corpus_lookup_batch_returns_outcomes(store):
    """End-to-end sanity: pick a model that the corpus has, look up a few
    question_ids, get back actual outcomes."""
    models = store.all_models()
    assert models, "corpus has zero models"
    # Pick the model with the most coverage
    coverages = [(m, store.coverage_for_model(m)["n_outcomes"]) for m in models]
    top_model = max(coverages, key=lambda kv: kv[1])[0]

    # Grab some question_ids that have outcomes for this model
    store._ensure_loaded()
    rows = store._conn.execute(  # type: ignore[union-attr]
        "SELECT DISTINCT question_global_id FROM outcomes WHERE model_id = ? LIMIT 10",
        [top_model],
    ).fetchall()
    qids = [r[0] for r in rows]
    assert qids

    result = store.lookup_batch(top_model, qids)
    assert len(result) == len(qids)
    for qid in qids:
        assert qid in result
        assert 0.0 <= result[qid] <= 1.0


def test_real_corpus_mean_outcomes_match_known_ordering(store):
    """Sanity: among LiveBench-covered models, larger models should generally
    outperform smaller ones. Tests against known ordering:
      Claude 3.5 Sonnet > Claude 3.5 Haiku
      Llama 3.3 70B > Llama 3.1 8B
    """
    pairs = [
        ("claude-3-5-sonnet", "claude-3-5-haiku"),
        ("llama-3.3-70b-versatile-groq", "llama-3.1-8b-instant-groq"),
    ]
    models = set(store.all_models())
    for bigger, smaller in pairs:
        if bigger not in models or smaller not in models:
            continue  # skip if either model isn't covered
        big_mean = store.coverage_for_model(bigger)["mean_outcome"]
        small_mean = store.coverage_for_model(smaller)["mean_outcome"]
        assert big_mean > small_mean, (
            f"sanity regression: {bigger}={big_mean:.3f} should beat "
            f"{smaller}={small_mean:.3f} on LiveBench mean"
        )
