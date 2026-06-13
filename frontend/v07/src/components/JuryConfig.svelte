<script>
  import { onMount } from 'svelte';
  import { juryConfigOpen, selectedModel } from '../lib/stores.js';
  import { getModels } from '../lib/api.js';

  let models = $state([]);
  let loading = $state(true);
  let error = $state(false);
  let panelEl = $state(null);

  // Member model_ids (the jurors) + the chosen synthesizer model_id.
  let selectedIds = $state([]);
  let synthId = $state('smart_routing');

  const tierOrder = ['premium', 'moderate', 'cheap'];
  const tierMeta = {
    premium: { emoji: '🔴', label: 'Premium', color: 'var(--tier-premium)' },
    moderate: { emoji: '🟡', label: 'Moderate', color: 'var(--tier-moderate)' },
    cheap: { emoji: '🟢', label: 'Budget', color: 'var(--tier-cheap)' },
  };

  let grouped = $derived.by(() => {
    const g = {};
    for (const m of models) (g[m.tier || 'other'] ||= []).push(m);
    for (const t of Object.keys(g)) {
      g[t].sort((a, b) => (b.cost_per_1k_tokens ?? -Infinity) - (a.cost_per_1k_tokens ?? -Infinity));
    }
    return g;
  });

  let selectedCount = $derived(selectedIds.length);
  let allSelected = $derived(models.length > 0 && selectedIds.length === models.length);

  function isOn(id) {
    return selectedIds.includes(id);
  }
  function toggle(id) {
    selectedIds = isOn(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id];
  }
  function selectAll() {
    selectedIds = models.map((m) => m.model_id);
  }
  function clearAll() {
    selectedIds = [];
  }

  function close() {
    juryConfigOpen.set(false);
  }

  function convene() {
    const members = models
      .filter((m) => selectedIds.includes(m.model_id))
      .map((m) => ({ model_id: m.model_id, display_name: m.display_name, tier: m.tier, provider: m.provider }));
    if (members.length < 2) return;

    let synthMeta;
    if (synthId === 'smart_routing') {
      synthMeta = { model_id: 'smart_routing', display_name: 'Smart Routing' };
    } else {
      const sm = models.find((m) => m.model_id === synthId);
      synthMeta = { model_id: synthId, display_name: sm?.display_name || synthId };
    }

    selectedModel.set({
      id: 'jury',
      name: 'LLM Jury',
      mode: 'jury',
      members,
      synthesizer: synthMeta,
    });
    close();
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }

  function tierColor(tier) {
    return tierMeta[tier]?.color || 'var(--text-muted)';
  }

  onMount(async () => {
    try {
      models = await getModels();
    } catch {
      error = true;
    } finally {
      loading = false;
    }

    // Prefill from an active jury; otherwise default to "all models together"
    // (the headline use case) with Smart Routing synthesizing.
    const sm = $selectedModel;
    if (sm?.mode === 'jury' && Array.isArray(sm.members) && sm.members.length) {
      selectedIds = sm.members.map((m) => m.model_id);
      synthId = sm.synthesizer?.model_id || 'smart_routing';
    } else {
      selectedIds = models.map((m) => m.model_id);
      synthId = 'smart_routing';
    }

    function handleClick(e) {
      if (panelEl && !panelEl.contains(e.target)) close();
    }
    document.addEventListener('mousedown', handleClick);
    window.addEventListener('keydown', onKeydown);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      window.removeEventListener('keydown', onKeydown);
    };
  });
</script>

