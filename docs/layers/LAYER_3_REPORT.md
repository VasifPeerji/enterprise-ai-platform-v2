# Layer 3 — Benchmark-Driven kNN Router: Engineering Report

> **Status:** ✅ Built, tested, live-verified — wired behind a canary flag (default `0.0`, i.e. dormant; legacy path still serves until dialed up)
> **Last verified:** 2026-06-02 (251 Layer 3 tests green, live Qdrant e2e)
> **Companion docs:** [LAYER_3_RESEARCH.md](LAYER_3_RESEARCH.md), [PROBLEM_INVENTORY.md](PROBLEM_INVENTORY.md) (local), [high_risk_classifier_choice.md](../layer3/high_risk_classifier_choice.md), [encoder_choice.md](../layer3/encoder_choice.md)
>
> **Update (corpus expansion):** §5 and §11 describe the *as-built* coverage
> (2.8% — 394 LiveBench questions, the root cause of the high fallback rate). A
> later harvest (`scripts/layer3/harvest_outcomes.py` + `merge_outcomes.py`)
> pulled per-question results from SWE-bench, the Open-LLM-Leaderboard MMLU-Pro
> details, and LiveBench (no paid calls) and lifted coverage to ~93% of the corpus
> for the served open models — so the kNN now engages on academic/reasoning/coding
> queries that used to fall back. The figures below are the pre-harvest baseline.

---

## 1. What Layer 3 is

Layer 3 picks the **cheapest model that can correctly answer a query**, by
predicting each candidate model's quality from a corpus of public benchmark
**outcomes** and selecting the cheapest one that clears a quality floor. It
replaces the legacy Layer 3 (fast-triage) + Layer 4 (uncertainty) + Layer 5
(bandit) with a single benchmark-grounded stage.

**No model training anywhere.** The encoder is off-the-shelf; the only thing
that "learns" is an online EMA calibration multiplier updated post-call from
observed quality. There is **no decoder-LLM on the hot path** — the kNN does the
work the legacy ~6.5 KB LLM rubric used to do on every query.

**Hard contract / success targets** (`Layer3SuccessTargets`):

| Target | Goal | Measured |
|---|---|---|
| p50 latency | ≤ 50 ms | ~60 ms post-warmup (live) |
| p99 latency | ≤ 200 ms | within budget post-warmup |
| Fallback rate | ≤ 5% | **not yet met on diverse queries** — corpus-coverage bound (§11) |
| Over-routing rate | ≤ 2% | to be measured in Batch 4 (validation harness) |
| Correctness lift | ≥ 10pp | to be measured in Batch 4 |
| Decoder-LLM calls on hot path | 0 | **0** ✅ |

---

## 2. Why it was redesigned

The old Layer 3 was the subject of a forensic **103-issue audit** (tracked as
3.A1–3.O5 in PROBLEM_INVENTORY.md). The failure modes were structural, not
tunable:

- **Keyword intent/domain tables** — the MEDICAL list contained `"vision"`, so
  every computer-vision query routed to MEDICAL → premium tier. `"python" in
  query` matched "i love python movies". `startswith("def ")` caught "def of
  recursion".
- **~6.5 KB LLM rubric on every non-bypassed query** (~500 ms hot-path cost, no
  prompt caching, raw query interpolation = injection vector).
- **Magic-number confidence formulas** (`0.76 + score×0.08` for medical, no
  justification) and **`min()` aggregation** that destroyed information.

The redesign removes all of that mechanism wholesale. Most audit items are
therefore closed *by construction* (the code that caused them no longer exists),
not by patching — see PROBLEM_INVENTORY.md for the per-item disposition.

---

## 3. Architecture — Stage A→D

`KnnRouter.route()` (`src/layer0_model_infra/routing/knn_router.py`) runs four
stages; several short-circuit. Every external dependency is injectable so the
selection logic is unit-testable without a live encoder or Qdrant.

