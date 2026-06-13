<script>
  import {
    settingsOpen,
    suggestionsEnabled,
    theme,
    webSearchEnabled,
    verifyClaimsEnabled,
  } from '../lib/stores.js';

  // Click-outside dismissal — bound to the popup root.
  function clickOutside(node, callback) {
    function handle(e) {
      if (node && !node.contains(e.target)) callback();
    }
    document.addEventListener('mousedown', handle, true);
    return { destroy() { document.removeEventListener('mousedown', handle, true); } };
  }

  function close() {
    settingsOpen.set(false);
  }
</script>

<div
  class="settings-popup"
  use:clickOutside={close}
  role="dialog"
  aria-label="Preferences"
>
  <div class="popup-header">
    <div class="popup-title">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
      <span>Preferences</span>
    </div>
    <button class="popup-close" onclick={close} aria-label="Close">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path d="M18 6L6 18M6 6l12 12" />
      </svg>
    </button>
  </div>

  <!-- ── Appearance ─────────────────── -->
  <div class="pref-group">
    <div class="pref-section">Appearance</div>
    <label class="pref-row">
      <span class="pref-text">
        <span class="pref-label">Dark mode</span>
        <span class="pref-desc">Use the dark interface. Turn off for the light theme.</span>
      </span>
      <button
        class="switch"
        class:on={$theme === 'dark'}
        role="switch"
        aria-checked={$theme === 'dark'}
        aria-label="Toggle dark mode"
        onclick={() => theme.update((t) => (t === 'dark' ? 'light' : 'dark'))}
      >
        <span class="switch-thumb"></span>
      </button>
    </label>
  </div>

  <!-- ── Answering ──────────────────── -->
  <div class="pref-group">
    <div class="pref-section">Answering</div>

    <label class="pref-row">
      <span class="pref-text">
        <span class="pref-label">Smart suggestions</span>
        <span class="pref-desc">Follow-up &amp; refine chips under each answer. Each is a small extra model call — turn off to save tokens.</span>
      </span>
      <button
        class="switch"
        class:on={$suggestionsEnabled}
        role="switch"
        aria-checked={$suggestionsEnabled}
        aria-label="Toggle smart suggestions"
        onclick={() => suggestionsEnabled.update((v) => !v)}
      >
        <span class="switch-thumb"></span>
      </button>
    </label>

    <label class="pref-row">
      <span class="pref-text">
        <span class="pref-label">Web search</span>
        <span class="pref-desc">Let answers pull in live web results. Also toggleable from the composer.</span>
      </span>
      <button
        class="switch"
        class:on={$webSearchEnabled}
        role="switch"
        aria-checked={$webSearchEnabled}
        aria-label="Toggle web search"
        onclick={() => webSearchEnabled.update((v) => !v)}
      >
        <span class="switch-thumb"></span>
      </button>
    </label>

    <label class="pref-row">
      <span class="pref-text">
        <span class="pref-label">Claim verification</span>
        <span class="pref-desc">Fact-check each answer's claims against its sources. Adds a verification pass.</span>
      </span>
      <button
        class="switch"
        class:on={$verifyClaimsEnabled}
        role="switch"
        aria-checked={$verifyClaimsEnabled}
        aria-label="Toggle claim verification"
        onclick={() => verifyClaimsEnabled.update((v) => !v)}
      >
        <span class="switch-thumb"></span>
      </button>
    </label>
  </div>

  <div class="popup-footer">Preferences are saved on this device.</div>
</div>

<style>
  .settings-popup {
    position: absolute;
    top: calc(100% + 10px);
    right: 0;
    width: 340px;
    max-width: calc(100vw - 32px);
    max-height: min(600px, calc(100vh - 90px));
    overflow-y: auto;
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    padding: var(--space-4);
    box-shadow: var(--shadow-lg), 0 0 0 1px rgba(var(--overlay-rgb), 0.03);
    z-index: 200;
    animation: popupIn 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
    transform-origin: top right;
  }
  @keyframes popupIn {
    from { opacity: 0; transform: translateY(-4px) scale(0.97); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .popup-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-4);
  }
  .popup-title {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-secondary);
  }
  .popup-close {
    width: 26px;
    height: 26px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .popup-close:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  /* ── Grouped sections ───────────── */
  .pref-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .pref-group + .pref-group {
    margin-top: var(--space-4);
    padding-top: var(--space-4);
    border-top: 1px solid var(--border-subtle);
  }
  .pref-section {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
  }

  /* ── Preference row ─────────────── */
  .pref-row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    cursor: pointer;
  }
  .pref-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }
  .pref-label {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
  }
  .pref-desc {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    line-height: var(--leading-normal);
  }

  /* ── Switch ─────────────────────── */
  .switch {
    flex-shrink: 0;
    position: relative;
    width: 38px;
    height: 22px;
    border-radius: var(--radius-full);
    background: var(--bg-hover);
    border: 1px solid var(--border-default);
    transition: background var(--duration-fast), border-color var(--duration-fast);
    margin-top: 2px;
  }
  .switch.on {
    background: var(--accent-primary);
    border-color: var(--accent-primary);
  }
  .switch-thumb {
    position: absolute;
    top: 50%;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #ffffff;
    transform: translateY(-50%);
    transition: left var(--duration-fast) var(--ease-out);
    box-shadow: var(--shadow-sm);
  }
  .switch.on .switch-thumb {
    left: 18px;
  }

  .popup-footer {
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border-subtle);
    font-size: 10px;
    color: var(--text-muted);
    text-align: center;
    letter-spacing: 0.02em;
  }

  @media (max-width: 480px) {
    .settings-popup {
      width: calc(100vw - 32px);
      right: 16px;
    }
  }
</style>
