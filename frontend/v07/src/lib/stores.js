/**
 * V07 Reactive Stores — Svelte writable/derived stores
 * Central state management with LocalStorage persistence
 */
import { writable, derived } from 'svelte/store';

// ── Helpers ──────────────────────────────────────────────
function persistentWritable(key, initial) {
  let stored;
  try {
    const raw = localStorage.getItem(`v07_${key}`);
    stored = raw ? JSON.parse(raw) : initial;
  } catch {
    stored = initial;
  }
  const store = writable(stored);
  store.subscribe((val) => {
    try {
      localStorage.setItem(`v07_${key}`, JSON.stringify(val));
    } catch { /* quota exceeded — ignore */ }
  });
  return store;
}

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

// ── Conversations ────────────────────────────────────────
export const conversations = persistentWritable('conversations', []);
export const activeConversationId = persistentWritable('activeConversationId', null);

// Current conversation messages (derived)
export const currentMessages = derived(
  [conversations, activeConversationId],
  ([$conversations, $activeId]) => {
    if (!$activeId) return [];
    const conv = $conversations.find((c) => c.id === $activeId);
    return conv ? conv.messages : [];
  }
);

// ── Model selection ──────────────────────────────────────
export const selectedModel = persistentWritable('selectedModel', {
  id: 'smart_routing',
  name: 'Smart Routing',
  mode: 'smart', // 'smart' | 'manual'
});

// ── UI State ─────────────────────────────────────────────
export const sidebarOpen = persistentWritable('sidebarOpen', true);
export const isLoading = writable(false);
export const isTyping = writable(false);
export const modelSelectorOpen = writable(false);

// ── Attachments / Web search ─────────────────────────────
// File objects the user has attached to the next message. Cleared after send.
export const attachedFiles = writable([]);
// When true, the next send routes through searchWeb() and the user's prompt
// is enriched with the top results before being sent to /chat.
export const webSearchEnabled = persistentWritable('webSearchEnabled', false);

// ── Loading indicator (themed per request type) ──────────
// Drives the per-mode loading card shown while we wait for the backend:
//   - 'normal'      → standard chat
//   - 'web_search'  → web search route (Tavily + chat)
//   - 'file_rag'    → file upload route (RAG against uploaded docs)
export const loadingMode = writable('normal');
// Stage id within the current mode's pipeline (e.g. 'searching', 'reading',
// 'synthesizing', 'composing'). The LoadingIndicator component knows which
// stages each mode has and which are done vs. active vs. pending.
export const loadingStage = writable(null);
// Arbitrary side info the indicator can display (query text, source count,
// uploaded filenames, etc.) — kept loose so we can enrich it per stage.
export const loadingMeta = writable({});

// ── Streaming ────────────────────────────────────────────
// True while the assistant response is being progressively revealed
// (or while we're still waiting for the backend). Drives the stop button.
export const isStreaming = writable(false);
// Id of the assistant message currently being streamed (so ChatArea can
// show a blinking cursor on it).
export const streamingMessageId = writable(null);
// { abort: () => void } — set while a request is in flight or the typewriter
// is running. Calling abort() cancels both.
export const streamController = writable(null);

