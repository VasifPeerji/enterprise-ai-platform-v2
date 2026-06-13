<script>
  import { onMount } from 'svelte';
  import {
    commandPaletteOpen,
    conversations,
    activeConversationId,
    createConversation,
    theme,
    suggestionsEnabled,
    webSearchEnabled,
    sidebarOpen,
    modelSelectorOpen,
    settingsOpen,
    shortcutsOpen,
    pushToast,
    openCompare,
  } from '../lib/stores.js';
  import { downloadConversationMarkdown } from '../lib/export.js';

  let query = $state('');
  let selectedIdx = $state(0);
  let inputEl = $state(null);
  let panelEl = $state(null);
  let listEl = $state(null);

  function close() {
    commandPaletteOpen.set(false);
  }

  // Inline icon paths (24×24, stroke). Keyed per action.
  const I = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    theme: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    spark: '<path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4-6.2-4.5-6.2 4.5 2.4-7.4L2 9.4h7.6L12 2z"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>',
    panel: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/>',
    model: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    compare: '<rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="14" y="4" width="7" height="16" rx="1.5"/>',
  };

  let activeConv = $derived(($conversations || []).find((c) => c.id === $activeConversationId) || null);

  // Most recent user prompt in the active chat — the seed for "compare models".
  function lastUserPrompt(conv) {
    const msgs = (conv && conv.messages) || [];
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') {
        const c = msgs[i].content;
        if (Array.isArray(c)) return c.filter((b) => b?.type === 'text').map((b) => b.text || '').join(' ').trim();
        return typeof c === 'string' ? c : '';
      }
    }
    return '';
  }

  // Action commands — labels react to current state for the toggles.
  let actions = $derived([
    { id: 'new-chat', label: 'New chat', hint: 'Start a fresh conversation', icon: I.plus, keywords: 'new create start', run: () => createConversation() },
    { id: 'theme', label: $theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme', icon: I.theme, keywords: 'theme dark light appearance mode', run: () => theme.update((t) => (t === 'dark' ? 'light' : 'dark')) },
    { id: 'suggestions', label: $suggestionsEnabled ? 'Turn off smart suggestions' : 'Turn on smart suggestions', icon: I.spark, keywords: 'suggestions follow up refine tokens', run: () => suggestionsEnabled.update((v) => !v) },
    { id: 'web', label: $webSearchEnabled ? 'Turn off web search' : 'Turn on web search', icon: I.globe, keywords: 'web search internet online', run: () => webSearchEnabled.update((v) => !v) },
    { id: 'sidebar', label: $sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar', icon: I.panel, keywords: 'sidebar panel hide show', run: () => sidebarOpen.update((v) => !v) },
    { id: 'model', label: 'Select model…', hint: 'Smart Routing or a specific model', icon: I.model, keywords: 'model routing pick choose', run: () => modelSelectorOpen.set(true) },
    { id: 'prefs', label: 'Open preferences…', icon: I.gear, keywords: 'settings preferences options', run: () => settingsOpen.set(true) },
    { id: 'shortcuts', label: 'Keyboard shortcuts', icon: I.keyboard, keywords: 'keyboard shortcuts keys help cheatsheet', run: () => shortcutsOpen.set(true) },
    ...(lastUserPrompt(activeConv)
      ? [{
          id: 'compare',
          label: 'Compare models side-by-side',
          hint: 'Run your last prompt on two models',
          icon: I.compare,
          keywords: 'compare side by side models ab test versus routing diff',
          run: () => openCompare(lastUserPrompt(activeConv), null),
        }]
      : []),
    ...(activeConv && (activeConv.messages || []).length
      ? [{
          id: 'export',
          label: 'Export this chat as Markdown',
          icon: I.download,
          keywords: 'export download markdown save chat file',
          run: () => {
            const name = downloadConversationMarkdown(activeConv);
            pushToast(`Exported ${name}`, { type: 'success' });
          },
        }]
      : []),
  ]);

  let convItems = $derived(
    ($conversations || []).map((c) => ({
      id: 'conv:' + c.id,
      label: c.title || 'Untitled chat',
      icon: I.chat,
      type: 'conversation',
      keywords: c.title || '',
      run: () => activeConversationId.set(c.id),
    })),
  );

  function match(item, q) {
    if (!q.trim()) return true;
    const hay = (item.label + ' ' + (item.keywords || '')).toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every((tok) => hay.includes(tok));
  }

  let filteredActions = $derived(actions.filter((a) => match(a, query)));
  let filteredConvs = $derived(convItems.filter((c) => match(c, query)).slice(0, 8));
  let flat = $derived([...filteredActions, ...filteredConvs]);

  // Keep the selection in range as the filtered list shrinks/grows.
  $effect(() => {
    if (selectedIdx > flat.length - 1) selectedIdx = Math.max(0, flat.length - 1);
  });

  function execute(item) {
    if (!item) return;
    close();
    item.run();
  }

  function onKeydown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIdx = flat.length ? (selectedIdx + 1) % flat.length : 0;
      scrollSelectedIntoView();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIdx = flat.length ? (selectedIdx - 1 + flat.length) % flat.length : 0;
      scrollSelectedIntoView();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      execute(flat[selectedIdx]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }

  function scrollSelectedIntoView() {
    queueMicrotask(() => {
      listEl?.querySelector(`[data-cmd-idx="${selectedIdx}"]`)?.scrollIntoView({ block: 'nearest' });
    });
  }

  // Reset to the top result whenever the query changes.
  function onInput() {
    selectedIdx = 0;
  }

  onMount(() => {
    inputEl?.focus();
    function handleClickOutside(e) {
      if (panelEl && !panelEl.contains(e.target)) close();
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  });
</script>

<div class="cmd-overlay">
  <div class="cmd-panel" bind:this={panelEl}>
    <div class="cmd-search">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
      </svg>
      <input
        bind:this={inputEl}
        bind:value={query}
        oninput={onInput}
        onkeydown={onKeydown}
        type="text"
        placeholder="Type a command or search chats…"
        aria-label="Command palette"
        autocomplete="off"
        spellcheck="false"
      />
      <kbd class="cmd-esc">esc</kbd>
    </div>

    <div class="cmd-list" bind:this={listEl}>
      {#if flat.length === 0}
        <div class="cmd-empty">No matches for “{query}”</div>
      {:else}
        {#if filteredActions.length}
          <div class="cmd-section">Actions</div>
          {#each filteredActions as item, i}
            {@const idx = i}
            <button
              class="cmd-item"
              class:active={selectedIdx === idx}
              data-cmd-idx={idx}
              onclick={() => execute(item)}
              onmousemove={() => (selectedIdx = idx)}
            >
              <svg class="cmd-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{@html item.icon}</svg>
              <span class="cmd-item-label">{item.label}</span>
              {#if item.hint}<span class="cmd-item-hint">{item.hint}</span>{/if}
            </button>
          {/each}
        {/if}

        {#if filteredConvs.length}
          <div class="cmd-section">Chats</div>
          {#each filteredConvs as item, i}
            {@const idx = filteredActions.length + i}
            <button
              class="cmd-item"
              class:active={selectedIdx === idx}
              data-cmd-idx={idx}
              onclick={() => execute(item)}
              onmousemove={() => (selectedIdx = idx)}
            >
              <svg class="cmd-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{@html item.icon}</svg>
              <span class="cmd-item-label">{item.label}</span>
            </button>
          {/each}
        {/if}
      {/if}
    </div>

    <div class="cmd-footer">
      <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
      <span><kbd>↵</kbd> select</span>
      <span><kbd>esc</kbd> close</span>
    </div>
  </div>
</div>

<style>
  .cmd-overlay {
    position: fixed;
    inset: 0;
    z-index: 210;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 12vh;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    animation: cmdFade 0.15s var(--ease-out);
  }
  @keyframes cmdFade { from { opacity: 0; } to { opacity: 1; } }

  .cmd-panel {
    width: 560px;
    max-width: calc(100vw - 32px);
    max-height: 64vh;
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: cmdPop 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes cmdPop {
    from { opacity: 0; transform: translateY(-6px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .cmd-search {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
    color: var(--text-muted);
  }
  .cmd-search input {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-primary);
    font-size: var(--text-md);
    font-family: var(--font-sans);
  }
  .cmd-search input::placeholder { color: var(--text-muted); }
  .cmd-esc {
    font-size: 10px;
    font-family: var(--font-mono);
    color: var(--text-muted);
    background: rgba(var(--overlay-rgb), 0.06);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 2px 6px;
  }

  .cmd-list {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-2);
  }
  .cmd-section {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
    padding: var(--space-2) var(--space-2) var(--space-1);
  }
  .cmd-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    text-align: left;
    color: var(--text-secondary);
    transition: background var(--duration-fast), color var(--duration-fast);
  }
  .cmd-item.active {
    background: rgba(16, 163, 127, 0.1);
    color: var(--text-primary);
  }
  .cmd-item-icon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    color: var(--text-tertiary);
  }
  .cmd-item.active .cmd-item-icon { color: var(--accent-primary); }
  .cmd-item-label {
    flex: 1;
    min-width: 0;
    font-size: var(--text-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cmd-item-hint {
    font-size: var(--text-xs);
    color: var(--text-muted);
    flex-shrink: 0;
  }
  .cmd-empty {
    padding: var(--space-8);
    text-align: center;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }

  .cmd-footer {
    display: flex;
    gap: var(--space-4);
    padding: var(--space-2) var(--space-4);
    border-top: 1px solid var(--border-subtle);
    font-size: 10px;
    color: var(--text-muted);
  }
  .cmd-footer kbd {
    font-family: var(--font-mono);
    background: rgba(var(--overlay-rgb), 0.06);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    padding: 0 4px;
    margin-right: 2px;
  }

  @media (max-width: 600px) {
    .cmd-overlay { padding-top: 8vh; }
    .cmd-item-hint { display: none; }
  }
</style>
