# Layer 3 — Data Sources

> The benchmark corpus that powers the kNN router. Per-question outcomes for ~22 registry models from a mix of public leaderboards, refreshed monthly.

This document lists every external data source the Layer 3 corpus build consumes, with download command, schema, row count after normalisation, license, and refresh cadence. The build script (`scripts/layer3/build_outcomes_corpus.py`) consumes each source as a plug-in module under `scripts/layer3/_sources/`.

## Outputs

| File | Schema | Purpose |
|---|---|---|
| `data/processed/outcomes.parquet` | `(question_global_id, model_id, outcome, source_url, ingested_at)` | The kNN router's per-model quality predictions |
| `data/processed/questions.parquet` | `(question_global_id, question_text, benchmark_source, language, modality, domain, difficulty_tier)` | Loaded into Qdrant payload by `embed_corpus.py` |
| `data/processed/validation_set.parquet` | same as `questions.parquet` | 650 locked queries — never used as kNN neighbors |
| `data/processed/validation_outcomes.parquet` | same as `outcomes.parquet` | Per-(model, validation query) outcomes for the zero-cost validation methodology (P7) |
| `data/validation_set_ids.json` | `{locked_ids: [str]}` | Consumed by `build_outcomes_corpus.py` to exclude validation IDs from the corpus side |

## Sources

### LiveBench

| | |
|---|---|
| HuggingFace IDs | `livebench/livebench`, `livebench/reasoning`, `livebench/coding`, `livebench/math`, `livebench/model_judgment` |
| Site | https://livebench.ai |
| License | Apache-2.0 |
| Refresh cadence | Monthly (LiveBench updates with new problems + new model submissions) |
| Per-question outcomes | **Yes** — `model_judgment` dataset has per-(model, question) judge scores |
| Outcome normalization | LiveBench judge scores are already in [0, 1] for most tasks; pass-through with clamping |

Primary source for per-question outcomes. Coverage is strongest for open-weights models (Llama 3.x, Qwen, DeepSeek, Gemma) since those are evaluated on every LiveBench run; commercial models (GPT-4o, Claude 3.5, Gemini) appear sporadically depending on submission cadence.

### MMLU-Pro

| | |
|---|---|
| HuggingFace ID | `TIGER-Lab/MMLU-Pro` |
| Paper | https://arxiv.org/abs/2406.01574 |
| License | MIT |
| Refresh cadence | Static (12k questions, no rolling refresh) |
| Per-question outcomes | Partial — bundled with HF Open LLM Leaderboard v2 details files, scattered across per-model HF repos |
| Outcome normalization | Binary pass/fail per question → outcome ∈ {0.0, 1.0} |

12k question metadata is reliable and gives us strong complexity-anchor coverage (14 academic domains). Per-(model, question) outcomes need per-model leaderboard detail repos — a future builder will harvest them. For now, MMLU-Pro contributes question metadata to the corpus, and aggregate accuracy scores feed `model_aggregate_scores.json`.

### GPQA-Diamond

| | |
|---|---|
| HuggingFace ID | `Idavidrein/gpqa` (config `gpqa_diamond`) |
| Paper | https://arxiv.org/abs/2311.12022 |
| License | CC-BY-4.0 (gated — requires accepting terms via `huggingface-cli login`) |
| Refresh cadence | Static (198 expert-validated questions) |
| Per-question outcomes | Aggregate scores only (per-question outcomes not publicly distributed) |

PhD-level science questions. Acts as the upper-tier complexity anchor. Gated on HuggingFace; skipped at build time if the gate hasn't been accepted by the running HF token. The system works without it — the questions are well-substituted by the harder slice of MMLU-Pro.

### LiveCodeBench

| | |
|---|---|
| HuggingFace ID | `livecodebench/code_generation_lite` |
| Site | https://livecodebench.github.io |
| License | MIT |
| Refresh cadence | Continuous (new problems posted monthly) |
| Per-question outcomes | Available in live JSON releases at the site, not bundled with the HF dataset |
| Outcome normalization | Binary pass@1 |

Per-problem code-generation outcomes. Questions are pulled cleanly from the HF dataset; outcomes require parsing the official leaderboard JSON releases — a future builder will harvest them.

### SWE-bench Verified

| | |
|---|---|
| HuggingFace ID | `princeton-nlp/SWE-bench_Verified` |
| Site | https://www.swebench.com |
| License | MIT |
| Refresh cadence | Continuous (model submissions accumulate) |
| Per-question outcomes | Per-model patch-resolution status published as GitHub submission JSONs |
| Outcome normalization | Binary resolved/unresolved per issue |