// ── Session ──────────────────────────────────────────────
// Browser-unique session id, generated once and persisted forever. Used as
// the simulation-session key on the backend so each browser has its own
// wallet/conversation history — no longer shared across users.
function readOrCreateSessionId() {
  try {
    const existing = localStorage.getItem('v07_session_id');
    if (existing) return existing;
  } catch { /* localStorage blocked */ }
  const next =
    typeof crypto !== 'undefined' && crypto.randomUUID
      ? `v07-${crypto.randomUUID().slice(0, 12)}`
      : `v07-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  try { localStorage.setItem('v07_session_id', next); } catch {}
  return next;
}
export const sessionId = writable(readOrCreateSessionId());

// ── Wallet ───────────────────────────────────────────────
// Balance is persisted locally so a refresh doesn't blow it away while we're
// still waiting for the backend's getWalletBalance() to respond. The
// backend remains the source of truth — its value overwrites ours when the
// initial load completes and after every chat response.
export const walletBalance = persistentWritable('walletBalance', 25.0);
export const lastCostCharged = writable(0);
export const walletPopupOpen = writable(false);

// Recent charges shown in the wallet popup's activity feed. Capped to the
// last 25 to keep the list scannable and localStorage small.
export const walletTransactions = persistentWritable('walletTransactions', []);

/**
 * Append a charge to the recent-activity list. Newest first, capped at 25.
 */
export function recordTransaction({ amount, modelName, mode }) {
  if (!Number.isFinite(amount) || amount <= 0) return;
  walletTransactions.update((list) => {
    const next = [
      {
        amount,
        modelName: modelName || 'AI',
        mode: mode || 'chat',
        timestamp: new Date().toISOString(),
      },
      ...list,
    ];
    return next.slice(0, 25);
  });
}

/**
 * Clear the activity log — used after a wallet refill so the new session
 * starts with a fresh slate.
 */
export function clearTransactions() {
  walletTransactions.set([]);
}

// ── Page Viewer (RAG) ────────────────────────────────────
export const pageViewerProof = writable(null); // set to a proof object to open viewer

// ── Route ────────────────────────────────────────────────
export const currentRoute = writable({ mode: 'chat', collection: null });

// ── Actions ──────────────────────────────────────────────

export function createConversation(firstMessage = null) {
  const id = generateId();
  const now = new Date().toISOString();
  const conv = {
    id,
    title: firstMessage
      ? firstMessage.slice(0, 60) + (firstMessage.length > 60 ? '…' : '')
      : 'New Chat',
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
  conversations.update((list) => [conv, ...list]);
  activeConversationId.set(id);
  return id;
}

export function addMessage(conversationId, message) {
  conversations.update((list) =>
    list.map((c) => {
      if (c.id !== conversationId) return c;
      const updated = {
        ...c,
        messages: [...c.messages, { ...message, id: generateId(), timestamp: new Date().toISOString() }],
        updatedAt: new Date().toISOString(),
      };
      // Update title from first user message
      if (updated.messages.length === 1 && message.role === 'user') {
        const text = typeof message.content === 'string' ? message.content : message.content?.[0]?.text || 'New Chat';
        updated.title = text.slice(0, 60) + (text.length > 60 ? '…' : '');
      }
      return updated;
    })
  );
}

// Per-message UI state — id of the message currently in inline-edit mode
// (the user clicked the ✏️ on their own bubble). At most one at a time.
export const editingMessageId = writable(null);

// Id of the assistant message currently being read aloud by the browser's
// speechSynthesis. Drives the speaker→stop icon toggle in MessageActions.
export const speakingMessageId = writable(null);

// Toggle a 👍/👎 reaction on a specific message. Clicking the same reaction
// twice clears it; clicking the opposite reaction switches it.
export function setMessageReaction(conversationId, messageId, reaction) {
  conversations.update((list) =>
    list.map((c) => {
      if (c.id !== conversationId) return c;
      return {
        ...c,
        messages: c.messages.map((m) =>
          m.id === messageId
            ? { ...m, reaction: m.reaction === reaction ? null : reaction }
            : m,
        ),
        updatedAt: new Date().toISOString(),
      };
    }),
  );
}

// Truncate the conversation immediately AFTER the given message id —
// dropping every message that came later. Used by edit + regenerate flows
// so the new model response replaces (rather than appends to) the old one.
export function truncateConversationAfter(conversationId, messageId) {
  conversations.update((list) =>
    list.map((c) => {
      if (c.id !== conversationId) return c;
      const idx = c.messages.findIndex((m) => m.id === messageId);
      if (idx < 0) return c;
      return {
        ...c,
        messages: c.messages.slice(0, idx + 1),
        updatedAt: new Date().toISOString(),
      };
    }),
  );
}

// Update an existing message's fields (used during streaming to progressively
// reveal content and to attach final metadata when the stream completes).
export function updateMessage(conversationId, messageId, patch) {
  conversations.update((list) =>
    list.map((c) => {
      if (c.id !== conversationId) return c;
      return {
        ...c,
        messages: c.messages.map((m) =>
          m.id === messageId ? { ...m, ...patch } : m
        ),
        updatedAt: new Date().toISOString(),
      };
    })
  );
}

// Add a message and return its generated id so callers can update it later.
export function addMessageAndGetId(conversationId, message) {
  const id = generateId();
  conversations.update((list) =>
    list.map((c) => {
      if (c.id !== conversationId) return c;
      const updated = {
        ...c,
        messages: [...c.messages, { ...message, id, timestamp: new Date().toISOString() }],
        updatedAt: new Date().toISOString(),
      };
      if (updated.messages.length === 1 && message.role === 'user') {
        const text = typeof message.content === 'string' ? message.content : message.content?.[0]?.text || 'New Chat';
        updated.title = text.slice(0, 60) + (text.length > 60 ? '…' : '');
      }
      return updated;
    })
  );
  return id;
}

export function deleteConversation(id) {
  conversations.update((list) => list.filter((c) => c.id !== id));
  activeConversationId.update((current) => (current === id ? null : current));
}

// Rename a conversation. Trims whitespace and ignores empty titles so the
// user can't accidentally clear the title to nothing.
export function renameConversation(id, newTitle) {
  const trimmed = (newTitle || '').trim();
  if (!trimmed) return;
  conversations.update((list) =>
    list.map((c) =>
      c.id === id ? { ...c, title: trimmed, updatedAt: new Date().toISOString() } : c,
    ),
  );
}

// Flip a conversation's bookmark flag. The field defaults to false for
// pre-existing conversations that don't have it yet.
export function toggleBookmark(id) {
  conversations.update((list) =>
    list.map((c) => (c.id === id ? { ...c, bookmarked: !c.bookmarked } : c)),
  );
}

// Derived list of bookmarked conversations — used by the sidebar's
// Bookmarks view.
export const bookmarkedConversations = derived(conversations, ($c) =>
  $c.filter((conv) => conv.bookmarked),
);

export function clearConversations() {
  conversations.set([]);
  activeConversationId.set(null);
}
