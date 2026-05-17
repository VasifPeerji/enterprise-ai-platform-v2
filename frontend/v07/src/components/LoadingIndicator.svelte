<script>
  import { loadingMode, loadingStage, loadingMeta } from '../lib/stores.js';

  // Each mode declares its own ordered pipeline. The component figures out
  // which stage is done / active / pending from the current loadingStage.
  const PIPELINES = {
    normal: [
      { id: 'thinking', label: 'Thinking' },
      { id: 'composing', label: 'Composing answer' },
    ],
    web_search: [
      { id: 'searching', label: 'Searching the web' },
      { id: 'reading', label: 'Reading top sources' },
      { id: 'synthesizing', label: 'Synthesizing answer' },
      { id: 'composing', label: 'Composing response' },
    ],
    file_rag: [
      { id: 'uploading', label: 'Uploading documents' },
      { id: 'parsing', label: 'Parsing & indexing content' },
      { id: 'retrieving', label: 'Searching your documents' },
      { id: 'composing', label: 'Generating grounded answer' },
    ],
  };

  let pipeline = $derived(PIPELINES[$loadingMode] || PIPELINES.normal);
  let currentIdx = $derived(Math.max(0, pipeline.findIndex((s) => s.id === $loadingStage)));

  function hostFromUrl(u) {
    try { return new URL(u).hostname.replace(/^www\./, ''); }
    catch { return u; }
  }

  function humanSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
</script>