```
route(query, layer1_analysis?)
  │
  ├─ Stage A — Verdict cache (verdict_cache.py)
  │    SHA256 exact match  →  Model2Vec ANN (cos ≥ 0.93) over normalised queries
  │    LRU 10k · 7-day TTL · schema-versioned · negation-polarity guard
  │    only ON-POLICY decisions cached · revalidates cached model still active
  │    HIT → return cached decision (sub-ms)                          [CACHE_HIT]
  │
  ├─ Stage B — Feature extraction (feature_extractor.py)
  │    language (lingua 3-tier) · modality (text/code/math/vision/multimodal)
  │    high-risk domain (regex Tier-1 + bge Tier-2, gated to TEXT)
  │    token estimates · difficulty signal
  │    In production reuses Layer 1's ModalityAnalysis via extract_from_layer1()
  │
  ├─ (vision / multimodal modality → Stage D: corpus has zero coverage)
  │
  ├─ Stage C — kNN (knn_router.py + outcome_store.py + aggregate_scores.py)
  │    encode query (MiniLM, FP16/CUDA, CPU fallback) → Qdrant ANN (k=20, cos≥0.55)
  │    < 3 neighbours above threshold → Stage D (off-distribution)
  │    per model: similarity-weighted avg of neighbour outcomes
  │              (length-adjusted sim; needs ≥3 outcomes & coverage≠low)
  │              else → modality-weighted aggregate prior
  │              × online calibration multiplier (confidence-gated)
  │    quality floor (0.65 default / 0.75 high-risk / +0.10 low-coverage penalty)
  │    ε-exploration (0.015) · warmup forcing (0.05) · COST-MIN inside floor set
  │    selection → [KNN_CORPUS | EXPLORATION | WARMUP]
  │
  └─ Stage D — Fallback (fallback_router.py)
       per-modality safe default; walks past inactive defaults to cheapest
       capable active model. Reasons: insufficient_neighbors · no_model_above_floor
       · all_qualifying_rate_limited · unsupported_modality_no_coverage · search_error
       → [FALLBACK]

  Post-call (Layer 7): observed quality → calibration EMA update
       (READ path live in router; WRITE hook is a documented TODO — §11)
```

**Anti-over-routing is structural:** cost-minimisation runs *inside* the
qualifying set, so a model below its floor can never win however cheap.
**Anti-under-routing** is the floor + the +0.10 low-coverage penalty + Layer 7
quality eval + Layer 8 escalation + the elevated 0.75 high-risk floor.

---

## 4. Locked design parameters

All in `config/routing_config.py` (`Layer3Config`); zero hardcoded magic numbers
in the router; env-overridable where useful.

| Group | Values |
|---|---|
| Quality floor | default **0.65**, high-risk **0.75**, low-coverage penalty **+0.10**, ceiling 0.95 |
| kNN | k=20, min_similarity 0.55, **min_neighbors_for_trust 3**, min_outcomes_per_model 3, length-adj sim `0.7 + 0.3·ratio` |
| Filters | `filter_by_modality=False`, `filter_by_language=False` (see §6) |
| Exploration (P2) | rate 0.015, borderline_band 0.05, max_obs 30 |
| Warmup (P4) | max_age 30d, min_obs_to_exit 100, forced_rate 0.05 |
| Calibration | EMA α 0.1, confidence `1−exp(−n/50)`, apply-threshold 0.3, clamp [0.5, 1.5], auto_save 50 |
| Verdict cache | TTL 7d, semantic 0.93, max 10k, negation guard on |
| High-risk | tier2=`bge`, bge_threshold 0.62 |
| Encoder | `paraphrase-multilingual-MiniLM-L12-v2`, 384-dim, cosine, Apache-2.0 |

---

## 5. Data assets (verified)

| Asset | Reality |
|---|---|
| `questions.parquet` | **13,898** unique benchmark questions |
| `outcomes.parquet` | **5,431** rows — only **394 questions (2.8%)** have per-model outcomes, across **16 models** |
| `validation_set.parquet` | **650** locked queries — **0/650 leakage** into the corpus (verified) |
| `model_aggregate_scores.json` | 22 models — modality-weighted benchmark priors |
| Qdrant `layer3_benchmark_corpus` | **13,898** points, 384-dim, cosine, HNSW m16/ef200; built with **MiniLM** (verified by self-similarity = 1.0) |
| Registry (`registry.json`) | **22 models → 16 active** with current keys (groq 5, openrouter 5, google 3, cohere 2, hf 1); 6 inactive (openai 2, anthropic 4) via `required_env_var` gating |
| Corpus distribution | modality text 9,842 / math 3,018 / code 1,038 (no vision/multimodal); 100% English; sources mmlu_pro 12,032 / livebench 1,366 / swe_bench 500 |

