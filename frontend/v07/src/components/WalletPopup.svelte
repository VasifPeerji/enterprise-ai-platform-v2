<script>
  import {
    walletBalance,
    walletTransactions,
    walletPopupOpen,
    lastCostCharged,
    sessionId,
    clearTransactions,
  } from '../lib/stores.js';
  import { resetWallet } from '../lib/api.js';

  let refilling = $state(false);
  let refillError = $state('');
  let popupEl = $state(null);

  // Click-outside dismissal — bound to the popup root.
  function clickOutside(node, callback) {
    function handle(e) {
      if (node && !node.contains(e.target)) callback();
    }
    document.addEventListener('mousedown', handle, true);
    return { destroy() { document.removeEventListener('mousedown', handle, true); } };
  }

  async function handleRefill() {
    if (refilling) return;
    refilling = true;
    refillError = '';
    try {
      const newBalance = await resetWallet($sessionId);
      walletBalance.set(newBalance);
      lastCostCharged.set(0);
      clearTransactions();
    } catch (e) {
      refillError = e.message || 'Refill failed. Is the backend running?';
    } finally {
      refilling = false;
    }
  }

  function close() {
    walletPopupOpen.set(false);
  }

  // ── Derived totals ───────────────────────────────────
  let totalSpent = $derived(
    $walletTransactions.reduce((s, t) => s + (t.amount || 0), 0),
  );
  let isLow = $derived($walletBalance < 5);

  // ── Time formatting ──────────────────────────────────
  function relativeTime(iso) {
    const ms = Date.now() - new Date(iso).getTime();
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }

  function fmtCost(v) {
    if (v < 0.0001) return '<$0.0001';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    return `$${v.toFixed(2)}`;
  }

  function fmtBalance(v) {
    return Number(v).toFixed(2);
  }
</script>

<div
  class="wallet-popup"
  bind:this={popupEl}
  use:clickOutside={close}
  role="dialog"
  aria-label="Wallet"
