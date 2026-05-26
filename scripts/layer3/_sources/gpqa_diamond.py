"""
GPQA-Diamond builder.

198 PhD-level science questions across biology / chemistry / physics. The
hardest published QA benchmark — questions are written by domain PhDs and
human-validated as hard.

Used here for: (a) question metadata in the Qdrant payload as upper-tier
complexity anchors, (b) per-model outcomes harvested from public benchmark
runs where available.

The dataset (``Idavidrein/gpqa``) is gated on HuggingFace — requires
``huggingface-cli login`` with a token that has accepted the gate. If access
isn't granted, we log a warning and skip; the system still works without it.

License: CC-BY-4.0 for questions.
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

SOURCE_KEY = "gpqa_diamond"
SOURCE_URL = "https://huggingface.co/datasets/Idavidrein/gpqa"


def build(
    accumulator: CorpusAccumulator,
    mapper: ModelIdMapper,
    logger,
    *,
    sample_only: bool = False,
    max_questions: Optional[int] = None,
) -> int:
    """Add GPQA-Diamond questions to the corpus (metadata only — outcomes
    aren't publicly distributed per-question for most models; the leaderboard
    publishes aggregate accuracy which we capture in model_aggregate_scores.json).
    """
    logger.info("gpqa_diamond_build_starting")
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("gpqa_diamond_skipped: datasets library not installed")
        return 0

    # The Diamond config is the hardest 198-question subset
    ds = None
    for repo_id, config in [
        ("Idavidrein/gpqa", "gpqa_diamond"),
        ("Idavidrein/gpqa", "diamond"),
        ("Idavidrein/gpqa", None),
    ]:
        try:
            ds = load_dataset(repo_id, config) if config else load_dataset(repo_id)
            logger.info("gpqa_diamond_loaded repo=%s config=%s", repo_id, config)
            break
        except Exception as exc:
            err = str(exc)[:200]
            if "gated" in err.lower() or "401" in err or "403" in err:
                logger.warning(
                    "gpqa_diamond_gated: needs `huggingface-cli login` with token that "
                    "has accepted the dataset gate at %s. Skipping for now.",
                    SOURCE_URL,
                )
                return 0
            logger.info("gpqa_diamond_repo_unavailable err=%s", err)
            continue

    if ds is None:
        logger.warning("gpqa_diamond_skipped: no reachable variant")
        return 0

    splits = ds.items() if hasattr(ds, "items") else [("train", ds)]
    n_questions = 0
    limit = 50 if sample_only else (max_questions or 198)
    for _split, split_ds in splits:
        for row in split_ds:
            if n_questions >= limit:
                break
            qid_local = row.get("question_id") or row.get("id") or row.get("Record ID")
            if qid_local is None:
                # Stable hash from the question text
                qtext = row.get("Question") or row.get("question") or ""
                if not qtext:
                    continue
                qid_local = abs(hash(qtext)) % (10 ** 12)
            qid = make_question_global_id("gpqa_diamond", qid_local)

            qtext = row.get("Question") or row.get("question") or ""
            subdomain = (row.get("Subdomain") or row.get("subdomain") or "").lower()
            modality = "math" if any(k in subdomain for k in ("phys", "math")) else "text"

            accumulator.add_question(QuestionRow(
                question_global_id=qid,
                question_text=qtext[:2000],
                benchmark_source="gpqa_diamond",
                language="en",
                modality=modality,
                domain=subdomain or "science",
                difficulty_tier="expert",
            ))
            n_questions += 1

    logger.info("gpqa_diamond_build_done question_rows=%d outcomes=0", n_questions)
    return 0
