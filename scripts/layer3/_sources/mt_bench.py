"""
MT-Bench builder.

80 multi-turn conversational prompts with judge scores (1-10 scale) from
LMSYS Chatbot Arena. Used as a secondary validation slice (multi-turn
behavior).

Normalisation: 1-10 → /9 - 1/9 → [0, 1]; we then anchor 0 = "completely
unacceptable answer" and 1 = "perfect".

License: Apache-2.0.
"""

from __future__ import annotations

from typing import Optional

from scripts.layer3._common import (
    CorpusAccumulator,
    ModelIdMapper,
    OutcomeRow,
    QuestionRow,
    make_question_global_id,
    normalise_outcome,
)

SOURCE_KEY = "mt_bench"
SOURCE_URL = "https://huggingface.co/datasets/lmsys/mt_bench_human_judgments"


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
    include_outcomes: bool = False,
) -> int:
    logger.info("mt_bench_build_starting include_outcomes=%s", include_outcomes)
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("mt_bench_skipped: datasets library not installed")
        return 0

    ds = None
    for repo_id in [
        "lmsys/mt_bench_human_judgments",
        "lmsys/mt-bench",
    ]:
        try:
            ds = load_dataset(repo_id)
            logger.info("mt_bench_loaded repo=%s", repo_id)
            break
        except Exception as exc:
            logger.info("mt_bench_repo_unavailable repo=%s err=%s", repo_id, str(exc)[:120])
            continue
    if ds is None:
        logger.warning("mt_bench_skipped: no reachable variant")
        return 0

    splits = ds.items() if hasattr(ds, "items") else [("train", ds)]
    n_questions = 0
    limit = 30 if sample_only else (max_questions or 80)
    seen = set()
    for _split, split_ds in splits:
        for row in split_ds:
            if n_questions >= limit:
                break
            qid_local = row.get("question_id") or row.get("id")
            if qid_local is None or qid_local in seen:
                continue
            seen.add(qid_local)

            qtext = ""
            for k in ("conversation_a", "prompt", "question"):
                v = row.get(k)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    qtext = v[0].get("content", "")
                elif isinstance(v, str):
                    qtext = v
                if qtext:
                    break
            if not qtext:
                continue

            qid = make_question_global_id("mt_bench", qid_local)
            accumulator.add_question(QuestionRow(
                question_global_id=qid,
                question_text=qtext[:2000],
                benchmark_source="mt_bench",
                language="en",
                modality="text",
                domain="general",
                difficulty_tier="moderate",
            ))
            n_questions += 1

    logger.info("mt_bench_build_done question_rows=%d outcomes=0", n_questions)
    return 0
