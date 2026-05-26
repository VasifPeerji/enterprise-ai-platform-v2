"""
Tests for the corpus build framework (scripts/layer3/_common.py).

Covers:
  • Accumulator deduplicates by (model_id, qid)
  • Question rows deduplicate by qid (first writer wins)
  • Parquet output schema is what outcome_store expects
  • Outcome clamp + normalisation
  • Model-ID mapper handles missing entries gracefully
  • Validation-ID lock loads correctly
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from scripts.layer3._common import (
    CorpusAccumulator,
    ModelIdMapper,
    OutcomeRow,
    QuestionRow,
    hash_text_id,
    load_locked_validation_ids,
    make_question_global_id,
    normalise_outcome,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(qid="livebench:q1", model="llama-3.3-70b-versatile-groq", outcome=0.85,
         source="https://livebench.ai") -> OutcomeRow:
    return OutcomeRow(
        question_global_id=qid,
        model_id=model,
        outcome=outcome,
        source_url=source,
        ingested_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Outcome deduplication
# ---------------------------------------------------------------------------


def test_first_outcome_added_returns_true():
    acc = CorpusAccumulator()
    assert acc.add_outcome(_row()) is True
    assert len(acc.outcomes) == 1


def test_duplicate_outcome_skipped():
    """Same (model_id, qid) — second write should be a no-op."""
    acc = CorpusAccumulator()
    acc.add_outcome(_row(outcome=0.85))
    added = acc.add_outcome(_row(outcome=0.95))  # different score, same pair
    assert added is False
    assert len(acc.outcomes) == 1
    # The first outcome wins — second is discarded
    assert acc.outcomes[0].outcome == pytest.approx(0.85, abs=1e-5)


def test_different_model_same_question_both_kept():
    acc = CorpusAccumulator()
    acc.add_outcome(_row(model="llama-3.3-70b-versatile-groq"))
    acc.add_outcome(_row(model="deepseek-v3-openrouter-free"))
    assert len(acc.outcomes) == 2


def test_different_question_same_model_both_kept():
    acc = CorpusAccumulator()
    acc.add_outcome(_row(qid="livebench:q1"))
    acc.add_outcome(_row(qid="livebench:q2"))
    assert len(acc.outcomes) == 2


def test_outcome_clamped_to_unit_interval():
    acc = CorpusAccumulator()
    acc.add_outcome(_row(outcome=1.5))   # over-clip
    acc.add_outcome(_row(qid="q2", outcome=-0.3))  # under-clip
    assert acc.outcomes[0].outcome == 1.0
    assert acc.outcomes[1].outcome == 0.0


# ---------------------------------------------------------------------------
# Question deduplication
# ---------------------------------------------------------------------------


def test_first_question_wins():
    acc = CorpusAccumulator()
    acc.add_question(QuestionRow(
        question_global_id="livebench:q1",
        question_text="How do I deploy nginx?",
        benchmark_source="livebench",
        modality="text",
    ))
    acc.add_question(QuestionRow(
        question_global_id="livebench:q1",   # same qid
        question_text="DIFFERENT TEXT",
        benchmark_source="other",
        modality="code",
    ))
    assert len(acc.questions) == 1
    assert acc.questions["livebench:q1"].question_text == "How do I deploy nginx?"


# ---------------------------------------------------------------------------
# Parquet output
# ---------------------------------------------------------------------------


def test_outcomes_parquet_has_expected_schema(tmp_path: Path):
    acc = CorpusAccumulator()
    acc.add_outcome(_row())
    out = tmp_path / "outcomes.parquet"
    acc.write_outcomes_parquet(out)
    table = pq.read_table(out)
    # Schema must match what OutcomeStore expects
    assert set(table.column_names) == {
        "question_global_id", "model_id", "outcome", "source_url", "ingested_at",
    }


def test_questions_parquet_has_expected_schema(tmp_path: Path):
    acc = CorpusAccumulator()
    acc.add_question(QuestionRow(
        question_global_id="livebench:q1",
        question_text="?",
        benchmark_source="livebench",
    ))
    out = tmp_path / "questions.parquet"
    acc.write_questions_parquet(out)
    table = pq.read_table(out)
    assert set(table.column_names) == {
        "question_global_id", "question_text", "benchmark_source",
        "language", "modality", "domain", "difficulty_tier",
    }


def test_summary_counts():
    acc = CorpusAccumulator()
    acc.add_outcome(_row(qid="q1", model="m1"))
    acc.add_outcome(_row(qid="q1", model="m2"))
    acc.add_outcome(_row(qid="q2", model="m1"))
    acc.add_question(QuestionRow(
        question_global_id="q1", question_text="?", benchmark_source="x"))
    s = acc.summary()
    assert s == {
        "n_outcomes": 3,
        "n_unique_models": 2,
        "n_unique_questions": 2,
        "n_question_rows": 1,
    }


# ---------------------------------------------------------------------------
# Model-ID mapping
# ---------------------------------------------------------------------------


def test_mapper_loads_bundled_mapping():
    """The shipped model_id_mapping.json parses + has at least one entry per source."""
    mapper = ModelIdMapper()
    # Spot-check: the LiveBench mapping should know about Llama 3.3 70B
    assert mapper.map("livebench", "llama-3.3-70b-instruct") == "llama-3.3-70b-versatile-groq"


def test_mapper_unknown_source_returns_none():
    mapper = ModelIdMapper()
    assert mapper.map("nonexistent-source", "anything") is None


def test_mapper_unknown_model_returns_none_and_tracks():
    mapper = ModelIdMapper()
    assert mapper.map("livebench", "totally-fictional-model") is None
    assert "totally-fictional-model" in mapper.unmapped_seen["livebench"]


def test_mapper_known_model_does_not_appear_in_unmapped():
    mapper = ModelIdMapper()
    mapper.map("livebench", "llama-3.3-70b-instruct")
    assert "llama-3.3-70b-instruct" not in mapper.unmapped_seen["livebench"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_make_question_global_id():
    assert make_question_global_id("livebench", "q1") == "livebench:q1"
    assert make_question_global_id("livebench", 42) == "livebench:42"


def test_hash_text_id_is_deterministic():
    a = hash_text_id("test", "Hello world")
    b = hash_text_id("test", "Hello world")
    c = hash_text_id("test", "Different text")
    assert a == b
    assert a != c
    assert a.startswith("test:sha-")


def test_normalise_outcome_clamps():
    assert normalise_outcome(1.5) == 1.0
    assert normalise_outcome(-0.3) == 0.0
    assert normalise_outcome(0.7) == pytest.approx(0.7, abs=1e-5)


def test_normalise_outcome_scaling():
    # Scale 1..10 → 0..1
    assert normalise_outcome(5.5, scale_min=1.0, scale_max=10.0) == pytest.approx(0.5, abs=1e-5)
    assert normalise_outcome(10.0, scale_min=1.0, scale_max=10.0) == 1.0
    assert normalise_outcome(1.0, scale_min=1.0, scale_max=10.0) == 0.0


def test_normalise_outcome_non_numeric_returns_zero():
    assert normalise_outcome(None) == 0.0
    assert normalise_outcome("not a number") == 0.0


# ---------------------------------------------------------------------------
# Locked-validation-ids file
# ---------------------------------------------------------------------------


def test_load_locked_validation_ids_missing_returns_empty(tmp_path, monkeypatch):
    """When validation_set_ids.json doesn't exist, return empty set so a
    first-time corpus build proceeds without exclusion.
    """
    from scripts.layer3 import _common
    monkeypatch.setattr(_common, "VALIDATION_IDS_JSON", tmp_path / "missing.json")
    assert load_locked_validation_ids() == set()


def test_load_locked_validation_ids_reads_json(tmp_path, monkeypatch):
    from scripts.layer3 import _common
    path = tmp_path / "ids.json"
    path.write_text(json.dumps({"locked_ids": ["q1", "q2", "q3"]}))
    monkeypatch.setattr(_common, "VALIDATION_IDS_JSON", path)
    assert load_locked_validation_ids() == {"q1", "q2", "q3"}