<div class="jury-overlay">
  <div class="jury-panel animate-slide-down" bind:this={panelEl}>
    <!-- ── Header ───────────────────────── -->
    <div class="jury-header">
      <div class="jury-title">
        <span class="jury-emblem">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3v18M3 7h18M7 7l-3 7a3 3 0 0 0 6 0l-3-7zM17 7l-3 7a3 3 0 0 0 6 0l-3-7z"/>
          </svg>
        </span>
        <div>
          <h3>Assemble your LLM Jury</h3>
          <p class="jury-sub">Every selected model answers independently, then a synthesizer merges their strengths into one strong answer — and you still see each model's individual answer.</p>
        </div>
      </div>
      <button class="close-btn" onclick={close} aria-label="Close">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>

    <!-- ── Jurors toolbar ───────────────── -->
    <div class="jury-toolbar">
      <span class="jury-section-label">Jurors <span class="jury-count">{selectedCount}</span></span>
      <div class="jury-toolbar-actions">
        <button class="jury-link" class:on={allSelected} onclick={selectAll}>Select all</button>
        <span class="jury-dot-sep">·</span>
        <button class="jury-link" onclick={clearAll}>Clear</button>
      </div>
    </div>

    <!-- ── Member list ──────────────────── -->
    <div class="jury-list">
      {#if loading}
        <div class="jury-loading">
          {#each [1, 2, 3, 4] as _}
            <div class="skeleton" style="height: 44px; margin-bottom: 6px;"></div>
          {/each}
        </div>
      {:else if error}
        <div class="jury-msg">Couldn’t load models. Is the backend running on :8000?</div>
      {:else}
        {#each tierOrder as tier}
          {#if grouped[tier]?.length}
            <div class="jury-tier-label" style="--tier-color: {tierMeta[tier]?.color}">
              <span>{tierMeta[tier]?.emoji}</span><span>{tierMeta[tier]?.label}</span>
            </div>
            {#each grouped[tier] as m}
              <button class="juror-row" class:on={isOn(m.model_id)} onclick={() => toggle(m.model_id)} role="checkbox" aria-checked={isOn(m.model_id)}>
                <span class="juror-check" style="--tc: {tierColor(m.tier)}">
                  {#if isOn(m.model_id)}
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>
                  {/if}
                </span>
                <span class="juror-dot" style="background: {tierColor(m.tier)}"></span>
                <span class="juror-name">{m.display_name}</span>
                <span class="juror-provider">{m.provider}</span>
              </button>
            {/each}
          {/if}
        {/each}
      {/if}
    </div>

    <!-- ── Synthesizer ──────────────────── -->
    <div class="jury-synth">
      <label class="jury-section-label" for="jury-synth-select">Synthesizer</label>
      <select id="jury-synth-select" class="jury-select" bind:value={synthId}>
        <option value="smart_routing">Smart Routing (recommended)</option>
        {#each models as m}
          <option value={m.model_id}>{m.display_name}</option>
        {/each}
      </select>
      <p class="jury-synth-note">Combines the jurors' answers into the final verdict.</p>
    </div>

    <!-- ── Footer ───────────────────────── -->
    <div class="jury-footer">
      <span class="jury-cost-note">
        {#if selectedCount >= 2}
          {selectedCount} + 1 model calls per message
        {:else}
          Select at least 2 jurors
        {/if}
      </span>
      <button class="convene-btn" onclick={convene} disabled={selectedCount < 2}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>
        Convene jury
      </button>
    </div>
  </div>
</div>

<style>
  .jury-overlay {
    position: fixed;
    inset: 0;
    z-index: 120;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 56px;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
  }
  .jury-panel {
    width: 460px;
    max-width: calc(100vw - 32px);
    max-height: calc(100vh - 100px);
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Header ──────────────────────── */
  .jury-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-5) var(--space-3);
    border-bottom: 1px solid var(--border-subtle);
  }
  .jury-title { display: flex; gap: var(--space-3); align-items: flex-start; }
  .jury-emblem {
    flex-shrink: 0;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--accent-gradient);
    color: #fff;
  }
  .jury-title h3 {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    margin: 0 0 2px;
  }
  .jury-sub {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    line-height: 1.5;
    margin: 0;
  }
  .close-btn {
    flex-shrink: 0;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .close-btn:hover { background: var(--bg-hover); color: var(--text-primary); }

  /* ── Toolbar ─────────────────────── */
  .jury-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-3) var(--space-5) var(--space-1);
  }
  .jury-section-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
  }
  .jury-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 16px;
    padding: 0 5px;
    margin-left: 4px;
    border-radius: 8px;
    background: rgba(16, 163, 127, 0.15);
    color: var(--accent-primary);
    font-size: 10px;
    font-weight: var(--weight-bold);
  }
  .jury-toolbar-actions { display: flex; align-items: center; gap: var(--space-2); }
  .jury-link {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    transition: color var(--duration-fast);
  }
  .jury-link:hover { color: var(--accent-primary); }
  .jury-link.on { color: var(--accent-primary); }
  .jury-dot-sep { color: var(--text-muted); font-size: var(--text-xs); }

  /* ── Member list ─────────────────── */
  .jury-list {
    flex: 1;
    min-height: 80px;
    overflow-y: auto;
    padding: var(--space-1) var(--space-3) var(--space-2);
  }
  .jury-tier-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 10px;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
    padding: var(--space-3) var(--space-2) var(--space-1);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .juror-row {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    text-align: left;
    transition: background var(--duration-fast);
  }
  .juror-row:hover { background: var(--bg-hover); }
  .juror-row.on { background: rgba(16, 163, 127, 0.06); }
  .juror-check {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid var(--border-default);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    flex-shrink: 0;
    transition: all var(--duration-fast);
  }
  .juror-row.on .juror-check {
    background: var(--accent-primary);
    border-color: var(--accent-primary);
  }
  .juror-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .juror-name {
    flex: 1;
    min-width: 0;
    font-size: var(--text-sm);
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .juror-provider {
    font-size: var(--text-xs);
    color: var(--text-muted);
    flex-shrink: 0;
    text-transform: capitalize;
  }

  /* ── Synthesizer ─────────────────── */
  .jury-synth {
    padding: var(--space-3) var(--space-5);
    border-top: 1px solid var(--border-subtle);
  }
  .jury-select {
    width: 100%;
    margin-top: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-family: var(--font-sans);
    cursor: pointer;
  }
  .jury-select:focus { outline: none; border-color: var(--accent-primary); }
  .jury-synth-note {
    margin: var(--space-2) 0 0;
    font-size: var(--text-xs);
    color: var(--text-muted);
  }

  /* ── Footer ──────────────────────── */
  .jury-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-5);
    border-top: 1px solid var(--border-subtle);
  }
  .jury-cost-note { font-size: var(--text-xs); color: var(--text-muted); }
  .convene-btn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--accent-primary);
    color: #fff;
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    transition: all var(--duration-fast);
  }
  .convene-btn:hover:not(:disabled) {
    background: var(--accent-hover);
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(16, 163, 127, 0.32);
  }
  .convene-btn:disabled { opacity: 0.45; cursor: not-allowed; }

  @media (max-width: 480px) {
    .jury-panel { width: calc(100vw - 24px); max-height: calc(100vh - 72px); }
  }
</style>
