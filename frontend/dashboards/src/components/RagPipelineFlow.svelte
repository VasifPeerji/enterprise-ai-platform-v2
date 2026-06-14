<script>
  import { routeFor } from '../lib/registry.js'
  import { navigate } from '../lib/router.js'

  // Two tracks that meet at the per-tenant vector store.
  const ingestion = [
    { slug: 'parsing', n: '1', label: 'Parse', sub: '7 formats → pages' },
    { slug: 'chunking', n: '2', label: 'Chunk', sub: 'structure-aware' },
    { slug: 'embedding', n: '3', label: 'Embed + Index', sub: 'resilient → Qdrant' },
  ]
  const query = [
    { slug: 'retrieval', n: '4', label: 'Retrieve', sub: 'hybrid + strategies' },
    { slug: 'reranking', n: '5', label: 'Rerank', sub: 'domain-aware' },
    { slug: 'assembly', n: '6', label: 'Assemble', sub: 'proofs + slots' },
    { slug: 'generation', n: '7', label: 'Generate', sub: 'evidence-only' },
    { slug: 'verification', n: '8', label: 'Verify', sub: 'claim-by-claim' },
    { slug: 'citation', n: '9', label: 'Cite', sub: 'highlight spans' },
  ]
</script>

<div class="flow">
  <div class="track">
    <div class="track-label">Ingestion · once per document</div>
    <div class="nodes">
      <div class="endcap">📄 Document</div>
      <span class="arr">→</span>
      {#each ingestion as s, i}
        <button class="node" onclick={() => navigate(routeFor('rag', s.slug))}>
          <span class="n">{s.n}</span>
          <span class="nl">{s.label}</span>
          <span class="ns">{s.sub}</span>
        </button>
        {#if i < ingestion.length - 1}<span class="arr">→</span>{/if}
      {/each}
    </div>
  </div>

  <div class="store-row">
    <span class="store-arr">↓ write</span>
    <div class="store">
      <span class="store-icon">▤</span>
      <div><b>Per-tenant vector store</b><span>Qdrant collection + document metadata</span></div>
    </div>
    <span class="store-arr">read ↓</span>
  </div>

  <div class="track">
    <div class="track-label">Query-time · every question</div>
    <div class="nodes">
      <div class="endcap q">❓ Query</div>
      <span class="arr">→</span>
      {#each query as s, i}
        <button class="node" onclick={() => navigate(routeFor('rag', s.slug))}>
          <span class="n">{s.n}</span>
          <span class="nl">{s.label}</span>
          <span class="ns">{s.sub}</span>
        </button>
        {#if i < query.length - 1}<span class="arr">→</span>{/if}
      {/each}
      <span class="arr">→</span>
      <div class="endcap ans">✓ Cited answer</div>
    </div>
  </div>
</div>

<style>
  .flow { display: flex; flex-direction: column; gap: 14px; }
  .track-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .nodes { display: flex; align-items: stretch; gap: 6px; flex-wrap: wrap; }
  .node { display: flex; flex-direction: column; gap: 2px; text-align: left; background: linear-gradient(180deg, var(--surface-2), var(--surface-1)); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 10px 13px; min-width: 108px; transition: all 0.13s ease; }
  .node:hover { border-color: var(--accent-line); transform: translateY(-2px); box-shadow: 0 10px 24px -12px var(--accent-1); }
  .n { font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); width: 20px; height: 20px; display: grid; place-items: center; border-radius: 5px; }
  .nl { font-size: 13px; font-weight: 650; color: var(--text-1); margin-top: 3px; }
  .ns { font-size: 11px; color: var(--text-3); }
  .arr { display: grid; place-items: center; color: var(--text-3); font-size: 14px; }
  .endcap { display: grid; place-items: center; padding: 10px 14px; border-radius: var(--r-md); font-size: 13px; font-weight: 600; background: var(--surface-3); border: 1px solid var(--border-2); color: var(--text-2); }
  .endcap.q { border-color: var(--accent-line); color: var(--accent-2); }
  .endcap.ans { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .store-row { display: flex; align-items: center; gap: 16px; justify-content: center; }
  .store-arr { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); }
  .store { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-radius: var(--r-md); background: radial-gradient(circle at 30% 30%, var(--accent-soft), transparent), var(--surface-2); border: 1px solid var(--accent-line); }
  .store-icon { font-size: 22px; color: var(--accent-2); }
  .store b { font-size: 13.5px; color: var(--text-1); }
  .store div { display: flex; flex-direction: column; }
  .store span { font-size: 11.5px; color: var(--text-3); }
</style>
