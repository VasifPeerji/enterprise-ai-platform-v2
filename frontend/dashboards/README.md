# Layer Dashboards

Presentation-grade, interactive dashboards that open up **every layer/step** of the two core
systems in this platform:

- **Smart Routing System** — the 9-layer routing brain (L0 → L1 → L1.5 → L2 → L3 → L6 → L7 → L8 → L9)
- **RAG + Citation** — ingestion + query-time, parse → chunk → embed → retrieve → rerank → assemble → generate → verify → cite

Each dashboard answers three questions for its layer: **what it does**, **why it's strong**, and
**how it shapes the final output** — with a live input → output tester, the real configuration
values, charts, and a signature visualization.

## Why it's a separate app

This is intentionally a standalone Svelte app, **completely separate from `frontend/v07`** (the
product chat UI). It must never be coupled to it. The two apps share nothing and run on different
ports.

## Faithful simulations, no backend required

For reliability during live presentations, every interactive demo runs a **faithful client-side
simulation** of the real layer logic, seeded with the actual thresholds and config values from the
Python source (`src/layer0_model_infra/routing/…` and `src/layer1_intelligence/…`). There is **no
dependency** on a running backend, Qdrant, the GPU, or API keys — it just works.

Where a step's deepest behaviour relies on a neural model (e.g. an ML embedding tier), the
simulation reproduces the deterministic tiers exactly and clearly labels the ML tier as
illustrative.

## Run it

```bash
cd frontend/dashboards
npm install
npm run dev        # http://localhost:5273
```

`npm run build` produces a static bundle in `dist/` that can be served anywhere.

## Structure

```
src/
  main.js                 app entry
  App.svelte              layout: sidebar + routed content
  lib/
    registry.js           single source of truth for nav + page metadata
    router.js             tiny hash router
    pages.js              route → component map (grows as dashboards land)
    sim/                  faithful client-side simulations of each layer
  components/
    Sidebar.svelte
    ui/                   shared kit (Card, Pill, Stat, PageHeader, …)
  routes/
    Home.svelte           landing grid
    Placeholder.svelte    on-brand "coming soon" for unbuilt pages
    smart-routing/        one component per routing layer
    rag/                  one component per RAG step
  styles/                 tokens.css + base.css
```

Adding a dashboard: build its component under `routes/<system>/`, register it in `pages.js`, and
flip the item's `status` to `'ready'` in `registry.js`.
