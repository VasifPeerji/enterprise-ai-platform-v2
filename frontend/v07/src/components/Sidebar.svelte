<script>
  import {
    conversations,
    bookmarkedConversations,
    activeConversationId,
    sidebarOpen,
    createConversation,
    deleteConversation,
    renameConversation,
    toggleBookmark,
  } from '../lib/stores.js';
  import { tick } from 'svelte';

  // Two top-level views: chats history vs bookmarks.
  let view = $state('chats'); // 'chats' | 'bookmarks'
  let sectionExpanded = $state(true);

  // Per-row interaction state.
  let openMenuId = $state(null);     // conv whose ⋯ menu is open
  let renamingId = $state(null);     // conv currently being renamed inline
  let renameValue = $state('');
  let renameInputEl = $state(null);
  let confirmDeleteId = $state(null); // conv awaiting delete confirmation

  function getTimeGroup(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return 'This Week';
    if (diffDays < 30) return 'This Month';
    return 'Older';
  }

  // Free-text filter over the visible list — matches conversation titles and
  // any message prose, so you can find a chat by something you said in it.
  let searchQuery = $state('');
  let baseList = $derived(view === 'bookmarks' ? $bookmarkedConversations : $conversations);
  let visibleList = $derived.by(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return baseList;
    return baseList.filter((conv) => {
      if (conv.title?.toLowerCase().includes(q)) return true;
      return (conv.messages || []).some((m) =>
        (m.content || []).some(
          (b) => b?.type === 'text' && b.text?.toLowerCase().includes(q),
        ),
      );
    });
  });
  // Pick the right source list based on view, then bucket by time.
  let grouped = $derived.by(() => {
    const groups = {};
    for (const conv of visibleList) {
      const group = getTimeGroup(conv.updatedAt || conv.createdAt);
      if (!groups[group]) groups[group] = [];
      groups[group].push(conv);
    }
    return groups;
  });

  function handleNewChat() {
    createConversation();
    openMenuId = null;
    renamingId = null;
  }

  function handleSelect(id) {
    if (renamingId === id) return; // don't switch chat while renaming its title
    activeConversationId.set(id);
    openMenuId = null;
    if (window.innerWidth < 768) sidebarOpen.set(false);
  }

  function toggleMenu(e, id) {
    e.stopPropagation();
    openMenuId = openMenuId === id ? null : id;
    confirmDeleteId = null;
  }

  function doBookmark(id) {
    toggleBookmark(id);
    openMenuId = null;
  }

  async function startRename(id, currentTitle) {
    renamingId = id;
    renameValue = currentTitle;
    openMenuId = null;
    await tick();
    renameInputEl?.focus();
    renameInputEl?.select();
  }

  function commitRename() {
    if (renamingId) {
      renameConversation(renamingId, renameValue);
      renamingId = null;
      renameValue = '';
    }
  }

  function cancelRename() {
    renamingId = null;
    renameValue = '';
  }

  function handleRenameKey(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitRename();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelRename();
    }
  }

  function askDelete(id) {
    confirmDeleteId = id;
    openMenuId = null;
  }

  function doDelete(id) {
    deleteConversation(id);
    confirmDeleteId = null;
  }

  // Click-outside action for the action menus & delete confirm.
  function clickOutside(node, callback) {
    function handle(e) {
      if (node && !node.contains(e.target)) callback();
    }
    document.addEventListener('mousedown', handle, true);
    return {
      destroy() { document.removeEventListener('mousedown', handle, true); },
    };
  }
</script>

