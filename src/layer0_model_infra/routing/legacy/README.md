# Legacy routing pipeline (archived)

This folder is the original **Layer 3-5 routing approach**, retired when the
benchmark-driven kNN router (`src/layer0_model_infra/routing/knn_router.py`)
replaced it as the production router.

It is kept intact and importable so the prior research and engineering effort
remain available for documentation, the slide deck and the thesis. **None of it
is on the live routing path anymore** — `router.py` calls the kNN router directly
and falls back to a minimal safe-default model if Layer 3 is disabled.

## Contents

| Module | Old layer | What it did |
| --- | --- | --- |
| `fast_triage.py` | Layer 3 | LLM-based intent / domain / complexity classification |
| `complexity_classifier.py` | Layer 3 | the ~6.5KB-rubric 70B complexity scorer behind fast_triage — one LLM call per query, the hot-path cost the kNN router removed |
| `uncertainty_estimator.py` | Layer 4 | query-surface (regex) heuristic uncertainty estimate |
| `bandit_router.py` | Layer 5 | Thompson-sampling contextual bandit model selection |
| `query_analyzer.py` | - | an older standalone query-analysis helper (already unused before retirement) |

## Why it was retired

The kNN router selects the cheapest model whose benchmarked / kNN-grounded
quality clears a floor, learns online from real outcomes, and is self-sufficient
(it degrades to its own prior-based fallback on infrastructure failure). The
legacy chain made a 70B LLM call per query just to classify it, could not
discriminate easy from hard queries from per-model scalar priors, and was only
ever reached as a fall-through once the kNN router was activated. See the git
history and `docs/layers/LAYER_3_REPORT.md` for the full story.

## Configuration and tests

- Config: the legacy `Pydantic` config classes (`BanditConfig`,
  `ComplexityThresholds`, `FastTriageConfig`, `DeepJudgeConfig`) remain in
  `src/layer0_model_infra/config/routing_config.py` under the LEGACY section.
- Tests: unit tests for these modules remain under `tests/layer0_model_infra/`
  (`test_fast_triage.py`, `test_complexity_classifier.py`,
  `test_complexity_gold_set.py`, `test_uncertainty_estimator.py`,
  `test_bandit_router.py`).
