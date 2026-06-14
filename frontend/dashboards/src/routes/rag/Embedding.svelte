<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'

  let health = $state('healthy') // healthy | flaky | down

  const active = $derived(health === 'healthy' ? 'primary' : health === 'flaky' ? 'retry' : 'fallback')
  const providers = [
    { key: 'primary', name: 'GatewayEmbeddingProvider', sub: 'qwen3-embedding · 1024-dim · full semantic', tier: 'primary' },
    { key: 'retry', name: 'ResilientEmbeddingProvider', sub: 'retry + circuit breaker on transient failures', tier: 'wrapper' },
    { key: 'fallback', name: 'DeterministicEmbeddingProvider', sub: 'hash-based stable vectors · degraded but never fails', tier: 'fallback' },
  ]
  const note = $derived({
    healthy: 'Primary embedding model is up — full-quality semantic vectors.',
    flaky: 'Transient failures — the resilient wrapper retries and succeeds. No user impact.',
    down: 'Primary is down and the circuit breaker has opened — retrieval degrades to deterministic vectors but the request never fails.',
  }[health])
</script>

<PageHeader
  badge="3"
  eyebrow="RAG + Citation · Step 3"
  title="Resilient Embedding & Indexing"
  tagline="Turns each chunk into a vector and writes it to a per-tenant Qdrant collection — wrapped in a resilience cascade so that even when the embedding model degrades, retrieval keeps working rather than failing the user."
  stats={[
    { value: '1024-dim', label: 'primary vectors', tone: 'accent' },
    { value: 'circuit-broken', label: 'on failure' },
    { value: 'never fails', label: 'the request' },
    { value: 'per-tenant', label: 'collections' },
  ]}
/>

