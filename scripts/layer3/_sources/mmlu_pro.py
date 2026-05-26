"""
MMLU-Pro builder.

MMLU-Pro is a 12k-question multi-choice benchmark covering 14 domains
(biology, business, chemistry, computer science, economics, engineering,
health, history, law, math, philosophy, physics, psychology, other).
It's a strong COMPLEXITY anchor — its per-model accuracy scores are the
most-cited reasoning benchmark across recent model releases.

Two roles here:
  1. Question metadata for Qdrant payload (so MMLU-Pro questions appear as
     potential kNN neighbors).
  2. Per-(model, question) outcomes via the HuggingFace Open LLM Leaderboard
     v2 results dataset, where they exist.

The dataset itself (``TIGER-Lab/MMLU-Pro``) is unrestricted. The per-model
outcomes have to be harvested from Open LLM Leaderboard v2 details files —
those are scattered across per-model HF repos. We try the consolidated
``open-llm-leaderboard/results`` repo first (if accessible); if that fails,
we fall through to question-metadata-only ingestion (still useful for kNN
neighbors).

License: MIT (questions) + per-model licenses for outcomes.
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


SOURCE_KEY = "mmlu_pro"
SOURCE_URL = "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro"


# MMLU-Pro category → modality + domain mapping
_CATEGORY_TO_MODALITY = {
    "computer science": "code",
    "engineering": "text",
    "math": "math",
    "physics": "math",
    "chemistry": "text",
    "biology": "text",
    "health": "text",
    "psychology": "text",
    "economics": "text",
    "business": "text",
    "law": "text",
    "history": "text",
    "philosophy": "text",
    "other": "text",
}


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
) -> int:
    """Add MMLU-Pro questions to the corpus + harvest per-model outcomes
    where the HF Open LLM Leaderboard v2 data is reachable.
    """
    logger.info("mmlu_pro_build_starting")
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("mmlu_pro_skipped: datasets library not installed")
        return 0

    # ---- 1. Question metadata ----
    qids = _load_questions(load_dataset, accumulator, logger,
                           sample_only=sample_only,
                           max_questions=max_questions)
    if not qids:
        logger.warning("mmlu_pro_no_questions_loaded")
        return 0

    # ---- 2. Outcomes from Open LLM Leaderboard v2 (best-effort) ----
    n_outcomes = _load_outcomes_from_open_llm_leaderboard(
        load_dataset, accumulator, mapper, logger, qids,
        sample_only=sample_only,
    )
    logger.info("mmlu_pro_build_done question_rows=%d outcomes=%d", len(qids), n_outcomes)
    return n_outcomes


def _load_questions(
    load_dataset, accumulator, logger, *,
    sample_only: bool, max_questions: Optional[int],
) -> set[str]:
    """Load MMLU-Pro questions; add to accumulator. Returns set of qids loaded."""
    try:
        ds = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
    except Exception as exc:
        logger.warning("mmlu_pro_questions_load_failed err=%s", str(exc)[:200])
        return set()

    qids: set[str] = set()
    n_loaded = 0
    limit = 100 if sample_only else (max_questions or len(ds))
    for row in ds:
        if n_loaded >= limit:
            break
        qid_local = row.get("question_id") or row.get("id")
        if qid_local is None:
            continue
        qid = make_question_global_id("mmlu_pro", qid_local)
        category = (row.get("category") or "").lower()
        accumulator.add_question(QuestionRow(
            question_global_id=qid,
            question_text=(row.get("question") or "")[:2000],
            benchmark_source="mmlu_pro",
            language="en",
            modality=_CATEGORY_TO_MODALITY.get(category, "text"),
            domain=category or "general",
            difficulty_tier="complex",
        ))
        qids.add(qid)
        n_loaded += 1

    logger.info("mmlu_pro_questions_loaded n=%d", n_loaded)
    return qids


def _load_outcomes_from_open_llm_leaderboard(
    load_dataset, accumulator, mapper, logger,
    qids_in_corpus: set[str], *, sample_only: bool,
) -> int:
    """Best-effort outcome harvest from open-llm-leaderboard/results.

    The leaderboard data is sharded per-model. We try a small set of repos
    that we know typically expose per-question accuracy on MMLU-Pro. If none
    are reachable, returns 0 — the questions are still in the corpus, they
    just don't have outcomes attached for now (the aggregate-score prior
    fallback covers this case).
    """
    candidate_repos = [
        "open-llm-leaderboard/results",  # consolidated (may or may not exist)
    ]

    n_added = 0
    for repo_id in candidate_repos:
        try:
            ds = load_dataset(repo_id, trust_remote_code=False)
        except Exception as exc:
            logger.info(
                "mmlu_pro_outcomes_repo_unavailable repo=%s err=%s",
                repo_id, str(exc)[:120],
            )
            continue

        # Iterate over splits / rows
        for _split, split_ds in ds.items() if hasattr(ds, "items") else [("default", ds)]:
            for row in split_ds:
                # The leaderboard "results" repo is sparse. Look for any row
                # that looks like an MMLU-Pro per-question accuracy entry.
                benchmark = (row.get("benchmark") or row.get("task") or "").lower()
                if "mmlu_pro" not in benchmark and "mmlu-pro" not in benchmark:
                    continue

                source_model = row.get("model") or row.get("model_id")
                qid_local = row.get("question_id") or row.get("doc_id")
                accuracy = row.get("acc") or row.get("accuracy") or row.get("score")
                if source_model is None or qid_local is None or accuracy is None:
                    continue

                qid = make_question_global_id("mmlu_pro", qid_local)
                if qid not in qids_in_corpus:
                    continue
                registry = mapper.map(SOURCE_KEY, str(source_model))
                if registry is None:
                    continue
                try:
                    score = float(accuracy)
                except (TypeError, ValueError):
                    continue
                if score > 1.0:
                    score = score / 100.0  # percent → fraction
                if accumulator.add_outcome(OutcomeRow(
                    question_global_id=qid,
                    model_id=registry,
                    outcome=score,
                    source_url=f"https://huggingface.co/datasets/{repo_id}",
                )):
                    n_added += 1
                if sample_only and n_added >= 200:
                    return n_added

    if n_added == 0:
        logger.info(
            "mmlu_pro_outcomes_unavailable note=Per-question outcomes for MMLU-Pro "
            "are scattered across per-model details files on HF Open LLM Leaderboard "
            "v2; the consolidated results repo isn't reachable. Questions are in the "
            "corpus; outcome lookup will fall back to the aggregate prior. To harvest "
            "per-question outcomes, run a focused fetcher against individual "
            "open-llm-leaderboard/details_* repos in a future patch."
        )
    return n_added
