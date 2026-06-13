<script>
  import { onMount } from 'svelte';
  import {
    compareState,
    closeCompare,
    sessionId,
    walletBalance,
    recordTransaction,
  } from '../lib/stores.js';
  import { sendMessage, getModels } from '../lib/api.js';
  import MessageRenderer from './MessageRenderer.svelte';

  // The Smart Routing anchor — always the left column's default.
  const SMART = { modelId: 'smart_routing', name: 'Smart Routing', tier: 'smart' };

  // Two columns: each runs the same prompt on its own model. `status` is
  // 'idle' | 'loading' | 'done' | 'error'.
  let cols = $state([blankCol(SMART), blankCol(null)]);

  let models = $state([]);
  let modelsLoading = $state(false);
  let modelsError = $state(false);

  // Per-column AbortControllers, held in a plain (non-reactive) array so the
  // setup effect never has to read `cols` — keeping it free of self-deps.
  let controllers = [null, null];
  // Guards against stale async writes: every re-init bumps `runSeq`, and a
  // resolving request whose captured seq is stale just bails.
  let runSeq = 0;
  // Tracks which prompt the current columns were built for, so re-opening with
  // the same prompt doesn't needlessly re-run (and a new prompt does).
  let setupKey = null;

  function blankCol(sel) {
    return { sel, status: 'idle', result: null, error: null, menuOpen: false };
  }

  // ── Lazy model load (shared by both column pickers) ───────
  async function ensureModels() {
    if (models.length || modelsLoading) return;
    modelsLoading = true;
    modelsError = false;
    try {
      models = await getModels();
    } catch {
      modelsError = true;
    } finally {
      modelsLoading = false;
    }
  }

  // Pick the right column's default: match the seed answer's model by name if
  // we can, otherwise contrast Smart Routing against the priciest premium model
  // — the most vivid "look what routing saves you" story.
  function resolveSeedModel(list, seed) {
    if (seed?.name) {
      const m = list.find((x) => x.display_name === seed.name);
      if (m) return { modelId: m.model_id, name: m.display_name, tier: m.tier, provider: m.provider };
    }
    const premium = list.find((x) => x.tier === 'premium') || list[0];
    if (premium) {
      return { modelId: premium.model_id, name: premium.display_name, tier: premium.tier, provider: premium.provider };
    }
    return null;
  }

  // ── Run a single column ───────────────────────────────────
  // `sel` is passed in (never read from `cols`) so this is safe to call from
  // the setup effect without creating a self-referential dependency.
  async function runColumn(i, sel, seq) {
    if (!sel) return;
    // Abort any prior in-flight request for this column.
    controllers[i]?.abort();
    const controller = new AbortController();
    controllers[i] = controller;
    cols[i] = { ...cols[i], sel, status: 'loading', error: null, result: null };

    const isSmart = sel.modelId === 'smart_routing';
    try {
      const res = await sendMessage($compareState.prompt, {
        modelId: isSmart ? 'smart_routing' : sel.modelId,
        sessionId: $sessionId,
        signal: controller.signal,
      });
      if (seq !== runSeq) return; // a newer run superseded us
      // Forcing a model bills that model's profile but the backend still reports
      // the router's own pick in model_used — surface the chosen model instead,
      // matching the regenerate-with-model convention elsewhere.
      if (!isSmart) {
        res.model = { ...res.model, name: sel.name, tier: sel.tier, provider: sel.provider };
        res.routing = { ...res.routing, mode: 'manual' };
      }
      if (res.cost?.balanceUsd !== null && res.cost?.balanceUsd !== undefined) {
        walletBalance.set(res.cost.balanceUsd);
      }
      if (res.cost?.chargedUsd) {
        recordTransaction({ amount: res.cost.chargedUsd, modelName: res.model?.name || sel.name, mode: 'compare' });
      }
      cols[i] = { ...cols[i], status: 'done', result: res };
    } catch (e) {
      if (seq !== runSeq) return;
      if (e.name === 'AbortError') return; // user closed / changed model
      cols[i] = { ...cols[i], status: 'error', error: humanize(e?.message) };
    }
  }

  function humanize(msg) {
    if (!msg) return 'Something went wrong.';
    if (/fetch|network|failed to fetch/i.test(msg)) return 'Could not reach the backend (is it running on :8000?).';
    return msg;
  }

  // ── Column model selection ────────────────────────────────
  function pickModel(i, sel) {
    cols[i] = { ...cols[i], menuOpen: false };
    runColumn(i, sel, runSeq);
  }

  function toggleMenu(i) {
    cols[i] = { ...cols[i], menuOpen: !cols[i].menuOpen };
    if (cols[i].menuOpen) ensureModels();
  }

  function rerun(i) {
    runColumn(i, cols[i].sel, runSeq);
  }

  // ── Init / teardown driven by the store ───────────────────
  // Only reads the store + a plain guard, and only WRITES `cols` — the actual
  // runs are deferred to a microtask so their cols/network reads never become
  // dependencies of this effect.
  $effect(() => {
    const s = $compareState;
    if (s.open && s.prompt && setupKey !== s.prompt) {
      setupKey = s.prompt;
      runSeq += 1;
      const seq = runSeq;
      const seed = s.seed;
      cols = [blankCol(SMART), blankCol(null)];
      queueMicrotask(() => {
        if (seq !== runSeq) return;
        runColumn(0, SMART, seq);
        ensureModels().then(() => {
          if (seq !== runSeq) return;
          const right = resolveSeedModel(models, seed);
          if (right) runColumn(1, right, seq);
        });
      });
    } else if (!s.open && setupKey !== null) {
      // Closed — abort anything in flight and reset for next time.
      setupKey = null;
      runSeq += 1;
      controllers.forEach((c) => c?.abort());
      controllers = [null, null];
    }
  });

  function close() {
    closeCompare();
  }

  function onKeydown(e) {
    // The component stays mounted, so only swallow Escape while actually open —
    // otherwise we'd hijack Escape from every other overlay.
    if (e.key === 'Escape' && $compareState.open) {
      e.preventDefault();
      close();
    }
  }

  function clickOutside(node, cb) {
    function handle(e) {
      if (node && !node.contains(e.target)) cb();
    }
    document.addEventListener('mousedown', handle, true);
    return { destroy() { document.removeEventListener('mousedown', handle, true); } };
  }

  // ── Tier presentation (shared with the model menu) ────────
  function tierColor(tier) {
    if (tier === 'smart') return 'var(--accent-primary)';
    if (tier === 'premium') return 'var(--tier-premium)';
    if (tier === 'moderate') return 'var(--tier-moderate)';
    if (tier === 'cheap') return 'var(--tier-cheap)';
    return 'var(--text-muted)';
  }
  const tierOrder = ['premium', 'moderate', 'cheap'];
  const tierLabel = { premium: 'Premium', moderate: 'Moderate', cheap: 'Budget' };
  let groupedModels = $derived.by(() => {
    const g = {};
    for (const m of models) (g[m.tier] ||= []).push(m);
    return g;
  });

  // ── Cost / latency formatting + the savings verdict ───────
  function fmtCost(v) {
    if (v === null || v === undefined) return '—';
    if (v === 0) return 'Free';
    if (v < 0.0001) return '<$0.0001';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    return `$${v.toFixed(2)}`;
  }
  function fmtLatency(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }

  let bothDone = $derived(cols[0]?.status === 'done' && cols[1]?.status === 'done');

  // A plain-language verdict comparing the two finished answers on cost (and
  // latency as a secondary note). Only shown once both columns resolve.
  let verdict = $derived.by(() => {
    if (!bothDone) return null;
    const a = cols[0].result, b = cols[1].result;
    const ca = a?.cost?.chargedUsd, cb = b?.cost?.chargedUsd;
    const na = a?.model?.name || 'Left', nb = b?.model?.name || 'Right';
    const la = a?.routing?.latencyMs, lb = b?.routing?.latencyMs;
    if (!Number.isFinite(ca) || !Number.isFinite(cb)) return null;

    let cheaperName = null, costLine = '';
    if (ca === cb) {
      costLine = 'Both cost the same per answer';
    } else {
      const cheaperLeft = ca < cb;
      cheaperName = cheaperLeft ? na : nb;
      const lo = Math.min(ca, cb), hi = Math.max(ca, cb);
      if (lo === 0) {
        costLine = `${cheaperName} answered free`;
      } else {
        const pct = Math.round(((hi - lo) / hi) * 100);
        costLine = `${cheaperName} cost ${pct}% less`;
      }
    }

    let latLine = '';
    if (Number.isFinite(la) && Number.isFinite(lb) && la !== lb) {
      const fasterName = la < lb ? na : nb;
      const delta = Math.abs(la - lb);
      latLine = `${fasterName} was ${fmtLatency(delta)} faster`;
    }
    return { cheaperName, costLine, latLine };
  });

  onMount(() => {
    window.addEventListener('keydown', onKeydown);
    return () => window.removeEventListener('keydown', onKeydown);
  });
