# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An enterprise AI platform whose centerpiece is the **Smart Routing System**: an adaptive,
benchmark-grounded router that sends each LLM query to the *cheapest model that clears a
quality floor*, learning from observed outcomes without retraining anything. FastAPI backend,
Python 3.11. Stack: Qdrant (vector search), DuckDB + Parquet (benchmark-outcome corpus),
sentence-transformers / Model2Vec (encoders), LiteLLM (provider gateway), SQLModel + Postgres,
running on a local Windows + RTX 4060 workstation.

The authoritative architecture write-up is `THESIS_HANDOFF_SMART_ROUTING_SYSTEM.md` (repo root).
Read it before any non-trivial routing work — it documents every stage, algorithm, threshold,
and the research evolution. **Trust it and the code over `README.md` / `ARCHITECTURE.md` /
`docs/SMART_ROUTING.md`, which are presentation-grade and carry inflated/aspirational numbers.**

## ⚠️ Two different "layer" numbering schemes — do not conflate them

This is the #1 source of confusion in this repo.

1. **Platform layers** = the `src/layerN_*` top-level packages (a vertical product stack):
   `layer0_model_infra` (routing + gateway), `layer1_intelligence` (RAG / grounding / citations),
   `layer2_orchestrator` (execution loop), `layer3_domain` (document ingestion), and
   `layer4_platform` / `layer5_governance` / `layer6_aiops` (mostly scaffolding, ~0% built).

2. **Routing pipeline stages L0–L9** = the nine stages of the router itself. **All of them live
   inside `src/layer0_model_infra/`** — they are NOT the `src/layerN_*` directories. So "Layer 3"
   almost always means the **kNN router stage**, not `src/layer3_domain/`.

When someone says "Layer 3 is the highest-stakes layer," they mean the kNN router in
`src/layer0_model_infra/routing/knn_router.py`, not the document-domain package.

## Architecture: the routing pipeline

**Decision brain vs. execution body** — kept deliberately separate:
- `src/layer0_model_infra/router.py` (`ModelRouter`) is the **decision brain**: runs L0→L3,
  returns a structured `RoutingDecision`. No tokens spent; unit-testable in isolation.
- `src/layer2_orchestrator/execution_loop.py` is the **execution body**: invokes the chosen
  model and runs L6 (test-time compute) → L7 (quality eval) → L8 (escalation) → L9 (telemetry).

Stage → file map (all under `src/layer0_model_infra/`):

| Stage | What it does | File |
|------|--------------|------|
| L0 Fast Path | deterministic bypass of trivial queries (greetings/arithmetic/facts), 15-lang | `routing/fast_path.py` |
| L1 Modality Gate + Security | modality detection, prompt-injection defense, PII, input bounds | `routing/modality_gate.py` |
| L1.5 Input Signals | pure-compute difficulty/feature extraction | `routing/input_signals.py` |
| L2 Semantic Memory | outcome-aware semantic cache of prior decisions | `routing/semantic_memory.py` |
| **L3 kNN Router** | benchmark-grounded per-model quality prediction + cost-minimal pick | `routing/knn_router.py` |
| L3 support | feature extraction, high-risk detect, verdict cache, outcomes, priors, safe-default | `routing/feature_extractor.py`, `high_risk_classifier.py`, `verdict_cache.py`, `outcome_store.py`, `aggregate_scores.py`, `fallback_router.py` |
| L6 Test-Time Compute | best-of-N / self-consistency / generator-verifier for borderline queries | `routing/test_time_compute.py` |
| L7 Quality Evaluation | deterministic + heuristic silent-failure detection (no LLM judge on hot path) | `routing/quality_evaluator.py` |
| L8 Auto-Escalation | bounded climb up L3's cost-sorted qualifying set on quality failure | `routing/escalation_engine.py` |
| L9 Telemetry + Learning | async telemetry, online EMA calibration, KL drift detection | `routing/telemetry.py`, `calibration_store.py`, `drift_detector.py` |

The **kNN router** (L3) is a four-stage A→D pipeline: (A) verdict cache, (B) feature extraction,
(C) encode → Qdrant kNN search → per-model similarity-weighted quality prediction → cost-minimal
selection inside the qualifying set, (D) safe-default fallback. Cost minimization runs *inside*
the set of models that already cleared the floor — over-routing is structurally impossible, not a
tuning target. The encoder is `paraphrase-multilingual-MiniLM-L12-v2` (384-dim); high-risk Tier-2
uses `bge-small-en`; the cache/fast-path use Model2Vec `potion-base-8M`.

**Learning loop (retrains nothing):** per `(model, modality:language:high_risk:difficulty)` cell,
an EMA calibration multiplier (α=0.1, clamped [0.5,1.5]) corrects raw predictions; only
`knn_corpus` (neighbour-grounded) decisions feed it. A KL-divergence drift scan freezes a model's
calibration on a `halt`-level distribution shift. The only gradient-trained component anywhere is
`routing/benchmark_router.py` (a small advisory GBC) — it is **NOT on the kNN hot path**.

