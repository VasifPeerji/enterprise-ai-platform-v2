# Layer 3 — Fast Triage: Research Notes

> **Layer:** Layer 3 (intent + domain + complexity classification — the foundation of model selection)
> **Constraint:** zero decoder-LLM calls on every query; multi-lingual coverage mandatory; downstream layers 4–8 are fallbacks for Layer 3 — so Layer 3 must be ~95%+ accurate
> **Last updated:** 2026-05-21

Companion: [LAYER_3_REPORT.md](LAYER_3_REPORT.md), [PROTOCOL.md](PROTOCOL.md), [PROBLEM_INVENTORY.md](PROBLEM_INVENTORY.md).

---

## 1. Problem framing

Layer 3 sits between the semantic-memory cache (Layer 2) and the uncertainty estimator (Layer 4). For every non-bypass, non-cached query it must produce three classifications: **intent** (8 classes), **domain** (8 classes), **complexity_band** (5 ordinal classes — trivial → expert). Layer 4 uses the uncertainty signal; Layer 5 (bandit) uses the (intent, domain, complexity) tuple as its routing context.

The previous design uses substring keyword tables for intent + domain and an 8 KB LLM rubric prompt for complexity. The project owner's exhaustive audit catalogued **103 issues across 15 categories** ([PROBLEM_INVENTORY.md](PROBLEM_INVENTORY.md) §"Layer 3"). The headline problems:

- Substring keyword matching produces catastrophic false positives ("vision" → MEDICAL → premium tier; "Hi, can you build me a complete e-commerce site?" → CASUAL → cheap model)
- An LLM call on every non-bypass query (~500 ms hot path, no own-decision caching, fragile JSON parser, hardcoded fallback chain with no backoff)
- No calibrated probabilities or "I don't know" output — `min(intent_conf, domain_conf, complexity_conf)` aggregator destroys information; magic-number confidence formulas everywhere
- Hand-picked rubric weights, band thresholds (0.12 / 0.20 / 0.55 / 0.85), confidence multipliers — none derived
- No tracking of LLM-vs-rubric disagreement, heuristic-fallback rate, or any post-deployment health signal

We are redesigning Layer 3 from first principles. The current implementation is being thrown out.

---

## 2. The convergent design across 6 parallel research streams

Six research streams ran in parallel covering: SOTA papers (R1), production systems (R2), intent/domain classifiers (R3), encoder model selection (R4), complexity + calibration (R5), and LLM reliability + structured output (R6). Their independent conclusions converged on the **same three-stage cascade**:

```
┌─ Stage A — Sub-ms heuristic + verdict cache ────────────────────────┐
│   • Hash + Model2Vec-ANN verdict cache (provider-agnostic, free)    │
│   • Language detection inherited from Layer 1                       │
│   • Compiled regex pack for high-confidence prefixes                │
│   Latency target:  p50 ~1 ms · p99 ~3 ms                           │
│   Expected hit-rate: 35-55% of production traffic                   │
├─────────────────────────────────────────────────────────────────────┤
│  Stage B — Encoder + 3 calibrated MLP heads (HOT PATH)              │
│   • English path:  BAAI/bge-small-en-v1.5  (ONNX int8, ~6-10 ms)   │
│   • Non-English:   minishlab/potion-multilingual-128M (sub-ms, 101 │
│                    langs — already-installed Model2Vec family)      │
│   • 3 heads on shared 384-dim embedding:                            │
│       intent_head:     MLP(384→128→9 = 8 + UNKNOWN)                │
│       domain_head:     MLP(384→128→9 = 8 + UNKNOWN)                │
│       complexity_head: CORAL ordinal MLP(384→128→5)                │
│   • Per-head temperature scaling (Guo 2017)                         │
│   • Conformal prediction (MAPIE) abstention thresholds              │
│   • Asymmetric ordinal loss: under-routing penalty = 10× over-     │
│     routing                                                         │
│   Latency target:  p50 ~8 ms (EN) / ~3 ms (non-EN) · p99 ~15 ms    │
│   Expected coverage: ~85-90% of remaining traffic                   │
├─────────────────────────────────────────────────────────────────────┤
│  Stage C — Structured LLM arbitrator (RARE FALLBACK)                │
│   • Fires when ANY of:                                              │
│       (a) Stage B max-prob < calibrated τ for ANY head              │
│       (b) Conformal prediction set size > 1 for ANY head            │
│       (c) Domain ∈ {medical, legal, finance} regardless of conf    │
│   • Instructor + Pydantic schema (zero JSON-repair surface)         │
│   • Microsoft Spotlighting (datamarking + XML) for injection guard  │
│   • pybreaker per-provider circuit breaker, tenacity retries        │
│   • LiteLLM router for cross-provider failover                      │
│   • Provider-opportunistic prompt caching (Anthropic cache_control, │
│     OpenAI automatic, Groq automatic for GPT-OSS/K2)                │
│   Latency target:  p50 ~500 ms · p99 ~1200 ms                      │
│   Expected fire-rate: ~10-15% of traffic                           │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
       TriageResult (intent, domain, complexity_band, calibrated
       per-head probabilities, abstention flags, provenance metadata)
```

