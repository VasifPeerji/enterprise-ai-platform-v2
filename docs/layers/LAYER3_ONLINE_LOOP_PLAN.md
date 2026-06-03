# Layer 3 — Online Loop & Conversational Grounding (plan)

Status: scoped & approved 2026-06-04. Not yet built. Sequencing locked: **A first, then B**.

## Goal
Make the kNN router give *grounded* model choices for **conversational / chat** traffic,
not just academic benchmarks. Today chat queries fall back ~75% (the corpus is
exam/issue-phrased) or route via priors, because we have **no per-model evidence about
how *our* models handle chat**. This plan creates that evidence (A) and a loop to refine
it from live traffic (B).

## State this builds on (2026-06-04)
- Router dormant (`LAYER3_CANARY_FRACTION=0.0`); legacy serves all traffic.
- Chat **cost** is already solved: off-distribution text falls back to free
  `llama-3.3-70b-versatile-groq`; high-risk stays premium `gemini-1.5-pro` (commit `ce97d92`).
- 1024 WildBench real-user tasks added as **questions-only** (corpus 13,898 → 14,922,
  commit `0886e96`). Fallback only dropped 76.6 → 74.5% — 1024 is too sparse; the lever is
  per-model **outcomes**, not more questions.
- Offline measurement tool: `scripts/layer3/validate_routing.py` over the 650 locked queries.

## The crux — a free quality signal ("how good was this answer?")
`quality_evaluator.py` (Layer 7) already exists and runs on live traffic, but its **free**
stages (deterministic validators + heuristics) measure *plausibility* (coherence / format /
refusal / truncation), **not correctness** — a confident wrong answer scores high. Its
stage-3 LLM judge needs a judge model. So we need a stronger *free* correctness signal.

**Decided approach: decide at build time.** Prototype the candidates on a small sample,
compare (agreement + sanity), then commit to one with evidence:
- **Open reward model (local):** a model trained to score `(prompt, response) → scalar`.
  Local, fast, no rate limits. Must confirm one fits the RTX 4060 (8 GB).
- **Checklist-judge (free model):** grade each output against WildBench's per-task
  `checklist` (concrete yes/no criteria) using a free strong model (e.g. `llama-3.3-70b`).
  Faithful to WildBench's own method (they use GPT-4); rate-limited; judge is itself free.
- (Heuristic-only and self-consistency considered too weak for open-ended chat correctness.)

## Sub-project A — Offline outcome generation (FIRST; needs no activation)
For each active free model × WildBench task: generate an answer (free APIs) → grade it
(chosen signal) → write `(question_global_id, model_id, outcome)` to `outcomes.parquet`.
This grounds the WildBench questions so chat queries get real per-model evidence → grounded
routing. Reuse the `merge_outcomes.py` + coverage re-tag flow.

- **Honesty:** $0 but **rate-limit-bound, not "harvest"** — it *generates*. OpenRouter-free =
  ~200 req/day (fully grounding those models = days); Groq/HF far faster. Stage by provider;
  prioritize the strong free models on a task subset first.
- **Scope:** ~8–10 strong free models × 1024 tasks ≈ 8–10k generations + grades.

## Sub-project B — Live calibration loop (SECOND; wire now, fires on activation)
Wire `calibration_store.update(l3_decision, observed_quality)` + `cooldown.mark(model_id)`
into the orchestrator's post-Layer-7 path (`layer2_orchestrator/execution_loop.py`). EMA
multipliers self-correct from served traffic; the free fallback becomes rate-limit-safe.

- **Integration detail (the real complexity):** the orchestrator runs on the *adapted legacy*
  decision; the raw L3 `RoutingDecision` (with `source` / `predicted_quality` / `feature_cell`
  that `update()` needs) only survives inside `pipeline_metadata`. Cleanest fix: stash the L3
  decision on the returned object so the orchestrator hands it to `update()` after Layer 7.
  Only `KNN_CORPUS` decisions feed the EMA.
- Fires only when `canary > 0` + live traffic. The wiring can be built and unit-tested now.

## First build step (ready to execute) — the grader prototype
1. Pick ~50 WildBench tasks (mixed modalities) that carry checklists.
2. Generate answers from 2 free models (e.g. `llama-3.3-70b-versatile-groq`,
   `qwen-2.5-coder-32b-openrouter-free`) — ~100 generations.
3. Grade with (a) checklist-judge and (b) an open reward model.
4. Compare: do the two agree? Do grades look sane vs. a human glance? Present numbers → pick.

## Risks / open questions
- Reward model fitting 8 GB VRAM — validate before committing to it.
- Free-API rate limits make full A a multi-hour-to-day staged batch.
- Free reward/judge grades are noisier than GPT-4 — the prototype measures how much.
- Two-pipeline hazard: a full `build_outcomes_corpus.py` rebuild would drop the
  harvested+generated outcomes (they live via the incremental merge path) — keep using merge.
