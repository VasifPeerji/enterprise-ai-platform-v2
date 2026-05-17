<script>
  import { createEventDispatcher } from 'svelte';

  let { proof = null, visible = false } = $props();
  const dispatch = createEventDispatcher();

  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let isDragging = $state(false);
  let lastPos = $state({ x: 0, y: 0 });

  function close() {
    dispatch('close');
  }

  function zoomIn() {
    zoom = Math.min(zoom + 0.25, 3);
  }

  function zoomOut() {
    zoom = Math.max(zoom - 0.25, 0.5);
  }

  function resetZoom() {
    zoom = 1;
    panX = 0;
    panY = 0;
  }

  function handleMouseDown(e) {
    if (zoom > 1) {
      isDragging = true;
      lastPos = { x: e.clientX, y: e.clientY };
    }
  }

  function handleMouseMove(e) {
    if (isDragging) {
      panX += e.clientX - lastPos.x;
      panY += e.clientY - lastPos.y;
      lastPos = { x: e.clientX, y: e.clientY };
    }
  }

  function handleMouseUp() {
    isDragging = false;
  }

  function handleClick(e) {
    // Click to zoom in at point
    if (zoom < 2 && !isDragging) {
      zoom = 2;
      const rect = e.currentTarget.getBoundingClientRect();
      const relX = (e.clientX - rect.left) / rect.width - 0.5;
      const relY = (e.clientY - rect.top) / rect.height - 0.5;
      panX = -relX * rect.width;
      panY = -relY * rect.height;
    }
  }

  function renderHighlightedText(pageText, highlights) {
    if (!pageText) return '';
    const ordered = [...(highlights || [])]
      .filter(h => Number.isInteger(h.start_char) && Number.isInteger(h.end_char) && h.end_char > h.start_char)
      .sort((a, b) => a.start_char - b.start_char);
    if (!ordered.length) return escapeHtml(pageText);

    let cursor = 0;
    let html = '';
    for (const h of ordered) {
      const start = Math.max(cursor, Math.min(h.start_char, pageText.length));
      const end = Math.max(start, Math.min(h.end_char, pageText.length));
      if (start > cursor) html += escapeHtml(pageText.slice(cursor, start));
      html += `<mark class="highlight">${escapeHtml(pageText.slice(start, end))}</mark>`;
      cursor = end;
    }
    if (cursor < pageText.length) html += escapeHtml(pageText.slice(cursor));
    return html;
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
</script>

{#if visible && proof}
  <div class="viewer-overlay" onclick={close} role="dialog">
    <div 
      class="viewer-panel" 
      onclick={(e) => e.stopPropagation()}
      role="document"
    >
      <!-- Header -->
      <div class="viewer-header">
        <div class="viewer-title-area">
          <h3 class="viewer-title">{proof.title || 'Source Document'}</h3>
          <span class="viewer-page">Page {proof.page_number || '—'}</span>
          {#if proof.source_uri}
            <span class="viewer-uri">{proof.source_uri}</span>
          {/if}
        </div>
        <div class="viewer-controls">
          <button class="ctrl-btn" onclick={zoomOut} title="Zoom out">−</button>
          <span class="zoom-level">{Math.round(zoom * 100)}%</span>
          <button class="ctrl-btn" onclick={zoomIn} title="Zoom in">+</button>
          <button class="ctrl-btn" onclick={resetZoom} title="Reset">⤢</button>
          <button class="ctrl-btn close-x" onclick={close} title="Close">✕</button>
        </div>
      </div>

      <!-- Content -->
      <div 
        class="viewer-content"
        class:zoomed={zoom > 1}
        onmousedown={handleMouseDown}
        onmousemove={handleMouseMove}
        onmouseup={handleMouseUp}
        onmouseleave={handleMouseUp}
        onclick={handleClick}
        role="img"
        aria-label="Page content"
      >
        <div 
          class="page-text"
          style="transform: scale({zoom}) translate({panX/zoom}px, {panY/zoom}px)"
        >
          {@html renderHighlightedText(proof.page_text || '', proof.highlights || [])}
        </div>
      </div>

      <!-- Citation badges -->
      {#if proof.citation_indices?.length}
        <div class="viewer-footer">
          <span class="footer-label">Linked citations:</span>
          {#each proof.citation_indices as cidx}
            <span class="citation-pill">Citation {cidx + 1}</span>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .viewer-overlay {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-6);
  }

  .viewer-panel {
    width: 100%;
    max-width: 900px;
    max-height: calc(100vh - 80px);
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Header ─────────────────────── */
  .viewer-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border-subtle);
  }

  .viewer-title-area {
    min-width: 0;
  }

  .viewer-title {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    margin: 0 0 var(--space-1);
  }

  .viewer-page {
    font-size: var(--text-sm);
    color: var(--accent-primary);
    font-weight: var(--weight-medium);
  }

  .viewer-uri {
    display: block;
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin-top: var(--space-1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .viewer-controls {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-shrink: 0;
  }

  .ctrl-btn {
    width: 32px;
    height: 32px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--text-md);
    color: var(--text-secondary);
    background: var(--surface-glass);
    border: 1px solid var(--border-subtle);
    transition: all var(--duration-fast);
  }
  .ctrl-btn:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .close-x {
    margin-left: var(--space-2);
  }

  .zoom-level {
    font-size: var(--text-xs);
    color: var(--text-muted);
    min-width: 40px;
    text-align: center;
    font-family: var(--font-mono);
  }

  /* ── Content ────────────────────── */
  .viewer-content {
    flex: 1;
    overflow: auto;
    padding: var(--space-6);
    cursor: zoom-in;
  }
  .viewer-content.zoomed {
    cursor: grab;
  }
  .viewer-content.zoomed:active {
    cursor: grabbing;
  }

  .page-text {
    font-size: var(--text-base);
    line-height: 1.8;
    color: var(--text-primary);
    white-space: pre-wrap;
    transform-origin: top left;
    transition: transform 0.15s ease;
  }

  .page-text :global(.highlight) {
    background: rgba(245, 158, 11, 0.25);
    color: var(--text-primary);
    padding: 2px 4px;
    border-radius: 3px;
    border-bottom: 2px solid var(--warning);
    font-weight: var(--weight-medium);
  }

  /* ── Footer ─────────────────────── */
  .viewer-footer {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-5);
    border-top: 1px solid var(--border-subtle);
    flex-wrap: wrap;
  }

  .footer-label {
    font-size: var(--text-xs);
    color: var(--text-muted);
  }

  .citation-pill {
    font-size: var(--text-xs);
    padding: 2px 10px;
    border-radius: var(--radius-full);
    background: rgba(16, 163, 127, 0.1);
    color: var(--accent-primary);
    font-weight: var(--weight-medium);
  }

  @media (max-width: 600px) {
    .viewer-overlay {
      padding: var(--space-2);
    }
    .viewer-panel {
      max-height: calc(100vh - 32px);
    }
  }
</style>