**Config — no magic numbers in source.** Every threshold/ratio/TTL lives in
`src/layer0_model_infra/config/routing_config.py` as Pydantic models, with `DEVELOPMENT_CONFIG` /
`PRODUCTION_CONFIG` profiles selected by `get_routing_config()`. Environment-level toggles
(e.g. the `LAYER3_ENABLED` kill switch, quality-floor overrides) live in `src/shared/config.py`
(`Settings`). Models live in `registry.py` and activate/deactivate at runtime based on the presence
of provider API keys.

## Prior-path routing work + honest findings (2026-06-13, all on origin/main)

The **prior path** — when a query has no kNN neighbours (~76% of diverse traffic) — scored every
model off a flat, query-*independent* constant, and was the system's weak spot. Committed work,
each config-gated and reversible:

- **Debiased priors** (`50a3292`). `aggregate_scores.prior_quality()` multiplies the published-
  benchmark prior by a per-`(model, modality)` **realism factor** = measured/prior, loaded from
  `data/model_prior_realism.json` (regenerate with `scripts/layer3/calibrate_priors.py --write`).
  Published priors ran **+0.18 to +0.45 above measured reality**, so cheap weak models cleared
  floors they had no business clearing (under-routing). Applied on the **prior path only** — the
  kNN-grounded path is untouched. Consequence: `knn_router._effective_floor` now **skips the
  low-coverage penalty for any model that has a realism factor** (else it double-counts the same
  correction).
- **Risk-aware escalation gated to the grounded path** (`50a3292`). The escalation in
  `knn_router._choose` only fires when `knn_grounded=True`. On the prior path every prediction
  carries the same placeholder confidence (`prior_confidence`, 0.20), so the old code escalated
  *every* off-distribution query up to the strongest (often paid) model — defeating cost-min.
- **High-risk recipe false-positive fix** (`eed5f0b`). `high_risk_classifier.py` gained a
  `NEUTRAL_PROTOTYPES` background bank: a query is flagged high-risk only when it is closer to a
  risk prototype than to a benign one. Fixes "how to make a milkshake **at home**" → MEDICAL (it
  was matching "treat a deep cut **at home**") without dropping medical recall (held-out eval:
  recall 1.0, precision 0.84 → 0.99). A threshold bump can't do this — real emergencies sit in the
  same similarity band as the recipe FPs.
- **Learned quality head** (`68012d8`): `routing/quality_head.py` + `data/quality_head.npz`
  (trained by `scripts/layer3/train_quality_head.py`). A per-model Ridge regressor over the query
  embedding predicts per-`(query, model)` quality on the prior path, replacing the flat prior for
  the 4 models whose 5-fold CV genuinely beats it (llama-8b/70b, qwen-72b, gpt-4o-mini). numpy-only
  inference (`W·emb + b`), **inert + falls back to the prior if the artifact is missing**, gated by
  `Layer3QualityHeadConfig.enable`.

**Honest evaluation — DO NOT oversell these** (verified this session via a strict, blind,
held-out benchmark: split questions 70/30, retrain heads on the 70%, route among *registry* models
on the unseen 30% scored against real graded outcomes; "cost" = model size in B params since all
models are free):
- The **learned head is roughly a wash** vs the flat prior (≈0.545 correct / 70.6B vs 0.554 /
  73.7B) — marginally cheaper, marginally *less* correct. Hand-picked demo queries flatter it; the
  blind benchmark is sober. It is the right *shape* (zero per-query LLM call) but **data-limited**.
- The prior path today ≈ **always-strongest**; the **oracle is 0.697 / 66.4B**, so there is real
  cost+correctness headroom no predictor on this data captures.
- A **cascade** (try-cheap → verify → escalate, FrugalGPT-style) has a high *ceiling* (0.695 /
  47.3B with a *perfect* judge) but the entire win is **gated by the judge**: a cheap judge
  (llama-70B) silently passes some wrong cheap answers (under-routes); a strong judge is itself a
  **per-query LLM call**, which **defeats the cost goal at scale and contradicts the founding
  principle that the kNN router exists specifically to avoid per-query LLM calls.** Only
  *deterministic* verification (code compiles / tests pass, JSON+schema valid — the existing L7
  checks) is judge-free, and it only covers **structured outputs**, never factual/reasoning.
- **The genuine lever stays what the analysis found first: more grounding data** — it sharpens the
  kNN *and* the head (both judge-free predictors) and is the known rate-limit-walled bottleneck.

**Rule of thumb for future routing work:** prefer prediction (kNN / head) + free *deterministic*
checks + more grounding data over bolting any per-query LLM judge onto the hot path. When you test
a routing change, use a **blind held-out benchmark against real outcomes**, not hand-picked demo
queries — the latter consistently over-flatter whatever you just built.

## Deterministic grounding + escalation/floor work (2026-06-13 cont., local on `main`, NOT pushed)

Follow-on to the section above, and the first **positive controlled proof** that "more grounding
data is the lever" — paired with a **negative control** (floor tuning does nothing). Full write-up:
`docs/THESIS_SESSION_DETERMINISTIC_GROUNDING.md`.

