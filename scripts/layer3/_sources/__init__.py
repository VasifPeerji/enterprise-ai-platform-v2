"""Per-source corpus builders.

Each module exports a ``build(accumulator, mapper, logger, *, sample_only=False)``
callable. The main script (``build_outcomes_corpus.py``) imports and runs them
in dependency order.

Sources currently implemented:
  • livebench          — primary per-question outcomes for ~30+ current models
  • mmlu_pro           — 12K questions (metadata for Qdrant payload) + outcomes
                         where present in HF Open LLM Leaderboard v2 dumps
  • gpqa_diamond       — 198 PhD-level questions (metadata only — gated dataset)
  • livecodebench      — 500+ code problems with per-model pass/fail
  • swe_bench_verified — 500 GitHub issues with per-model patch resolution
  • mmlu_classic       — 14k questions for older-model coverage fallback

Each source contributes outcomes and/or question metadata. The accumulator
de-duplicates by ``(model_id, question_global_id)`` and ``question_global_id``
respectively, so re-running a source is idempotent.
"""

from typing import Callable, Iterable

# Re-exported builder registry — imported by build_outcomes_corpus.py
SourceBuildFn = Callable[..., int]