The **2.8% outcome coverage** is the single most important number in this report
— it governs how often kNN can engage vs. fall back (§11).

---

## 6. Evidence-driven decisions (deviations from the original plan)

Each justified by live measurement, not intuition:

1. **kNN modality + language filters OFF** — corpus is 100% English and its
   modality is domain-tagged vs. the query's literal tag; hard filters starved
   neighbours with no upside. Rely on the multilingual encoder + 0.55 threshold.
2. **min_neighbors_for_trust 5 → 3** — a cosine-1.0 exact match was being
   discarded for lack of 4 runners-up.
3. **High-risk Tier-2 = bge, gated to TEXT** — 3-arm benchmark: regex alone
   F1 0.32 / recall 0.19; regex+bge **F1 0.97 / recall 1.0 / 19 ms**;
   regex+mDeBERTa F1 0.75 / 156 ms. Gating to TEXT → production
   **P 0.936 / R 1.000 / F1 0.967**. mDeBERTa rejected (slower, worse).
4. **Code-intent heuristic** — "write a function to…" upgrades TEXT→CODE so it
   gets the free code model, not the text default.
5. **Layer 1 vision-bridge fix** — Layer 1's `requires_vision` fires on diagram
   keywords ("plot of Hamlet", "microservices architecture") with no image; the
   bridge no longer promotes those to the vision modality.
6. **Registry reconciliation** — build the legacy `ModelDefinition` straight
   from the `RegistryEntry` (never via aliases, which were removed); `gpt-4o` no
   longer silently misroutes to `claude-sonnet-4`. Pricing converted per-1M→per-1k.

---

## 7. Measured results

| Measurement | Result | Source |
|---|---|---|
| Encoder throughput | 42.9 ms p99 / 549 qps / 674 MB VRAM (RTX 4060) | `benchmark_encoders.py` |
| Live route latency | ~60 ms p50 post-warmup (250 ms first kernel-warm call) | live probe |
| High-risk detection | P 0.936 / R 1.000 / F1 0.967 | `benchmark_high_risk_detection.py` |
| kNN engagement (diverse queries) | ~28% engage kNN; ~72% fall back to safe defaults | live 18-query spread |
| Validation leakage | 0 / 650 | corpus build check |

The kNN engages confidently on **in-distribution** queries (math/science, which
the academic corpus covers) — e.g. "derivative of x²·sin(x)" → kNN, predicted
quality 0.76, neighbours ~0.73–0.78. **Off-distribution** queries (everyday
prose, most code, medical advice) fall back to a capable safe default. **Answer
accuracy is preserved; only cost-optimisation is limited** where the corpus is
thin.

---

## 8. Test coverage

`tests/layer3/` — **251 passed, 0 skipped** (was 243 + 8 Qdrant-skipped before
host connectivity was fixed).

| Area | Coverage |
|---|---|
| Stage A verdict cache | exact/semantic hits, TTL/schema staleness, negation guard, on-policy-only caching |
| Stage B features | language cascade, modality, code-intent, high-risk Tier-1+Tier-2, Layer-1 bridge |
| Stage C kNN | prior vs kNN selection, calibration multiplier, floor + low-coverage penalty, ε-exploration, warmup, S3 context-window, M4 cooldown, M6 revalidation, S2 graceful degradation |
| Stage D fallback | every reason, inactive-default walk, vision/multimodal routing |
| Calibration store | EMA update, confidence gating, KNN_CORPUS-only, auto-save, freeze |
| Integration | adapter (per-1M→per-1k, reconciliation), canary split, router fallthrough |
| Live Qdrant e2e | encoder→Qdrant→outcome lookup, coherent neighbours, multilingual, end-to-end route |

---

## 9. Integration & rollout

Wired in `router.py` after Layer 2, replacing legacy L3–L5, behind flags in
`shared/config.py`:

