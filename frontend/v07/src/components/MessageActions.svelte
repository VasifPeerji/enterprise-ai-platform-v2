<script>
  import { createEventDispatcher } from 'svelte';
  import { speakingMessageId } from '../lib/stores.js';
  import { getModels } from '../lib/api.js';

  let {
    message,
    role,
    canRegenerate = false,
    disabled = false,
  } = $props();

  const dispatch = createEventDispatcher();

  // Extract a flat readable string from a rich-content array. Used by copy
  // and read-aloud — the bubble may contain text + tables + charts + ..., we
  // want only the prose for clipboard / TTS.
  function extractText(content) {
    if (!Array.isArray(content)) return '';
    const parts = [];
    for (const b of content) {
      if (!b) continue;
      if (b.type === 'text') parts.push(b.text || '');
      else if (b.type === 'table') {
        const rows = [b.headers || [], ...(b.rows || [])];
        parts.push(rows.map((r) => r.join('  |  ')).join('\n'));
      }
    }
    return parts
      .join('\n\n')
      // Strip markdown emphasis / links / headings for cleaner copy + TTS.
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/[*_~`]+/g, '')
      .replace(/^#{1,6}\s+/gm, '')
      .trim();
  }

  let copyState = $state('idle'); // 'idle' | 'success' | 'failed'

  async function handleCopy() {
    if (disabled) return;
    try {
      await navigator.clipboard.writeText(extractText(message.content));
      copyState = 'success';
    } catch {
      copyState = 'failed';
    }
    setTimeout(() => (copyState = 'idle'), 1500);
  }

  function handleToggleReadAloud() {
    if (disabled) return;
    if (!('speechSynthesis' in window)) {
      // Old browser — quietly skip.
      return;
    }
    if ($speakingMessageId === message.id) {
      window.speechSynthesis.cancel();
      speakingMessageId.set(null);
      return;
    }
    // Cancel anything else currently being read, then start fresh.
    window.speechSynthesis.cancel();
    const text = extractText(message.content);
    if (!text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.onend = () => {
      if (window.speechSynthesis.speaking === false) speakingMessageId.set(null);
    };
    utterance.onerror = () => speakingMessageId.set(null);
    window.speechSynthesis.speak(utterance);
    speakingMessageId.set(message.id);
  }

  function handleReaction(reaction) {
    if (disabled) return;
    dispatch('reaction', { reaction });
  }

  function handleEdit() {
    if (disabled) return;
    dispatch('edit');
  }

  function handleRegenerate() {
    if (disabled) return;
    dispatch('regenerate');
  }

  // ── "Try another model" menu ────────────────────────────────
  // Lazy-loads the model list on first open, then re-runs the prompt forcing
  // the chosen model so the same question can be compared across models.
  let modelMenuOpen = $state(false);
  let models = $state([]);
  let modelsLoading = $state(false);
  let modelsError = $state(false);

  async function toggleModelMenu() {
    if (disabled) return;
    modelMenuOpen = !modelMenuOpen;
    if (modelMenuOpen && !models.length && !modelsLoading) {
      modelsLoading = true;
      modelsError = false;
      try {
        models = await getModels();
      } catch {
        modelsError = true;
      } finally {
        modelsLoading = false;
      }
    }
  }

  function pickModel(sel) {
    modelMenuOpen = false;
    dispatch('regenerateWith', { model: sel });
  }

  function clickOutside(node, cb) {
    function handle(e) {
      if (node && !node.contains(e.target)) cb();
    }
    document.addEventListener('mousedown', handle, true);
    return { destroy() { document.removeEventListener('mousedown', handle, true); } };
  }

  function tierColor(tier) {
    if (tier === 'premium') return 'var(--tier-premium)';
    if (tier === 'moderate') return 'var(--tier-moderate)';
    if (tier === 'cheap') return 'var(--tier-cheap)';
    return 'var(--accent-primary)';
  }

  const tierOrder = ['premium', 'moderate', 'cheap'];
  const tierLabel = { premium: 'Premium', moderate: 'Moderate', cheap: 'Budget' };
  let groupedModels = $derived.by(() => {
    const g = {};
    for (const m of models) (g[m.tier] ||= []).push(m);
    return g;
  });

  let isSpeaking = $derived($speakingMessageId === message.id);
  let liked = $derived(message.reaction === 'like');
  let disliked = $derived(message.reaction === 'dislike');
</script>

<div class="msg-actions" class:user={role === 'user'}>
  <!-- ── Copy (both roles) ───────────────────────────── -->
  <button
    class="action-btn"
    class:success={copyState === 'success'}
    class:failed={copyState === 'failed'}
    onclick={handleCopy}
    title={copyState === 'success' ? 'Copied!' : copyState === 'failed' ? 'Failed' : 'Copy'}
    aria-label="Copy message"
    {disabled}
  >
    {#if copyState === 'success'}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M5 12l5 5L20 7"/>
      </svg>
    {:else}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="9" width="13" height="13" rx="2"/>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
      </svg>
    {/if}
  </button>

  {#if role === 'user'}
    <!-- ── Edit (user only) ────────────────────────── -->
    <button class="action-btn" onclick={handleEdit} title="Edit & resend" aria-label="Edit message" {disabled}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
      </svg>
    </button>
  {:else}
    <!-- ── 👍 Like (assistant only) ─────────────────── -->
    <button
      class="action-btn"
      class:liked
      onclick={() => handleReaction('like')}
      title={liked ? 'Remove rating' : 'Good response'}
      aria-label="Like"
      aria-pressed={liked}
      {disabled}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill={liked ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M7 10v12M15 5.88L14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7m8-16.12L9 12v10m6-16.12V4a2 2 0 0 0-2-2"/>
      </svg>
    </button>

    <!-- ── 👎 Dislike (assistant only) ──────────────── -->
    <button
      class="action-btn"
      class:disliked
      onclick={() => handleReaction('dislike')}
      title={disliked ? 'Remove rating' : 'Bad response'}
      aria-label="Dislike"
      aria-pressed={disliked}
      {disabled}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill={disliked ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17 14V2M9 18.12L10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H17m-8 16.12L15 12V2m-6 16.12V20a2 2 0 0 0 2 2"/>
      </svg>
    </button>

    <!-- ── Read aloud (assistant only) ──────────────── -->
    <button
      class="action-btn"
      class:active={isSpeaking}
      onclick={handleToggleReadAloud}
      title={isSpeaking ? 'Stop reading' : 'Read aloud'}
      aria-label={isSpeaking ? 'Stop reading' : 'Read aloud'}
      {disabled}
    >
      {#if isSpeaking}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="1.5"/>
        </svg>
      {:else}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
        </svg>
      {/if}
    </button>

    <!-- ── Regenerate (assistant only) ──────────────── -->
    {#if canRegenerate}
      <button class="action-btn" onclick={handleRegenerate} title="Regenerate response" aria-label="Regenerate" {disabled}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>
          <path d="M21 3v5h-5"/>
          <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>
          <path d="M8 16H3v5"/>
        </svg>
      </button>
    {/if}

    <!-- ── Regenerate with another model (assistant only) ── -->
    {#if canRegenerate}
      <div class="model-menu-wrap" use:clickOutside={() => (modelMenuOpen = false)}>
        <button
          class="action-btn"
          class:menu-open={modelMenuOpen}
          onclick={toggleModelMenu}
          title="Regenerate with another model"
          aria-label="Regenerate with another model"
          aria-haspopup="menu"
          aria-expanded={modelMenuOpen}
          {disabled}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="4" y="4" width="16" height="16" rx="2" />
            <rect x="9" y="9" width="6" height="6" />
            <path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" />
          </svg>
        </button>
        {#if modelMenuOpen}
          <div class="model-menu" role="menu">
            <div class="mm-header">Regenerate with…</div>
            <button class="mm-item" role="menuitem" onclick={() => pickModel({ modelId: 'smart_routing', name: 'Smart Routing', tier: 'smart' })}>
              <span class="mm-dot smart"></span>
              <span class="mm-name">Smart Routing</span>
            </button>
            {#if modelsLoading}
              <div class="mm-note">Loading models…</div>
            {:else if modelsError}
              <div class="mm-note">Couldn’t load models</div>
            {:else}
              {#each tierOrder as tier}
                {#if groupedModels[tier]?.length}
                  <div class="mm-tier">{tierLabel[tier]}</div>
                  {#each groupedModels[tier] as m}
                    <button class="mm-item" role="menuitem" onclick={() => pickModel({ modelId: m.model_id, name: m.display_name, tier: m.tier, provider: m.provider })}>
                      <span class="mm-dot" style="background: {tierColor(m.tier)}"></span>
                      <span class="mm-name">{m.display_name}</span>
                    </button>
                  {/each}
                {/if}
              {/each}
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .msg-actions {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    margin-top: var(--space-2);
    opacity: 0.55;
    transition: opacity var(--duration-fast);
  }
  /* Brighten on bubble hover via parent .message-row:hover (set externally),
     and always show when speech is active so the stop button stays visible. */
  :global(.message-row:hover) .msg-actions,
  .msg-actions:hover,
  .msg-actions:focus-within {
    opacity: 1;
  }
  .msg-actions.user {
    justify-content: flex-end;
  }

  .action-btn {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text-tertiary);
    background: transparent;
    border: none;
    cursor: pointer;
    transition: all var(--duration-fast);
  }
  .action-btn:hover:not(:disabled) {
    background: rgba(var(--overlay-rgb), 0.06);
    color: var(--text-primary);
  }
  .action-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* State-driven colors */
  .action-btn.liked {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.12);
  }
  .action-btn.disliked {
    color: #ef4444;
    background: rgba(239, 68, 68, 0.12);
  }
  .action-btn.success {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.12);
    animation: popSuccess 0.3s var(--ease-out);
  }
  .action-btn.failed {
    color: #ef4444;
    background: rgba(239, 68, 68, 0.12);
  }
  .action-btn.active {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.18);
    animation: speakingPulse 1.6s ease-in-out infinite;
  }
  @keyframes popSuccess {
    0% { transform: scale(0.9); }
    50% { transform: scale(1.12); }
    100% { transform: scale(1); }
  }
  @keyframes speakingPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(16, 163, 127, 0.4); }
    50% { box-shadow: 0 0 0 4px rgba(16, 163, 127, 0); }
  }

  /* ── Try-another-model menu ─────── */
  .model-menu-wrap {
    position: relative;
    display: inline-flex;
  }
  .action-btn.menu-open {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.12);
  }
  .model-menu {
    position: absolute;
    bottom: calc(100% + 6px);
    left: 0;
    z-index: 40;
    min-width: 220px;
    max-height: 320px;
    overflow-y: auto;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 4px;
    box-shadow: var(--shadow-lg);
    animation: mmIn 0.15s var(--ease-out);
  }
  @keyframes mmIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .mm-header {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    font-weight: var(--weight-semibold);
    padding: 6px 8px 4px;
  }
  .mm-tier {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    padding: 6px 8px 2px;
  }
  .mm-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px 8px;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    text-align: left;
    transition: background var(--duration-fast), color var(--duration-fast);
  }
  .mm-item:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .mm-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--text-muted);
  }
  .mm-dot.smart {
    background: var(--accent-primary);
    box-shadow: 0 0 6px var(--accent-glow);
  }
  .mm-name {
    font-size: var(--text-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mm-note {
    padding: 8px;
    font-size: var(--text-xs);
    color: var(--text-muted);
    text-align: center;
  }

  @media (max-width: 600px) {
    .msg-actions { opacity: 1; }
    .action-btn { width: 30px; height: 30px; }
  }
</style>
