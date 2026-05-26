"""
SWE-bench Verified builder.

500 GitHub issues, human-verified to be solvable. Per-model patch resolution
outcomes are published openly via the SWE-bench leaderboard, with submission
JSONs on GitHub.

For this batch we ingest the issue metadata (so SWE-bench issues appear as
kNN neighbors for coding queries). Per-model outcomes need parsing leaderboard
submissions — that's a planned future patch.

License: MIT.
"""

from __future__ import annotations

from typing import Optional

from scripts.layer3._common import (
    CorpusAccumulator,
    ModelIdMapper,
    QuestionRow,
    make_question_global_id,
)

SOURCE_KEY = "swe_bench_verified"
SOURCE_URL = "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified"


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
) -> int:
    logger.info("swe_bench_verified_build_starting")
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("swe_bench_verified_skipped: datasets library not installed")
        return 0

    ds = None
    for repo_id in ["princeton-nlp/SWE-bench_Verified", "princeton-nlp/SWE-bench-Lite"]:
        try:
            ds = load_dataset(repo_id)
            logger.info("swe_bench_loaded repo=%s", repo_id)
            break
        except Exception as exc:
            logger.info("swe_bench_repo_unavailable repo=%s err=%s", repo_id, str(exc)[:120])
            continue

    if ds is None:
        logger.warning("swe_bench_skipped: no reachable variant")
        return 0

    splits = ds.items() if hasattr(ds, "items") else [("test", ds)]
    n_questions = 0
    limit = 50 if sample_only else (max_questions or 500)
    for _split, split_ds in splits:
        for row in split_ds:
            if n_questions >= limit:
                break
            qid_local = row.get("instance_id") or row.get("id")
            if qid_local is None:
                continue
            qid = make_question_global_id("swe_bench_verified", qid_local)
            problem = (row.get("problem_statement") or row.get("issue") or "")
            accumulator.add_question(QuestionRow(
                question_global_id=qid,
                question_text=problem[:2000],
                benchmark_source="swe_bench_verified",
                language="en",
                modality="code",
                domain="tech",
                difficulty_tier="complex",
            ))
            n_questions += 1

    logger.info(
        "swe_bench_verified_build_done question_rows=%d outcomes=0",
        n_questions,
    )
    return 0
