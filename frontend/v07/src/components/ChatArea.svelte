<script>
  import {
    currentMessages,
    isTyping,
    activeConversationId,
    streamingMessageId,
    editingMessageId,
  } from '../lib/stores.js';
  import MessageRenderer from './MessageRenderer.svelte';
  import WelcomeScreen from './WelcomeScreen.svelte';
  import LoadingIndicator from './LoadingIndicator.svelte';
  import MessageActions from './MessageActions.svelte';
  import QuickRefine from './QuickRefine.svelte';
  import FollowUpSuggestions from './FollowUpSuggestions.svelte';
  import RoutingInsight from './RoutingInsight.svelte';

  let editingText = $state('');
  let editingTextarea = $state(null);

  async function startEdit(message) {
    // Pull the plain-text prompt out for the textarea seed.
    const text = (message.content || [])
      .filter((b) => b?.type === 'text')
      .map((b) => b.text)
      .join('\n\n');
    editingText = text;
    dispatch('editStart', { messageId: message.id });
    await tick();
    editingTextarea?.focus();
    if (editingTextarea) {
      editingTextarea.style.height = 'auto';
      editingTextarea.style.height = editingTextarea.scrollHeight + 'px';
      editingTextarea.setSelectionRange(text.length, text.length);
    }
  }
  function cancelEdit() {
    editingText = '';
    dispatch('editCancel');
  }
  function commitEdit(message) {
    dispatch('editCommit', { messageId: message.id, text: editingText });
    editingText = '';
  }
  function handleEditKeydown(e, message) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      commitEdit(message);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }
  function autoResize(e) {
    e.target.style.height = 'auto';
    e.target.style.height = e.target.scrollHeight + 'px';
  }
  import { createEventDispatcher, tick, onMount } from 'svelte';

  let { route = { mode: 'chat', collection: null } } = $props();

  const dispatch = createEventDispatcher();
  let scrollContainer = $state(null);

  // ── Smart auto-scroll ───────────────────────────────────────
  // Follow the conversation only while the user is parked near the bottom.
  // If they scroll up to re-read mid-stream, we stop yanking them down and
  // surface a "jump to latest" button instead. A brand-new user turn always
  // pulls the view down (they just acted) — matching ChatGPT/Claude/Gemini.
  let pinnedToBottom = $state(true);
  let showJumpButton = $state(false);
  const NEAR_BOTTOM_PX = 140;

  function recomputePin() {
    if (!scrollContainer) return;
    const dist =
      scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight;
    pinnedToBottom = dist < NEAR_BOTTOM_PX;
    showJumpButton = !pinnedToBottom;
  }

  function scrollToBottom(behavior = 'smooth') {
    if (!scrollContainer) return;
    // Honor the OS reduced-motion setting: a JS scrollTo ignores the CSS
    // scroll-behavior override, so resolve it here.
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    scrollContainer.scrollTo({
      top: scrollContainer.scrollHeight,
      behavior: reduce ? 'auto' : behavior,
    });
    pinnedToBottom = true;
    showJumpButton = false;
  }

  $effect(() => {
    const msgs = $currentMessages;
    const typing = $isTyping; // re-run when the loading indicator toggles
    if (!scrollContainer) return;
    const userJustSent = msgs[msgs.length - 1]?.role === 'user';
    if (pinnedToBottom || userJustSent) {
      tick().then(() => scrollToBottom('smooth'));
    }
  });

  function handleSuggestion(event) {
    // Bubble up to App.svelte for sending
    dispatch('send', { message: event.detail.message });
  }

  function getModelColor(tier) {
    if (tier === 'premium') return 'var(--tier-premium)';
    if (tier === 'moderate') return 'var(--tier-moderate)';
    if (tier === 'cheap') return 'var(--tier-cheap)';
    if (tier === 'grounded') return 'var(--accent-primary)';
    return 'var(--text-muted)';
  }
</script>

