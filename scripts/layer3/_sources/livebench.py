"""
LiveBench builder.

LiveBench is the highest-value single source for this corpus:
  • Monthly refresh — current models, current contamination protection
  • Per-question outputs + judgments for many commercial and open models
  • Six task categories: reasoning, coding, mathematics, data-analysis,
    language, instruction-following — gives us modality coverage out of
    the box
  • HuggingFace datasets ``livebench/livebench``, ``livebench/model_answer``,
    ``livebench/model_judgment``

Schema we ingest:
  • ``livebench/livebench`` — one row per question with task_id, category,
    turns (the prompt), ground_truth, etc.
  • ``livebench/model_judgment`` — one row per (model, question) with the
    judge's score in [0, 1]. This is our outcome.

Outcome normalisation: LiveBench judge scores are already in [0, 1] (binary
pass/fail for some tasks, graded for others). We pass them through unchanged.

License: Apache-2.0. https://livebench.ai

This module gracefully reports zero outcomes if the dataset can't be loaded
(network down, gated, schema changed) — the main builder logs the warning
and continues with other sources.
"""

from __future__ import annotations

from typing import Optional

from scripts.layer3._common import (
    CorpusAccumulator,
    ModelIdMapper,
    OutcomeRow,
    QuestionRow,
    make_question_global_id,
)


# LiveBench category → our coarse modality mapping
_LB_CATEGORY_TO_MODALITY = {
    "coding": "code",
    "math": "math",
    "mathematics": "math",
    "reasoning": "text",
    "data_analysis": "text",
    "language": "text",
    "instruction_following": "text",
}

_LB_CATEGORY_TO_DIFFICULTY = {
    "coding": "complex",
    "math": "complex",
    "mathematics": "complex",
    "reasoning": "complex",
    "data_analysis": "moderate",
    "language": "moderate",
    "instruction_following": "moderate",
}

SOURCE_KEY = "livebench"
SOURCE_URL_BASE = "https://huggingface.co/datasets/livebench"


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
) -> int:
    """Pull LiveBench questions + judgments and add them to the accumulator.

    Args:
        sample_only: when True, load a tiny slice for quick smoke tests
        max_questions: hard cap on questions ingested (after dedup)

    Returns the number of outcome rows added.
    """
    logger.info("livebench_build_starting")
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("livebench_skipped: datasets library not installed")
        return 0

    # ----- 1. Pull questions -----
    questions = _load_questions(load_dataset, logger, sample_only=sample_only)
    if not questions:
        logger.warning("livebench_skipped: zero questions loaded")
        return 0

    if max_questions is not None:
        questions = questions[:max_questions]

    # Add question metadata rows (deduplicated by qid)
    n_question_rows_added = 0
    qids_in_corpus: set[str] = set()
    for q in questions:
        category = (q.get("category") or "").lower()
        qid = make_question_global_id("livebench", q.get("question_id") or q.get("task_id") or q.get("id"))
        qids_in_corpus.add(qid)
        prompt_text = _extract_prompt(q)
        if not prompt_text:
            continue
        accumulator.add_question(QuestionRow(
            question_global_id=qid,
            question_text=prompt_text[:2000],  # cap stored text to 2KB
            benchmark_source="livebench",
            language="en",
            modality=_LB_CATEGORY_TO_MODALITY.get(category, "text"),
            domain="general",
            difficulty_tier=_LB_CATEGORY_TO_DIFFICULTY.get(category, "moderate"),
        ))
        n_question_rows_added += 1

    logger.info("livebench_questions_loaded n=%d (added=%d)", len(questions), n_question_rows_added)

    # ----- 2. Pull judgments and join to model_id mapping -----
    n_outcomes = _load_and_join_judgments(
        load_dataset, accumulator, mapper, logger,
        qids_in_corpus, sample_only=sample_only,
    )
    logger.info("livebench_build_done outcomes=%d", n_outcomes)
    return n_outcomes


