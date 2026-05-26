"""
Build the Layer 3 outcomes corpus.

Run from repo root:

    python -m scripts.layer3.build_outcomes_corpus
    python -m scripts.layer3.build_outcomes_corpus --sample-only      # quick smoke test
    python -m scripts.layer3.build_outcomes_corpus --sources livebench mmlu_pro

End state:
  • data/processed/outcomes.parquet    — per-(model, question) outcomes
  • data/processed/questions.parquet   — per-question metadata (loaded into
                                         Qdrant payload by embed_corpus.py)
  • artifacts/layer3/corpus_build_report.json — provenance + per-source counts

The build is incremental + idempotent:
  • Re-running with the same sources produces the same parquet contents
  • Adding a new source only appends new rows (de-dup by (model_id, qid))
  • Excludes validation_set ids (P7) from outcomes.parquet but keeps them in
    a separate validation_outcomes.parquet (built by build_validation_set.py)

Sources are loaded as plug-ins from ``scripts/layer3/_sources/``. To add a
new source: create ``_sources/your_source.py`` with a ``build(...)`` function
and register it in ``SOURCES`` below.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

from scripts.layer3._common import (
    ARTIFACTS_LAYER3,
    OUTCOMES_PARQUET,
    QUESTIONS_PARQUET,
    CorpusAccumulator,
    ModelIdMapper,
    ensure_dirs,
    get_pipeline_logger,
    load_locked_validation_ids,
)


# Ordered list of sources to build. Each entry maps to a module under
# ``scripts/layer3/_sources/``.
SOURCES = [
    "livebench",            # per-(model, question) outcomes — primary signal
    "mmlu_pro",             # 12k questions + best-effort outcomes
    "gpqa_diamond",         # 198 PhD-level (gated; soft fail)
    "livecodebench",        # 500+ code problems
    "swe_bench_verified",   # 500 GitHub issues
    "arena_hard",           # 500 validation prompts (questions only — locked out)
    "mt_bench",             # 80 validation prompts (questions only — locked out)
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Layer 3 outcomes corpus")
    parser.add_argument(
        "--sample-only", action="store_true",
        help="Load a tiny slice per source — for quick smoke testing.",
    )
    parser.add_argument(
        "--sources", nargs="+", default=None,
        help="Subset of sources to build (default: all). Names match files in _sources/.",
    )
    parser.add_argument(
        "--max-questions-per-source", type=int, default=None,
        help="Cap questions ingested per source. Useful for partial builds.",
    )
    parser.add_argument(
        "--skip-validation-lock", action="store_true",
        help="Don't filter out validation_set ids. Only for testing.",
    )
    args = parser.parse_args()

    logger = get_pipeline_logger("layer3.corpus")
    ensure_dirs()

    sources_to_run = args.sources or SOURCES
    logger.info("corpus_build_starting sources=%s sample_only=%s",
                sources_to_run, args.sample_only)

    accumulator = CorpusAccumulator()
    mapper = ModelIdMapper()

    locked_ids = set() if args.skip_validation_lock else load_locked_validation_ids()
    if locked_ids:
        logger.info("validation_lock_active n_ids=%d", len(locked_ids))

    per_source_stats: list[dict] = []
    t_start = time.perf_counter()
    for source_name in sources_to_run:
        try:
            module = importlib.import_module(f"scripts.layer3._sources.{source_name}")
        except ImportError as exc:
            logger.warning("source_module_missing source=%s err=%s", source_name, exc)
            continue
        if not hasattr(module, "build"):
            logger.warning("source_module_no_build_fn source=%s", source_name)
            continue

        t0 = time.perf_counter()
        n_outcomes_before = len(accumulator.outcomes)
        n_questions_before = len(accumulator.questions)

        kwargs = {
            "sample_only": args.sample_only,
            "max_questions": args.max_questions_per_source,
        }
        try:
            n_outcomes_returned = module.build(accumulator, mapper, logger, **kwargs)
        except Exception as exc:
            logger.exception("source_failed source=%s err=%s", source_name, exc)
            continue

        elapsed = time.perf_counter() - t0
        per_source_stats.append({
            "source": source_name,
            "outcomes_added": len(accumulator.outcomes) - n_outcomes_before,
            "questions_added": len(accumulator.questions) - n_questions_before,
            "elapsed_seconds": round(elapsed, 2),
        })
        logger.info(
            "source_done source=%s outcomes_added=%d questions_added=%d elapsed=%.1fs",
            source_name,
            len(accumulator.outcomes) - n_outcomes_before,
            len(accumulator.questions) - n_questions_before,
            elapsed,
        )

    # Apply validation lock: drop outcomes whose qid is in the locked set;
    # drop questions whose qid is locked too (they live in validation_set.parquet
    # only, not the kNN corpus).
    if locked_ids:
        before_outcomes = len(accumulator.outcomes)
        accumulator.outcomes = [r for r in accumulator.outcomes if r.question_global_id not in locked_ids]
        for qid in list(accumulator.questions.keys()):
            if qid in locked_ids:
                del accumulator.questions[qid]
        logger.info(
            "validation_lock_applied dropped_outcomes=%d kept_outcomes=%d",
            before_outcomes - len(accumulator.outcomes),
            len(accumulator.outcomes),
        )

    # Write Parquet
    summary = accumulator.summary()
    logger.info("writing_parquet summary=%s", summary)
    accumulator.write_outcomes_parquet(OUTCOMES_PARQUET)
    accumulator.write_questions_parquet(QUESTIONS_PARQUET)

    elapsed_total = time.perf_counter() - t_start

    # Per-model coverage (post-build sanity check)
    coverage = {}
    for row in accumulator.outcomes:
        coverage[row.model_id] = coverage.get(row.model_id, 0) + 1
    coverage_sorted = sorted(coverage.items(), key=lambda kv: -kv[1])

    # Report
    report = {
        "schema_version": "1.0",
        "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "elapsed_seconds_total": round(elapsed_total, 2),
        "sources_run": sources_to_run,
        "per_source": per_source_stats,
        "totals": summary,
        "outcomes_per_model": dict(coverage_sorted),
        "outputs": {
            "outcomes_parquet": str(OUTCOMES_PARQUET.relative_to(Path.cwd())) if OUTCOMES_PARQUET.is_relative_to(Path.cwd()) else str(OUTCOMES_PARQUET),
            "questions_parquet": str(QUESTIONS_PARQUET.relative_to(Path.cwd())) if QUESTIONS_PARQUET.is_relative_to(Path.cwd()) else str(QUESTIONS_PARQUET),
        },
    }
    report_path = ARTIFACTS_LAYER3 / "corpus_build_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info("corpus_build_done totals=%s report=%s", summary, report_path)
    mapper.report(logger)

    return 0


if __name__ == "__main__":
    sys.exit(main())
