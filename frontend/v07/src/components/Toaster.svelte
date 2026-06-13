<script>
  import { toasts, dismissToast } from '../lib/stores.js';

  // Per-type accent + icon. Kept tiny — toasts are glanceable, not detailed.
  const ICONS = {
    success: '<path d="M5 12l5 5L20 7"/>',
    error: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    warning: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  };

  function runAction(t) {
    try { t.action?.onClick?.(); } finally { dismissToast(t.id); }
  }
</script>

<div class="toaster" role="region" aria-label="Notifications" aria-live="polite">
  {#each $toasts as t (t.id)}
    <div class="toast {t.type}" role="status">
      <svg class="toast-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        {@html ICONS[t.type] || ICONS.info}
      </svg>
      <span class="toast-msg">{t.message}</span>
      {#if t.action?.label}
        <button class="toast-action" onclick={() => runAction(t)}>{t.action.label}</button>
      {/if}
      <button class="toast-close" onclick={() => dismissToast(t.id)} aria-label="Dismiss">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>
  {/each}
</div>

<style>
  .toaster {
    position: fixed;
    bottom: calc(var(--space-4) + 84px); /* clear the input bar */
    left: 50%;
    transform: translateX(-50%);
    z-index: 300;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    pointer-events: none;
    width: max-content;
    max-width: min(92vw, 460px);
  }

  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    box-shadow: var(--shadow-lg);
    font-size: var(--text-sm);
    color: var(--text-primary);
    max-width: 100%;
    animation: toastIn 0.24s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes toastIn {
    from { opacity: 0; transform: translateY(8px) scale(0.97); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .toast-icon { flex-shrink: 0; }
  .toast.success .toast-icon { color: var(--success); }
  .toast.error .toast-icon { color: var(--error); }
  .toast.warning .toast-icon { color: var(--warning); }
  .toast.info .toast-icon { color: var(--accent-primary); }

  .toast-msg {
    flex: 1;
    min-width: 0;
    line-height: var(--leading-normal);
  }

  .toast-action {
    flex-shrink: 0;
    padding: 3px 10px;
    border-radius: var(--radius-sm);
    background: rgba(var(--overlay-rgb), 0.06);
    border: 1px solid var(--border-subtle);
    color: var(--accent-primary);
    font-size: var(--text-xs);
    font-weight: var(--weight-semibold);
    transition: all var(--duration-fast);
  }
  .toast-action:hover { background: rgba(16, 163, 127, 0.12); }

  .toast-close {
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .toast-close:hover { background: var(--bg-hover); color: var(--text-primary); }

  @media (max-width: 600px) {
    .toaster { bottom: calc(var(--space-3) + 76px); }
  }
</style>
