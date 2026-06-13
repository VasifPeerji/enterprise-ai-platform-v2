<script>
  import { shortcutsOpen } from '../lib/stores.js';

  // Platform-aware modifier label (⌘ on macOS, Ctrl elsewhere).
  const mod =
    typeof navigator !== 'undefined' && /mac/i.test(navigator.platform || '')
      ? '⌘'
      : 'Ctrl';

  const groups = [
    {
      title: 'General',
      items: [
        { keys: [mod, 'K'], label: 'Command palette' },
        { keys: [mod, 'N'], label: 'New chat' },
        { keys: ['?'], label: 'This shortcuts sheet' },
        { keys: ['Esc'], label: 'Close dialog / stop streaming' },
      ],
    },
    {
      title: 'Composer',
      items: [
        { keys: ['Enter'], label: 'Send message' },
        { keys: ['Shift', 'Enter'], label: 'New line' },
        { keys: ['Drop'], label: 'Drag a file onto the window to attach' },
      ],
    },
  ];

  function close() {
    shortcutsOpen.set(false);
  }
  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="sc-overlay" onclick={close} role="presentation">
  <div class="sc-panel" onclick={(e) => e.stopPropagation()} role="dialog" aria-label="Keyboard shortcuts">
    <div class="sc-header">
      <h3>Keyboard shortcuts</h3>
      <button class="sc-close" onclick={close} aria-label="Close">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
      </button>
    </div>
    <div class="sc-body">
      {#each groups as g}
        <div class="sc-group">
          <div class="sc-group-title">{g.title}</div>
          {#each g.items as item}
            <div class="sc-row">
              <span class="sc-label">{item.label}</span>
              <span class="sc-keys">
                {#each item.keys as k, i}
                  <kbd>{k}</kbd>{#if i < item.keys.length - 1}<span class="sc-plus">+</span>{/if}
                {/each}
              </span>
            </div>
          {/each}
        </div>
      {/each}
    </div>
  </div>
</div>

<style>
  .sc-overlay {
    position: fixed;
    inset: 0;
    z-index: 220;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-4);
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    animation: scFade 0.15s var(--ease-out);
  }
  @keyframes scFade { from { opacity: 0; } to { opacity: 1; } }

  .sc-panel {
    width: 460px;
    max-width: 100%;
    max-height: 80vh;
    overflow-y: auto;
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    animation: scPop 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes scPop {
    from { opacity: 0; transform: translateY(-6px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .sc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border-subtle);
  }
  .sc-header h3 {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    margin: 0;
  }
  .sc-close {
    width: 30px;
    height: 30px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .sc-close:hover { background: var(--bg-hover); color: var(--text-primary); }

  .sc-body {
    padding: var(--space-4) var(--space-5) var(--space-5);
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }
  .sc-group-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
    margin-bottom: var(--space-2);
  }
  .sc-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-2) 0;
  }
  .sc-label {
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .sc-keys {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
  .sc-keys kbd {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--text-primary);
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-bottom-width: 2px;
    border-radius: var(--radius-sm);
    padding: 2px 7px;
    min-width: 18px;
    text-align: center;
  }
  .sc-plus { color: var(--text-muted); font-size: 11px; }
</style>
