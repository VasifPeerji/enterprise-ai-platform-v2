"""
Arena-Hard builder.

500 high-quality human-written prompts curated from Chatbot Arena. The most
faithful proxy for "real LLM-routing traffic" in any public benchmark — the
prompts are from real users doing real comparisons.

Per-(model, prompt) outcomes are stored as win-rate vs a fixed reference model
(Llama-2-70B by default) — published in ``lmsys/arena-hard-auto-v0.1`` and
the per-model judgment dumps.

This builder is also called by ``build_validation_set.py`` to lock these 500
prompts out of the kNN corpus side (P7 of the patch list).

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
)

SOURCE_KEY = "arena_hard"
SOURCE_URL = "https://huggingface.co/datasets/lmsys/arena-hard-auto-v0.1"

BENCHMARK_NAME = "arena_hard"


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
    include_outcomes: bool = False,
) -> int:
    """Add Arena-Hard questions to the corpus.

    ``include_outcomes=False`` is the default — Arena-Hard is used as the
    LOCKED VALIDATION SET, so its questions must be excluded from the kNN
    corpus side (otherwise the router can cheat by retrieving the validation
    query itself as a neighbor).
    """
    logger.info("arena_hard_build_starting include_outcomes=%s", include_outcomes)
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("arena_hard_skipped: datasets library not installed")
        return 0

    ds = None
    for repo_id in [
        "lmsys/arena-hard-auto",
        "lmsys/arena-hard-auto-v0.1",
    ]:
        try:
            ds = load_dataset(repo_id)
            logger.info("arena_hard_loaded repo=%s", repo_id)
            break
        except Exception as exc:
            logger.info("arena_hard_repo_unavailable repo=%s err=%s", repo_id, str(exc)[:120])
            continue
    if ds is None:
        logger.warning("arena_hard_skipped: no reachable variant")
        return 0

    splits = ds.items() if hasattr(ds, "items") else [("train", ds)]
    n_questions = 0
    limit = 100 if sample_only else (max_questions or 500)
    for _split, split_ds in splits:
        for row in split_ds:
            if n_questions >= limit:
                break
            qid_local = (
                row.get("question_id")
                or row.get("uid")
                or row.get("id")
            )
            qtext = ""
            # Arena-Hard-Auto v0.1 stores the prompt in 'turns' (list of dicts)
            # with key 'content'. Other variants use 'prompt' / 'question'.
            for k in ("turns", "prompt", "question", "instruction", "input"):
                v = row.get(k)
                if isinstance(v, str) and v:
                    qtext = v
                    break
                if isinstance(v, list) and v:
                    first = v[0]
                    if isinstance(first, dict):
                        qtext = first.get("content", "") or first.get("text", "")
                    elif isinstance(first, str):
                        qtext = first
                    if qtext:
                        break
            if not qtext:
                continue
            if qid_local is None:
                from scripts.layer3._common import hash_text_id
                qid = hash_text_id("arena_hard", qtext)
            else:
                qid = make_question_global_id("arena_hard", qid_local)

            accumulator.add_question(QuestionRow(
                question_global_id=qid,
                question_text=qtext[:2000],
                benchmark_source="arena_hard",
                language="en",
                modality="text",  # Arena-Hard is overwhelmingly text reasoning
                domain="general",
                difficulty_tier="complex",
            ))
            n_questions += 1

    logger.info("arena_hard_build_done question_rows=%d", n_questions)
    return 0
