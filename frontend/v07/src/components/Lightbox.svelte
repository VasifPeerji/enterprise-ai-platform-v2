<script>
  import { lightboxImage } from '../lib/stores.js';

  let zoomed = $state(false);

  function close() {
    zoomed = false;
    lightboxImage.set(null);
  }
  function toggleZoom(e) {
    e.stopPropagation();
    zoomed = !zoomed;
  }
  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if $lightboxImage}
  <div class="lb-overlay" onclick={close} role="presentation">
    <div class="lb-controls">
      <button class="lb-btn" onclick={(e) => { e.stopPropagation(); toggleZoom(e); }} aria-label={zoomed ? 'Zoom out' : 'Zoom in'} title={zoomed ? 'Zoom out' : 'Zoom in'}>
        {#if zoomed}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M8 11h6"/></svg>
        {:else}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M11 8v6M8 11h6"/></svg>
        {/if}
      </button>
      <button class="lb-btn" onclick={close} aria-label="Close" title="Close">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>

    <div class="lb-stage" class:zoomed onclick={(e) => e.stopPropagation()} role="presentation">
      <img
        src={$lightboxImage.src}
        alt={$lightboxImage.alt || 'Image'}
        class:zoomed
        onclick={toggleZoom}
      />
      {#if $lightboxImage.caption}
        <div class="lb-caption">{$lightboxImage.caption}</div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .lb-overlay {
    position: fixed;
    inset: 0;
    z-index: 240;
    background: rgba(0, 0, 0, 0.85);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-8);
    animation: lbFade 0.16s var(--ease-out);
  }
  @keyframes lbFade { from { opacity: 0; } to { opacity: 1; } }

  .lb-controls {
    position: fixed;
    top: var(--space-4);
    right: var(--space-4);
    display: flex;
    gap: var(--space-2);
  }
  .lb-btn {
    width: 38px;
    height: 38px;
    border-radius: var(--radius-full);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.18);
    transition: background var(--duration-fast);
  }
  .lb-btn:hover { background: rgba(255, 255, 255, 0.2); }

  .lb-stage {
    max-width: 100%;
    max-height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    overflow: auto;
  }
  .lb-stage img {
    max-width: 100%;
    max-height: 82vh;
    object-fit: contain;
    border-radius: var(--radius-md);
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
    cursor: zoom-in;
    transition: transform 0.2s var(--ease-out);
    animation: lbPop 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .lb-stage img.zoomed {
    max-width: none;
    max-height: none;
    cursor: zoom-out;
  }
  @keyframes lbPop {
    from { opacity: 0; transform: scale(0.96); }
    to { opacity: 1; transform: scale(1); }
  }
  .lb-caption {
    color: rgba(255, 255, 255, 0.8);
    font-size: var(--text-sm);
    text-align: center;
    max-width: 720px;
  }
</style>