<div class="chat-viewport">
  <div class="chat-area" bind:this={scrollContainer} onscroll={recomputePin}>
  {#if !$activeConversationId || $currentMessages.length === 0}
    <WelcomeScreen on:suggestion={handleSuggestion} />
  {:else}
    <div class="messages-container">
      {#each $currentMessages as message, mIdx (message.id)}
        {@const isLastAssistant = message.role === 'assistant'
          && mIdx === $currentMessages.length - 1
          && message.id !== $streamingMessageId}
        {@const isEditing = $editingMessageId === message.id}
        <div class="message-row {message.role}" class:animate-fade-in-up={true}>
          {#if message.role === 'assistant'}
            <div class="avatar bot-avatar">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
              </svg>
            </div>
          {/if}

          <div class="message-column {message.role}">
            <div class="message-bubble {message.role}" class:streaming={message.id === $streamingMessageId} class:editing={isEditing}>
              {#if isEditing && message.role === 'user'}
                <!-- ── Inline edit mode (user message) ─────────── -->
                <textarea
                  bind:this={editingTextarea}
                  bind:value={editingText}
                  oninput={autoResize}
                  onkeydown={(e) => handleEditKeydown(e, message)}
                  class="edit-textarea"
                  rows="2"
                ></textarea>
                <div class="edit-actions">
                  <span class="edit-hint">Enter ↵ to save · Esc to cancel</span>
                  <div class="edit-buttons">
                    <button class="edit-btn-cancel" onclick={cancelEdit}>Cancel</button>
                    <button class="edit-btn-save" onclick={() => commitEdit(message)} disabled={!editingText.trim()}>
                      Save & resend
                    </button>
                  </div>
                </div>
              {:else}
                <MessageRenderer
                  content={message.content || []}
                  role={message.role}
                  streaming={message.id === $streamingMessageId}
                  on:quickReply={(e) => dispatch('send', e.detail)}
                  on:viewProof={(e) => dispatch('viewProof', e.detail)}
                />

                {#if message.role === 'assistant' && message.model && message.id !== $streamingMessageId}
                  <div class="message-meta">
                    <!-- Headline shows the (impressive) commercial model name.
                         Hovering reveals the truth: the real backing model that
                         ran, plus the original→fallback chain when the gateway
                         failed over off a rate-limited free model. -->
                    <span class="meta-model-wrap" class:has-tooltip={message.model?.actualModel}>
                      <span class="meta-model" style="--dot-color: {getModelColor(message.model?.tier)}">
                        <span class="meta-dot"></span>
                        {message.model?.name || 'AI'}
                      </span>
                      {#if message.model?.actualModel}
                        <span class="meta-tooltip" role="tooltip">
                          {#if message.model?.fellBack}
                            <span class="mt-row">
                              <span class="mt-label">Routed to</span>
                              <span class="mt-val">{message.model.requestedModel}</span>
                            </span>
                            <span class="mt-row mt-fallback">
                              <span class="mt-label">{message.model.fallbackReason === 'escalation' ? 'Escalated to' : 'Fell back to'}</span>
                              <span class="mt-val">{message.model.actualModel}</span>
                            </span>
                            <span class="mt-note">
                              {message.model.fallbackReason === 'escalation'
                                ? 'Quality escalation — upgraded mid-flight'
                                : 'Free-tier rate limit — automatic failover'}
                            </span>
                          {:else}
                            <span class="mt-row">
                              <span class="mt-label">Running on</span>
                              <span class="mt-val">{message.model.actualModel}</span>
                            </span>
                          {/if}
                        </span>
                      {/if}
                    </span>
                    {#if message.cost?.chargedUsd > 0}
                      <span class="meta-cost">${message.cost.chargedUsd.toFixed(4)}</span>
                    {/if}
                  </div>
                {/if}

                <!-- Routing transparency — why the smart router picked this
                     model, the query analysis, quality/escalation outcome, and
                     latency/cost. The platform's headline differentiator. -->
                {#if message.role === 'assistant' && message.routing && message.id !== $streamingMessageId}
                  <RoutingInsight
                    routing={message.routing}
                    model={message.model}
                    cost={message.cost}
                  />
                {/if}
              {/if}
            </div>

            <!-- ── Per-message action toolbar (copy, edit, like, etc.) ── -->
            {#if !isEditing && message.id !== $streamingMessageId}
              <MessageActions
                {message}
                role={message.role}
                canRegenerate={message.role === 'assistant'}
                on:reaction={(e) => dispatch('reaction', { messageId: message.id, reaction: e.detail.reaction })}
                on:edit={() => startEdit(message)}
                on:regenerate={() => dispatch('regenerate', { messageId: message.id })}
              />
            {/if}

            <!-- ── Quick refine + follow-ups (only on the latest done response) ── -->
            {#if isLastAssistant}
              <QuickRefine
                {message}
                on:refine={(e) => dispatch('refine', e.detail)}
              />
              <!-- Pass the preceding user message so follow-ups can reason about
                   the original question's intent + subject, not just the
                   response prose. -->
              <FollowUpSuggestions
                {message}
                userMessage={mIdx > 0 && $currentMessages[mIdx - 1]?.role === 'user'
                  ? $currentMessages[mIdx - 1]
                  : null}
                on:pick={(e) => dispatch('followUp', e.detail)}
              />
            {/if}
          </div>

          {#if message.role === 'user'}
            <div class="avatar user-avatar">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 3a4 4 0 100 8 4 4 0 000-8z"/>
              </svg>
            </div>
          {/if}
        </div>
      {/each}

      {#if $isTyping && !$streamingMessageId}
        <div class="message-row assistant animate-fade-in-up">
          <div class="avatar bot-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
          </div>
          <div class="message-bubble assistant loading-bubble">
            <LoadingIndicator />
          </div>
        </div>
      {/if}
    </div>
  {/if}
  </div>

  {#if showJumpButton}
    <button
      class="jump-to-latest"
      onclick={() => scrollToBottom()}
      aria-label="Scroll to latest message"
      title="Scroll to latest"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 5v14M19 12l-7 7-7-7" />
      </svg>
    </button>
  {/if}
</div>

<style>
  .chat-viewport {
    position: relative;
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .chat-area {
    flex: 1;
    overflow-y: auto;
    scroll-behavior: smooth;
    min-height: 0;
  }

  /* ── Jump-to-latest button ───────── */
  .jump-to-latest {
    position: absolute;
    bottom: var(--space-4);
    left: 50%;
    transform: translateX(-50%);
    width: 38px;
    height: 38px;
    border-radius: var(--radius-full);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    color: var(--text-secondary);
    box-shadow: var(--shadow-md);
    z-index: 15;
    animation: jumpIn 0.2s var(--ease-out);
    transition: background var(--duration-fast), color var(--duration-fast),
                transform var(--duration-fast);
  }
  .jump-to-latest:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
    transform: translateX(-50%) translateY(-2px);
  }
  @keyframes jumpIn {
    from { opacity: 0; transform: translateX(-50%) translateY(6px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  .messages-container {
    max-width: var(--chat-max-width);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4) var(--space-12);
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
  }

  /* ── Message row ────────────────── */
  .message-row {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
  }
  .message-row.user {
    justify-content: flex-end;
  }

  /* ── Avatar ─────────────────────── */
  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 2px;
  }
  .bot-avatar {
    background: var(--accent-gradient);
    color: white;
  }
  .user-avatar {
    background: var(--bg-elevated);
    color: var(--text-secondary);
    border: 1px solid var(--border-subtle);
  }

  /* ── Message bubble ─────────────── */
  /* Column wrapper: bubble + action toolbar + refine + follow-ups stack
     vertically and share the same horizontal alignment as the bubble. */
  .message-column {
    display: flex;
    flex-direction: column;
    min-width: 0;
    max-width: 85%;
  }
  .message-column.user {
    align-items: flex-end;
  }
  .message-column.assistant {
    max-width: 90%;
    align-items: stretch;
  }

  .message-bubble {
    min-width: 60px;
    max-width: 100%;
  }
  .message-bubble.user {
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg);
    padding: var(--space-3) var(--space-4);
  }
  .message-bubble.assistant {
    max-width: 100%;
  }
  .message-bubble.editing {
    width: 100%;
    background: var(--bg-elevated);
    border: 1px solid var(--accent-primary);
    border-radius: var(--radius-lg);
    padding: var(--space-3);
    box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.12);
  }

  /* ── Inline-edit textarea ───────────────────────── */
  .edit-textarea {
    width: 100%;
    background: transparent;
    color: var(--text-primary);
    font-size: var(--text-base);
    line-height: var(--leading-normal);
    font-family: var(--font-sans);
    border: none;
    outline: none;
    resize: none;
    min-height: 48px;
    max-height: 400px;
    overflow-y: auto;
    padding: 0;
    margin: 0;
  }
  .edit-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-top: var(--space-3);
    padding-top: var(--space-2);
    border-top: 1px solid var(--border-subtle);
  }
  .edit-hint {
    font-size: 10px;
    color: var(--text-muted);
    font-family: var(--font-mono);
  }
  .edit-buttons {
    display: flex;
    gap: var(--space-2);
  }
  .edit-btn-cancel,
  .edit-btn-save {
    padding: 5px 12px;
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    transition: all var(--duration-fast);
  }
  .edit-btn-cancel {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-secondary);
  }
  .edit-btn-cancel:hover { color: var(--text-primary); background: rgba(255, 255, 255, 0.1); }
  .edit-btn-save {
    background: var(--accent-primary);
    color: white;
  }
  .edit-btn-save:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .edit-btn-save:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  @media (max-width: 600px) {
    .edit-hint { display: none; }
  }

  /* ── Meta info ──────────────────── */
  .message-meta {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-top: var(--space-3);
    padding-top: var(--space-2);
    border-top: 1px solid var(--border-subtle);
  }

  .meta-model {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .meta-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dot-color, var(--text-muted));
  }

  .meta-cost {
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-family: var(--font-mono);
  }

  /* ── Model name + reveal-the-truth tooltip ───────────────── */
  .meta-model-wrap {
    position: relative;
    display: inline-flex;
  }
  .meta-model-wrap.has-tooltip .meta-model {
    cursor: help;
    border-bottom: 1px dotted var(--border-strong);
    padding-bottom: 1px;
  }
  .meta-tooltip {
    position: absolute;
    bottom: calc(100% + 8px);
    left: 0;
    z-index: 50;
    display: flex;
    flex-direction: column;
    gap: 5px;
    min-width: 220px;
    padding: 10px 12px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    opacity: 0;
    visibility: hidden;
    transform: translateY(4px);
    transition: opacity var(--duration-fast) var(--ease-out),
                transform var(--duration-fast) var(--ease-out),
                visibility var(--duration-fast);
    pointer-events: none;
  }
  .meta-model-wrap:hover .meta-tooltip,
  .meta-model-wrap:focus-within .meta-tooltip {
    opacity: 1;
    visibility: visible;
    transform: translateY(0);
  }
  .mt-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    font-size: var(--text-xs);
    white-space: nowrap;
  }
  .mt-label { color: var(--text-muted); }
  .mt-val {
    color: var(--text-primary);
    font-weight: var(--weight-medium);
    font-family: var(--font-mono);
  }
  .mt-fallback .mt-val { color: var(--warning); }
  .mt-note {
    font-size: 10px;
    color: var(--text-muted);
    border-top: 1px solid var(--border-subtle);
    padding-top: 5px;
    margin-top: 1px;
  }

  @media (max-width: 600px) {
    .messages-container {
      padding: var(--space-4) var(--space-3) var(--space-12);
    }
    .message-bubble {
      max-width: 92% !important;
    }
  }
</style>
