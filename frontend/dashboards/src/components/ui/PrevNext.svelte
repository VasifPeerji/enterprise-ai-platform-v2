<script>
  import { flatPages } from '../../lib/registry.js'
  import { navigate } from '../../lib/router.js'

  let { current } = $props() // route string like "/smart-routing/layer-0"

  const idx = $derived(flatPages.findIndex((p) => p.route.replace(/^#/, '') === current))
  const prev = $derived(idx > 0 ? flatPages[idx - 1] : null)
  const next = $derived(idx >= 0 && idx < flatPages.length - 1 ? flatPages[idx + 1] : null)
</script>

<nav class="pn">
  {#if prev}
    <button class="pn-btn" onclick={() => navigate(prev.route)}>
      <span class="dir">← Previous</span>
      <span class="ttl">{prev.title}</span>
    </button>
  {:else}<span></span>{/if}
  {#if next}
    <button class="pn-btn right" onclick={() => navigate(next.route)}>
      <span class="dir">Next →</span>
      <span class="ttl">{next.title}</span>
    </button>
  {/if}
</nav>

<style>
  .pn {
    display: flex;
    justify-content: space-between;
    gap: 14px;
    margin-top: 8px;
  }
  .pn-btn {
    display: flex;
    flex-direction: column;
    gap: 3px;
    text-align: left;
    background: var(--surface-2);
    border: 1px solid var(--border-1);
    border-radius: var(--r-md);
    padding: 13px 18px;
    min-width: 200px;
    transition: background 0.15s ease, border-color 0.15s ease;
  }
  .pn-btn:hover { background: var(--surface-hover); border-color: var(--accent-line); }
  .pn-btn.right { text-align: right; }
  .dir { font-size: 11.5px; color: var(--text-3); font-weight: 600; }
  .ttl { font-size: 14px; color: var(--text-1); font-weight: 600; }
</style>