</script>

{#if $compareState.open}
  <div class="cmp-overlay" role="dialog" aria-modal="true" aria-label="Compare models">
    <div class="cmp-panel" use:clickOutside={close}>
      <!-- ── Header ───────────────────────────── -->
      <div class="cmp-header">
        <div class="cmp-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="7" height="16" rx="1.5"/>
            <rect x="14" y="4" width="7" height="16" rx="1.5"/>
          </svg>
          <span>Compare models</span>
        </div>
        <button class="cmp-close" onclick={close} aria-label="Close compare">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div class="cmp-prompt" title={$compareState.prompt}>
        <span class="cmp-prompt-label">Prompt</span>
        <span class="cmp-prompt-text">{$compareState.prompt}</span>
      </div>

      <!-- ── Verdict banner ───────────────────── -->
      {#if verdict}
        <div class="cmp-verdict">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 6L9 17l-5-5"/>
          </svg>
          <span class="cmp-verdict-cost">{verdict.costLine}</span>
          {#if verdict.latLine}<span class="cmp-verdict-sep">·</span><span class="cmp-verdict-lat">{verdict.latLine}</span>{/if}
        </div>
      {/if}

      <!-- ── Two columns ──────────────────────── -->
      <div class="cmp-cols">
        {#each cols as col, i}
          <div class="cmp-col">
            <!-- Column head: model picker + stats -->
            <div class="cmp-col-head">
              <div class="cmp-picker-wrap" use:clickOutside={() => (cols[i] = { ...cols[i], menuOpen: false })}>
                <button class="cmp-picker" onclick={() => toggleMenu(i)} aria-haspopup="menu" aria-expanded={col.menuOpen}>
                  <span class="cmp-dot" style="background: {tierColor(col.sel?.tier)}"></span>
                  <span class="cmp-picker-name">{col.sel?.name || 'Choose a model'}</span>
                  <svg class="cmp-caret" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M6 9l6 6 6-6"/>
                  </svg>
                </button>
                {#if col.menuOpen}
                  <div class="cmp-menu" role="menu">
                    <button class="cmp-mi" role="menuitem" onclick={() => pickModel(i, SMART)}>
                      <span class="cmp-dot" style="background: var(--accent-primary); box-shadow: 0 0 6px var(--accent-glow)"></span>
                      <span class="cmp-mi-name">Smart Routing</span>
                    </button>
                    {#if modelsLoading}
                      <div class="cmp-note">Loading models…</div>
                    {:else if modelsError}
                      <div class="cmp-note">Couldn’t load models</div>
                    {:else}
                      {#each tierOrder as tier}
                        {#if groupedModels[tier]?.length}
                          <div class="cmp-tier">{tierLabel[tier]}</div>
                          {#each groupedModels[tier] as m}
                            <button class="cmp-mi" role="menuitem" onclick={() => pickModel(i, { modelId: m.model_id, name: m.display_name, tier: m.tier, provider: m.provider })}>
                              <span class="cmp-dot" style="background: {tierColor(m.tier)}"></span>
                              <span class="cmp-mi-name">{m.display_name}</span>
                            </button>
                          {/each}
                        {/if}
                      {/each}
                    {/if}
                  </div>
                {/if}
              </div>

              <div class="cmp-stats">
                {#if col.status === 'done' && col.result}
                  <span class="cmp-stat" title="End-to-end latency">{fmtLatency(col.result.routing?.latencyMs)}</span>
                  <span class="cmp-stat cmp-stat-cost"
                        class:cheaper={verdict && verdict.cheaperName === col.result.model?.name}
                        title="Simulated cost for this answer">{fmtCost(col.result.cost?.chargedUsd)}</span>
                  <button class="cmp-rerun" onclick={() => rerun(i)} title="Run again" aria-label="Run again">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>
                      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>
                    </svg>
                  </button>
                {/if}
              </div>
            </div>

            <!-- Column body: the answer -->
            <div class="cmp-body">
              {#if col.status === 'loading'}
                <div class="cmp-loading">
                  <span class="cmp-spinner"></span>
                  <span>Generating…</span>
                </div>
              {:else if col.status === 'error'}
                <div class="cmp-error">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>
                  </svg>
                  <span>{col.error}</span>
                  <button class="cmp-retry" onclick={() => rerun(i)}>Retry</button>
                </div>
              {:else if col.status === 'done' && col.result}
                <MessageRenderer content={col.result.content || []} role="assistant" />
              {:else}
                <div class="cmp-loading"><span>Pick a model to run.</span></div>
              {/if}
            </div>
          </div>
        {/each}
      </div>

      <div class="cmp-footer">
        Each column is a live, separately-billed call. Smart Routing picks the cheapest model that clears the quality bar.
      </div>
    </div>
  </div>
{/if}

<style>
  .cmp-overlay {
    position: fixed;
    inset: 0;
    z-index: 215;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-6);
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(5px);
    -webkit-backdrop-filter: blur(5px);
    animation: cmpFade 0.16s var(--ease-out);
  }
  @keyframes cmpFade { from { opacity: 0; } to { opacity: 1; } }

  .cmp-panel {
    width: 1080px;
    max-width: 100%;
    max-height: 88vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    overflow: hidden;
    animation: cmpPop 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes cmpPop {
    from { opacity: 0; transform: translateY(-6px) scale(0.985); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  /* ── Header ──────────────────────── */
  .cmp-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4) var(--space-4) var(--space-3);
  }
  .cmp-title {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
  }
  .cmp-title svg { color: var(--accent-primary); }
  .cmp-close {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .cmp-close:hover { background: var(--bg-hover); color: var(--text-primary); }

  .cmp-prompt {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    margin: 0 var(--space-4) var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: rgba(var(--overlay-rgb), 0.04);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
  }
  .cmp-prompt-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    font-weight: var(--weight-semibold);
    flex-shrink: 0;
  }
  .cmp-prompt-text {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── Verdict banner ──────────────── */
  .cmp-verdict {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0 var(--space-4) var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: rgba(16, 163, 127, 0.1);
    border: 1px solid rgba(16, 163, 127, 0.25);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
    color: var(--text-primary);
    animation: cmpFade 0.25s var(--ease-out);
  }
  .cmp-verdict svg { color: var(--accent-primary); flex-shrink: 0; }
  .cmp-verdict-cost { font-weight: var(--weight-semibold); }
  .cmp-verdict-sep { color: var(--text-muted); }
  .cmp-verdict-lat { color: var(--text-secondary); }

  /* ── Columns ─────────────────────── */
  .cmp-cols {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: var(--border-subtle);
    border-top: 1px solid var(--border-subtle);
    border-bottom: 1px solid var(--border-subtle);
    overflow: hidden;
  }
  .cmp-col {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--bg-secondary);
  }
  .cmp-col-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-subtle);
    background: rgba(var(--overlay-rgb), 0.02);
  }

  .cmp-picker-wrap { position: relative; min-width: 0; }
  .cmp-picker {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    max-width: 100%;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    transition: background var(--duration-fast);
  }
  .cmp-picker:hover { background: var(--bg-hover); }
  .cmp-picker-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cmp-caret { color: var(--text-muted); flex-shrink: 0; }
  .cmp-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

  .cmp-menu {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 20;
    min-width: 220px;
    max-height: 300px;
    overflow-y: auto;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 4px;
    box-shadow: var(--shadow-lg);
    animation: cmpFade 0.14s var(--ease-out);
  }
  .cmp-tier {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    padding: 6px 8px 2px;
  }
  .cmp-mi {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px 8px;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    text-align: left;
    transition: background var(--duration-fast), color var(--duration-fast);
  }
  .cmp-mi:hover { background: var(--bg-hover); color: var(--text-primary); }
  .cmp-mi-name { font-size: var(--text-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cmp-note { padding: 8px; font-size: var(--text-xs); color: var(--text-muted); text-align: center; }

  .cmp-stats {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-shrink: 0;
  }
  .cmp-stat {
    font-size: var(--text-xs);
    font-family: var(--font-mono);
    color: var(--text-tertiary);
  }
  .cmp-stat-cost {
    padding: 1px 6px;
    border-radius: var(--radius-sm);
    background: rgba(var(--overlay-rgb), 0.05);
  }
  .cmp-stat-cost.cheaper {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.12);
    font-weight: var(--weight-semibold);
  }
  .cmp-rerun {
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .cmp-rerun:hover { background: var(--bg-hover); color: var(--text-primary); }

  .cmp-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-4);
  }

  .cmp-loading {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-muted);
    font-size: var(--text-sm);
    padding: var(--space-4) 0;
  }
  .cmp-spinner {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid rgba(var(--overlay-rgb), 0.2);
    border-top-color: var(--accent-primary);
    animation: cmpSpin 0.7s linear infinite;
  }
  @keyframes cmpSpin { to { transform: rotate(360deg); } }

  .cmp-error {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid rgba(239, 68, 68, 0.3);
    background: rgba(239, 68, 68, 0.06);
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    font-size: var(--text-sm);
  }
  .cmp-error svg { color: #ef4444; }
  .cmp-retry {
    align-self: flex-start;
    padding: 4px 10px;
    border-radius: var(--radius-sm);
    background: var(--bg-hover);
    color: var(--text-primary);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
  }
  .cmp-retry:hover { background: var(--bg-active); }

  .cmp-footer {
    padding: var(--space-3) var(--space-4);
    font-size: var(--text-xs);
    color: var(--text-muted);
    text-align: center;
  }

  @media (max-width: 760px) {
    .cmp-overlay { padding: 0; }
    .cmp-panel { max-height: 100vh; height: 100vh; border-radius: 0; border: none; width: 100%; }
    .cmp-cols { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }
  }
</style>