500 GitHub issues, human-verified as solvable. The benchmark for agentic-coding capability. Questions land in the corpus cleanly; the per-(model, issue) resolved status needs the SWE-bench submission JSONs — a future builder.

### Arena-Hard-Auto

| | |
|---|---|
| HuggingFace ID | `lmsys/arena-hard-auto-v0.1` |
| Paper | https://arxiv.org/abs/2406.11939 |
| License | Apache-2.0 |
| Refresh cadence | Static (500 high-quality prompts) |
| Used for | **Validation set only** — locked out of the kNN corpus side per P7 |

Best proxy for real LLM-routing traffic in any public benchmark. 500 prompts curated from Chatbot Arena. All 500 land in `validation_set.parquet`; their `question_global_id`s are written to `data/validation_set_ids.json` and excluded by `build_outcomes_corpus.py` from the kNN corpus.

### MT-Bench

| | |
|---|---|
| HuggingFace ID | `lmsys/mt_bench_human_judgments` |
| Paper | https://arxiv.org/abs/2306.05685 |
| License | Apache-2.0 |
| Refresh cadence | Static (80 multi-turn conversations) |
| Used for | **Validation set only** — locked out of the kNN corpus side per P7 |

80 multi-turn conversational prompts with human judge scores. Adds multi-turn coverage to the validation set.

## Sources NOT YET integrated (intended for future iterations)

| Source | Reason | Tracker |
|---|---|---|
| HF Open LLM Leaderboard v2 details | Per-model details files are scattered across per-model HF repos; needs a dedicated multi-repo fetcher | Future patch |
| LiveCodeBench monthly outcome JSONs | Released on GitHub releases, not the HF dataset | Future patch |
| SWE-bench Verified submission JSONs | One JSON per model submission on GitHub | Future patch |
| BFCL (function calling) | Narrow domain; deprioritised until telemetry shows need | Future patch |
| GAIA (tool use) | Same | Future patch |
| RouterBench (405k × 11 LLMs) | Almost zero overlap with current registry (uses GPT-3.5, Claude-v2, Llama-2-70B, etc.) | Deferred |

## How to add a new source

1. Create `scripts/layer3/_sources/your_source.py` exporting a `build(accumulator, mapper, logger, *, sample_only, max_questions) -> int` function.
2. Add per-source model ID mappings to `src/layer0_model_infra/data/model_id_mapping.json` under a new key.
3. Register the source in `SOURCES` in `scripts/layer3/build_outcomes_corpus.py`.
4. Re-run the corpus build: `python -m scripts.layer3.build_outcomes_corpus`.

Re-runs are idempotent — the accumulator de-duplicates by `(model_id, question_global_id)`. Adding a source only appends new rows.

## Refresh procedure

```bash
# 1. Pull fresh data from each source (or specific sources)
python -m scripts.layer3.build_outcomes_corpus
python -m scripts.layer3.build_outcomes_corpus --sources livebench    # narrower

# 2. If the validation set definition changed, rebuild it FIRST so the
#    locked IDs are current
python -m scripts.layer3.build_validation_set
python -m scripts.layer3.build_outcomes_corpus      # then rebuild corpus with new lock

# 3. Re-embed everything into Qdrant
python -m scripts.layer3.setup_qdrant_collection
python -m scripts.layer3.embed_corpus
```

Monthly cadence is intended; the build is read-mostly and re-runnable any time.

## Provenance and license summary

| Source | License | Commercial-use OK | Citation required |
|---|---|---|---|
| LiveBench | Apache-2.0 | Yes | No |
| MMLU-Pro | MIT | Yes | No |
| GPQA-Diamond | CC-BY-4.0 | Yes (with attribution) | Yes |
| LiveCodeBench | MIT | Yes | No |
| SWE-bench Verified | MIT | Yes | No |
| Arena-Hard | Apache-2.0 | Yes | No |
| MT-Bench | Apache-2.0 | Yes | No |

All sources are usable for our internal commercial routing system. GPQA-Diamond's CC-BY-4.0 requires attribution in any public derivative — we cite it in `model_aggregate_scores.json`'s `_meta.sources` block.

## Reports

After every build, two report files land under `artifacts/layer3/`:

- `corpus_build_report.json` — per-source row counts, elapsed times, total outcomes/questions, per-model coverage
- `validation_build_report.json` — validation set composition by source + modality
- `embed_report.json` — written by `embed_corpus.py`: throughput, sanity-probe results

These are committed (under 100 KB each) so anyone reviewing the system can see exactly what data the kNN router is grounded in.
