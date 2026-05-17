# Per-Layer Development Protocol

> **Scope:** Every layer of the smart routing system (Layer 0 through Layer 9).
> **Purpose:** Codify the rules every layer follows so that what we shipped for Layer 0 is the template, not the exception.

This document is short on purpose. Long process docs nobody reads. Short protocol docs people use.

---

## The five-pass protocol

Every layer's retrofit goes through five passes, **in this order**:

### 1. Independent audit

> *"Read the code. Find issues. Don't trust the reviewer feedback was exhaustive."*

- Re-read every connected file.
- Look for: correctness bugs, observability gaps, decoupling issues, configuration smells, scalability traps, test coverage holes.
- Pay particular attention to concurrency, error handling, and the failure modes the existing tests don't cover.
- Each issue gets: **file:line ref**, **severity (🔴/🟡/🟠)**, **why it matters** (concrete failure scenario), **proposed fix**.
- Output: a structured audit report inline in the work or in a sub-section of LAYER_N_REPORT.md.

### 2. Library / literature research

> *"Before writing any heuristic, find out what exists."*

- **Papers (arXiv):** state-of-the-art for the sub-problem
- **GitHub:** maintained libraries that solve part of this
- **HuggingFace:** pre-trained models that run locally in milliseconds
- **Engineering blogs + Reddit / X:** what production systems actually use
- For each library considered: name + link + latency + install size + maintenance status + 1-sentence verdict (use / defer / reject).
- Output: a "Library Evaluation Matrix" in LAYER_N_RESEARCH.md.

### 3. Constraint-respecting design

The hard constraint for *every* layer that touches the routing decision: **no decoder-LLM calls in the hot path.**

Allowed in the hot path:
- Lookup tables, regex, deterministic ML (linear models, tree-based, calibrated heuristics)
- Pre-trained encoder models for inference only (sentence-transformers, Model2Vec, MiniLM, e5 — anything where you load weights once and do ~ms inference)
- Anything that runs in < 50 ms on CPU per query

Not allowed in the hot path:
- API calls to Groq / OpenAI / Anthropic / Gemini
- Decoder model inference (anything where you generate tokens)
- Anything that needs network at routing-decision time

### 4. Measurement / evidence capture

Per-layer benchmark suite that captures:

- **Latency:** p50, p95, p99 (each layer's target documented)
- **Precision / recall** on the layer's golden eval set (hand-labelled, multilingual where relevant)
- **Multilingual coverage:** % hit rate by language (for layers that depend on language)
- **Adversarial test suite:** tricky cases that fool the layer (grows over time)
- **Counterfactual quality:** on a sample, also run the "naive" old path and compare

Outputs:
- `scripts/benchmark_layer_N.py` — reproducible benchmark script
- `artifacts/layer_N/golden_set.json` — labeled eval queries
- `artifacts/layer_N/benchmark_results.json` — produced by the script

### 5. Observability hooks

Every decision the layer makes gets logged with enough metadata to audit later:

- Decision provenance (which rule / model fired)
- Confidence score
- Latency for the decision
- Inputs that triggered the path
- Shadow-eval hook: for 1% of decisions, also run the alternative path in parallel for comparison

This is what proves the layer works in production, not just in tests.

---

## Library Evaluation Protocol

> *"Are you making sure the library is actually useful and is better?"*

Before any external library lands in a layer's hot path, the following must be true:

### Pre-conditions

1. **Library is maintained.** Last commit < 12 months ago, or maintained by a credible team.
2. **License is compatible** with project license (no GPL contamination if project is permissive).
3. **Install footprint** is reasonable (< 200 MB on disk including required model weights).

### The experiment

Set up a head-to-head benchmark with **three** arms:

| Arm | What runs |
|---|---|
| **Heuristic (Tier 1)** | The pure-heuristic baseline currently shipping |
| **Library only** | The library replacement, no heuristic fallback |
| **Hybrid** | Heuristic first, library as fallback when heuristic returns NONE |

Evaluate on **two** datasets:

| Dataset | Purpose |
|---|---|
| **Golden set** | The layer's hand-curated happy-path queries. Library must not regress here. |
| **Out-of-distribution corpus** | Queries that the heuristic was *never designed to catch*. This is where the library has to earn its place. |

Sweep at least 5 thresholds. Report F1, precision, recall, latency p99, false positives, false negatives — per arm × per threshold × per dataset.

### Adopt / reject / hybrid rubric

| Outcome | Decision |
|---|---|
| Hybrid F1 ≥ Heuristic F1 + 5 pp on OOD AND precision ≥ heuristic baseline AND p99 < layer budget | **Adopt as hybrid Tier 2** |
| Library matches heuristic accuracy AND simplifies code (e.g. removes 200 lines of curated patterns) AND latency budget ok | **Adopt as full replacement** (rare) |
| Library only improves on a niche segment with FP regression | **Reject — document the experiment** |
| Library matches heuristic but no improvement | **Reject — added dependency for zero benefit** |

The fourth row matters: *no improvement = reject, regardless of how trendy the library is.* Track this in the research doc so we don't re-test the same library forever.

### Required artifacts when adopting

| Artifact | Path |
|---|---|
| Experiment runner | `experiments/layer_N_<library>_vs_heuristic/experiment.py` |
| OOD corpus | `experiments/layer_N_<library>_vs_heuristic/<dataset>.json` |
| Results | `experiments/layer_N_<library>_vs_heuristic/results.json` |
| Decision rationale | Section in `LAYER_N_RESEARCH.md` with the F1 / precision / threshold numbers |
| Tests | Library-specific tests in the layer's test file, skip-marked if library missing |
| Graceful degradation | Layer must work (perhaps with reduced recall) if library is uninstalled or fails to load |

---

## Where to put what

```
docs/layers/
├── PROTOCOL.md                # this file (one copy for all layers)
├── LAYER_0_RESEARCH.md        # one per layer
├── LAYER_0_REPORT.md
├── LAYER_1_RESEARCH.md
├── LAYER_1_REPORT.md
└── …

artifacts/layer_N/
├── golden_set.json
├── benchmark_results.json
└── (any per-run JSON outputs)

experiments/layer_N_<topic>/
├── experiment.py
├── <dataset>.json
├── results.json
└── (optional) analysis.md

scripts/
└── benchmark_layer_N.py
```

---

## The Layer 0 precedent

Layer 0 is the reference implementation of this protocol. When in doubt about what each step should look like, read:

- [LAYER_0_RESEARCH.md](LAYER_0_RESEARCH.md) — research pass with library evaluation matrix
- [LAYER_0_REPORT.md](LAYER_0_REPORT.md) — engineering report including Phase 0 (broken-state narrative), Phase 1 (heuristic), Phase 2 (library experiment), Phase 3 (hybrid)
- [experiments/layer_0_model2vec_vs_heuristic/experiment.py](../../experiments/layer_0_model2vec_vs_heuristic/experiment.py) — example of the three-arm experiment
- [scripts/benchmark_layer_0.py](../../scripts/benchmark_layer_0.py) — example of the reproducible benchmark

The same shape should hold for Layers 1-9.
