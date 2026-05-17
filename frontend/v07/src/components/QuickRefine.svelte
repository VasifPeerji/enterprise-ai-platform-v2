<script>
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { generateSmartSuggestions } from '../lib/api.js';
  import { sessionId, walletBalance } from '../lib/stores.js';

  // `message` = the assistant response to refine.
  // `userMessage` = the immediately-preceding user turn — supplies extra
  // context for the LLM (the action labels should fit the user's intent).
  let { message, userMessage = null } = $props();

  const dispatch = createEventDispatcher();

  let actions = $state([]);     // [{ label, prompt }, ...]
  let loading = $state(false);
  let failed = $state(false);
  let inFlight = null;

  function extractPlainText(content) {
    if (!Array.isArray(content)) return '';
    return content
      .filter((b) => b?.type === 'text')
      .map((b) => b.text || '')
      .join('\n\n')
      .trim();
  }

  // ── Effect: ask the LLM for tailored refine actions ──
  // The smart-suggestions API caches per message id and dedupes concurrent
  // calls, so even though FollowUpSuggestions hits the same function for
  // the same message, only one network round-trip actually fires.
  $effect(() => {
    const msgId = message?.id;
    if (!msgId) return;

    failed = false;

    const userText = extractPlainText(userMessage?.content);
    const responseText = extractPlainText(message?.content);

    // Refine is meaningless for very short responses — skip the call.
    if (!responseText || responseText.length < 100) {
      actions = [];
      loading = false;
      return;
    }

    if (inFlight) inFlight.abort();
    inFlight = new AbortController();
    const localCtrl = inFlight;

    loading = true;
    actions = [];

    generateSmartSuggestions({
      messageId: msgId,
      userText,
      responseText,
      sessionId: get(sessionId),
      signal: localCtrl.signal,
    })
      .then(({ refineActions, cost }) => {
        if (localCtrl.signal.aborted) return;
        actions = Array.isArray(refineActions) ? refineActions : [];
        if (cost?.balanceUsd != null) walletBalance.set(cost.balanceUsd);
      })
      .catch((e) => {
        if (localCtrl.signal.aborted || e?.name === 'AbortError') return;
        console.warn('[V07] Refine actions failed:', e?.message || e);
        failed = true;
        actions = [];
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

  // Click handler — wraps the action's instruction with the original
  // response inlined, since the backend doesn't keep per-session chat
  // history. The LLM receiving this turn sees "instruction + original"
  // and produces the refined version in one shot.
  function run(action) {
    const original = extractPlainText(message?.content);
    if (!original) return;
    const fullPrompt =
      `${action.prompt}\n\n` +
      `---\n\n` +
      `Original response to refine (apply the instruction above to this exact text and output ONLY the refined version, no preamble):\n\n` +
      `${original}`;
    dispatch('refine', { id: action.label, prompt: fullPrompt });
  }
</script>

{#if loading}
  <div class="quick-refine">
    <div class="qr-header">
      <svg class="qr-spark" width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4-6.2-4.5-6.2 4.5 2.4-7.4L2 9.4h7.6L12 2z"/>
      </svg>
      <span>Refine</span>
    </div>
    <div class="qr-skel-row">
      <div class="qr-skel" style="width: 90px;"></div>
      <div class="qr-skel" style="width: 110px;"></div>
      <div class="qr-skel" style="width: 80px;"></div>
      <div class="qr-skel" style="width: 100px;"></div>
    </div>
  </div>
{:else if !failed && actions.length > 0}
  <div class="quick-refine">
    <div class="qr-header">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4-6.2-4.5-6.2 4.5 2.4-7.4L2 9.4h7.6L12 2z"/>
      </svg>
      <span>Refine</span>
    </div>
    <div class="qr-chips">
      {#each actions as a, i}
        <button
          class="qr-chip"
          onclick={() => run(a)}
          title={a.prompt}
          style="animation-delay: {i * 40}ms"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-9-9c2.49 0 4.83.97 6.59 2.74L21 8"/>
            <path d="M21 3v5h-5"/>
          </svg>
          <span>{a.label}</span>
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .quick-refine {
    margin-top: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    animation: refineSlideIn 0.3s var(--ease-out);
  }
  @keyframes refineSlideIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .qr-header {
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
  .qr-header svg { color: var(--accent-primary); }
  .qr-spark {
    animation: sparkleSpin 1.4s ease-in-out infinite;
    transform-origin: center;
  }
  @keyframes sparkleSpin {
    0%, 100% { transform: scale(0.85) rotate(0deg); opacity: 0.6; }
    50% { transform: scale(1.1) rotate(180deg); opacity: 1; }
  }

  .qr-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  .qr-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border-radius: var(--radius-full);
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    transition: all var(--duration-fast);
    opacity: 0;
    transform: translateY(3px);
    animation: chipFadeIn 0.3s var(--ease-out) forwards;
  }
  @keyframes chipFadeIn {
    to { opacity: 1; transform: translateY(0); }
  }
  .qr-chip:hover {
    background: rgba(16, 163, 127, 0.1);
    border-color: rgba(16, 163, 127, 0.4);
    color: var(--text-primary);
    transform: translateY(-1px);
  }
  .qr-chip svg {
    color: var(--accent-primary);
    flex-shrink: 0;
  }

  /* Loading skeletons — pill-shaped to hint at the chips that will follow. */
  .qr-skel-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  .qr-skel {
    height: 24px;
    border-radius: var(--radius-full);
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 0.025) 0%,
      rgba(255, 255, 255, 0.07) 50%,
      rgba(255, 255, 255, 0.025) 100%
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