**Why this shape:**

1. **Almost every production system independently arrived here.** R2 surveyed Aurelio Labs Semantic Router, vLLM Semantic Router (Red Hat, Apache-2.0), RouteLLM (LMSYS/Berkeley), NotDiamond, Portkey, Helicone, Cloudflare AI Gateway, LangChain, LlamaIndex. The unanimous pattern: *"keyword pre-filter → embedding kNN/classifier → LLM-judge fallback for low-confidence"*. No system that has run in production long enough to have a postmortem uses anything else.

2. **It eliminates substring matching entirely.** Stage B operates on learned embedding distance via three classifier heads, not keyword tables. The "vision → MEDICAL" class of bug becomes structurally impossible.

3. **The LLM call moves from hot path to ~10-15% of traffic.** The current implementation makes an LLM call on every non-bypass query (~500 ms). The new design uses the LLM only when the encoder cannot produce confidence above the conformal threshold — measured to be ~10-15% of traffic on similar workloads (Hybrid LLM, arXiv 2404.14618).

4. **It has a principled "I don't know."** Stage C's conformal-prediction-set output gives `Intent.UNKNOWN` / `Domain.UNKNOWN` / `ComplexityBand.UNCERTAIN` with a guaranteed coverage rate. The downstream consumer (Layer 4) gets honest uncertainty, not a magic confidence number.

---

## 3. Library Evaluation Matrix

### 3.1 Encoder backbones (Stage B)

| Model | Params | Dim | MTEB-Class | CPU lat (~ms, int8) | Multiling | License | Verdict |
|---|---|---|---|---|---|---|---|
| **BAAI/bge-small-en-v1.5** | 33.4 M | 384 | **74.14** | 6-10 | EN | MIT | **ADOPT** — primary EN encoder |
| **minishlab/potion-multilingual-128M** | 128 M | 256 | 52.36 (MMTEB) | <1 (static) | **101** | MIT | **ADOPT** — non-EN path (already in env via Model2Vec) |
| thenlper/gte-small | 33.4 M | 384 | 72.31 | 6-12 | EN | MIT | Backup option (slightly lower than bge-small) |
| paraphrase-multilingual-MiniLM-L12-v2 | 118 M | 384 | unpublished | 15-20 | 50+ | Apache-2.0 | Defer — slower than bge-small, MTEB-Class not published |
| bge-base-en-v1.5 / gte-base / nomic / mxbai | 100+ M | 768 | 75-76 | 35-60 | EN | mixed | **Reject** — over latency budget |
| jina-embeddings-v3 | 570 M | 1024 | 82.58 | 80-200 | 89 | **CC-BY-NC** | **Reject** — license blocker + latency |
| bge-m3 | 568 M | 1024 | n/a | 80-150 | 100+ | MIT | **Reject** — too slow |
| ModernBERT-base | 149 M | 768 | n/a (decoder-encoder hybrid) | 9-14 (GPU) | EN | Apache-2.0 | Defer — used by vLLM Semantic Router but CPU latency unfavourable |

**Decision: dual-encoder dispatched by Layer 1's detected language.** EN → bge-small (highest MTEB-Class at sub-15ms); non-EN → potion-multilingual (already installed, sub-ms, 101 langs). Total disk footprint < 200 MB combined int8.

### 3.2 Stage C structured-output library

