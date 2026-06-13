<script>
  // Surfaces the smart router's per-answer decision — the platform's headline
  // capability and the one thing a single-model chatbot can't show. Reads the
  // enriched `routing` object built in api.js (transformResponse): the routing
  // reasoning, the query analysis (complexity/intent/domain/modality), a
  // confidence + deterministic quality read, the Layer-8 escalation outcome,
  // and latency/cost. Collapsed by default so the chat stays clean; the summary
  // line still tells the routing story at a glance.
  //
  // This shows the routing DECISION, never the free backing model that actually
  // executes — the display rule (show the router's pick) is preserved.

  let { routing = null, model = null, cost = null } = $props();

  let expanded = $state(false);

  // RAG answers route through grounded retrieval, not the kNN model router, so
  // they carry only a reasoning string — render a slimmer grounded variant.
  let isGrounded = $derived(routing?.mode === 'rag' || model?.tier === 'grounded');

  // Title-case a backend enum like "high_risk" → "High risk".
  function pretty(s) {
    if (!s) return '';
    return String(s)
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // Pricing-tier → dot color (premium/moderate/cheap map to token vars).
  function tierColor(tier) {
    const t = (tier || '').toLowerCase();
    if (t === 'premium') return 'var(--tier-premium)';
    if (t === 'moderate') return 'var(--tier-moderate)';
    if (t === 'cheap' || t === 'budget') return 'var(--tier-cheap)';
    return 'var(--accent-primary)';
  }

  // Confidence label → semantic color. Unknown labels stay neutral.
  function confColor(c) {
    const v = (c || '').toLowerCase();
    if (/(high|strong|grounded)/.test(v)) return 'var(--success)';
    if (/(med|moderate)/.test(v)) return 'var(--warning)';
    if (/(low|weak)/.test(v)) return 'var(--error)';
    return 'var(--text-tertiary)';
  }

  function fmtLatency(ms) {
    if (ms == null) return null;
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
  }

  function fmtCost(v) {
    if (v == null) return null;
    if (v === 0) return 'Free';
    if (v < 0.0001) return '<$0.0001';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    return `$${v.toFixed(2)}`;
  }

  // The analysis chips — only those the backend actually reported.
  let chips = $derived(
    [
      { label: 'Complexity', value: pretty(routing?.complexity) },
      { label: 'Intent', value: pretty(routing?.intent) },
      { label: 'Domain', value: pretty(routing?.domain) },
      { label: 'Modality', value: pretty(routing?.modality) },
    ].filter((c) => c.value),
  );

  // Quality score 0–1 → percentage for the meter. null when not reported.
  let qualityPct = $derived(
    routing?.qualityScore != null ? Math.round(routing.qualityScore * 100) : null,
  );

  let latencyText = $derived(fmtLatency(routing?.latencyMs));
  let costText = $derived(fmtCost(cost?.chargedUsd ?? null));

  // Whether there's anything worth expanding into.
  let hasDetail = $derived(
    !!(routing?.reasoning || chips.length || qualityPct != null || routing?.escalationAvailable),
  );
</script>

{#if routing}
  <div class="routing-insight" class:grounded={isGrounded}>
    <button
      class="ri-summary"
      class:open={expanded}
      onclick={() => (expanded = !expanded)}
      aria-expanded={expanded}
      title={expanded ? 'Hide routing insight' : 'Show why this model was chosen'}
    >
      <span class="ri-spark" aria-hidden="true">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
      </span>
      <span class="ri-summary-text">
        {#if isGrounded}
          Grounded retrieval
        {:else}
          <span class="ri-dot" style="background: {tierColor(routing.tier)}"></span>
          Routed to <strong>{model?.name || 'model'}</strong>
        {/if}
      </span>
      <!-- Collapsed-state quick facts so the story reads at a glance -->
      <span class="ri-quick">
        {#if routing.complexity}<span class="ri-quick-chip">{pretty(routing.complexity)}</span>{/if}
        {#if routing.escalated}<span class="ri-quick-chip escalated">Escalated</span>{/if}
        {#if routing.fastPath}<span class="ri-quick-chip">⚡ Fast path</span>{/if}
        {#if routing.memoryHit}<span class="ri-quick-chip">⤿ Cached</span>{/if}
      </span>
      {#if hasDetail}
        <svg class="ri-chevron" class:open={expanded} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      {/if}
    </button>

    {#if expanded && hasDetail}
      <div class="ri-body">
        {#if routing.reasoning}
          <p class="ri-reasoning">{routing.reasoning}</p>
        {/if}

        {#if chips.length}
          <div class="ri-chips">
            {#each chips as c}
              <span class="ri-chip">
                <span class="ri-chip-label">{c.label}</span>
                <span class="ri-chip-value">{c.value}</span>
              </span>
            {/each}
          </div>
        {/if}

        <!-- Confidence + deterministic quality gate -->
        {#if routing.confidence || qualityPct != null}
          <div class="ri-metrics">
            {#if routing.confidence}
              <div class="ri-metric">
                <span class="ri-metric-label">Confidence</span>
                <span class="ri-metric-value" style="color: {confColor(routing.confidence)}">
                  {pretty(routing.confidence)}
                </span>
              </div>
            {/if}
            {#if qualityPct != null}
              <div class="ri-metric ri-metric-wide">
                <span class="ri-metric-label">Quality check</span>
                <span class="ri-meter" aria-label="Quality score {qualityPct} percent">
                  <span class="ri-meter-fill" style="width: {qualityPct}%"></span>
                </span>
                <span class="ri-metric-value">{qualityPct}%</span>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Escalation outcome (Layer 8) -->
        {#if routing.escalated}
          <div class="ri-status escalated">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="17 11 12 6 7 11" /><polyline points="17 18 12 13 7 18" />
            </svg>
            Escalated {routing.escalationCount}
            {routing.escalationCount === 1 ? 'level' : 'levels'} — a quality check
            upgraded the model mid-flight.
          </div>
        {:else if routing.qualityPassed}
          <div class="ri-status ok">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M5 12l5 5L20 7" />
            </svg>
            First pick cleared the quality gate — no escalation needed.
          </div>
        {/if}

        <!-- Footer: the cost/latency story -->
        <div class="ri-foot">
          {#if !isGrounded}
            <span class="ri-foot-item">Cheapest model that cleared the bar</span>
          {/if}
          <span class="ri-foot-spacer"></span>
          {#if latencyText}<span class="ri-foot-metric">{latencyText}</span>{/if}
          {#if costText}<span class="ri-foot-metric ri-foot-cost">{costText}</span>{/if}
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .routing-insight {
    margin-top: var(--space-2);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: linear-gradient(180deg, rgba(16, 163, 127, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
    overflow: hidden;
  }

  /* ── Summary row (always visible) ───────────────────────── */
  .ri-summary {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: 7px 10px;
    text-align: left;
    color: var(--text-tertiary);
    transition: background var(--duration-fast), color var(--duration-fast);
  }
  .ri-summary:hover { background: rgba(255, 255, 255, 0.03); color: var(--text-secondary); }
  .ri-summary.open { border-bottom: 1px solid var(--border-subtle); }

  .ri-spark {
    display: inline-flex;
    color: var(--accent-primary);
    flex-shrink: 0;
  }
  .ri-summary-text {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    white-space: nowrap;
  }
  .ri-summary-text strong { color: var(--text-primary); font-weight: var(--weight-semibold); }
  .ri-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .ri-quick {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    flex-wrap: wrap;
  }
  .ri-quick-chip {
    font-size: 10px;
    padding: 1px 7px;
    border-radius: var(--radius-full);
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-tertiary);
    white-space: nowrap;
  }
  .ri-quick-chip.escalated {
    background: rgba(245, 158, 11, 0.14);
    color: var(--warning);
  }

  .ri-chevron {
    flex-shrink: 0;
    color: var(--text-muted);
    transition: transform var(--duration-fast);
  }
  .ri-chevron.open { transform: rotate(180deg); }

  /* ── Expanded body ──────────────────────────────────────── */
  .ri-body {
    padding: var(--space-3) 10px var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    animation: riExpand 0.22s var(--ease-out);
  }
  @keyframes riExpand {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .ri-reasoning {
    font-size: var(--text-sm);
    line-height: var(--leading-normal);
    color: var(--text-secondary);
    margin: 0;
  }

  .ri-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .ri-chip {
    display: inline-flex;
    flex-direction: column;
    gap: 1px;
    padding: 4px 10px;
    border-radius: var(--radius-sm);
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border-subtle);
  }
  .ri-chip-label {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
  }
  .ri-chip-value {
    font-size: var(--text-xs);
    color: var(--text-primary);
    font-weight: var(--weight-medium);
  }

  /* ── Metrics (confidence + quality meter) ───────────────── */
  .ri-metrics {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    flex-wrap: wrap;
  }
  .ri-metric {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .ri-metric-wide { flex: 1; min-width: 160px; }
  .ri-metric-label {
    font-size: var(--text-xs);
    color: var(--text-muted);
    white-space: nowrap;
  }
  .ri-metric-value {
    font-size: var(--text-xs);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    font-family: var(--font-mono);
  }
  .ri-meter {
    position: relative;
    flex: 1;
    height: 6px;
    min-width: 60px;
    border-radius: var(--radius-full);
    background: var(--bg-elevated);
    overflow: hidden;
  }
  .ri-meter-fill {
    position: absolute;
    inset: 0 auto 0 0;
    height: 100%;
    border-radius: var(--radius-full);
    background: var(--accent-gradient);
    transition: width 0.5s var(--ease-out);
  }

  /* ── Escalation / quality status line ───────────────────── */
  .ri-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-xs);
    line-height: 1.4;
    padding: 6px 10px;
    border-radius: var(--radius-sm);
  }
  .ri-status svg { flex-shrink: 0; }
  .ri-status.ok {
    background: rgba(16, 163, 127, 0.08);
    color: var(--accent-primary);
  }
  .ri-status.escalated {
    background: rgba(245, 158, 11, 0.1);
    color: var(--warning);
  }

  /* ── Footer ─────────────────────────────────────────────── */
  .ri-foot {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--border-subtle);
  }
  .ri-foot-item {
    font-size: 10px;
    color: var(--text-muted);
    font-style: italic;
  }
  .ri-foot-spacer { flex: 1; }
  .ri-foot-metric {
    font-size: var(--text-xs);
    font-family: var(--font-mono);
    color: var(--text-tertiary);
  }
  .ri-foot-cost { color: var(--success); }

  @media (max-width: 600px) {
    .ri-quick { display: none; }
  }
</style>