<aside class="sidebar" class:open={$sidebarOpen}>
  <!-- ── Header: collapse · bookmarks · new chat ────────── -->
  <div class="sidebar-header">
    <button
      class="header-icon"
      onclick={() => sidebarOpen.set(false)}
      aria-label="Close sidebar"
      title="Close sidebar"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
      </svg>
    </button>

    <div class="header-spacer"></div>

    <button
      class="header-icon"
      class:active={view === 'bookmarks'}
      onclick={() => (view = view === 'bookmarks' ? 'chats' : 'bookmarks')}
      aria-label="Bookmarks"
      aria-pressed={view === 'bookmarks'}
      title={view === 'bookmarks' ? 'Show all chats' : 'Show bookmarks'}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill={view === 'bookmarks' ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
      </svg>
    </button>

    <button
      class="header-icon"
      onclick={handleNewChat}
      aria-label="New chat"
      title="New chat"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 20h9"/>
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
      </svg>
    </button>
  </div>

  <!-- ── Search ─────────────────────────────────────────── -->
  <div class="sidebar-search">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
    </svg>
    <input
      type="text"
      placeholder="Search chats…"
      bind:value={searchQuery}
      aria-label="Search conversations"
    />
    {#if searchQuery}
      <button class="search-clear" onclick={() => (searchQuery = '')} aria-label="Clear search" title="Clear search">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
      </button>
    {/if}
  </div>

  <!-- ── Section header (Chats / Bookmarks, collapsible) ──── -->
  <button
    class="section-header"
    onclick={() => (sectionExpanded = !sectionExpanded)}
    aria-expanded={sectionExpanded}
  >
    <span class="section-title">{view === 'bookmarks' ? 'Bookmarks' : 'Chats'}</span>
    <svg
      class="section-chevron"
      class:collapsed={!sectionExpanded}
      width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
    >
      <polyline points="18 15 12 9 6 15"/>
    </svg>
  </button>

  <!-- ── Conversation list ──────────────────────────────── -->
  {#if sectionExpanded}
    <nav class="conversation-list">
      {#each Object.entries(grouped) as [group, convs]}
        <div class="group">
          <div class="group-label">{group}</div>
          {#each convs as conv (conv.id)}
            <div
              class="conv-item"
              class:active={$activeConversationId === conv.id}
              onclick={() => handleSelect(conv.id)}
              role="button"
              tabindex="0"
              onkeydown={(e) => e.key === 'Enter' && handleSelect(conv.id)}
            >
              {#if conv.bookmarked && view !== 'bookmarks'}
                <svg class="conv-bookmark-dot" width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              {/if}

              {#if renamingId === conv.id}
                <input
                  bind:this={renameInputEl}
                  bind:value={renameValue}
                  onkeydown={handleRenameKey}
                  onblur={commitRename}
                  onclick={(e) => e.stopPropagation()}
                  class="conv-rename-input"
                  maxlength="120"
                />
              {:else}
                <span class="conv-title">{conv.title}</span>
              {/if}

              <button
                class="conv-menu-btn"
                class:visible={openMenuId === conv.id}
                onclick={(e) => toggleMenu(e, conv.id)}
                aria-label="Conversation options"
                aria-haspopup="menu"
                aria-expanded={openMenuId === conv.id}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="5" r="1.5"/>
                  <circle cx="12" cy="12" r="1.5"/>
                  <circle cx="12" cy="19" r="1.5"/>
                </svg>
              </button>

              {#if openMenuId === conv.id}
                <div
                  class="conv-menu"
                  role="menu"
                  use:clickOutside={() => (openMenuId = null)}
                  onclick={(e) => e.stopPropagation()}
                >
                  <button class="menu-item" onclick={() => doBookmark(conv.id)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill={conv.bookmarked ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                    </svg>
                    {conv.bookmarked ? 'Remove bookmark' : 'Bookmark'}
                  </button>
                  <button class="menu-item" onclick={() => startRename(conv.id, conv.title)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                    Rename
                  </button>
                  <div class="menu-divider"></div>
                  <button class="menu-item menu-danger" onclick={() => askDelete(conv.id)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14"/>
                    </svg>
                    Delete
                  </button>
                </div>
              {/if}

              {#if confirmDeleteId === conv.id}
                <div
                  class="conv-confirm"
                  use:clickOutside={() => (confirmDeleteId = null)}
                  onclick={(e) => e.stopPropagation()}
                >
                  <span class="confirm-text">Delete this chat?</span>
                  <div class="confirm-actions">
                    <button class="confirm-cancel" onclick={() => (confirmDeleteId = null)}>Cancel</button>
                    <button class="confirm-delete" onclick={() => doDelete(conv.id)}>Delete</button>
                  </div>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/each}

      {#if visibleList.length === 0}
        <div class="empty-state">
          {#if searchQuery}
            <p>No chats match “{searchQuery}”</p>
            <p class="empty-hint">Try a different word, or clear the search</p>
          {:else if view === 'bookmarks'}
            <p>No bookmarks yet</p>
            <p class="empty-hint">Bookmark a chat from its <strong>⋯</strong> menu</p>
          {:else}
            <p>No conversations yet</p>
            <p class="empty-hint">Click <strong>✏️</strong> to start a new chat</p>
          {/if}
        </div>
      {/if}
    </nav>
  {/if}

  <!-- ── Brand footer ──────────────────────────────────── -->
  <div class="sidebar-bottom">
    <div class="sidebar-brand">
      <div class="brand-icon">V07</div>
      <span class="brand-text">Enterprise AI Platform</span>
    </div>
  </div>
</aside>

<style>
  .sidebar {
    width: var(--sidebar-width);
    height: 100vh;
    background: var(--surface-sidebar);
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    transition: transform var(--duration-slow) var(--ease-out),
                width var(--duration-slow) var(--ease-out);
    z-index: 20;
    overflow: hidden;
  }
  :global(.sidebar-collapsed) .sidebar {
    width: 0;
    border-right: none;
  }

  /* ── Header row ─────────────────────── */
  .sidebar-header {
    display: flex;
    align-items: center;
    padding: var(--space-3);
    gap: 2px;
  }
  .header-spacer { flex: 1; }

  .header-icon {
    width: 34px;
    height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    transition: all var(--duration-fast);
  }
  .header-icon:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .header-icon.active {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.12);
  }

  /* ── Search ─────────────────────────── */
  .sidebar-search {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0 var(--space-3) var(--space-1);
    padding: var(--space-2) var(--space-3);
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    color: var(--text-muted);
    transition: border-color var(--duration-fast);
  }
  .sidebar-search:focus-within { border-color: var(--accent-primary); }
  .sidebar-search svg { flex-shrink: 0; }
  .sidebar-search input {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-primary);
    font-size: var(--text-sm);
    padding: 0;
  }
  .sidebar-search input::placeholder { color: var(--text-muted); }
  .search-clear {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    color: var(--text-muted);
    flex-shrink: 0;
    transition: all var(--duration-fast);
  }
  .search-clear:hover { background: var(--bg-hover); color: var(--text-primary); }

  /* ── Section title (Chats / Bookmarks) ─────────────── */
  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: var(--space-2) var(--space-4);
    margin-top: var(--space-1);
    color: var(--text-secondary);
    transition: color var(--duration-fast);
  }
  .section-header:hover { color: var(--text-primary); }
  .section-title {
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
  }
  .section-chevron {
    transition: transform var(--duration-fast);
    color: var(--text-muted);
  }
  .section-chevron.collapsed {
    transform: rotate(180deg);
  }

  /* ── Conversation list ──────────────── */
  .conversation-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 var(--space-2);
  }
  .group { margin-bottom: var(--space-2); }
  .group-label {
    font-size: 10px;
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
    padding: var(--space-3) var(--space-3) var(--space-1);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .conv-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    text-align: left;
    transition: background var(--duration-fast);
    position: relative;
    min-height: 36px;
  }
  .conv-item:hover { background: var(--bg-hover); }
  .conv-item.active { background: var(--bg-active); }

  .conv-bookmark-dot {
    color: var(--accent-primary);
    flex-shrink: 0;
  }

  .conv-title {
    flex: 1;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .conv-item.active .conv-title { color: var(--text-primary); }

  .conv-rename-input {
    flex: 1;
    background: var(--bg-elevated);
    border: 1px solid var(--accent-primary);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    padding: 4px 8px;
    outline: none;
    width: 100%;
    min-width: 0;
  }

  .conv-menu-btn {
    opacity: 0;
    color: var(--text-muted);
    padding: 4px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    flex-shrink: 0;
    transition: all var(--duration-fast);
  }
  .conv-item:hover .conv-menu-btn,
  .conv-menu-btn.visible {
    opacity: 1;
  }
  .conv-menu-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-primary);
  }

  /* ── Action menu popover ────────────── */
  .conv-menu {
    position: absolute;
    top: calc(100% - 4px);
    right: var(--space-2);
    min-width: 170px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 4px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    z-index: 30;
    animation: menuFadeIn 0.15s var(--ease-out);
  }
  @keyframes menuFadeIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .menu-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 8px var(--space-3);
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
    color: var(--text-secondary);
    text-align: left;
    transition: background var(--duration-fast), color var(--duration-fast);
  }
  .menu-item:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .menu-item.menu-danger { color: var(--error, #ef4444); }
  .menu-item.menu-danger:hover {
    background: rgba(239, 68, 68, 0.1);
    color: var(--error, #ef4444);
  }
  .menu-divider {
    height: 1px;
    background: var(--border-subtle);
    margin: 4px 0;
  }

  /* ── Inline delete confirmation ───── */
  .conv-confirm {
    position: absolute;
    top: calc(100% - 4px);
    right: var(--space-2);
    min-width: 200px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    z-index: 30;
    animation: menuFadeIn 0.15s var(--ease-out);
  }
  .confirm-text {
    display: block;
    font-size: var(--text-sm);
    color: var(--text-primary);
    margin-bottom: var(--space-2);
  }
  .confirm-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
  }
  .confirm-cancel, .confirm-delete {
    padding: 4px var(--space-3);
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    transition: all var(--duration-fast);
  }
  .confirm-cancel {
    background: var(--bg-hover);
    color: var(--text-secondary);
  }
  .confirm-cancel:hover { color: var(--text-primary); }
  .confirm-delete {
    background: var(--error, #ef4444);
    color: white;
  }
  .confirm-delete:hover { opacity: 0.9; }

  /* ── Empty state ─────────────────── */
  .empty-state {
    text-align: center;
    padding: var(--space-8) var(--space-4);
    color: var(--text-muted);
  }
  .empty-state p { font-size: var(--text-sm); }
  .empty-hint {
    font-size: var(--text-xs) !important;
    margin-top: var(--space-1);
  }
  .empty-hint :global(strong) {
    color: var(--text-secondary);
    font-weight: var(--weight-semibold);
  }

  /* ── Brand footer ────────────────── */
  .sidebar-bottom {
    padding: var(--space-3);
    border-top: 1px solid var(--border-subtle);
  }
  .sidebar-brand {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
  }
  .brand-icon {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    background: var(--accent-gradient);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    font-weight: var(--weight-bold);
    color: white;
    letter-spacing: 0.02em;
    flex-shrink: 0;
  }
  .brand-text {
    font-size: var(--text-xs);
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @media (max-width: 768px) {
    .sidebar { position: fixed; left: 0; top: 0; }
    .sidebar:not(.open) { transform: translateX(-100%); }
  }
</style>