- **Deterministic MMLU-Pro grounding** (`e931dc9`). The 4 newest free models (`gpt-oss-120b/20b`,
  `qwen3-32b`, `llama-4-scout`) had **0** per-question outcomes on the 12,032-question MMLU-Pro set
  (vs 12,032 each for llama-8b/70b, qwen-72b), so on academic queries they rode the flat prior and
  the router defaulted to 120B. Harvesting public scores can't fix this — those models aren't on any
  leaderboard. `scripts/layer3/generate_mmlu_outcomes.py` runs them on MMLU-Pro and grades by
  **exact-match on the gold letter** — judge-free, $0, resumable, writes to
  `data/processed/harvested/outcomes_mmlu_det.parquet`; fold in with `merge_generated_outcomes.py
  --src mmlu_det`. Questions are already embedded, so outcomes attach with no re-embed. **Measured
  (leakage-safe LOO — each question's self-match masked in Qdrant — scored on real outcomes,
  free-only): correctness 0.597 → 0.629 at 98.2B → 65.4B avg size, 100% free** = a Pareto win
  (gpt-oss-120b picks 117 → 68, llama-4-scout 2 → 69). **In-domain academic only** — does NOT fix
  conversational over-routing (still needs production-feedback grounding). 278/12,032 ≈ 2.3% coverage
  already moves routing this much → marginal value per grounded question is high; scaling the run
  extends the win. Eval/merge tools: `validate_loo_mmlu.py` (`--free-only` for proxy-free scoring).