def _load_questions(load_dataset, logger, *, sample_only: bool) -> list[dict]:
    """Load LiveBench question datasets across ALL categories.

    LiveBench publishes one HuggingFace dataset per category. We load all of
    them so the question_ids we ingest line up with the model_judgment dataset's
    coverage (which spans every category). Sequencing matters: if we only load
    `reasoning`, only a sliver of judgments will join.
    """
    # All six LiveBench categories (Apache-2.0, refreshed monthly)
    category_repos = [
        "livebench/reasoning",
        "livebench/coding",
        "livebench/math",
        "livebench/language",
        "livebench/data_analysis",
        "livebench/instruction_following",
    ]
    questions: list[dict] = []
    seen_ids: set[str] = set()
    n_loaded_per_repo: dict[str, int] = {}

    for repo_id in category_repos:
        try:
            ds = load_dataset(repo_id)
        except Exception as exc:
            logger.info("livebench_category_unavailable repo=%s err=%s",
                        repo_id, str(exc)[:120])
            continue

        n_from_this = 0
        for split_name, split_ds in ds.items() if hasattr(ds, "items") else [("test", ds)]:
            for row in split_ds:
                rid = row.get("question_id") or row.get("task_id") or row.get("id")
                if rid is None or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                questions.append(dict(row))
                n_from_this += 1
                if sample_only and len(questions) >= 50:
                    n_loaded_per_repo[repo_id] = n_from_this
                    logger.info("livebench_categories_loaded counts=%s total=%d",
                                n_loaded_per_repo, len(questions))
                    return questions
        n_loaded_per_repo[repo_id] = n_from_this

    logger.info("livebench_categories_loaded counts=%s total=%d",
                n_loaded_per_repo, len(questions))
    return questions


def _load_and_join_judgments(
    load_dataset,
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    qids_in_corpus: set[str],
    *,
    sample_only: bool,
) -> int:
    """Load model_judgment and add (qid, model_id, outcome) rows to the
    accumulator. Filters to qids we already loaded as questions.
    """
    candidates = [
        "livebench/model_judgment",
        "livebench/judgments",
    ]
    n_added = 0
    n_unmapped = 0

    for repo_id in candidates:
        try:
            ds = load_dataset(repo_id)
        except Exception as exc:
            logger.info("livebench_judgment_repo_unavailable repo=%s err=%s", repo_id, str(exc)[:120])
            continue

        for split_name, split_ds in ds.items() if hasattr(ds, "items") else [("train", ds)]:
            for row in split_ds:
                source_model = row.get("model") or row.get("model_id") or row.get("model_name")
                qid_local = row.get("question_id") or row.get("task_id") or row.get("id")
                score = _extract_score(row)
                if source_model is None or qid_local is None or score is None:
                    continue

                qid = make_question_global_id("livebench", qid_local)
                if qid not in qids_in_corpus:
                    continue

                registry_model = mapper.map(SOURCE_KEY, str(source_model))
                if registry_model is None:
                    n_unmapped += 1
                    continue

                added = accumulator.add_outcome(OutcomeRow(
                    question_global_id=qid,
                    model_id=registry_model,
                    outcome=score,
                    source_url=f"{SOURCE_URL_BASE}/{repo_id.split('/')[-1]}",
                ))
                if added:
                    n_added += 1
                if sample_only and n_added >= 500:
                    return n_added

        # Don't try further candidates if one succeeded
        if n_added > 0:
            break

    if n_unmapped > 0:
        logger.info("livebench_unmapped_model_rows n=%d (see model_id_mapping report at end)", n_unmapped)
    return n_added


def _extract_prompt(row: dict) -> Optional[str]:
    """LiveBench rows have different prompt shapes per category. Try the common ones."""
    if "turns" in row:
        turns = row["turns"]
        if isinstance(turns, list) and turns:
            t0 = turns[0]
            if isinstance(t0, dict):
                return t0.get("content") or t0.get("text")
            return str(t0)
    for k in ("prompt", "question", "input", "text"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _extract_score(row: dict) -> Optional[float]:
    """LiveBench judgments may store the score under different keys.

    Returns a float in [0, 1] or None if no score is parseable.
    """
    for k in ("score", "judgment", "rating", "value", "result"):
        v = row.get(k)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            # Could be a string like "pass" / "fail"
            if isinstance(v, str):
                vl = v.lower().strip()
                if vl in ("pass", "true", "correct", "yes"):
                    return 1.0
                if vl in ("fail", "false", "incorrect", "no"):
                    return 0.0
            continue
        # LiveBench scores are typically already 0..1 — clamp defensively.
        if f > 1.0 and f <= 10.0:
            f = f / 10.0  # MT-Bench-style 1..10 scale fallback
        return max(0.0, min(1.0, f))
    return None
