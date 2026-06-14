/* ============================================================================
   Dashboard registry — the single source of truth for navigation, the landing
   grid, and per-page headers. Pure data (no component imports) so it can be
   consumed anywhere without pulling the whole route tree.

   `status`:  'ready'  → built, routes to its component
              'soon'   → routes to the on-brand Placeholder

   Flip an item to 'ready' (and register its component in pages.js) as each
   dashboard lands.
   ========================================================================== */

export const systems = [
  {
    id: 'smart-routing',
    theme: 'theme-routing',
    title: 'Smart Routing System',
    short: 'Smart Routing',
    tagline:
      'Routes every query to the cheapest model that can answer it correctly — benchmark-grounded, zero per-query LLM calls.',
    accent1: '#6366f1',
    accent2: '#22d3ee',
    items: [
      { slug: 'overview', badge: '∑', nav: 'Pipeline Overview', title: 'Pipeline Overview', tagline: 'The whole 9-layer routing brain, end to end', status: 'ready', kind: 'overview' },
      { slug: 'layer-0', badge: 'L0', nav: 'Layer 0 · Fast Path', title: 'Fast Path Bypass', tagline: 'Sub-millisecond bypass for trivial queries', status: 'ready' },
      { slug: 'layer-1', badge: 'L1', nav: 'Layer 1 · Modality Gate', title: 'Modality Gate', tagline: 'Security + modality / language / code signal extraction', status: 'ready' },
      { slug: 'layer-1-5', badge: 'L1½', nav: 'Layer 1.5 · Input Signals', title: 'Input Signals', tagline: 'Continuous difficulty signal extraction', status: 'ready' },
      { slug: 'layer-2', badge: 'L2', nav: 'Layer 2 · Semantic Memory', title: 'Semantic Memory', tagline: 'Outcome-aware cache with 6 correctness guards', status: 'ready' },
      { slug: 'layer-3', badge: 'L3', nav: 'Layer 3 · kNN Router', title: 'Benchmark-Grounded kNN Router', tagline: 'The brain — predicts per-model quality from benchmark neighbours', status: 'ready', flagship: true },
      { slug: 'layer-6', badge: 'L6', nav: 'Layer 6 · Test-Time Compute', title: 'Test-Time Compute', tagline: 'Spend more compute only where uncertainty warrants it', status: 'ready' },
      { slug: 'layer-7', badge: 'L7', nav: 'Layer 7 · Quality Eval', title: 'Quality Evaluation', tagline: 'Cost-free correctness signal — no per-query judge LLM', status: 'ready' },
      { slug: 'layer-8', badge: 'L8', nav: 'Layer 8 · Escalation', title: 'Escalation Ladder', tagline: 'Climb to a stronger model only when quality fails', status: 'ready' },
      { slug: 'layer-9', badge: 'L9', nav: 'Layer 9 · Telemetry + Drift', title: 'Telemetry & Drift', tagline: 'Observability + KL-divergence drift detection', status: 'ready' },
    ],
  },
  {
    id: 'rag',
    theme: 'theme-rag',
    title: 'RAG + Citation',
    short: 'RAG + Citation',
    tagline:
      'Answers grounded strictly in retrieved evidence, with verifiable per-claim citations down to the highlighted source span.',
    accent1: '#10b981',
    accent2: '#2dd4bf',
    items: [
      { slug: 'overview', badge: '∑', nav: 'Pipeline Overview', title: 'Pipeline Overview', tagline: 'Ingestion + query-time, end to end', status: 'ready', kind: 'overview' },
      { slug: 'parsing', badge: '1', nav: 'Document Parsing', title: 'Document Parsing & Ingestion', tagline: 'Seven formats → clean, page-bounded text', status: 'ready' },
      { slug: 'chunking', badge: '2', nav: 'Structure-Aware Chunking', title: 'Structure-Aware Chunking', tagline: 'Chunks that respect articles, sections & pages', status: 'ready' },
      { slug: 'embedding', badge: '3', nav: 'Embedding & Indexing', title: 'Resilient Embedding & Indexing', tagline: 'Primary embedding with a never-fail fallback', status: 'ready' },
      { slug: 'retrieval', badge: '4', nav: 'Query-Aware Retrieval', title: 'Query-Aware Retrieval', tagline: 'Hybrid search + five intent-driven strategies', status: 'ready' },
      { slug: 'reranking', badge: '5', nav: 'Domain-Aware Reranking', title: 'Domain-Aware Reranking', tagline: 'Lift the right evidence to the top', status: 'ready' },
      { slug: 'assembly', badge: '6', nav: 'Context Assembly', title: 'Grounded Context Assembly', tagline: 'Citation slots, page proofs & evidence groups', status: 'soon' },
      { slug: 'generation', badge: '7', nav: 'Constrained Generation', title: 'Evidence-Constrained Generation', tagline: 'Answer only from the cited sources', status: 'soon' },
      { slug: 'verification', badge: '8', nav: 'Claim Verification', title: 'Claim Verification', tagline: 'Every assertion checked against its source — or refused', status: 'soon' },
      { slug: 'citation', badge: '9', nav: 'Citation & Highlighting', title: 'Citation Packaging & Highlighting', tagline: 'Exact highlighted spans on the rendered page', status: 'soon', flagship: true },
    ],
  },
]

/** Build the canonical hash route for a (systemId, slug). */
export function routeFor(systemId, slug) {
  return `#/${systemId}/${slug}`
}

/** Flat lookup: path like "/smart-routing/layer-0" → { system, item }. */
export function resolve(path) {
  const clean = (path || '').replace(/^#/, '').replace(/^\//, '')
  const [systemId, slug] = clean.split('/')
  const system = systems.find((s) => s.id === systemId)
  if (!system) return null
  const item = system.items.find((i) => i.slug === slug)
  if (!item) return null
  return { system, item }
}

/** Ordered flat list of every page (for prev/next navigation). */
export const flatPages = systems.flatMap((s) =>
  s.items.map((i) => ({ systemId: s.id, slug: i.slug, route: routeFor(s.id, i.slug), title: i.title }))
)
