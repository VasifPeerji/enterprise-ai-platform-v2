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
  harmless).
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

`frontend/v07/` is a full Svelte 5 + Vite 8 single-page app (the showcase UI). **It is dev-served by
Vite and is NOT statically mounted by FastAPI** — run it separately; Vite proxies API calls to
`:8000`.

- Dev: `cd frontend/v07 && npm install && npm run dev`.
- `src/lib/api.js` is the backend-contract bridge **and** carries real client-side logic: the typed
  content-block transformer, **Chart.js auto-detection from markdown tables / prose**, the verbose
  `(Citation N, …)` → clean `[N]` superscript rewrite, and mammoth.js `.docx`→text before upload.
- **Web search is entirely client-side** (`searchWeb`: Tavily → SearXNG → DuckDuckGo → Wikipedia
  fallback); results are injected into the prompt before it is sent, so the backend never sees the
  search step. There is no server-side web-search route — don't go looking for one.
- `src/lib/stores.js` holds the state (conversations, simulated wallet, streaming, hash routing
  `#/rag/<collection>`). Authoritative doc: `docs/THESIS_HANDOFF_v07.md`.

## The external chatbot widget (public-facing, embeddable)

Distinct from V07: an **embeddable widget** companies drop on their *own* public site via one
`<script>` tag. It reuses the smart router + grounded-RAG stack but is a separate, public,
cross-origin surface. Code lives in `src/layer4_platform/` + `src/interfaces/http/routes/widget.py`
(public), `admin_bots.py` / `admin_console.py` (admin control plane), `middleware/widget_cors.py`,
`src/layer3_domain/web_crawler.py`. Authoritative doc: `docs/THESIS_HANDOFF_EXTERNAL_WIDGET.md`.
Tests: `tests/widget/` (kept **torch-free** — registry / rate-limit / crawler-via-httpx-MockTransport
/ CORS shim; widget JS is verified out-of-band with jsdom, not in the Python suite).

- **A company = tenant + grounded collection + a `BotConfig`** (`layer4_platform/bot_registry.py`).
  `PublicBotConfig` is the **only** shape the browser receives and is a safe projection that
  **never carries `tenant_id` / `collection_id` / `allowed_origins`** — a leaked `bot_id` (it sits in
  the page source) yields branding only. Configs persist as JSON under `.runtime/bot_configs/`
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
  (CORS is browser-side, bypassable), plus per-IP/per-bot rate limits (`widget_rate_limit.py`).
- **The loader (`WIDGET_LOADER_JS` in widget.py)** is vanilla JS in a Shadow DOM, themed entirely from
  `--bot-*` CSS variables fed by the config (re-skin = config edit, no code). **Rich answer content
  (HTML/CSS/JS) renders in a `sandbox`ed iframe with NO `allow-same-origin`** so model/KB-supplied
  scripts can't reach the host page — never render model HTML straight into the host DOM. The loader
  source must **never contain the literal `</script>`** (write `'</scr' + 'ipt>'`) so it can embed in
  inline scripts / jsdom tests.
- **The crawler** (`web_crawler.py`, endpoint `POST /grounded-documents/collections/{id}/crawl`) is
  same-domain, robots-aware, `httpx` + stdlib `html.parser`, **static/SSR only** (runs no JS — SPAs
  return thin pages, reported in warnings). It feeds the **same** `ingest_assets` path as uploads.
- **Config:** env-level toggles/caps in `Settings` (`WIDGET_PUBLIC_ENABLED`, `WIDGET_RATE_*`,
  `WIDGET_CRAWLER_MAX_*`). Endpoints: public `/widget/{id}/config|chat|chat/stream|suggest`,
  `/widget/loader.js`, `/widget/preview`; admin `/admin/bots/*` (+ `/debug-chat`), `/admin/console`.

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
- `docs/layer3/runbook.md` + `docs/layer3/*.md` — L3 operational runbook and design-choice rationale
  (encoder bake-off, high-risk classifier, data sources, aggregate priors).
- `docs/layers/LAYER_*_REPORT.md` / `LAYER_*_RESEARCH.md` — per-layer deep dives.
- `scripts/dashboard.py` — Streamlit observability dashboard (routing-source mix, drift scan).