<div class="loading-card mode-{$loadingMode}">
  <!-- ── Icon + header ───────────────────────────────────── -->
  <div class="loading-header">
    {#if $loadingMode === 'web_search'}
      <div class="icon-slot globe-slot">
        <span class="pulse-ring ring1"></span>
        <span class="pulse-ring ring2"></span>
        <span class="pulse-ring ring3"></span>
        <svg class="globe-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>
        </svg>
      </div>
    {:else if $loadingMode === 'file_rag'}
      <div class="icon-slot doc-slot">
        <div class="doc-shape">
          <div class="doc-fold"></div>
          <div class="doc-line l1"></div>
          <div class="doc-line l2"></div>
          <div class="doc-line l3"></div>
        </div>
        <div class="scan-line"></div>
      </div>
    {:else}
      <div class="icon-slot orb-slot">
        <span class="orbit-ring"></span>
        <span class="orbit-particle"></span>
        <span class="orbit-core"></span>
      </div>
    {/if}

    <div class="loading-titles">
      <div class="loading-title">
        {pipeline[currentIdx]?.label || 'Working'}
        <span class="ellipsis"><span></span><span></span><span></span></span>
      </div>
      <div class="loading-subtitle">
        {#if $loadingMode === 'web_search' && $loadingMeta?.query}
          for <em>"{$loadingMeta.query.length > 60 ? $loadingMeta.query.slice(0, 60) + '…' : $loadingMeta.query}"</em>
        {:else if $loadingMode === 'file_rag' && $loadingMeta?.files?.length}
          {$loadingMeta.files.length} file{$loadingMeta.files.length === 1 ? '' : 's'}{#if $loadingMeta.totalBytes} · {humanSize($loadingMeta.totalBytes)}{/if}
        {:else if $loadingMode === 'normal'}
          analysing your message
        {/if}
      </div>
    </div>
  </div>

  <!-- ── Source/file chips (appear once we have them) ─────── -->
  {#if $loadingMode === 'web_search' && $loadingMeta?.sources?.length}
    <div class="entity-row">
      {#each $loadingMeta.sources as src, i}
        <div class="entity-chip" style="animation-delay: {i * 80}ms">
          <span class="entity-favicon"></span>
          <span class="entity-name">{hostFromUrl(src.url)}</span>
        </div>
      {/each}
      {#if $loadingMeta.sourcesFound > $loadingMeta.sources.length}
        <div class="entity-chip more-chip" style="animation-delay: {$loadingMeta.sources.length * 80}ms">
          +{$loadingMeta.sourcesFound - $loadingMeta.sources.length} more
        </div>
      {/if}
    </div>
  {/if}

  {#if $loadingMode === 'file_rag' && $loadingMeta?.files?.length}
    <div class="entity-row">
      {#each $loadingMeta.files as name, i}
        <div class="entity-chip file-entity" style="animation-delay: {i * 80}ms">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <path d="M14 2v6h6"/>
          </svg>
          <span class="entity-name">{name}</span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- ── Pipeline progress ─────────────────────────────────── -->
  <div class="stages">
    {#each pipeline as stage, i}
      <div
        class="stage-row"
        class:done={i < currentIdx}
        class:active={i === currentIdx}
        class:pending={i > currentIdx}
      >
        <span class="stage-icon">
          {#if i < currentIdx}
            <svg viewBox="0 0 24 24" class="check-mark" width="12" height="12">
              <path d="M5 12.5l4 4L19 7" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          {:else if i === currentIdx}
            <span class="mini-spinner"></span>
          {:else}
            <span class="dot-empty"></span>
          {/if}
        </span>
        <span class="stage-label">{stage.label}</span>
      </div>
    {/each}
  </div>

  <!-- ── Skeleton response (sets visual anchor for incoming text) ── -->
  <div class="skeleton">
    <div class="skeleton-line w-90"></div>
    <div class="skeleton-line w-70"></div>
    <div class="skeleton-line w-80"></div>
  </div>
</div>

<style>
  .loading-card {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.025) 0%, rgba(255, 255, 255, 0.01) 100%);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    max-width: 440px;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    animation: cardFadeIn 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
    position: relative;
    overflow: hidden;
  }
  /* Faint accent glow that gently breathes */
  .loading-card::before {
    content: '';
    position: absolute;
    inset: -1px;
    border-radius: inherit;
    padding: 1px;
    background: linear-gradient(135deg, rgba(16, 163, 127, 0.4), transparent 40%, rgba(16, 163, 127, 0.15) 100%);
    -webkit-mask: linear-gradient(#000, #000) content-box, linear-gradient(#000, #000);
    mask: linear-gradient(#000, #000) content-box, linear-gradient(#000, #000);
    -webkit-mask-composite: xor;
    mask-composite: exclude;
    pointer-events: none;
    animation: borderBreathe 3s ease-in-out infinite;
  }
  @keyframes cardFadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes borderBreathe {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
  }

  /* ── Header (icon + titles) ─────────────────────────────── */
  .loading-header {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }
  .icon-slot {
    width: 44px;
    height: 44px;
    position: relative;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-primary);
  }
  .loading-titles {
    min-width: 0;
  }
  .loading-title {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .loading-subtitle {
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .loading-subtitle em {
    color: var(--text-secondary);
    font-style: normal;
  }

  /* ── Animated ellipsis on the title ───────────────────── */
  .ellipsis {
    display: inline-flex;
    margin-left: 2px;
    gap: 2px;
  }
  .ellipsis span {
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: var(--text-tertiary);
    animation: dotPulse 1.4s ease-in-out infinite;
    align-self: center;
  }
  .ellipsis span:nth-child(2) { animation-delay: 0.2s; }
  .ellipsis span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes dotPulse {
    0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
    40% { opacity: 1; transform: scale(1.2); }
  }

  /* ── Normal mode: orbiting particle ───────────────────── */
  .orb-slot {
    border-radius: 50%;
  }
  .orbit-ring {
    position: absolute;
    inset: 6px;
    border: 1.5px solid rgba(16, 163, 127, 0.18);
    border-top-color: var(--accent-primary);
    border-right-color: rgba(16, 163, 127, 0.6);
    border-radius: 50%;
    animation: spin 1.2s linear infinite;
  }
  .orbit-particle {
    position: absolute;
    width: 6px;
    height: 6px;
    background: var(--accent-primary);
    border-radius: 50%;
    top: 4px;
    left: 50%;
    margin-left: -3px;
    box-shadow: 0 0 10px var(--accent-primary), 0 0 16px rgba(16, 163, 127, 0.5);
    transform-origin: 3px 18px;
    animation: spin 1.2s linear infinite;
  }
  .orbit-core {
    position: absolute;
    inset: 14px;
    background: radial-gradient(circle, var(--accent-primary) 0%, transparent 70%);
    border-radius: 50%;
    animation: corePulse 1.6s ease-in-out infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  @keyframes corePulse {
    0%, 100% { transform: scale(0.8); opacity: 0.6; }
    50% { transform: scale(1.2); opacity: 1; }
  }

  /* ── Web mode: globe with radar pulses ────────────────── */
  .globe-slot { }
  .globe-svg {
    width: 26px;
    height: 26px;
    animation: globeRotate 4s linear infinite;
    z-index: 1;
  }
  @keyframes globeRotate {
    to { transform: rotate(360deg); }
  }
  .pulse-ring {
    position: absolute;
    inset: 6px;
    border: 1.5px solid var(--accent-primary);
    border-radius: 50%;
    opacity: 0;
    animation: pulseOut 2.2s ease-out infinite;
  }
  .pulse-ring.ring1 { animation-delay: 0s; }
  .pulse-ring.ring2 { animation-delay: 0.73s; }
  .pulse-ring.ring3 { animation-delay: 1.46s; }
  @keyframes pulseOut {
    0% { transform: scale(0.35); opacity: 1; }
    100% { transform: scale(1.5); opacity: 0; }
  }

  /* ── File mode: document with scan line ───────────────── */
  .doc-slot { }
  .doc-shape {
    position: relative;
    width: 26px;
    height: 32px;
    border: 1.5px solid var(--accent-primary);
    border-radius: 3px;
    background: linear-gradient(180deg, transparent 0%, rgba(16, 163, 127, 0.06) 100%);
  }
  .doc-fold {
    position: absolute;
    top: -1px;
    right: -1px;
    width: 7px;
    height: 7px;
    background: var(--surface-chat);
    border-left: 1.5px solid var(--accent-primary);
    border-bottom: 1.5px solid var(--accent-primary);
    border-bottom-left-radius: 3px;
  }
  .doc-line {
    position: absolute;
    height: 1.5px;
    background: var(--accent-primary);
    opacity: 0.55;
    left: 3px;
    border-radius: 1px;
  }
  .doc-line.l1 { top: 9px; right: 3px; }
  .doc-line.l2 { top: 14px; right: 3px; }
  .doc-line.l3 { top: 19px; right: 10px; }
  .scan-line {
    position: absolute;
    left: 9px;
    right: 9px;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-primary), transparent);
    box-shadow: 0 0 8px var(--accent-primary);
    animation: scan 1.6s ease-in-out infinite;
    pointer-events: none;
  }
  @keyframes scan {
    0% { top: 4px; opacity: 0; }
    15% { opacity: 1; }
    85% { opacity: 1; }
    100% { top: 36px; opacity: 0; }
  }

  /* ── Entity chips (sources / files) ───────────────────── */
  .entity-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin-bottom: var(--space-3);
  }
  .entity-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    border-radius: var(--radius-full);
    background: rgba(16, 163, 127, 0.08);
    border: 1px solid rgba(16, 163, 127, 0.25);
    color: var(--text-secondary);
    font-size: 11px;
    font-family: var(--font-mono);
    opacity: 0;
    transform: translateY(4px);
    animation: chipPopIn 0.4s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
  }
  .entity-chip.more-chip {
    background: rgba(255, 255, 255, 0.04);
    border-color: var(--border-subtle);
    font-family: var(--font-sans);
  }
  .entity-chip.file-entity {
    background: rgba(255, 255, 255, 0.04);
    border-color: var(--border-subtle);
    color: var(--text-secondary);
  }
  .entity-favicon {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent-primary);
    box-shadow: 0 0 4px var(--accent-primary);
  }
  .entity-name {
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  @keyframes chipPopIn {
    to { opacity: 1; transform: translateY(0); }
  }

  /* ── Pipeline stages ──────────────────────────────────── */
  .stages {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: var(--space-3);
  }
  .stage-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    transition: opacity var(--duration-fast);
  }
  .stage-row.done .stage-label { color: var(--text-tertiary); }
  .stage-row.active .stage-label { color: var(--text-primary); font-weight: var(--weight-medium); }
  .stage-row.pending .stage-label { color: var(--text-muted); }
  .stage-row.pending { opacity: 0.55; }

  .stage-icon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .check-mark {
    color: var(--accent-primary);
    animation: checkPop 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes checkPop {
    from { transform: scale(0); }
    to { transform: scale(1); }
  }
  .mini-spinner {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 1.5px solid rgba(16, 163, 127, 0.25);
    border-top-color: var(--accent-primary);
    animation: spin 0.8s linear infinite;
  }
  .dot-empty {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    border: 1.5px solid var(--border-subtle);
  }

  /* ── Skeleton response preview ────────────────────────── */
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: 7px;
    padding-top: var(--space-3);
    border-top: 1px solid var(--border-subtle);
  }
  .skeleton-line {
    height: 9px;
    border-radius: 4px;
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 0.04) 0%,
      rgba(255, 255, 255, 0.09) 50%,
      rgba(255, 255, 255, 0.04) 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.6s linear infinite;
  }
  .skeleton-line.w-90 { width: 92%; }
  .skeleton-line.w-70 { width: 68%; }
  .skeleton-line.w-80 { width: 82%; }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* ── Responsive ───────────────────────────────────────── */
  @media (max-width: 600px) {
    .loading-card { max-width: 100%; padding: var(--space-3); }
    .entity-name { max-width: 90px; }
  }
</style>