<Card eyebrow="Live resilience cascade" title="Break the embedding model — watch it degrade, not die" glow>
  <div class="health">
    <span class="h-l">primary model:</span>
    <button class:on={health === 'healthy'} onclick={() => (health = 'healthy')}>healthy</button>
    <button class:on={health === 'flaky'} onclick={() => (health = 'flaky')}>flaky</button>
    <button class:on={health === 'down'} onclick={() => (health = 'down')}>down</button>
  </div>

  <div class="cascade">
    {#each providers as p, i}
      <div class="prov {active === p.key ? 'active' : ''} {health === 'down' && p.key === 'primary' ? 'failed' : ''}">
        <div class="prov-rail">
          <span class="prov-node">
            {#if health === 'down' && p.key === 'primary'}✕{:else if active === p.key}●{:else}○{/if}
          </span>
        </div>
        <div class="prov-body">
          <div class="prov-h">
            <span class="prov-name">{p.name}</span>
            <Pill tone={active === p.key ? 'accent' : 'neutral'} mono>{p.tier}</Pill>
            {#if active === p.key}<Pill tone="green" dot>serving</Pill>{/if}
          </div>
          <span class="prov-sub">{p.sub}</span>
        </div>
      </div>
    {/each}
  </div>
  <div class="cnote {health}">{note}</div>
</Card>

<div class="two">
  <Card eyebrow="The footgun it guards" title="Dimension mismatch">
    <p class="body2">
      The config once declared <code>EMBEDDING_DIMENSION=1536</code> while the real model emits
      <strong>1024</strong>. A mismatched vector silently corrupts similarity search. The index guards
      against it: on a dimension mismatch it <strong>drops the semantic component</strong> rather than
      comparing incompatible vectors.
    </p>
    <div class="dimrow">
      <div class="dim bad"><span>config said</span><b>1536</b></div>
      <span class="dim-x">≠</span>
      <div class="dim ok"><span>model emits</span><b>1024</b></div>
      <span class="dim-arrow">→</span>
      <div class="dim guard"><span>guard</span><b>drop semantic</b></div>
    </div>
  </Card>

  <Card eyebrow="Indexing" title="Per-tenant by construction">
    <div class="idx">
      <div class="idx-row"><b>collection</b><code>tenant-default-coll-xyz</code></div>
      <div class="idx-row"><b>payload</b><code>{'{ source_uri, page, article, content_type }'}</code></div>
      <div class="idx-row"><b>tenant filter</b><code>hard constraint on every query</code></div>
    </div>
    <p class="body2 mt">Collection IDs are tenant-scoped, so cross-tenant access is impossible by construction — one customer's documents can never surface in another's answers.</p>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="Graceful degradation, never a dead end">
  <p class="body">
    Embedding is the one step that depends on an external model, so it's the one most likely to wobble.
    Wrapping it in retry → circuit-breaker → deterministic fallback means a provider hiccup becomes a
    quiet quality dip instead of a failed request. The answer might be slightly less well-retrieved for
    a moment, but the user always gets one — and the tenant isolation guarantees it's only ever built
    from <strong>their</strong> evidence.
  </p>
</Card>

<PrevNext current="/rag/embedding" />

<style>
  .health { display: flex; align-items: center; gap: 8px; margin-bottom: 18px; }
  .h-l { font-size: 12.5px; color: var(--text-3); margin-right: 4px; }
  .health button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 7px 14px; font-size: 12.5px; transition: all 0.12s; }
  .health button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .cascade { display: flex; flex-direction: column; }
  .prov { display: flex; gap: 16px; opacity: 0.55; transition: opacity 0.2s; }
  .prov.active { opacity: 1; }
  .prov-rail { position: relative; width: 32px; flex-shrink: 0; display: flex; justify-content: center; }
  .prov-rail::before { content: ''; position: absolute; top: 0; bottom: 0; left: 50%; width: 2px; transform: translateX(-50%); background: var(--border-1); }
  .prov:first-child .prov-rail::before { top: 16px; }
  .prov:last-child .prov-rail::before { bottom: calc(100% - 16px); }
  .prov-node { position: relative; z-index: 1; margin-top: 4px; width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; font-size: 13px; background: var(--surface-3); border: 1px solid var(--border-2); color: var(--text-3); }
  .prov.active .prov-node { background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); color: var(--text-on-accent); border-color: transparent; }
  .prov.failed .prov-node { background: var(--red); color: #fff; border-color: transparent; }
  .prov-body { padding: 5px 0 16px; }
  .prov-h { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
  .prov-name { font-size: 14px; font-weight: 650; color: var(--text-1); }
  .prov-sub { font-size: 12px; color: var(--text-3); }
  .cnote { margin-top: 6px; padding: 12px 14px; border-radius: var(--r-md); font-size: 13px; line-height: 1.5; border: 1px solid var(--border-2); background: var(--surface-2); color: var(--text-2); }
  .cnote.healthy { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }
  .cnote.down { background: var(--amber-soft); border-color: color-mix(in srgb, var(--amber) 35%, transparent); color: var(--text-1); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .body2 { font-size: 13px; color: var(--text-2); line-height: 1.6; }
  .body2.mt { margin-top: 12px; }
  .body2 strong { color: var(--text-1); }
  code { font-family: var(--font-mono); font-size: 0.88em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 6px; border-radius: 5px; }
  .dimrow { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  .dim { display: flex; flex-direction: column; gap: 2px; padding: 9px 13px; border-radius: var(--r-sm); background: var(--surface-2); border: 1px solid var(--border-1); }
  .dim span { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }
  .dim b { font-family: var(--font-mono); font-size: 15px; color: var(--text-1); }
  .dim.bad b { color: var(--red); }
  .dim.ok b { color: var(--green); }
  .dim.guard b { color: var(--accent-2); font-size: 13px; }
  .dim-x, .dim-arrow { color: var(--text-3); }

  .idx { display: flex; flex-direction: column; gap: 9px; }
  .idx-row { display: flex; align-items: center; gap: 10px; }
  .idx-row b { width: 92px; flex-shrink: 0; font-size: 12px; color: var(--text-3); font-family: var(--font-mono); }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
</style>