- `LAYER3_ENABLED` (True) — builds the router at init.
- `LAYER3_CANARY_FRACTION` (**0.0** default) — share of traffic through L3,
  stable per `request_id`. **At 0.0 the new router is wired but dormant; the
  legacy pipeline serves everything** (and the legacy complexity classifier
  still issues a `groq-llama-3.3-70b` call per non-cached query — the exact
  hot-path the redesign removes, still active until the canary is raised).
- `LAYER3_SHADOW_MODE` (False) — run both, log `layer3_shadow_compare`, serve legacy.
- Layer 3 models register into the gateway registry **lazily** on first real L3
  route, so `canary=0.0` leaves the legacy candidate pool + legacy tests untouched.
- `_route_via_layer3` returns `None` on any failure → safe fallthrough to legacy.

Verified live at `canary=1.0`: `router.route()` serves Layer 3 decisions with
the full audit trail in `pipeline_metadata` and correct per-1k cost.

---

## 10. Reproducibility

```bash
# Tests (Qdrant up for the 8 live e2e tests)
pytest tests/layer3/ --no-cov -q

# Build / inspect the corpus
python scripts/layer3/build_outcomes_corpus.py
python scripts/layer3/embed_corpus.py     # encoder now sourced from routing_config
python scripts/layer3/setup_qdrant_collection.py

# Benchmarks behind the design decisions
python scripts/layer3/benchmark_encoders.py
python scripts/layer3/benchmark_high_risk_detection.py

# Dashboard (manual + corpus runner + L0→L3 pipeline)
streamlit run scripts/dashboard.py
```

Qdrant note: reach it at `127.0.0.1:6333` (not `localhost` — IPv6 on Windows +
Docker Desktop isn't forwarded by the port-proxy).

---

## 11. Known limitations

1. **Fallback-heavy on diverse traffic** — with only **2.8% outcome coverage**
   over an academic corpus, kNN engages ~28% on an everyday spread; the rest
   fall back. This is a *cost-optimisation* limit, not a correctness one
   (fallbacks go to capable defaults). **Fix = corpus expansion** (more outcome
   data + conversational sources) — the agreed next strategic topic.
2. **Canary at 0.0** — the router is not serving production traffic yet; the
   legacy 70B-per-query path is still live by default. Raising the canary (after
   Batch 4) is what actually retires that hot-path cost.
3. **Calibration WRITE hook is a TODO** — the READ path (multiplier applied in
   Stage C) is live; the post-Layer-7 `calibration.update()` feed and the
   gateway `cooldown.mark()` on 429 are wired as stores but not yet fed (Batch 5).
4. **Thresholds not yet rigorously calibrated** — `min_similarity`,
   `min_neighbors`, and the floor are pre-committed starting values; Batch 4's
   validation harness over the 650 locked queries tunes them and measures the
   real fallback / over-routing / correctness-lift rates.
5. **ONNX-int8 CPU path** — unimplemented; CPU fallback is sentence-transformers
   FP32.

---

## 12. Sign-off

| Criterion | Status |
|---|---|
| Old-L3 mechanism (keyword tables, LLM rubric, magic confidence) removed | ✅ |
| Stage A→D implemented, all safeguards load-bearing | ✅ |
| No decoder-LLM on the hot path | ✅ |
| No ML training (calibration = online EMA) | ✅ |
| Encoder choice benchmarked + documented | ✅ |
| High-risk Tier-2 choice benchmarked (bge) | ✅ |
| Data corpus built; 0/650 validation leakage | ✅ |
| 251 Layer 3 tests green, 0 skipped | ✅ |
| Live Qdrant e2e + integrated `router.route()` verified | ✅ |
| Dashboard integration (manual + corpus + pipeline) | ✅ |
| Rigorous threshold calibration (Batch 4) | ⏳ |
| Calibration write-path + cooldown feed (Batch 5) | ⏳ |
| Canary raised in production | ⏳ |
| Corpus expansion (lift kNN engagement) | 📝 deferred — agreed next topic |

✅ Core build complete and verified. Remaining items are measurement (Batch 4),
observability wiring (Batch 5), and the strategic corpus-coverage lever.