| Library | License | Status | Verdict |
|---|---|---|---|
| **[567-labs/instructor](https://github.com/567-labs/instructor)** | MIT | 11k stars, 3M monthly DLs, last release Jan 2026 | **ADOPT** — Pydantic-validated outputs, provider-agnostic, auto-retry on validation failure, uses each provider's strongest native mode (OpenAI strict-schema, Anthropic tools, Gemini responseSchema) |
| Outlines v1.0 | Apache-2.0 | Active | Defer — best for local/vLLM constrained decoding; overkill for hosted-API arbitrator |
| Guidance (Microsoft) | MIT | Active | Defer — strong for local models, weaker hosted-API ergonomics |
| LMQL | Apache-2.0 | Stalled (minimal 2025-26 activity) | **Reject** — research-grade |
| Marvin v3 | Apache-2.0 | Active | **Reject** — agentic toolkit, scope mismatch |

### 3.3 Stage C reliability libraries

| Component | Pick | License | Why |
|---|---|---|---|
| Retry / backoff | **[jd/tenacity](https://github.com/jd/tenacity)** | BSD | Industry default; `wait_random_exponential`; async-safe |
| Circuit breaker | **[danielfm/pybreaker](https://github.com/danielfm/pybreaker)** | BSD | Object-state breakers (per provider); Redis-shareable; exclude-exception list |
| Provider failover | **LiteLLM Router** (already installed) | MIT | `allowed_fails`, `cooldown_time`, `fallbacks`, `retry_policy` — wraps tenacity + pybreaker as cross-provider failover layer |
| Hedged requests | Custom `asyncio.wait(FIRST_COMPLETED)` (~30 LOC) | — | No mature Python lib; tail-latency reducer per "The Tail at Scale" |
| Injection defense | Inline Microsoft Spotlighting (~30 LOC) | — | XML encapsulation + datamarking; [arXiv 2403.14720](https://arxiv.org/pdf/2403.14720) |
| (rejected) Rebuff | Apache-2.0 | **archived May 2025** | Don't use |
| (deferred) LLM Guard | Apache-2.0 | ~200 MB transformer deps | Overkill for one arbitrator call |

### 3.4 Calibration + abstention libraries

| Component | Pick | License | Why |
|---|---|---|---|
| Temperature scaling | Pure PyTorch (~15 LOC) | — | One-parameter scalar `softmax(logits / T)`, fit T on val by NLL — Guo et al ICML 2017 |
| Isotonic fallback | `sklearn.isotonic.IsotonicRegression` | BSD | 3-line fallback when ECE > 0.05 |
| Conformal prediction | **[MAPIE](https://github.com/scikit-learn-contrib/MAPIE)** | BSD-3 | scikit-learn-contrib; Inductive Conformal Prediction; distribution-free coverage guarantee |
| Ordinal regression | **CORAL** (`coral-pytorch`) | MIT | For complexity head — bands are ordered, not categorical; penalises distance-2 errors more than distance-1 |
| Calibration metric | `torchmetrics.CalibrationError` | Apache-2.0 | ECE on 15-bin equal-width holdout |

### 3.5 Caching infrastructure

| Tier | Mechanism | Storage | Latency |
|---|---|---|---|
| Tier 0 (exact) | `SHA256(normalize(query) ∥ schema_version ∥ rubric_hash)` → SQLite key lookup | `artifacts/triage_cache.db` (WAL mode, same pattern as Layer 2) | ~0.1 ms |
| Tier 0b (semantic) | Model2Vec 256-d embedding → cosine ≥ 0.93 over in-memory NumPy matrix | Same DB, embedding stored as BLOB | ~0.5-1 ms |
| Tier 0c (provider) | Opportunistic cache_control markers on Stage C prompts | Provider-side | 0 ms |

Invalidation: cache key includes `schema_version` + `rubric_hash`, so updating the prompt template or the taxonomy auto-invalidates affected entries on the next write.

### 3.6 Training datasets

| Dataset | Use | License | Size |
|---|---|---|---|
| **[MASSIVE](https://arxiv.org/abs/2204.08582)** (Amazon) | Primary intent + domain training, multilingual | CC-BY-4.0 | 51 languages × 60 intents × 18 domains × ~16k utterances/lang |
| **[CLINC150](https://github.com/clinc/oos-eval)** | Fine-grained intent + 1.2k explicit OOS examples for UNKNOWN class | CC-BY-3.0 | 150 intents + 1.2k OOS |
| **[Banking77](https://huggingface.co/datasets/PolyAI/banking77)** | Banking-domain fine-grained eval + finance training | CC-BY-4.0 | 77 intents, ~13k utterances |
| **[HWU64](https://github.com/xliuhw/NLU-Evaluation-Data)** | General-assistant domain coverage | CC-BY-4.0 | 64 intents, 21 domains |
| **[RouterBench](https://arxiv.org/abs/2403.12031)** | Complexity head training + eval anchor | MIT | 405k samples × 11 LLMs × 8 datasets |
| **[MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro) + [GPQA-Diamond](https://huggingface.co/datasets/Idavidrein/gpqa)** | Complexity calibration anchors (PhD-expert difficulty labels) | MIT / CC-BY-4.0 | 12k + 198 questions |
| Synthetic (Claude/GPT-4o generated) | Taxonomy alignment + cross-domain bridge cases | — | ~5-10k labelled by judge LLM, filtered via disambiguation pass per Sahu et al 2022 |
| Wikipedia / CC-news random snippets | Out-of-distribution training for UNKNOWN class | CC-BY-SA | ~5k |

---

## 4. Things to explicitly NOT do

(direct quotes / paraphrases from the research streams)

- **Don't run a decoder LLM on every query.** R1: *"RouteLLM's Causal-LLM variant and Routoo's performance-predictor LLM both demonstrate that LLM-based routers add 100s of ms and fragility while only marginally beating BERT/MF routers on Arena data."*
- **Don't build a cascade-of-LLMs as the primary path.** R1: FrugalGPT-style cascading is incompatible with a 15 ms p50 budget — keep cascading for Layer 4/5 fallback only.
- **Don't use embedding-similarity-only routing without a learned head.** R2: Production teams report 50–200 ms latency and brittle behavior on multilingual/code queries. R5: cosine scores aren't probabilities — they need calibration.
- **Don't fuse intent + domain + complexity into one joint label.** R2: *"Joint label spaces explode and become impossible to threshold."* Three independent heads on shared embedding is the correct decomposition.
- **Don't trust embedding similarity for negation.** R2: arXiv 2403.04314 — *"intent embedders embed negations closer to positive intents than implicatures."* Need a separate negation guard (we already have one in Layer 2; reuse).
- **Don't skip the calibration step.** R5: Replace every magic `0.6 + score×0.12` with `softmax(logits / T_head)`. Hand-picked formulas are a guaranteed source of drift and disagreement.
- **Don't depend on Anthropic prompt caching as the primary cost-cutting mechanism.** R6: Anthropic write cost is +25% — only pays off after ~3 cache hits. Our own verdict cache (free, provider-agnostic) does the heavy lifting.
- **Don't reinvent retry / circuit-breaker logic.** R6: tenacity + pybreaker + LiteLLM router cover the failure surface in ~85 LOC combined.
- **Don't use Rebuff or any other unmaintained injection-defense library.** R6: Rebuff was archived May 2025. Use Microsoft Spotlighting (inline, ~30 LOC, no deps).

---

## 5. Things to definitely DO

(consolidated from all six streams)

- **Decouple intent / domain / complexity into three independent classifier heads on a shared encoder forward pass.** This is the convergent recommendation from R1 (RouterDC dual-contrastive training), R2 (vLLM Semantic Router 13-signal architecture), R3 (shared encoder + 3 MLP heads is the latency win), R5 (ordinal regression for complexity, categorical for intent/domain).
- **Use ONNX int8 quantization for the encoder.** R3 + R4: bge-small fp32 ~10-15 ms drops to ~3-5 ms post-quantization with negligible accuracy loss.
- **Train per-head calibrated abstention thresholds, not a single global threshold.** R3 + R5: Wang et al 2024 (arXiv 2405.19967) shows per-head calibrated thresholds give +6-15 % macro-F1 on known intents and +8-20 % on OOS.
- **Add an explicit "UNKNOWN" / "out-of-scope" class.** R3: CLINC150's 1.2k OOS examples + random Wikipedia snippets train this class. R5: conformal prediction set size > 1 → abstain. This closes 60-70 % of keyword-table failure modes outright.
- **Use asymmetric loss: under-routing penalty = 10× over-routing.** R5: per-(true, pred)-cell focal-cost loss; Bayes-optimal inference-time tie-break picks the higher complexity band when top-2 probs differ by < ε.
- **Pin the encoder version and monitor cosine-score distribution per route as a drift signal.** R2: the #1 reported production failure mode. Bumping the encoder must re-tune all thresholds in CI.
- **Treat the encoder as load-bearing.** R2: same encoder for queries and prototypes (the cardinal rule from every source). Cache embeddings of training prototypes at startup.
- **Wrap Stage C in Instructor + pybreaker + tenacity.** R6: zero JSON-repair surface, per-provider circuit trip, exponential backoff with jitter. ~355 LOC total.
- **Sanitize user input before interpolation into the LLM prompt** via Microsoft Spotlighting (XML encapsulation + datamarking + system-prompt anchoring). R6: ~30 LOC, no deps.
- **Build evaluation on RouterBench from day one.** R1 + R5: 405k samples, 11 LLMs, comparable to every public router benchmark. Plus MMLU-Pro + GPQA-Diamond as complexity anchors.

---

## 6. The locked-in architecture

(Reproduced here for the report; same diagram as §2.)

### 6.1 Latency budget

| Tier | p50 | p95 | p99 | When it fires |
|---|---|---|---|---|
| Stage A (heuristic + verdict cache) | 1 ms | 2 ms | 3 ms | always |
| Stage B (encoder + 3 heads) — EN | 8 ms | 12 ms | 15 ms | on Stage-A miss (~50-65 % of traffic) |
| Stage B (encoder + 3 heads) — non-EN | 3 ms | 5 ms | 8 ms | on Stage-A miss + lang ≠ en |
| Stage C (LLM judge w/ Instructor) | 500 ms | 900 ms | 1200 ms | on Stage-B abstain or high-risk domain (~10-15 %) |
| **End-to-end** | **~10 ms** | **~15 ms** | **~80 ms (p99 of Stage-B-only) / ~1500 ms (p99 inc. Stage C)** | — |

### 6.2 Public API (preserved)

`FastTriageClassifier.classify(query, input_signals=None, history=None, language=None, tenant_id=None) → TriageResult`

`TriageResult` is extended (backward-compatible) with:
- `intent_probs: dict[Intent, float]` — calibrated per-class probabilities
- `domain_probs: dict[Domain, float]`
- `complexity_probs: dict[ComplexityBand, float]`
- `intent_abstained: bool` (conformal set size > 1 OR max-prob < τ)
- `domain_abstained: bool`
- `complexity_abstained: bool`
- `stage_used: Literal["cache", "encoder", "llm_judge"]`
- `cache_hit_kind: Literal["exact", "semantic", None]`
- `encoder_used: Literal["bge-small-en", "potion-multilingual", None]`
- `llm_judge_invoked: bool`
- `llm_judge_reason: Optional[str]` — "low_confidence" / "high_risk_domain" / "head_disagreement"
- `latency_ms: float`
- `version: str` — schema version for cache invalidation

### 6.3 Configuration surface

New `FastTriageConfig` (extends [routing_config.py](../../src/layer0_model_infra/config/routing_config.py)):

```python
class FastTriageConfig(BaseModel):
    # Stage A
    enable_verdict_cache: bool = True
    verdict_cache_path: str = "artifacts/triage_cache.db"
    verdict_cache_ttl_seconds: float = 86_400 * 14  # 14 days
    semantic_cache_threshold: float = 0.93
    semantic_cache_max_entries: int = 50_000

    # Stage B
    en_encoder_model: str = "BAAI/bge-small-en-v1.5"
    en_encoder_quantization: Literal["fp32", "int8"] = "int8"
    multilingual_encoder_model: str = "minishlab/potion-multilingual-128M"
    intent_head_path: str = "artifacts/layer_3/intent_head.pt"
    domain_head_path: str = "artifacts/layer_3/domain_head.pt"
    complexity_head_path: str = "artifacts/layer_3/complexity_head.pt"

    # Calibration
    intent_temperature: float = 1.0   # learned
    domain_temperature: float = 1.0   # learned
    complexity_temperature: float = 1.0
    intent_abstain_threshold: float = 0.6   # calibrated via MAPIE
    domain_abstain_threshold: float = 0.6
    complexity_abstain_threshold: float = 0.55

    # Stage C escalation policy
    high_risk_domains: list[str] = ["medical", "legal", "finance"]
    always_invoke_llm_for_high_risk: bool = True
    llm_judge_model: str = "groq-llama-3.3-70b-free"
    llm_judge_fallback_chain: list[str] = [
        "groq-llama-3.1-8b-free",
        "gemini-2.0-flash-free",
        "gemini-2.0-flash-lite-free",
        "ollama-qwen3-8b",
    ]
    llm_judge_timeout_seconds: float = 5.0
    llm_judge_circuit_breaker_fail_threshold: int = 5
    llm_judge_circuit_breaker_reset_timeout: float = 60.0
    llm_judge_max_retries: int = 2

    # Asymmetric routing
    asymmetric_under_route_penalty: float = 10.0
    enable_bayes_optimal_tiebreak: bool = True
    tiebreak_epsilon: float = 0.05

    # Observability
    log_disagreement_rate: bool = True
    sample_llm_judge_for_telemetry: float = 0.01  # 1% shadow eval
```

---

## 7. Training-data strategy

### 7.1 Intent head

- **Source:** MASSIVE (60 intents → mapped to our 8) + CLINC150 (150 → 8) + HWU64 (64 → 8) + Banking77 (77 → mostly QA + planning in finance)
- **Taxonomy mapping:** documented in `artifacts/layer_3/intent_taxonomy_mapping.yaml` — many-to-one with provenance
- **OOS class:** CLINC150 OOS (1.2k) + 5k random Wikipedia / CC-news snippets + 5k Claude-generated adversarial near-misses
- **Augmentation:** 5-10k synthetic per intent generated by Claude-3.5-Sonnet (multilingual), filtered via disambiguation pass per Sahu et al 2022 ([arXiv 2204.01959](https://arxiv.org/pdf/2204.01959))
- **Train/val/test split:** 80/10/10 stratified by (intent × language)
- **Eval target:** ≥ 92 % macro-F1 on in-scope; ≥ 85 % OOS detection rate at 95 % in-scope accuracy

### 7.2 Domain head

- **Source:** MASSIVE (18 domains → 8) + cardiffnlp/tweet-topic-* (for casual + general) + medical / legal / finance corpora (MedQA + CaseHOLD + FinQA → ~3k samples each)
- **Cross-domain cases:** Claude-generated "privacy implications of AI in healthcare" / "tax fraud in cryptocurrency" / "malpractice in telemedicine" — labeled with multi-label allowing UNKNOWN when truly ambiguous
- **Eval target:** ≥ 95 % accuracy on medical/legal/finance recall (these are the high-stakes domains); ≥ 90 % overall

### 7.3 Complexity head

- **Source:** RouterBench (405k × 11 LLMs) — convert per-LLM success/fail labels to 5-band complexity. Specifically: a query that is solved by ≥ 9/11 LLMs → trivial; by 6-8 → simple; by 3-5 → moderate; by 1-2 → complex; by 0 → expert
- **Augmentation signals:** small-LM token entropy on a probe pass (DiffAdapt [arXiv 2510.19669](https://arxiv.org/pdf/2510.19669)) + cheap-model CoT length quartile (arXiv 2502.07266) — used as auxiliary features for the head
- **Anchors:** MMLU-Pro (12k questions, multi-choice difficulty) + GPQA-Diamond (198 PhD-expert questions, anchored to ≥ complex / expert)
- **Loss:** CORAL ordinal regression ([Cao et al 2019](https://arxiv.org/abs/1901.07884)) — penalises distance-2 errors more than distance-1
- **Eval target:** ≥ 75 % exact band; ≥ 95 % within-±1-band (the asymmetric-loss requirement); under-routing rate (cheap on hard) < 2 %

### 7.4 Calibration set

After training each head, a held-out 5 % slice is used for:
1. Temperature scaling: minimise NLL on `softmax(logits / T)` over a grid `T ∈ [0.5, 2.5]`
2. Conformal prediction calibration: MAPIE's `MapieClassifier` to derive `τ` achieving 95 % marginal coverage
3. ECE measurement: 15-bin equal-width reliability diagram, target ECE < 0.05

---

## 8. Multilingual strategy

Resolving the R3 vs R4 design tension:

- R3 recommended a single multilingual encoder (`paraphrase-multilingual-MiniLM-L12-v2`)
- R4 recommended dual-encoder (bge-small-en + potion-multilingual) dispatched by language

**Decision: R4's dual-encoder dispatched by Layer 1's `detected_language`.**

Rationale:
- Layer 1 already detects language with high confidence (3-tier cascade including Hinglish markers and lingua-py). The router can dispatch encoders for free.
- bge-small-en's MTEB-Classification (74.14) is the highest in its size class; paraphrase-multilingual-MiniLM-L12-v2 doesn't publish a clean MTEB-Class number and is ~2× slower.
- potion-multilingual is already in the environment (Model2Vec family is used in Layers 0 and 2), so the non-English path adds zero new dependencies.
- Cross-lingual transfer is handled at training time by training the heads on MASSIVE's parallel-translated utterances — both encoders produce 384-dim embeddings, so the same head weights work after a one-time linear adapter (learned during training).

Edge cases:
- Code-switched queries (e.g. Hinglish): Layer 1 emits `hi-Latn`. Dispatched to potion-multilingual. Acceptable accuracy loss; if telemetry shows hi-Latn underperforming, train a dedicated Hinglish head from the MASSIVE Hindi + English slices.
- Unknown / undetected language: fallback to `bge-small-en`. Logged for review.

---

## 9. Caching strategy (locked in)

The user explicitly said *"we'll have our own super effective Cache handling"* — so we don't depend on provider-specific prompt caching as the primary lever.

### 9.1 Tier 0 — exact-match verdict cache

- Key: `SHA256(normalize(query) || schema_version || rubric_hash)[:16]`
- Storage: `artifacts/triage_cache.db` (SQLite WAL, same pattern as Layer 2's `semantic_memory.db`)
- Value: serialised `TriageResult` (without per-call latency/timestamps)
- TTL: 14 days for high-confidence, 3 days for medium-confidence, 1 day for abstain entries (mirrors Layer 2's tiered TTL)
- Invalidation: schema_version or rubric_hash bump → no key matches → automatic
- Expected latency: ~0.1 ms per lookup

### 9.2 Tier 0b — semantic ANN cache

- Encoding: Model2Vec potion-base-8M (256-dim, already in env, ~200 µs per encode)
- Matrix: in-memory NumPy `[N × 256]`, loaded from SQLite at startup, max 50 000 entries
- Threshold: cosine ≥ 0.93 (configurable)
- Validation guards: reuse Layer 2's negation polarity + intent-mismatch guards (since the verdict is structurally similar)
- Expected latency: ~0.5-1 ms per lookup

### 9.3 Tier 0c — provider prompt caching (opportunistic, Stage C only)

When Stage C's LLM call resolves to a provider that supports caching:

| Provider | Mechanism | Action |
|---|---|---|
| Anthropic Claude | `cache_control: {"type": "ephemeral"}` on system prompt + rubric | Apply marker (1.25× write, 0.1× read; break-even after ~3 hits) |
| OpenAI GPT-4o family | Automatic for prompts ≥ 1024 tokens | No code change (free, -50 % read) |
| Groq (GPT-OSS, Kimi K2 only) | Automatic prefix match | No code change |
| Gemini | Explicit `cachedContent` API | Defer — storage fee not amortised at Stage-C volume |
| Groq (other models) | None | No-op |

The system prompt + rubric + few-shot exemplars (~3-4 KB combined) are placed at the top of every Stage-C call, with `cache_control` marker on the last block of that prefix. The user query (volatile) goes after the cache boundary.

---

## 10. Observability + continuous learning

(Addresses 3.N6, 3.N7, 3.N8, 3.O1-O5 from the audit.)

### 10.1 Per-decision telemetry

Every TriageResult logs:
- `stage_used` (cache / encoder / llm_judge)
- `cache_hit_kind` (exact / semantic / None)
- `encoder_used` (bge-small-en / potion-multilingual / None)
- `intent_max_prob`, `domain_max_prob`, `complexity_max_prob`
- `intent_abstained`, `domain_abstained`, `complexity_abstained`
- `llm_judge_invoked`, `llm_judge_reason`
- `latency_ms` (per stage + total)
- `version` (schema)

### 10.2 Aggregate metrics (computed in TelemetryLogger; Layer 9 work)

- `triage_cache_hit_rate` (target ≥ 35 %)
- `encoder_abstention_rate` (target ≤ 15 %, alarms above 25 %)
- `llm_judge_invocation_rate` (target ≤ 15 %)
- `llm_judge_circuit_breaker_trips` (alarm on > 0)
- `encoder_band_distribution` (drift signal)
- `llm_vs_encoder_disagreement_rate` (1 % shadow-eval sample — fires LLM judge on Stage B-confident queries to compute disagreement)
- `head_calibration_ece` (recomputed weekly from telemetry)

### 10.3 Shadow eval / A-B infrastructure

- 1 % of Stage-B-confident decisions also run the LLM judge (governed by `sample_llm_judge_for_telemetry`)
- Disagreement events feed an offline review queue (`artifacts/layer_3/disagreement_review.jsonl`)
- Weekly cron retrains the three heads on accumulated telemetry + reviewed disagreement (deferred to Layer 9 work — design hook is in place)

---

## 11. Sources

### Papers
- [RouteLLM (Ong et al, LMSYS, arXiv 2406.18665)](https://arxiv.org/abs/2406.18665)
- [Hybrid LLM (Ding et al, ICLR 2024, arXiv 2404.14618)](https://arxiv.org/abs/2404.14618)
- [GraphRouter (NeurIPS 2024, arXiv 2410.03834)](https://arxiv.org/abs/2410.03834)
- [RouterDC (arXiv 2409.19886)](https://arxiv.org/abs/2409.19886)
- [One Head, Many Models (Microsoft, Sept 2025, arXiv 2509.09782)](https://arxiv.org/abs/2509.09782)
- [vLLM Semantic Router (Red Hat, arXiv 2510.08731)](https://arxiv.org/html/2510.08731v1)
- [RouterBench (arXiv 2403.12031)](https://arxiv.org/abs/2403.12031)
- [FrugalGPT (Stanford, arXiv 2305.05176)](https://arxiv.org/abs/2305.05176)
- [Guo et al, On Calibration of Modern Neural Networks (ICML 2017, arXiv 1706.04599)](https://arxiv.org/abs/1706.04599)
- [Geifman & El-Yaniv, Selective Classification (arXiv 1705.08500)](https://arxiv.org/abs/1705.08500)
- [Shafer & Vovk, Conformal Prediction Tutorial (arXiv 0706.3188)](https://arxiv.org/abs/0706.3188)
- [Sahu et al, Data Augmentation for Intent Classification (arXiv 2204.01959)](https://arxiv.org/pdf/2204.01959)
- [Wang et al, Improved OOS Intent Classification (arXiv 2405.19967)](https://arxiv.org/pdf/2405.19967)
- [Cao et al, CORAL Ordinal Regression (arXiv 1901.07884)](https://arxiv.org/abs/1901.07884)
- [Microsoft Spotlighting (arXiv 2403.14720)](https://arxiv.org/pdf/2403.14720)
- [MASSIVE (Amazon, arXiv 2204.08582)](https://arxiv.org/abs/2204.08582)
- [Can Your Model Tell a Negation from an Implicature? (arXiv 2403.04314)](https://arxiv.org/pdf/2403.04314)

### Code + datasets
- [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5)
- [minishlab/potion-multilingual-128M](https://huggingface.co/minishlab/potion-multilingual-128M)
- [Aurelio Labs semantic-router](https://github.com/aurelio-labs/semantic-router)
- [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) · [vllm-semantic-router.com](https://vllm-semantic-router.com/)
- [567-labs/instructor](https://github.com/567-labs/instructor)
- [jd/tenacity](https://github.com/jd/tenacity)
- [danielfm/pybreaker](https://github.com/danielfm/pybreaker)
- [scikit-learn-contrib/MAPIE](https://github.com/scikit-learn-contrib/MAPIE)
- [coral-pytorch](https://github.com/Raschka-research-group/coral-pytorch)
- [MASSIVE dataset](https://github.com/alexa/massive)
- [CLINC150](https://github.com/clinc/oos-eval)
- [Banking77](https://huggingface.co/datasets/PolyAI/banking77)
- [HWU64](https://github.com/xliuhw/NLU-Evaluation-Data)
- [RouterBench](https://huggingface.co/datasets/withmartian/routerbench)

### Production engineering write-ups
- [Applied LLMs (Yan/Husain/Liu/Bischof/Shankar)](https://applied-llms.org/)
- [LMSYS RouteLLM blog](https://www.lmsys.org/blog/2024-07-01-routellm/)
- [Aurelio threshold-optimization notebook](https://github.com/aurelio-labs/semantic-router/blob/main/docs/06-threshold-optimization.ipynb)
- [TianPan.co — LLM routing in production (Oct 2025)](https://tianpan.co/blog/2025-10-19-llm-routing-production)
- [Red Hat — vLLM Semantic Router](https://developers.redhat.com/articles/2025/09/11/vllm-semantic-router-improving-efficiency-ai-reasoning)
- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [OpenAI prompt caching docs](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Groq prompt caching docs](https://console.groq.com/docs/prompt-caching)

---

## 12. Open questions (to revisit during build)

1. **Should the complexity head be 5-class CORAL or 1-class regression?** R5 leans CORAL (preserves ordinality, asymmetric-loss-friendly). Confirmed by trying both during build.
2. **How big is the synthetic-data budget?** Each Claude-generated batch costs ~$0.50 per 1k labelled examples. Budget cap to confirm with user.
3. **Should we train one head per language family** (Latin / CJK / Arabic / Devanagari) or one head shared across all encoders? R3 says shared; we'll validate on MASSIVE before locking in.
4. **GPU vs CPU at serve time?** ONNX int8 bge-small at ~6-10 ms on CPU fits the budget without GPU. Confirm during build via the benchmark script.
