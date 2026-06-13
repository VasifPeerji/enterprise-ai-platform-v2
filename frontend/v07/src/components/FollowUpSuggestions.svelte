<script>
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { generateSmartSuggestions } from '../lib/api.js';
  import { sessionId, walletBalance } from '../lib/stores.js';

  // `message` = the assistant response to suggest follow-ups for.
  // `userMessage` = the immediately-preceding user turn (the question).
  let { message, userMessage = null } = $props();

  const dispatch = createEventDispatcher();

  // The smart-suggestions API caches by message id internally, so we don't
  // need a second local cache. Both FollowUpSuggestions and QuickRefine
  // resolve to the same memoised result for any given message.

  let suggestions = $state([]);
  let loading = $state(false);
  let failed = $state(false);
  let inFlight = null; // AbortController for the active request

  function extractPlainText(content) {
    if (!Array.isArray(content)) return '';
    return content
      .filter((b) => b?.type === 'text')
      .map((b) => b.text || '')
      .join(' ')
      .trim();
  }

  // ── Effect: fetch (or read cache) whenever the message changes ──
  // The component is only rendered when isLastAssistant is true, but the
  // message itself can be a new one after each turn, so we key the cache
  // by message.id and refetch when the id changes.
  $effect(() => {
    const msgId = message?.id;
    if (!msgId) return;

    failed = false;

    const userText = extractPlainText(userMessage?.content);
    const responseText = extractPlainText(message?.content);

    // Don't burn an LLM call on trivial responses — nothing meaningful to
    // suggest, and the round-trip latency would feel wasted.
    if (!responseText || responseText.length < 80) {
      suggestions = [];
      loading = false;
      return;
    }

    // Abort any prior in-flight call (e.g. user regenerated faster than the
    // suggestions came back).
    if (inFlight) inFlight.abort();
    inFlight = new AbortController();
    const localCtrl = inFlight;

    loading = true;
    suggestions = [];

    generateSmartSuggestions({
      messageId: msgId,
      userText,
      responseText,
      sessionId: get(sessionId),
      signal: localCtrl.signal,
    })
      .then(({ followUps, cost }) => {
        if (localCtrl.signal.aborted) return;
        if (!Array.isArray(followUps) || followUps.length === 0) {
          failed = true;
          suggestions = [];
        } else {
          suggestions = followUps;
        }
        // Silently sync the wallet — the smart-suggestions LLM call charges
        // the simulated wallet but we don't record a transaction row so the
        // activity feed stays focused on the user's own turns. Balance
        // still reflects the backend truth.
        if (cost?.balanceUsd != null) walletBalance.set(cost.balanceUsd);
      })
      .catch((e) => {
        if (localCtrl.signal.aborted || e?.name === 'AbortError') return;
        console.warn('[V07] Smart suggestions failed:', e?.message || e);
        failed = true;
        suggestions = [];
      })
      .finally(() => {
        if (localCtrl === inFlight) {
          loading = false;
          inFlight = null;
        }
      });
  });

  onDestroy(() => {
    if (inFlight) inFlight.abort();
  });

  function pick(text) {
    dispatch('pick', { message: text });
  }
</script>

{#if loading}
  <div class="followups">
    <div class="fu-header">
      <svg class="fu-sparkle" width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4-6.2-4.5-6.2 4.5 2.4-7.4L2 9.4h7.6L12 2z"/>
      </svg>
      <span>Suggesting follow-ups…</span>
    </div>
    <div class="fu-skeleton-list">
      <div class="fu-skel" style="width: 72%;"></div>
      <div class="fu-skel" style="width: 58%;"></div>
      <div class="fu-skel" style="width: 80%;"></div>
      <div class="fu-skel" style="width: 64%;"></div>
    </div>
  </div>
{:else if !failed && suggestions.length > 0}
  <div class="followups">
    <div class="fu-header">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4-6.2-4.5-6.2 4.5 2.4-7.4L2 9.4h7.6L12 2z"/>
      </svg>
      <span>Try asking</span>
    </div>
    <div class="fu-list">
      {#each suggestions as s, i}
        <button
          class="fu-chip"
          onclick={() => pick(s)}
          style="animation-delay: {i * 50}ms"
          title={s}
        >
          {s}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14M12 5l7 7-7 7"/>
          </svg>
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .followups {
    margin-top: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px dashed var(--border-subtle);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .fu-header {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding-left: 2px;
  }
  .fu-header svg {
    color: var(--accent-primary);
  }
  .fu-sparkle {
    animation: sparkleSpin 1.4s ease-in-out infinite;
    transform-origin: center;
  }
  @keyframes sparkleSpin {
    0%, 100% { transform: scale(0.85) rotate(0deg); opacity: 0.6; }
    50% { transform: scale(1.1) rotate(180deg); opacity: 1; }
  }

  /* ── Loaded suggestions ──────────────────────── */
  .fu-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .fu-chip {
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: 8px 12px;
    border-radius: var(--radius-md);
    background: rgba(var(--overlay-rgb), 0.03);
    border: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
    transition: all var(--duration-fast);
    width: fit-content;
    max-width: 100%;
    opacity: 0;
    transform: translateY(4px);
    animation: chipFadeIn 0.3s var(--ease-out) forwards;
  }
  @keyframes chipFadeIn {
    to { opacity: 1; transform: translateY(0); }
  }
  .fu-chip:hover {
    background: rgba(16, 163, 127, 0.08);
    border-color: rgba(16, 163, 127, 0.4);
    color: var(--text-primary);
    transform: translateX(2px);
  }
  .fu-chip:hover svg {
    color: var(--accent-primary);
    transform: translateX(2px);
  }
  .fu-chip svg {
    color: var(--text-muted);
    flex-shrink: 0;
    transition: all var(--duration-fast);
  }

  /* ── Loading skeletons ───────────────────────── */
  .fu-skeleton-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .fu-skel {
    height: 32px;
    border-radius: var(--radius-md);
    background: linear-gradient(
      90deg,
      rgba(var(--overlay-rgb), 0.025) 0%,
      rgba(var(--overlay-rgb), 0.07) 50%,
      rgba(var(--overlay-rgb), 0.025) 100%
    );
    background-size: 200% 100%;
    animation: shimmerStripe 1.5s linear infinite;
    border: 1px solid var(--border-subtle);
  }
  @keyframes shimmerStripe {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
</style>