>
  <!-- ── Header ───────────────────────── -->
  <div class="popup-header">
    <div class="popup-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/>
        <path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/>
        <path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>
      </svg>
      <span>Demo Wallet</span>
    </div>
    <button class="popup-close" onclick={close} aria-label="Close">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path d="M18 6L6 18M6 6l12 12"/>
      </svg>
    </button>
  </div>

  <!-- ── Balance card ─────────────────── -->
  <div class="balance-card" class:low={isLow}>
    <div class="balance-glow"></div>
    <span class="balance-label">Current Balance</span>
    {#key $walletBalance}
      <div class="balance-amount">
        <span class="balance-currency">$</span>{fmtBalance($walletBalance)}
      </div>
    {/key}
    <span class="balance-sub">
      {isLow ? '⚠️ Running low — consider refilling' : 'Simulated USD · per-token billing'}
    </span>
  </div>

  <!-- ── Refill button ───────────────── -->
  <button
    class="refill-btn"
    onclick={handleRefill}
    disabled={refilling}
    aria-label="Refill wallet to $25"
  >
    {#if refilling}
      <span class="btn-spinner"></span>
      <span>Refilling…</span>
    {:else}
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12a9 9 0 1 1-9-9c2.49 0 4.83.97 6.59 2.74L21 8"/>
        <path d="M21 3v5h-5"/>
      </svg>
      <span>Refill to $25.00</span>
    {/if}
  </button>

  {#if refillError}
    <div class="refill-error">{refillError}</div>
  {/if}

  <!-- ── Activity feed ───────────────── -->
  <div class="activity-section">
    <div class="activity-header">
      <span class="activity-title">Recent Activity</span>
      {#if $walletTransactions.length}
        <span class="activity-total">{fmtCost(totalSpent)} spent</span>
      {/if}
    </div>

    {#if $walletTransactions.length === 0}
      <div class="activity-empty">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>
        </svg>
        <span>No charges yet — start a chat to see activity here.</span>
      </div>
    {:else}
      <div class="activity-list">
        {#each $walletTransactions.slice(0, 8) as tx}
          <div class="activity-row">
            <div class="activity-icon" class:web-mode={tx.mode === 'web_search'} class:file-mode={tx.mode === 'file_rag'}>
              {#if tx.mode === 'web_search'}
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>
                </svg>
              {:else if tx.mode === 'file_rag'}
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/>
                </svg>
              {:else}
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
              {/if}
            </div>
            <div class="activity-info">
              <span class="activity-model">{tx.modelName}</span>
              <span class="activity-time">{relativeTime(tx.timestamp)}</span>
            </div>
            <span class="activity-amount">−{fmtCost(tx.amount)}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- ── Footer note ─────────────────── -->
  <div class="popup-footer">
    Demo balance · resets independent of real billing
  </div>
</div>

<style>
  .wallet-popup {
    position: absolute;
    top: calc(100% + 10px);
    right: 0;
    width: 360px;
    max-width: calc(100vw - 32px);
    background: linear-gradient(180deg, rgba(28, 28, 38, 0.96) 0%, rgba(18, 18, 26, 0.98) 100%);
    backdrop-filter: blur(16px) saturate(140%);
    -webkit-backdrop-filter: blur(16px) saturate(140%);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    padding: var(--space-4);
    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(var(--overlay-rgb), 0.03);
    z-index: 200;
    animation: popupIn 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
    transform-origin: top right;
  }
  @keyframes popupIn {
    from { opacity: 0; transform: translateY(-4px) scale(0.97); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  /* ── Header ─────────────────────── */
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

  /* ── Balance card ──────────────── */
  .balance-card {
    position: relative;
    overflow: hidden;
    text-align: center;
    padding: var(--space-5) var(--space-4) var(--space-4);
    border-radius: var(--radius-lg);
    background: linear-gradient(
      135deg,
      rgba(16, 163, 127, 0.18) 0%,
      rgba(14, 165, 233, 0.12) 60%,
      rgba(139, 92, 246, 0.14) 100%
    );
    border: 1px solid rgba(16, 163, 127, 0.25);
    margin-bottom: var(--space-3);
  }
  .balance-card.low {
    background: linear-gradient(
      135deg,
      rgba(245, 158, 11, 0.16) 0%,
      rgba(239, 68, 68, 0.14) 100%
    );
    border-color: rgba(245, 158, 11, 0.35);
  }
  .balance-glow {
    position: absolute;
    top: -40%;
    left: 50%;
    width: 200%;
    height: 200%;
    transform: translateX(-50%);
    background: radial-gradient(circle, rgba(16, 163, 127, 0.18) 0%, transparent 50%);
    pointer-events: none;
    animation: glow 4s ease-in-out infinite;
  }
  .balance-card.low .balance-glow {
    background: radial-gradient(circle, rgba(245, 158, 11, 0.2) 0%, transparent 50%);
  }
  @keyframes glow {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  .balance-label {
    position: relative;
    display: block;
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: var(--space-2);
  }
  .balance-amount {
    position: relative;
    font-family: var(--font-mono);
    font-size: 42px;
    font-weight: var(--weight-bold);
    line-height: 1;
    background: linear-gradient(180deg, #ffffff 0%, #b4b4c4 100%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    letter-spacing: -0.02em;
    animation: balanceFlash 0.4s var(--ease-out);
  }
  .balance-card.low .balance-amount {
    background: linear-gradient(180deg, #fbbf24 0%, #f59e0b 100%);
    -webkit-background-clip: text;
    background-clip: text;
  }
  @keyframes balanceFlash {
    from { transform: scale(0.96); opacity: 0.6; }
    to { transform: scale(1); opacity: 1; }
  }
  .balance-currency {
    font-size: 24px;
    vertical-align: top;
    margin-right: 1px;
    opacity: 0.7;
  }
  .balance-sub {
    position: relative;
    display: block;
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin-top: var(--space-2);
  }

  /* ── Refill button ──────────────── */
  .refill-btn {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--accent-primary);
    color: white;
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    transition: all var(--duration-fast) var(--ease-out);
    margin-bottom: var(--space-2);
  }
  .refill-btn:hover:not(:disabled) {
    background: var(--accent-hover);
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(16, 163, 127, 0.35);
  }
  .refill-btn:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }
  .btn-spinner {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid rgba(var(--overlay-rgb), 0.3);
    border-top-color: white;
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .refill-error {
    padding: var(--space-2) var(--space-3);
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-xs);
    margin-bottom: var(--space-2);
  }

  /* ── Activity feed ──────────────── */
  .activity-section {
    margin-top: var(--space-4);
  }
  .activity-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-1);
    margin-bottom: var(--space-2);
  }
  .activity-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
  }
  .activity-total {
    font-size: var(--text-xs);
    font-family: var(--font-mono);
    color: var(--text-tertiary);
  }
  .activity-empty {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px dashed var(--border-subtle);
    border-radius: var(--radius-md);
    font-size: var(--text-xs);
    color: var(--text-muted);
    line-height: 1.4;
  }
  .activity-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 220px;
    overflow-y: auto;
  }
  .activity-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2);
    border-radius: var(--radius-sm);
    transition: background var(--duration-fast);
  }
  .activity-row:hover { background: rgba(var(--overlay-rgb), 0.04); }
  .activity-icon {
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(var(--overlay-rgb), 0.06);
    color: var(--text-secondary);
    flex-shrink: 0;
  }
  .activity-icon.web-mode {
    background: rgba(16, 163, 127, 0.12);
    color: var(--accent-primary);
  }
  .activity-icon.file-mode {
    background: rgba(139, 92, 246, 0.12);
    color: #c4b5fd;
  }
  .activity-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .activity-model {
    font-size: var(--text-xs);
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .activity-time {
    font-size: 10px;
    color: var(--text-muted);
    font-family: var(--font-mono);
  }
  .activity-amount {
    font-size: var(--text-xs);
    font-family: var(--font-mono);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  /* ── Footer ─────────────────────── */
  .popup-footer {
    margin-top: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border-subtle);
    font-size: 10px;
    color: var(--text-muted);
    text-align: center;
    letter-spacing: 0.02em;
  }

  @media (max-width: 480px) {
    .wallet-popup {
      width: calc(100vw - 32px);
      right: 16px;
    }
    .balance-amount { font-size: 36px; }
  }
</style>
