# Layer 3 — Aggregate Scores (the prior_quality fallback)

> When a registry model has fewer than the minimum number of per-question kNN neighbor outcomes, the kNN router falls back to a modality-weighted aggregate of that model's public benchmark scores. This document explains the math, the sources, and the maintenance.

## Why aggregate scores exist

The kNN router predicts per-model quality for the candidate models. For each candidate, it asks: "given the 20 nearest benchmark questions to this user query, what was this model's average outcome?"

That works when the model has dense per-question coverage (LiveBench-evaluated open-weights models). It fails when:

- The model is `coverage_quality=low` (Claude Opus 4.5, GPT-5, etc — frontier models published with aggregate scores but no per-question outputs).
- The kNN found neighbors the model wasn't evaluated on (some are; some aren't).

In both cases, we fall back to `prior_quality(model_id, modality)` — a modality-weighted average of the model's benchmark scores. The math is in [`src/layer0_model_infra/routing/aggregate_scores.py`](../../src/layer0_model_infra/routing/aggregate_scores.py).

## The math

```
prior_quality(model, modality) = Σ (score[bench] × weight[bench, modality])
                                 ─────────────────────────────────────────
                                       Σ weight[bench, modality]
                                       (for benchmarks present)
```

`score[bench]` is normalised to [0, 1]. `weight[bench, modality]` comes from `RELEVANCE_WEIGHTS` in `aggregate_scores.py`. The denominator excludes benchmarks the model doesn't have scored — missing benchmarks aren't penalised, they're skipped.

## Modality → benchmark weights

(Documented constant — change here AND in `RELEVANCE_WEIGHTS`. Reviewed and adjusted after corpus expansion.)

| Modality | Benchmark | Weight | Rationale |
|---|---|---|---|
| **code** | HumanEval | 0.20 | Most-cited code generation benchmark |
| | HumanEval+ | 0.15 | Edge cases, mutation testing |
| | MBPP | 0.15 | Basic Python problems |
| | LiveCodeBench | 0.20 | Recent, contamination-protected |
| | SWE-bench Verified | 0.10 | Agentic / multi-file editing |
| | LiveBench coding | 0.15 | Cross-task, monthly refresh |
| | Arena Elo (norm) | 0.05 | Catch-all signal |
| **math** | MATH-Hard | 0.30 | Hardest open math benchmark |
| | GSM8K | 0.15 | Word problems |
| | GPQA-Diamond | 0.20 | PhD-level science (overlaps math) |
| | BBH | 0.15 | Multi-step reasoning |
| | LiveBench reasoning | 0.15 | Cross-task, monthly refresh |
| | Arena Elo (norm) | 0.05 | Catch-all signal |
| **vision** | MMMU | 0.50 | Multimodal reasoning |
| | MathVista | 0.25 | Visual math |
| | Arena Elo (norm) | 0.25 | Catch-all signal |
| **multimodal** | MMMU | 0.35 | Multimodal reasoning |
| | MathVista | 0.15 | Visual math |
| | LiveBench reasoning | 0.20 | Text reasoning component |
| | MMLU-Pro | 0.15 | Broad knowledge component |
| | Arena Elo (norm) | 0.15 | Catch-all signal |
| **text** | MMLU-Pro | 0.25 | Multi-domain reasoning |
| | IFEval | 0.20 | Instruction following |
| | LiveBench reasoning | 0.15 | Cross-task, monthly refresh |
| | BBH | 0.15 | Multi-step reasoning |
| | GPQA-Diamond | 0.10 | Hard slice |
| | Arena Elo (norm) | 0.15 | Catch-all signal |

Each modality's weights sum to **1.0**, so when every benchmark is present the prior is a proper weighted average. The `test_relevance_weights_sum_to_one_per_modality` unit test enforces this.

## Source benchmarks

Listed in `model_aggregate_scores.json` under `_meta.sources`:

| Benchmark | Citation | Score scale | Normalisation |
|---|---|---|---|
| HumanEval | https://github.com/openai/human-eval | pass@1 | already [0,1] |
| HumanEval+ | https://github.com/evalplus/evalplus | pass@1 | already [0,1] |
| MBPP | https://huggingface.co/datasets/mbpp | pass@1 | already [0,1] |
| LiveCodeBench | https://livecodebench.github.io | pass@1 (4-cutoff avg) | already [0,1] |
| SWE-bench Verified | https://www.swebench.com | resolved rate | already [0,1] |
| MMLU | https://huggingface.co/datasets/cais/mmlu | 5-shot accuracy | already [0,1] |
| MMLU-Pro | https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro | accuracy | already [0,1] |
| GPQA-Diamond | https://huggingface.co/datasets/Idavidrein/gpqa | pass rate | already [0,1] |
| MATH-Hard | https://github.com/openai/prm800k | accuracy (hard split) | already [0,1] |
| GSM8K | https://huggingface.co/datasets/gsm8k | accuracy | already [0,1] |
| BBH | https://github.com/suzgunmirac/BIG-Bench-Hard | avg accuracy | already [0,1] |
| IFEval | https://huggingface.co/datasets/google/IFEval | instruction follow | already [0,1] |
| LiveBench coding | https://livebench.ai | subset average | already [0,1] |
| LiveBench reasoning | https://livebench.ai | subset average | already [0,1] |
| MMMU | https://mmmu-benchmark.github.io | accuracy | already [0,1] |
| MathVista | https://mathvista.github.io | accuracy | already [0,1] |
| Arena Elo (normalised) | https://lmarena.ai | `(elo − 1000) / 500`, clamped to [0,1] | computed |

## Worked example

Query: "Write a Python function to detect SQL injection in user input"  
Stage B detects modality=**code**.  
Stage C identifies Claude Opus 4.5 as a candidate (coverage_quality=`low`, so kNN fallback applies).

Claude Opus 4.5 scores from `model_aggregate_scores.json`:
- humaneval 0.95, humaneval_plus N/A, mbpp 0.93, livecodebench 0.82
- swe_bench_verified 0.74, livebench_coding 0.80, arena_elo_normalised 0.95

Computation:
```
total_score = 0.95×0.20 + 0.93×0.15 + 0.82×0.20 + 0.74×0.10 + 0.80×0.15 + 0.95×0.05
            = 0.190    + 0.140    + 0.164    + 0.074    + 0.120    + 0.048
            = 0.736

total_weight = 0.20 + 0.15 + 0.20 + 0.10 + 0.15 + 0.05 = 0.85
# (humaneval_plus weight 0.15 excluded — model has no score for it)

prior_quality = 0.736 / 0.85 = 0.866
```

Claude Opus 4.5 prior for this CODE query: **0.866**.

With the `+0.10` low-coverage floor penalty (effective floor = 0.65 + 0.10 = 0.75), Opus's prior (0.866) clears it — Opus qualifies. Cost minimisation then picks the cheapest qualifying model: if Qwen 2.5 Coder (free) has a comparable prior, Qwen wins. If only Opus qualifies, Opus is selected.

## Refresh cadence

The aggregate-scores file is built/refreshed by `scripts/layer3/build_aggregate_scores.py` (planned for the next batch), which pulls from:

- BenchLM (https://benchlm.ai)
- Artificial Analysis (https://artificialanalysis.ai)
- LMArena (https://lmarena.ai)
- Per-provider release notes (Anthropic, OpenAI, Google)

The current bundled file was hand-curated from the same sources as of 2026-05-21. It will be regenerated monthly via the build script once that lands.

Sanity-test the data after every refresh via `pytest tests/layer3/test_aggregate_scores.py`. Key sanities:
- Sum-of-weights = 1.0 per modality
- Frontier > cheap (Opus > Haiku on code)
- Dedicated coder > general (Qwen Coder > Llama 8B on code)

## Failure handling

| Case | Behaviour |
|---|---|
| Model not in `model_aggregate_scores.json` | Returns `DEFAULT_FALLBACK_VALUE = 0.50` |
| Modality unknown to `RELEVANCE_WEIGHTS` | Falls through to TEXT weights |
| Model has zero matching benchmarks | Falls through to `arena_elo_normalised` only; if that's missing too, returns 0.50 |

All three are logged at DEBUG level. None raise.