- **Stop selecting keyless + over-flagged premium models** (`570f9a7`, fixes A+B):
  - **B** — `knn_router._choose` now **skips inactive (keyless) models** in the qualifying loop. They
    were being "selected" then falling back to a free model at execution = phantom telemetry/cost.
    When no *active* model clears the floor, the existing best-available branch picks the best free.
  - **A** — `high_risk_classifier.py`'s neutral bank gained **third-person/factual exam anchors**
    (bar-exam law scenarios, finance-math, science facts) so academic MCQs aren't flagged as
    medical/legal/financial *advice*. Over-flagging 58 → ~42 on a 278-q probe with **recall held at
    exactly 1.0** — `test_eval_set_recall_and_precision` enforces `recall==1.0`, so the
    contract-enforceability anchors were left out (they suppressed the genuine positive "is a verbal
    agreement enforceable"). Recall is the hard constraint. 47 layer3 tests green.
- **Quality-floor calibration = NEGATIVE result** (`9d11f0a`). Built
  `scripts/layer3/calibrate_quality_floor.py` — the auto-tune script `Layer3QualityFloorConfig`'s
  docstring promised but never existed (encode-once, then sweep only the selection; `--full` keeps
  premium active to see the free-vs-paid axis). It proves **lowering the floor barely helps**:
  dropping high-risk 0.75 → 0.65 and the hard penalty → 0 buys only **+4pp free-select / −11 paid at
  flat correctness**, because the residual escalations are questions where free models *genuinely*
  predict < 0.65 (defensible, not a miscalibration). **Floor config left unchanged** — a clean
  negative control: the lever is the data, not the knobs.

State: the three commits are **local on `main`, not pushed** (push gated on owner OK). Outcome data
is gitignored/local — `outcomes.parquet` gained +1,070 rows (merged, reversible via
`outcomes.parquet.genmerge.bak`); the `harvested/` sidecars and `artifacts/layer3/loo_mmlu_*.json`
are local-only.

## The legacy router (archived, not deleted)

The original Fast-Triage → Uncertainty → Contextual-Bandit pipeline was **decommissioned** from
the live path; the kNN router is now the sole production router. The old modules are preserved
under `src/layer0_model_infra/routing/legacy/` (`fast_triage.py`, `complexity_classifier.py`,
`uncertainty_estimator.py`, `bandit_router.py`, `query_analyzer.py`) as a research artifact for
the thesis/PPT. **Standing instruction: keep documenting that the legacy code lives there; do not
silently delete it.** Their config classes (`BanditConfig`, `FastTriageConfig`, etc.) still sit in
`routing_config.py` labelled LEGACY.

Gotcha: `RoutingDecision` (in `router.py`) still exposes legacy-named fields — `triage_result`,
`uncertainty_score`, `bandit_context`. Post-decommission these are synthesized neutral dicts, not
real bandit/triage output. Don't read routing behavior from them; the live signal is in
`layer3_raw_decision` and `pipeline_metadata`.

## The RAG-with-citation subsystem (platform Layer 1 / Layer 3-domain)

Separate from routing, `src/layer1_intelligence/` + `src/layer3_domain/` implement a complete
**grounded-RAG-with-verifiable-citation** stack — the platform's second trust pillar. Flow: parse
(PDF via **PyMuPDF→pypdf**; form-feed text) → structure-aware chunk (legal-article / page-section /
paragraph) → resilient embed (Ollama `qwen3-embedding` gateway → deterministic 128-dim hash
fallback) → hybrid retrieve → rerank (+ optional cross-encoder) → grounded-support gate (refuses with
`NoRelevantContextError` → HTTP 404 when evidence is thin) → evidence-constrained generation
(temp 0.1) → `ClaimVerifier` (per-claim verdicts + a 0–100 verifiability score). Exposed via
`/grounded-documents/*` and `/chat` grounded mode (`grounded_collection_id`). Collections persist
three ways — in-process → JSON snapshot → async relational DB — and rehydrate on demand
(**tenant-checked**: a cross-tenant id is treated as not-found, never loaded into the shared cache).

- **The default vector store is `InMemoryVectorStore`** (dense 0.58 + lexical 0.42, plus a separate
  BM25 pass fused via RRF k=60, with drug/article/dose query bonuses). `RAG_VECTOR_BACKEND`
  (`src/shared/config.py`, default `memory`) switches it to `qdrant`, but **Qdrant is
  vector-similarity only** — it drops BM25, RRF, and every lexical bonus, trading retrieval quality
  for cross-restart persistence/scale; they are *not* interchangeable. The production factory falls
  back to memory if Qdrant is unreachable, and the adapter infers its collection dimension from the
  *actual* embeddings (so the stale `.env` `EMBEDDING_DIMENSION=1536` vs the model's real 1024 is
  harmless). **The in-memory index is rebuilt on restart** (doc text survives in the JSON snapshot +
  Postgres `content_json`, but vectors are re-embedded). `RAG_EAGER_HYDRATE` (default on) makes
  `DocumentCollectionService.hydrate_all()` re-index **every** persisted collection in a background
  task off the FastAPI lifespan at startup, so a bot answers on its first query post-restart instead of
  paying a cold lazy re-embed (turn it off on dev machines that hot-reload constantly).
- **Cross-encoder rerank** (`cross-encoder/ms-marco-MiniLM-L-6-v2`) is gated by
  `RAG_CROSS_ENCODER_ENABLED` (default on) so it can't surprise-load onto the GPU; its raw logits are
  **sigmoid-squashed to 0–1** so the grounding-gate thresholds and the displayed score are meaningful.
- **Original-page citations:** beyond char-offset highlight spans + full page text, a proof can render
  the **actual source page image** (`src/layer1_intelligence/pdf_render.py`, served by
  `GET /grounded-documents/collections/{id}/page-image`) with highlights drawn as *normalized
  rectangles* located via `fitz.search_for`. Both the standalone `/rag-citations/demo` **and V07's
  `PageViewer.svelte`** offer an "Original page" / "Extracted text" toggle and fall back to text when
  no image (V07's `api.js` stamps the collection id + tenant onto each proof so the viewer can build
  the image URL; the Vite proxy already covers `/grounded-documents`). Original PDF bytes are persisted
  per collection under `.runtime/grounded_collections/_files/` to re-render after a restart — **PDFs
  only, and only from ingest onward, so a collection created before this feature needs a re-ingest to
  get page images** (no stored bytes → `has_page_image=False` → text fallback). Contract types
  (`NormalizedRect`, `HighlightSpan.rects`, `PageProof.has_page_image`) live in
  `src/layer3_domain/document_models.py`.
- **Routing ↔ generation fusion seam.** By default `GatewayAnswerGenerator._choose_model_id` picks the
  answer model from a hardcoded free-model list, so grounded mode does *not* invoke the smart router.
  An optional per-call **`answer_model_id`** on `GroundedRAGService.answer_query` /
  `DocumentCollectionService.answer_query` (threaded as `model_id_override` into the generator) forces
  a specific model — e.g. the one the kNN router selected — without mutating the shared per-collection
  generator. Default `None` preserves current behavior; this is the seam for fusing router-selected
  models with cited answers. (It only takes effect in gateway generation mode; the extractive
  `HeuristicAnswerGenerator` accepts and ignores it.)
- **Domain heuristics are pluggable, not inline.** `src/layer1_intelligence/domain_profiles.py`
  (`LegalDomainProfile`, `MedicalDomainProfile`) owns the constitution/medicine query-expansions and
  the legal structured-answer logic; the engine calls `expand_domain_queries` /
  `structured_domain_answer`. Profiles are *content-triggered* (inspect the query/citations, not the
  declared domain), so a new domain is a new profile, not an edit to the engine. The article/dose
  **scoring bonuses** in `vector_index.py` are deliberately left as encapsulated helpers (entangled
  with the tuned score math; one is reused in a rerank conditional), not moved into profiles.
- **`ClaimVerifier` is read-only** — it scores, never rewrites or refuses (`auto_corrected` is a
  reserved/unused field). It runs embedding+lexical (the embedding path is real, same Ollama model)
  and reports `match_type` (verbatim/semantic/lexical) + `verbatim_supported_count`, so a ~100% score
  on a copied extractive answer is surfaced as "all verbatim from source" rather than mistaken for
  synthesis quality.
- Char-offset highlight spans + full page text are what make citations *verifiable*; the contract
  types live in `src/layer3_domain/document_models.py`.
- Authoritative doc: `docs/THESIS_HANDOFF_RAG_CITATION.md` (its §19 is the source-file map).

## Frontend (V07 — Svelte 5 SPA)

`frontend/v07/` is a full Svelte 5 (runes) + Vite 8 single-page app (the showcase UI). **It is
dev-served by Vite and is NOT statically mounted by FastAPI** — run it separately; Vite proxies API
calls to `:8000`.

- Dev: `cd frontend/v07 && npm install && npm run dev` (auto-increments the port 5173→5174→… if busy).
- **Verify frontend changes with `npm run build`** — it runs the Svelte compiler over every component
  and surfaces all template/compile errors; a clean build is the baseline check. The Vite plugin's
  a11y *warnings* are pre-existing and non-blocking. The Preview MCP is scoped to `C:\Users\Vasif2`
  and can't launch this D: project, **but it can drive an already-running dev server** if you point its
  tab at `http://localhost:<port>` (`preview_eval` to navigate, then inspect DOM / theme live).
- `src/lib/api.js` is the backend-contract bridge **and** carries real client-side logic: the typed
  content-block transformer, **Chart.js auto-detection from markdown tables / prose**, the verbose
  `(Citation N, …)` → clean `[N]` superscript rewrite, and mammoth.js `.docx`→text before upload.
  `transformResponse` flattens `/chat`'s `routing_decision`/`escalation`/`performance`/`cost` into the
  `routing` object the UI renders; `getModels()` is memoized.
- **Web search is entirely client-side** (`searchWeb`: Tavily → SearXNG → DuckDuckGo → Wikipedia
  fallback); results are injected into the prompt before it is sent, so the backend never sees the
  search step. There is no server-side web-search route — don't go looking for one.
- `src/lib/stores.js` holds the state (conversations, simulated wallet, streaming, theme, the active
  model/jury config, hash routing `#/rag/<collection>`), all localStorage-persisted.

**Typed content-block rendering is the extension seam.** Answers are arrays of typed blocks
(`text`/`table`/`chart`/`citations`/`verification`/`jury`/`image`/…); `MessageRenderer.svelte`
dispatches one branch per `type`, and the typewriter reveals text word-by-word while snapping non-text
blocks in whole. **Adding an answer feature = a new block type + a renderer branch**, not a rewrite —
that is how the claim-verification panel and the LLM Jury panel were added.

**The model "mode" lives in `selectedModel.mode`** (`smart` | `manual` | `jury`). Forcing a specific
model sends `simulation_profile_id` (a *billing profile*) — it does NOT swap the executor — so per the
demo display rule the UI keeps showing the *chosen* model and relabels forced runs as manual
comparisons. `ModelSelector.svelte` + the header chip switch between Smart Routing, a single model, and
the LLM Jury; user preferences (theme, smart suggestions, web search, claim verification) live in
`SettingsPopup.svelte`.

**Multi-model features (the UX differentiators), all orchestrated client-side over the same
`sendMessage`/`simulation_profile_id` path:**
- **Routing transparency** — `RoutingInsight.svelte` renders the router's reasoning, quality-gate
  meter, escalation status, and latency/cost under every answer (the headline differentiator).
- **Regenerate-with-model + side-by-side compare** (`ComparePanel.svelte`) — re-run a prompt on
  another model, or two at once with a live cost/latency verdict banner.
- **LLM Jury** (`JuryConfig.svelte` + `runJury` in `App.svelte`) — fan a prompt to N chosen models,
  then a synthesizer fuses their answers; the verdict + each juror's answer render as a `jury` block.
  **Fan-out is bounded-concurrency (4) + retry-with-backoff** — firing all N at once trips the provider
  rate limit. Two backend failure modes to know: a hard `ModelRateLimitError` (HTTP error → throws) and
  a **soft `execution_loop.py` `"Error: Execution failed"` returned as HTTP 200** (not an exception);
  both are detected and retried, and the synthesizer falls back to the strongest juror's answer rather
  than surfacing the error text.

Authoritative docs: `docs/THESIS_HANDOFF_v07.md` (the citation UX) + `docs/V07_FRONTEND_SESSION.md`
(the 2026-06 UX-enhancement session — routing transparency, compare, jury, settings consolidation —
with full rationale + commit trail).

## The external chatbot widget (public-facing, embeddable)

Distinct from V07: an **embeddable widget** companies drop on their *own* public site via one
`<script>` tag. It reuses the smart router + grounded-RAG stack but is a separate, public,
cross-origin surface. Code lives in `src/layer4_platform/` + `src/interfaces/http/routes/widget.py`
(public), `admin_bots.py` / `admin_console.py` / `admin_autopilot.py` (admin control plane),
`middleware/widget_cors.py`, `src/layer3_domain/web_crawler.py`. **AutoPilot** onboarding adds
`src/layer3_domain/site_renderer.py` (Playwright), `src/layer4_platform/theme_extractor.py`
(palette→theme), `src/layer4_platform/autopilot.py` (orchestrator). Docs:
`docs/THESIS_HANDOFF_EXTERNAL_WIDGET.md` (onboarding) + `docs/THESIS_EXTERNAL_WIDGET_COMPLETE.md`
(full deep-dive). Tests: `tests/widget/` (kept **torch-free** — registry / rate-limit /
crawler-via-httpx-MockTransport / CORS shim / `test_autopilot.py` palette+SSRF+autofill-parse; widget
+ console JS verified out-of-band with jsdom, not in the Python suite).

- **A company = tenant + grounded collection + a `BotConfig`** (`layer4_platform/bot_registry.py`).
  `PublicBotConfig` is the **only** shape the browser receives and is a safe projection that
  **never carries `tenant_id` / `collection_id` / `allowed_origins` / `preview_screenshot_id`** — a
  leaked `bot_id` (it sits in the page source) yields branding only. `BotTheme` adds `bot_bubble_color`
  (assistant bubble → `--bot-bubble`; `null` = adaptive light/dark tint), and `BotConfig` adds
  `preview_screenshot_id` (AutoPilot screenshot id for the preview backdrop; **server-only**). Configs
  persist as JSON under `.runtime/bot_configs/`
  (gitignored), dir resolved from `__file__` — do **not** copy `document_collections.py`'s hard-coded
  `D:/College/...` path. Adding a per-bot field means threading it through `BotCreateRequest`/
  `BotUpdateRequest` (admin_bots) → `create_bot` (bot_registry) → `PublicBotConfig.to_public()` →
  the loader → the console form.
- **The fusion (the entire reason this exists):** the public chat handler runs `model_router.route()`,
  then generates the grounded/cited answer *with that routed model* by passing `answer_model_id` into
  `grounded_collection_service.answer_query(...)` **and forcing `generation_mode="gateway"`**. The
  internal `/chat` grounded branch does NOT route (it bypasses the router). `answer_model_id` threads
  `document_collections.answer_query` → `GroundedRAGService.answer_query`/`stream_answer` →
  `GatewayAnswerGenerator.generate`/`generate_stream` (as `model_id_override`). Retrieval is shared by
  `GroundedRAGService._retrieve_context`, the prompt by `_build_grounded_messages` — keep both the
  blocking and streaming paths on the shared helpers so they never drift.
- **CORS is the #1 gotcha.** The public surface is credential-less and must NOT ride the global strict
  `CORSMiddleware`. `PublicWidgetCORSMiddleware` is added **last in `main.py` (→ outermost)**, acts
  **only on `/widget/*`** (answers preflight, reflects Origin, `credentials:false`), and passes every
  other path through untouched. A mounted sub-app does NOT work — the global CORS intercepts all
  preflight first. The authoritative origin gate is `bot_service.is_origin_allowed()` **in the handler**
  (CORS is browser-side, bypassable), plus per-IP/per-bot rate limits (`widget_rate_limit.py`). The
  gate also trusts the app's **own** origin (`_is_self_origin` vs `request.base_url`) so `/admin/console`
  and `/widget/preview` can chat any bot without it listing the demo host in `allowed_origins`.
- **The loader (`WIDGET_LOADER_JS` in widget.py)** is vanilla JS in a Shadow DOM, themed entirely from
  `--bot-*` CSS variables fed by the config (re-skin = config edit, no code). **Rich answer content
  (HTML/CSS/JS) renders in a `sandbox`ed iframe with NO `allow-same-origin`** so model/KB-supplied
  scripts can't reach the host page — never render model HTML straight into the host DOM. The loader
  source must **never contain the literal `</script>`** (write `'</scr' + 'ipt>'`) so it can embed in
  inline scripts / jsdom tests.
- **Knowledge in two ways, same `ingest_assets` path.** (1) The **crawler** (`web_crawler.py`,
  `POST /grounded-documents/collections/{id}/crawl`): same-domain, robots-aware, `httpx` + stdlib
  `html.parser`, **static/SSR only** (runs no JS — SPAs return thin pages, reported in warnings).
  (2) **Document upload** (`POST /grounded-documents/collections/upload`, multipart PDF/text), now
  exposed in the console. **Insight (verified):** a homepage crawl is mostly boilerplate, so pointed
  questions get *correctly* refused by the grounding gate (not a crawl/rehydration bug) — focused
  uploads (FAQ/brochure/prospectus) are the fix.
- **AutoPilot** (`POST /admin/autopilot/analyze`, gated by `WIDGET_AUTOPILOT_ENABLED`): paste a URL →
  review-ready bot draft. `autopilot.analyze_site` runs SSRF guard (`guard_public_url`, blocks
  private/loopback IPs) → **Playwright** headless render (`site_renderer.render_site`: full-page
  screenshot + visible text + metadata; **sync API via `asyncio.to_thread`** to dodge the Windows
  Proactor pitfall; **lazy** import so the app runs without the engine) → **KMeans palette →
  contrast-checked theme** (`theme_extractor`, Pillow+sklearn; honors `theme-color` meta; auto-darkens
  the primary so white header text clears WCAG contrast) → **router→LLM copy** (`get_router()` +
  `gateway.complete`, JSON `response_format`; deterministic fallback). It only *drafts* — the console
  fills the form and the human clicks Create. **Playwright browsers MUST sit on a real filesystem
  path** (`PLAYWRIGHT_BROWSERS_PATH` defaulted to `.runtime/pw-browsers/` in `site_renderer.py`): a
  sandboxed installer's writes to `%LOCALAPPDATA%\ms-playwright` get AppContainer-*virtualized* so the
  server sees "Executable doesn't exist" though it looks present. Install with that env var set;
  `.runtime/pw-browsers/` + `.runtime/widget_screenshots/` are gitignored.
- **The console** (`/admin/console`) has **Manual** and **✨ AutoPilot** modes; its live preview is a
  faithful **full-size (420×720) replica** of the real widget (surfaces subtitle + branding footer +
  bot/user bubbles), and for AutoPilot bots `/widget/preview` floats the widget over the captured site
  screenshot as a page backdrop (via `preview_screenshot_id`).
- **Config:** env-level toggles/caps in `Settings` (`WIDGET_PUBLIC_ENABLED`, `WIDGET_RATE_*`,
  `WIDGET_CRAWLER_MAX_*`, `WIDGET_AUTOPILOT_*`, `RAG_EAGER_HYDRATE`). New runtime deps: `playwright`
  (then `playwright install chromium`) and `Pillow`. Endpoints: public
  `/widget/{id}/config|chat|chat/stream|suggest`, `/widget/loader.js`, `/widget/preview`; admin
  `/admin/bots/*` (+ `/debug-chat`), `/admin/console`, `/admin/autopilot/analyze` +
  `/admin/autopilot/screenshot/{id}`.

## Cross-file invariants & gotchas (easy to get wrong)

- **Two registries, bridged by an adapter.** Routing happens over `data/registry.json` (the Layer 3
  registry); the **gateway executes** against the in-code `registry.py`. At startup
  `routing/layer3_adapter.register_layer3_models()` copies L3 models into the legacy registry,
  converting **per-1M → per-1k pricing (÷1000)**. Get the conversion wrong and every cost is 1000×
  off; edit one registry without the other and ids fail to resolve.
- **Corpus and query encoder must match.** `scripts/layer3/embed_corpus.py` and the live router both
  read the encoder name from `routing_config` for exactly this reason — a past bug embedded the
  corpus with `bge-small` while the router queried with MiniLM (different vector spaces, broken
  search). Never hardcode an encoder in only one place.
- **`scripts/layer3/merge_generated_outcomes.py` is the only script that mutates the live
  `outcomes.parquet`** (it backs up first). Every other pipeline script writes to `harvested/` or a
  proposed `*_merged` file. Don't hand-edit the live corpus.
- **Standalone scripts must inject `.env` themselves.** The app's pydantic `Settings` reads API keys
  from **OS env only**, not `.env`. A one-off script that relies on `.env` sees no keys unless it does
  `from dotenv import dotenv_values; [os.environ.setdefault(k, v) for k, v in dotenv_values('.env').items() if v]`
  first. (Symptom: every model "inactive" / 401s in a script the app itself runs fine.)
- **The L7 LLM judge cannot fire on the hot path** — not just "off by default." `_invoke_llm_judge`
  returns `None` whenever an event loop is running, so even passing `use_judge=True` is a no-op under
  the async orchestrator. Production quality is deterministic-validators + heuristics only.
- **The demo's commercial tiers are fictional.** `gpt-5.4-*`, `claude-4.6-*`, `deepseek-*` in
  `interfaces/http/demo_mode.py` are made-up presentation tiers mapped to free backing models — not
  real model ids and not typos. The wallet bills them at "commercial" rates while a free model runs.

## Commands

Environment: conda env **`enterprise-ai-platform`** (Python 3.11). Interpreter on this machine:
`D:/Software_Download_Files/anaconda3/envs/enterprise-ai-platform/python.exe`. Deps are
Poetry-managed (`poetry install`); `pip install -r requirements.txt` also works.

**Run the API** (repo root, env active):
```
python -m uvicorn src.interfaces.http.main:app --reload --host 0.0.0.0 --port 8000
```
or `.\run.bat` (auto-creates `.env`, picks poetry/conda as available). Endpoints: `/docs`,
`/health`, `/chat/demo` (embedded routing demo UI), `/rag-citations/demo`. Runs with `--reload`,
so backend + embedded-JS edits hot-reload.

**Infrastructure** (Docker): `docker-compose up -d qdrant postgres redis`.
- **Qdrant is required for L3** (kNN search) and the layer3 test suite.
- Postgres backs runtime telemetry persistence; Redis is optional. Phoenix / pgAdmin are optional
  (`pgadmin` only starts with `--profile tools`).
- **Qdrant reachability gotcha:** on Windows `localhost` resolves to IPv6 `::1`, which the Docker
  port-proxy doesn't forward. Use **`127.0.0.1`** — `.env` already sets `QDRANT_HOST=127.0.0.1`.
  Verify with `curl http://127.0.0.1:6333/readyz` (200). The container shows **"unhealthy"** because
  the compose healthcheck calls `curl`, absent from the qdrant image — a false alarm, ignore it.

**Tests** (`pytest`; `pyproject.toml` forces `--cov=src` + html/xml coverage on every run):
- ⚠️ **Never run the full suite in the background.** Tests load torch + the MiniLM encoder onto the
  RTX 4060, and `tests/layer0_model_infra/test_benchmark_router.py` *trains* models — detached runs
  hog the GPU and have to be killed. Run **foreground**, **targeted**, and warn before heavy runs.
- Routing baseline (~90s, foreground, needs Qdrant up):
  `pytest tests/layer3 tests/layer0_model_infra/test_fast_path.py`
- Single test: `pytest tests/layer3/test_knn_router.py::TestClassName::test_name`
- Test layout: `tests/layer3/` (kNN router + L3 components), `tests/layer0_model_infra/` (fast path,
  modality, quality eval, + the archived legacy-component tests), `tests/unit/` (RAG / documents),
  `tests/test_elite_pipeline.py` (end-to-end). `tests/integration` & `tests/e2e` are mostly empty.

**Lint / format / type:** `black .` and `ruff check .` (both line-length 100), `mypy src` (strict).

## Data & infra reality (mostly gitignored / local-only)

- Qdrant L3 corpus collection is **`layer3_benchmark_corpus`** (≈14,922 pts, 384-dim cosine) — a
  *different* collection from the RAG one (`enterprise_knowledge` in `.env.example`).
- The benchmark corpus (`data/.../questions.parquet`, `outcomes.parquet`, etc.) is local/gitignored.
  The `scripts/layer3/` directory holds the whole corpus-build / harvest / validation pipeline
  (`build_outcomes_corpus.py`, `harvest_outcomes.py`, `generate_outcomes.py`, `embed_corpus.py`,
  `setup_qdrant_collection.py`, `build_validation_set.py`). `validate_loo.py` regenerates the
  leave-one-out router-accuracy numbers ($0, self-contained) — re-run it before quoting any LOO
  figure; the headline validation JSONs are *not* committed artifacts.
- Dense grounding / the full correctness gate are **blocked behind free-tier API rate limits** —
  a known, long-standing constraint, not a bug.
- **Telemetry schema gotcha:** the app runs against an existing Postgres DB, and SQLModel
  `create_all` never `ALTER`s an existing table. Any new `RoutingTelemetryRecord` column needs
  `scripts/migrate_telemetry_l3_columns.py` (idempotent) run against the live DB, or every insert
  silently fails with "column … does not exist".

## Project conventions

- **Verify against real code/data before implementing — don't trust handoffs or memory blindly.**
  Measure real behavior by probing the live system; live probing has repeatedly caught bugs that
  unit tests missed. Accuracy is paramount here; thoroughness over speed, with visible incremental
  progress (use task tracking).
- **Commits:** lowercase subject, conversational body explaining *why* not *what*, no emojis, no
  `===` dividers, no `Co-Authored-By`, and never mention AI/Claude. Match the existing `git log`
  tone. Commit incrementally per logical chunk.
- **Never push, rebase, or force-push without explicit approval.** Default to local commits, then ask.
- **Demo display rule:** the UI always shows the *router-selected* model, never the execution
  fallback. Keyless premium models and rate-limited free tiers fall back to a free model at execution
  time, but `ChatResponse.model_used` reports `decision.selected_model.display_name`.
- **Local-only docs — never commit:** `docs/layers/PROBLEM_INVENTORY.md`,
  `docs/THESIS_HANDOFF_AND_9_LAYER_REFERENCE.md`, `docs/layers/LAYER3_BATCH3_HANDOFF.md`. These are
  working/handoff documents kept out of version control by convention.

## Where to read more

- `THESIS_HANDOFF_SMART_ROUTING_SYSTEM.md` — full routing architecture (the trustworthy overview).
- `docs/THESIS_HANDOFF_RAG_CITATION.md` — the grounded-RAG-with-citation subsystem (backend half).
- `docs/THESIS_HANDOFF_v07.md` — the V07 frontend and the end-to-end citation UX.
- `docs/THESIS_HANDOFF_EXTERNAL_WIDGET.md` — the public embeddable chatbot widget (routing↔citation
  fusion, per-bot config, CORS, crawler, rich content, premium UX).
- `docs/THESIS_EXTERNAL_WIDGET_COMPLETE.md` — the full widget deep-dive (AutoPilot pipeline, admin
  console, document upload, eager rehydration, security, verification, limitations) for the thesis.
- `docs/layer3/runbook.md` + `docs/layer3/*.md` — L3 operational runbook and design-choice rationale
  (encoder bake-off, high-risk classifier, data sources, aggregate priors).
- `docs/layers/LAYER_*_REPORT.md` / `LAYER_*_RESEARCH.md` — per-layer deep dives.
- `scripts/dashboard.py` — Streamlit observability dashboard (routing-source mix, drift scan).
