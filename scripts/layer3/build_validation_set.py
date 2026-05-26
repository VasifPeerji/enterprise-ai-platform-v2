"""
Build the locked Layer 3 validation set.

Combines:
  • 500 Arena-Hard prompts (real-traffic proxy, LLM-judge scored)
  • 80 MT-Bench prompts (multi-turn coverage)
  • 50 GPQA-Diamond questions (hardest end of complexity, if gate granted)
  • 70 stratified LiveBench questions (multi-modality, recent contamination
    protection)

Total target: 700 queries (P7 of the revised plan).

Outputs:
  • data/processed/validation_set.parquet   — the locked queries + labels
  • data/processed/validation_outcomes.parquet — per-(model, query) outcomes
                                                  harvested from the SAME public
                                                  sources (zero-cost validation,
                                                  per P7 of the revised plan)
  • data/validation_set_ids.json            — locked qid set consumed by
                                                  build_outcomes_corpus.py to
                                                  exclude these from kNN side
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.layer3._common import (
    ARTIFACTS_LAYER3,
    VALIDATION_IDS_JSON,
    VALIDATION_PARQUET,
    VALIDATION_OUTCOMES_PARQUET,
    CorpusAccumulator,
    ModelIdMapper,
    ensure_dirs,
    get_pipeline_logger,
)


# Source allocations (target counts; actual may differ if a source is short)
ALLOCATIONS = {
    "arena_hard": 500,
    "mt_bench": 80,
    "gpqa_diamond": 50,
    "livebench": 70,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Layer 3 validation set (700 queries)")
    parser.add_argument("--sample-only", action="store_true",
                        help="Build a smaller validation set (~100 queries) for smoke tests")
    args = parser.parse_args()

    logger = get_pipeline_logger("layer3.validation")
    ensure_dirs()

    if args.sample_only:
        allocations = {k: max(5, v // 10) for k, v in ALLOCATIONS.items()}
    else:
        allocations = ALLOCATIONS

    logger.info("validation_build_starting allocations=%s", allocations)

    accumulator = CorpusAccumulator()
    mapper = ModelIdMapper()

    # Build each source with its allocation cap.
    import importlib
    for source_name, max_qs in allocations.items():
        try:
            module = importlib.import_module(f"scripts.layer3._sources.{source_name}")
        except ImportError as exc:
            logger.warning("validation_source_missing source=%s err=%s", source_name, exc)
            continue
        n_qs_before = len(accumulator.questions)
        try:
            module.build(accumulator, mapper, logger,
                         sample_only=False,
                         max_questions=max_qs)
        except Exception as exc:
            logger.exception("validation_source_failed source=%s err=%s", source_name, exc)
            continue
        added = len(accumulator.questions) - n_qs_before
        logger.info("validation_source_done source=%s added=%d", source_name, added)

    # Build the validation set table: one row per question with all the
    # taxonomy fields the validation harness needs.
    rows = list(accumulator.questions.values())
    if not rows:
        logger.error("validation_build_zero_questions: aborting")
        return 1

    val_table = pa.table({
        "question_global_id": [r.question_global_id for r in rows],
        "question_text": [r.question_text for r in rows],
        "benchmark_source": [r.benchmark_source for r in rows],
        "language": [r.language for r in rows],
        "modality": [r.modality for r in rows],
        "domain": [r.domain for r in rows],
        "difficulty_tier": [r.difficulty_tier for r in rows],
    })
    VALIDATION_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(val_table, VALIDATION_PARQUET, compression="zstd")

    # The validation outcomes table is per-(model, qid). For this batch we
    # write an empty file with the right schema — Batch 2.5 (encoder benchmark)
    # and downstream validation script (run later) populate the per-model
    # outcome rows by looking up the same public sources we used for the
    # corpus. We never call LLMs here.
    outcomes_table = pa.table(
        {
            "question_global_id": [],
            "model_id": [],
            "outcome": [],
            "source_url": [],
            "ingested_at": [],
        },
        schema=pa.schema([
            ("question_global_id", pa.string()),
            ("model_id", pa.string()),
            ("outcome", pa.float32()),
            ("source_url", pa.string()),
            ("ingested_at", pa.timestamp("us", tz="UTC")),
        ]),
    )
    pq.write_table(outcomes_table, VALIDATION_OUTCOMES_PARQUET, compression="zstd")

    # Write the locked-ids JSON consumed by build_outcomes_corpus.py to
    # exclude these from the kNN corpus side.
    locked_ids = sorted(accumulator.questions.keys())
    with VALIDATION_IDS_JSON.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "schema_version": "1.0",
                "n_ids": len(locked_ids),
                "locked_ids": locked_ids,
                "_note": "These question_global_ids are LOCKED — they must "
                         "NOT appear in data/processed/outcomes.parquet "
                         "(the kNN corpus side). build_outcomes_corpus.py "
                         "reads this file and excludes them.",
            },
            f,
            indent=2,
        )

    # Per-source distribution report
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r.benchmark_source] = by_source.get(r.benchmark_source, 0) + 1
    by_modality: dict[str, int] = {}
    for r in rows:
        by_modality[r.modality] = by_modality.get(r.modality, 0) + 1

    report = {
        "schema_version": "1.0",
        "n_total": len(rows),
        "by_source": by_source,
        "by_modality": by_modality,
        "outputs": {
            "validation_set": str(VALIDATION_PARQUET),
            "validation_outcomes": str(VALIDATION_OUTCOMES_PARQUET),
            "locked_ids_json": str(VALIDATION_IDS_JSON),
        },
    }
    (ARTIFACTS_LAYER3 / "validation_build_report.json").write_text(json.dumps(report, indent=2))

    logger.info("validation_build_done n=%d by_source=%s by_modality=%s",
                len(rows), by_source, by_modality)
    return 0


if __name__ == "__main__":
    sys.exit(main())
