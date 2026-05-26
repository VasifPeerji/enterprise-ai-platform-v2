"""
LiveCodeBench builder.

500+ programming-contest problems with per-(model, problem) pass/fail
outcomes. Refreshed continuously; the leaderboard updates monthly with new
problems and submissions.

Source: ``livecodebench/code_generation_lite`` on HuggingFace + the official
JSON releases at https://livecodebench.github.io.

For this batch we ingest the questions + the bundled per-model accuracy where
the HuggingFace dataset exposes it. If the per-model outcome data isn't in a
shape we can parse, the questions still land in the corpus (they're useful
kNN neighbors for coding queries).

License: MIT.
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

SOURCE_KEY = "livecodebench"
SOURCE_URL = "https://huggingface.co/datasets/livecodebench/code_generation_lite"


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
) -> int:
    logger.info("livecodebench_build_starting")
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("livecodebench_skipped: datasets library not installed")
        return 0

    ds = None
    for repo_id in [
        "livecodebench/code_generation_lite",
        "livecodebench/code_generation",
    ]:
        try:
            ds = load_dataset(repo_id, trust_remote_code=False)
            logger.info("livecodebench_loaded repo=%s", repo_id)
            break
        except Exception as exc:
            logger.info("livecodebench_repo_unavailable repo=%s err=%s", repo_id, str(exc)[:120])
            continue

    if ds is None:
        logger.warning("livecodebench_skipped: no reachable variant")
        return 0

    splits = ds.items() if hasattr(ds, "items") else [("train", ds)]
    n_questions = 0
    limit = 100 if sample_only else (max_questions or 1000)
    for _split, split_ds in splits:
        for row in split_ds:
            if n_questions >= limit:
                break
            qid_local = (
                row.get("question_id")
                or row.get("task_id")
                or row.get("problem_id")
                or row.get("id")
            )
            if qid_local is None:
                continue
            qid = make_question_global_id("livecodebench", qid_local)
            qtext = (
                row.get("question_content")
                or row.get("problem_statement")
                or row.get("question")
                or row.get("prompt")
                or ""
            )
            difficulty = (row.get("difficulty") or "").lower()
            tier_map = {"easy": "moderate", "medium": "complex", "hard": "complex"}
            accumulator.add_question(QuestionRow(
                question_global_id=qid,
                question_text=qtext[:2000],
                benchmark_source="livecodebench",
                language="en",
                modality="code",
                domain="tech",
                difficulty_tier=tier_map.get(difficulty, "complex"),
            ))
            n_questions += 1

    logger.info(
        "livecodebench_build_done question_rows=%d outcomes=0 "
        "(per-model pass/fail data is in the live JSON releases, not bundled "
        "with the HF dataset — fetcher for those is a planned future patch)",
        n_questions,
    )
    return 0
