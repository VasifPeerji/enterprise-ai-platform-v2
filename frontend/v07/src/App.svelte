<script>
  import { onMount } from 'svelte';
  import Sidebar from './components/Sidebar.svelte';
  import ChatArea from './components/ChatArea.svelte';
  import InputBar from './components/InputBar.svelte';
  import ModelSelector from './components/ModelSelector.svelte';
  import PageViewer from './components/PageViewer.svelte';
  import {
    sidebarOpen,
    theme,
    currentRoute,
    modelSelectorOpen,
    settingsOpen,
    suggestionsEnabled,
    activeConversationId,
    createConversation,
    addMessage,
    addMessageAndGetId,
    updateMessage,
    isLoading,
    isTyping,
    isStreaming,
    streamingMessageId,
    streamController,
    loadingMode,
    loadingStage,
    loadingMeta,
    selectedModel,
    walletBalance,
    lastCostCharged,
    pageViewerProof,
    attachedFiles,
    webSearchEnabled,
    verifyClaimsEnabled,
    sessionId,
    walletPopupOpen,
    walletTransactions,
    recordTransaction,
    conversations,
    setMessageReaction,
    truncateConversationAfter,
    editingMessageId,
    speakingMessageId,
    pushToast,
    commandPaletteOpen,
    shortcutsOpen,
  } from './lib/stores.js';
  import {
    sendMessage,
    ragQuery,
    getWalletBalance,
    uploadFilesToCollection,
    searchWeb,
    formatSearchContext,
    generateSmartSuggestions,
    processFileForUpload,
  } from './lib/api.js';
  import WalletPopup from './components/WalletPopup.svelte';
  import SettingsPopup from './components/SettingsPopup.svelte';
  import Toaster from './components/Toaster.svelte';
  import CommandPalette from './components/CommandPalette.svelte';
  import ShortcutsOverlay from './components/ShortcutsOverlay.svelte';
  import Lightbox from './components/Lightbox.svelte';

  let route = $state({ mode: 'chat', collection: null });

  // Modifier-key label for shortcut hints (⌘ on macOS, Ctrl elsewhere).
  const modLabel =
    typeof navigator !== 'undefined' && /mac/i.test(navigator.platform || '') ? '⌘' : 'Ctrl';

  // Apply the chosen theme to <html data-theme> so the light-palette overrides
  // in tokens.css take effect. Dark is the default; the value is persisted.
  $effect(() => {
    document.documentElement.dataset.theme = $theme;
  });

  function toggleTheme() {
    theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
  }

  // ── Drag-and-drop file attach ───────────────────────────────
  // Drop files anywhere on the app to attach them to the next message — the
  // same pipeline as the paperclip button (processFileForUpload → attachedFiles
  // → grounded RAG on send). dragenter/leave fire per child element, so a depth
  // counter tracks when the cursor has truly left the window.
  let dragActive = $state(false);
  let dragDepth = 0;

  function dropAllowed() {
    return route.mode !== 'rag' && !$isLoading && !$isStreaming;
  }
  function dragHasFiles(e) {
    return Array.from(e.dataTransfer?.types || []).includes('Files');
  }
  function handleDragEnter(e) {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    dragDepth += 1;
    if (dropAllowed()) dragActive = true;
  }
  function handleDragOver(e) {
    if (!dragHasFiles(e)) return;
    e.preventDefault(); // required so the drop event fires
    if (e.dataTransfer) e.dataTransfer.dropEffect = dropAllowed() ? 'copy' : 'none';
  }
  function handleDragLeave(e) {
    if (!dragHasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dragActive = false;
  }
  async function handleDrop(e) {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    dragActive = false;
    if (!dropAllowed()) {
      pushToast(
        route.mode === 'rag'
          ? 'Attachments aren’t used in RAG mode — just ask about the collection.'
          : 'Wait for the current response to finish before attaching files.',
        { type: 'warning' },
      );
      return;
    }
    const files = Array.from(e.dataTransfer?.files || []);
    if (!files.length) return;

    const processed = [];
    const errors = [];
    for (const raw of files) {
      try {
        processed.push(await processFileForUpload(raw));
      } catch (err) {
        errors.push(err?.message || `Couldn’t read "${raw.name}".`);
      }
    }
    if (processed.length) {
      attachedFiles.update((curr) => [...curr, ...processed]);
      pushToast(`Attached ${processed.length} file${processed.length === 1 ? '' : 's'}`, {
        type: 'success',
      });
    }
    if (errors.length) {
      pushToast(errors[0], { type: 'error', duration: 6000 });
    }
  }

  // Hash-based routing
  function parseHash() {
    const hash = window.location.hash.slice(1) || '/';
    if (hash.startsWith('/rag/')) {
      const collection = decodeURIComponent(hash.slice(5));
      route = { mode: 'rag', collection };
    } else {
      route = { mode: 'chat', collection: null };
    }
    currentRoute.set(route);
  }

  onMount(async () => {
    parseHash();
    window.addEventListener('hashchange', parseHash);

    // Pull the latest wallet balance from the backend for this browser's
    // persistent session. The persisted local value is kept as a fallback
    // so a brief network blip doesn't blank the UI.
    try {
      const balance = await getWalletBalance($sessionId);
      walletBalance.set(balance);
    } catch { /* backend not running yet */ }

    return () => window.removeEventListener('hashchange', parseHash);
  });

  // Handle sending messages with streaming typewriter effect + stop support.
  // The `opts` arg lets refine / regenerate / edit flows reuse the same
  // pipeline without double-recording the user prompt as a bubble.
  async function handleSend(event, opts = {}) {
    const message = event.detail.message;
    if (!message.trim()) return;
    const skipUserBubble = opts.skipUserBubble === true;

    // Snapshot the attachments / search state for this send. Cleared from
    // the input bar immediately so the user can start composing the next
    // message while this one is in flight.
    let filesForSend = [];
    let useWebSearch = false;
    const unsubFiles = attachedFiles.subscribe((v) => (filesForSend = v));
    unsubFiles();
    const unsubWeb = webSearchEnabled.subscribe((v) => (useWebSearch = v));
    unsubWeb();
    let useVerify = false;
    const unsubVerify = verifyClaimsEnabled.subscribe((v) => (useVerify = v));
    unsubVerify();
    attachedFiles.set([]);

    // Create conversation if needed
    let convId;
    const unsub = activeConversationId.subscribe((v) => (convId = v));
    unsub();

    if (!convId) {
      convId = createConversation(message);
    }

    // Build the user-visible content for the bubble: text + file/search chips
    // (purely visual indicators; the actual file content rides via the
    // grounded collection, and search results ride inside the enriched prompt).
    const userContent = [{ type: 'text', text: message }];
    if (filesForSend.length) {
      userContent.push({
        type: 'attachments',
        files: filesForSend.map((f) => ({ name: f.name, size: f.size, type: f.type })),
      });
    }
    if (useWebSearch) {
      userContent.push({ type: 'web_search_indicator' });
    }

    if (!skipUserBubble) {
      addMessage(convId, {
        role: 'user',
        content: userContent,
      });
    }

    // Pick the loading-indicator mode based on what this send actually does.
    // File-RAG takes priority over web search since it's the heavier path.
    const mode = filesForSend.length
      ? 'file_rag'
      : useWebSearch
      ? 'web_search'
      : 'normal';
    loadingMode.set(mode);
    loadingMeta.set(
      mode === 'web_search'
        ? { query: message }
        : mode === 'file_rag'
        ? {
            files: filesForSend.map((f) => f.name),
            totalBytes: filesForSend.reduce((s, f) => s + (f.size || 0), 0),
          }
        : {},
    );
    loadingStage.set(
      mode === 'web_search' ? 'searching' : mode === 'file_rag' ? 'uploading' : 'thinking',
    );

    // Show loading state — themed indicator until the response arrives
    isLoading.set(true);
    isTyping.set(true);

    // Set up abort for the in-flight request
    const controller = new AbortController();
    // The typewriter's cancel flag — flipped by the stop button mid-stream
    let stopRequested = false;
    streamController.set({
      abort: () => {
        stopRequested = true;
        controller.abort();
      },
    });

    let asstId = null;

    try {
      let response;
      let modelState;
      const unsubModel = selectedModel.subscribe((v) => (modelState = v));
      unsubModel();

      // 1) Web search enrichment — fetch top web results and inline them
      //    into the prompt as numbered context. Failures here are non-fatal:
      //    we still send the original message so a flaky network doesn't
      //    break the chat. The raw results are stashed so we can rewrite
      //    [N] citations in the response into clickable links afterwards.
      let promptForBackend = message;
      let searchResultsUsed = null;
      if (useWebSearch) {
        try {
          const results = await searchWeb(message, { signal: controller.signal });
          if (results.length) {
            promptForBackend = formatSearchContext(results, message);
            searchResultsUsed = results;
            // Surface the sources as chips and tick the pipeline forward.
            loadingMeta.update((m) => ({
              ...m,
              sources: results.slice(0, 4).map((r) => ({ url: r.url, title: r.title })),
              sourcesFound: results.length,
            }));
            loadingStage.set('reading');
            await sleep(450);
            loadingStage.set('synthesizing');
          }
        } catch (e) {
          if (e.name === 'AbortError') throw e;
          console.warn('[V07] Web search failed, sending without context:', e);
        }
      }

      // 2) File upload — push the attachments into a fresh grounded
      //    collection. The chat call then runs in RAG mode against it so
      //    citations come back automatically.
      //
      // Stage timing — the backend does the bulk of the slow work *inside*
      // this single fetch (parse the file → chunk → embed every chunk →
      // store in the vector DB). That takes 10-60s for a real document.
      // If we left the stage at "uploading" until the await returns, the UI
      // would look frozen even though the backend is working hard. So we
      // schedule a timed advance to "parsing" while we're still waiting.
      let collectionIdOverride = null;
      if (filesForSend.length) {
        let uploadDone = false;
        const parsingTimer = setTimeout(() => {
          if (!uploadDone) loadingStage.set('parsing');
        }, 2500);

        try {
          const { collectionId, summary } = await uploadFilesToCollection(filesForSend, {
            sessionId: $sessionId,
            signal: controller.signal,
          });
          collectionIdOverride = collectionId;
          loadingMeta.update((m) => ({ ...m, summary }));
        } finally {
          uploadDone = true;
          clearTimeout(parsingTimer);
        }
        // Upload + indexing complete on the backend. The chat call (RAG)
        // will now do vector retrieval + generation — show retrieval first.
        loadingStage.set('retrieving');
      }

      // For the normal path, flip from "thinking" to "composing" right
      // before the chat call so the second stage actually lights up.
      if (mode === 'normal') {
        loadingStage.set('composing');
      } else if (mode === 'file_rag') {
        // We're already at "retrieving" from the post-upload block above.
        // The chat call does both retrieval + generation; advance to
        // "composing" partway through so the user sees the final stage.
        setTimeout(() => loadingStage.set('composing'), 1500);
      } else if (mode === 'web_search' && !searchResultsUsed) {
        // Search failed silently — collapse to composing.
        loadingStage.set('composing');
      }

      if (route.mode === 'rag' && route.collection) {
        response = await ragQuery(route.collection, promptForBackend, {
          sessionId: $sessionId,
          verifyClaims: useVerify,
          signal: controller.signal,
        });
      } else if (collectionIdOverride) {
        response = await ragQuery(collectionIdOverride, promptForBackend, {
          sessionId: $sessionId,
          verifyClaims: useVerify,
          signal: controller.signal,
        });
      } else {
        response = await sendMessage(promptForBackend, {
          // A "regenerate with model X" run forces that model for this turn;
          // otherwise use whatever the model chip is set to.
          modelId: opts.forceModelId || modelState.id || 'smart_routing',
          sessionId: $sessionId,
          verifyClaims: useVerify,
          signal: controller.signal,
        });
      }

      // For a forced "try another model" run, the backend still reports the
      // router's own pick in model_used — surface the model the user explicitly
      // chose instead, and flag the insight as a manual comparison run.
      if (opts.forceModelMeta) {
        response.model = {
          ...response.model,
          name: opts.forceModelMeta.name,
          tier: opts.forceModelMeta.tier,
          provider: opts.forceModelMeta.provider,
        };
        response.routing = { ...response.routing, mode: 'manual' };
      }

      // Update wallet balance from simulation. The backend is the source
      // of truth for cost calculation; the local store mirrors it.
      if (response.cost?.balanceUsd !== null && response.cost?.balanceUsd !== undefined) {
        walletBalance.set(response.cost.balanceUsd);
      }
      if (response.cost?.chargedUsd) {
        lastCostCharged.set(response.cost.chargedUsd);
        // Drop a row into the wallet's recent-activity feed so the user can
        // see what each message cost and which model billed for it.
        recordTransaction({
          amount: response.cost.chargedUsd,
          modelName: response.model?.name || 'AI',
          mode,
        });
        setTimeout(() => lastCostCharged.set(0), 3000);
      }

      // Post-process when web search was used: turn the model's "[1]" / "[2]"
      // markers into clickable inline links, strip any trailing URL-dump the
      // model produced anyway, and append a clean sources block at the end.
      let finalContent = response.content;
      if (searchResultsUsed?.length) {
        finalContent = enhanceWithWebSources(response.content, searchResultsUsed);
      }

      // Response arrived — switch from "typing dots" to streaming the message.
      // Append an empty assistant message we'll progressively fill in.
      isTyping.set(false);
      asstId = addMessageAndGetId(convId, {
        role: 'assistant',
        content: [],
        model: response.model,
        routing: response.routing,
        cost: response.cost,
      });
      streamingMessageId.set(asstId);
      isStreaming.set(true);

      // Kick off the follow-up / refine suggestions NOW, in parallel with the
      // typewriter. They're produced by a separate LLM round-trip; firing it
      // here (instead of when the chips mount after streaming) overlaps that
      // round-trip with the several seconds of typewriter animation, so by the
      // time the chips render they read the already-resolved cache and appear
      // instantly. Keyed by asstId, so FollowUpSuggestions/QuickRefine dedupe
      // onto this same request.
      if ($suggestionsEnabled) prewarmSuggestions(asstId, message, finalContent);

      await typewriterStream(convId, asstId, finalContent, () => stopRequested);
    } catch (error) {
      // AbortError before response arrived → user clicked stop early. Drop a
      // brief note so they see the action took effect.
      if (error.name === 'AbortError') {
        addMessage(convId, {
          role: 'assistant',
          content: [{ type: 'text', text: '_Response generation stopped._' }],
          model: { name: 'System', tier: 'moderate' },
        });
      } else {
        addMessage(convId, {
          role: 'assistant',
          content: [{ type: 'text', text: humanizeError(error.message) }],
          model: { name: 'System', tier: 'error' },
        });
      }
    } finally {
      isLoading.set(false);
      isTyping.set(false);
      isStreaming.set(false);
      streamingMessageId.set(null);
      streamController.set(null);
    }
  }

  // Progressively reveal the assistant content into the live message. Text
  // blocks are typed out word-by-word; non-text blocks (charts, tables,
  // citations, etc.) snap in once the preceding text is fully revealed.
  async function typewriterStream(convId, messageId, blocks, isStopped) {
    const revealed = [];
    // Words-per-tick controls speed: small batch keeps the effect smooth but
    // doesn't take forever on long answers.
    const WORDS_PER_TICK = 3;
    const TICK_MS = 18;

    for (const block of blocks) {
      if (isStopped()) break;

      if (block.type === 'text' && typeof block.text === 'string') {
        // Stream this text block word-by-word
        const words = block.text.split(/(\s+)/); // keep whitespace tokens
        let buf = '';
        revealed.push({ type: 'text', text: '' });
        const idx = revealed.length - 1;

        for (let i = 0; i < words.length; i += WORDS_PER_TICK) {
          if (isStopped()) break;
          buf += words.slice(i, i + WORDS_PER_TICK).join('');
          revealed[idx] = { type: 'text', text: buf };
          updateMessage(convId, messageId, { content: [...revealed] });
          await sleep(TICK_MS);
        }
        // Ensure full text if we exited the loop cleanly
        if (!isStopped()) {
          revealed[idx] = { type: 'text', text: block.text };
          updateMessage(convId, messageId, { content: [...revealed] });
        }
      } else {
        // Non-text block — show it whole
        revealed.push(block);
        updateMessage(convId, messageId, { content: [...revealed] });
        await sleep(TICK_MS);
      }
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // Pre-warm the follow-up / refine suggestions for an assistant message so the
  // generating LLM call overlaps the typewriter rather than starting after it.
  // Extracts the same plain text the chip components use and applies the same
  // skip threshold; fires fire-and-forget (any error surfaces when the chips
  // mount and retry). generateSmartSuggestions dedupes/caches by messageId, so
  // FollowUpSuggestions and QuickRefine attach to this same in-flight request.
  function prewarmSuggestions(messageId, userText, contentBlocks) {
    const responseText = (contentBlocks || [])
      .filter((b) => b?.type === 'text')
      .map((b) => b.text || '')
      .join('\n\n')
      .trim();
    if (responseText.length < 100) return;
    generateSmartSuggestions({ messageId, userText, responseText, sessionId: $sessionId }).catch(
      () => {},
    );
  }

  // Escape HTML special chars so titles can safely sit inside a title="…"
  // attribute on the inline citation link.
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Turn `[1]` markers in the response into clickable superscript links and
  // strip any trailing URL list the model produced (despite being asked not
  // to). Appends a structured `web_sources` content block with the actual
  // result list so the chat shows a clean Sources section at the bottom.
  function enhanceWithWebSources(content, results) {
    const enhanced = content.map((block) => {
      if (block.type !== 'text') return block;
      let text = block.text || '';

      // ── 1) Linkify [N] → <sup><a class="cite-link" href="…">[N]</a></sup>
      text = text.replace(/\[(\d+)\]/g, (m, n) => {
        const idx = parseInt(n, 10) - 1;
        const src = results[idx];
        if (!src) return m;
        const title = escapeHtml(src.title || src.url);
        return `<sup class="cite-sup"><a class="cite-link" href="${src.url}" target="_blank" rel="noopener noreferrer" title="${title}">${n}</a></sup>`;
      });

      // ── 2) Strip the model's trailing "Sources:" / "For more info…" dump.
      //      Find the first line that starts a URL list and chop everything
      //      from there to the end of the message — but only if at least one
      //      URL is present in that tail, so we don't accidentally truncate
      //      legitimate prose.
      const lines = text.split('\n');
      let cutoff = -1;
      for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!/^(Sources?:|References?:|For (?:more )?(?:detailed |further )?info|For more details?|You can refer to|Citations?:)/i.test(line))
          continue;
        const tail = lines.slice(i).join('\n');
        if (/https?:\/\//i.test(tail)) {
          cutoff = i;
          break;
        }
      }
      if (cutoff > 0) text = lines.slice(0, cutoff).join('\n').trimEnd();

      return { ...block, text };
    });

    // ── 3) Append a clean sources block.
    enhanced.push({
      type: 'web_sources',
      sources: results.map((r, i) => ({
        n: i + 1,
        title: r.title,
        url: r.url,
        snippet: (r.snippet || '').slice(0, 220),
      })),
    });

    return enhanced;
  }

  // Translate cryptic backend error messages into something a user can act
  // on. Falls back to the raw message for anything we don't recognise so we
  // never hide an unknown failure mode from view.
  function humanizeError(raw) {
    const msg = String(raw || '');

    if (/no relevant knowledge found/i.test(msg)) {
      return (
        "⚠️ I couldn't find anything relevant in your uploaded documents for that question. " +
        'A few things to try:\n\n' +
        '- Rephrase the question to match wording the document might use\n' +
        '- Ask about a specific section or topic you know is in the file\n' +
        "- If you just uploaded the file, make sure indexing finished — re-attach and retry if it didn't"
      );
    }

    if (/codec can't decode|invalid start byte|Parser detail|Failed to parse document/i.test(msg)) {
      const fileMatch = msg.match(/document ['"]([^'"]+)['"]/i);
      const fname = fileMatch ? `"${fileMatch[1]}"` : 'one of your files';
      return (
        `⚠️ I couldn't read ${fname} on the backend. The file is likely in a binary ` +
        'format I can\'t parse server-side (e.g. legacy .doc, .xls, or a corrupted upload). ' +
        'Try uploading the same content as **.pdf** or **.txt** — or, for Word, re-save as ' +
        '**.docx** (which gets converted to text automatically before upload).'
      );
    }

    if (/grounded collection.*not found|collection_id.*not found/i.test(msg)) {
      return (
        '⚠️ The uploaded collection couldn\'t be found on the backend. Try re-attaching ' +
        'your file(s) and sending again — the previous upload may not have finished.'
      );
    }

    if (/429|Too Many Requests|rate limit/i.test(msg)) {
      return '⚠️ Rate-limited by the upstream service. Wait a moment and try again.';
    }

    if (/network|fetch|ECONNREFUSED/i.test(msg)) {
      return '⚠️ Couldn\'t reach the backend. Make sure the FastAPI server is running on port 8000.';
    }

    return `⚠️ Error: ${msg}`;
  }

  function handleStop() {
    let ctrl;
    const unsub = streamController.subscribe((v) => (ctrl = v));
    unsub();
    if (ctrl?.abort) ctrl.abort();
  }

  // ── Read the active conversation snapshot synchronously ──
  function getActiveConv() {
    let convId, list;
    const u1 = activeConversationId.subscribe((v) => (convId = v));
    u1();
    const u2 = conversations.subscribe((v) => (list = v));
    u2();
    return list?.find((c) => c.id === convId) || null;
  }

  // Extract a flat text prompt from a message's content array — used to
  // re-send the original user prompt during regenerate.
  function extractPrompt(content) {
    if (!Array.isArray(content)) return '';
    return content
      .filter((b) => b?.type === 'text')
      .map((b) => b.text)
      .join('\n\n')
      .trim();
  }

  // ── Regenerate an assistant message ───────────────────────
  // Drops the assistant bubble (and anything after it), then re-runs the
  // immediately-preceding user prompt through the full pipeline.
  async function handleRegenerate(assistantMessageId) {
    const conv = getActiveConv();
    if (!conv) return;
    const asstIdx = conv.messages.findIndex((m) => m.id === assistantMessageId);
    if (asstIdx < 1) return;
    // Walk back to the nearest user message before this assistant turn.
    let userIdx = asstIdx - 1;
    while (userIdx >= 0 && conv.messages[userIdx].role !== 'user') userIdx--;
    if (userIdx < 0) return;
    const userMsg = conv.messages[userIdx];
    const prompt = extractPrompt(userMsg.content);
    if (!prompt) return;

    truncateConversationAfter(conv.id, userMsg.id);
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    speakingMessageId.set(null);
    await handleSend({ detail: { message: prompt } }, { skipUserBubble: true });
  }

  // ── Regenerate the same prompt on a specific model ─────────
  // Re-runs the preceding user turn forcing `sel.modelId` (or Smart Routing),
  // so you can compare the same query across models. sel = { modelId, name,
  // tier, provider }; modelId 'smart_routing' is a plain re-run.
  async function handleRegenerateWith(assistantMessageId, sel) {
    const conv = getActiveConv();
    if (!conv) return;
    const asstIdx = conv.messages.findIndex((m) => m.id === assistantMessageId);
    if (asstIdx < 1) return;
    let userIdx = asstIdx - 1;
    while (userIdx >= 0 && conv.messages[userIdx].role !== 'user') userIdx--;
    if (userIdx < 0) return;
    const userMsg = conv.messages[userIdx];
    const prompt = extractPrompt(userMsg.content);
    if (!prompt) return;

    truncateConversationAfter(conv.id, userMsg.id);
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    speakingMessageId.set(null);

    const isSmart = !sel || sel.modelId === 'smart_routing';
    await handleSend(
      { detail: { message: prompt } },
      {
        skipUserBubble: true,
        forceModelId: isSmart ? null : sel.modelId,
        forceModelMeta: isSmart
          ? null
          : { name: sel.name, tier: sel.tier, provider: sel.provider },
      },
    );
  }

  // ── Edit a user message and regenerate downstream ──────────
  async function handleEditCommit(userMessageId, newText) {
    const trimmed = (newText || '').trim();
    if (!trimmed) return;
    const conv = getActiveConv();
    if (!conv) return;
    const idx = conv.messages.findIndex((m) => m.id === userMessageId);
    if (idx < 0) return;

    // Rewrite the user bubble in-place, preserving any attachment indicators.
    const existing = conv.messages[idx];
    const passthrough = (existing.content || []).filter(
      (b) => b?.type === 'attachments' || b?.type === 'web_search_indicator',
    );
    updateMessage(conv.id, userMessageId, {
      content: [{ type: 'text', text: trimmed }, ...passthrough],
    });
    truncateConversationAfter(conv.id, userMessageId);
    editingMessageId.set(null);
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    speakingMessageId.set(null);

    await handleSend({ detail: { message: trimmed } }, { skipUserBubble: true });
  }

  // ── Quick refine (Shorter / Simpler / etc.) ────────────────
  // QuickRefine builds a self-contained prompt that already includes the
  // original assistant text inline, so we just fire it through handleSend
  // like any other user message. It appears as a new turn in the chat.
  async function handleQuickRefine(event) {
    const { prompt } = event.detail || {};
    if (!prompt) return;
    await handleSend({ detail: { message: prompt } });
  }

  // ── Follow-up suggestion picked ────────────────────────────
  async function handleFollowUpPick(event) {
    const { message } = event.detail || {};
    if (!message) return;
    await handleSend({ detail: { message } });
  }

  // ── Like / dislike on assistant messages ──────────────────
  function handleReaction(messageId, reaction) {
    const conv = getActiveConv();
    if (!conv) return;
    setMessageReaction(conv.id, messageId, reaction);
  }

  // ── Inline-edit start / cancel ────────────────────────────
  function handleStartEdit(messageId) {
    editingMessageId.set(messageId);
  }
  function handleCancelEdit() {
    editingMessageId.set(null);
  }

  // Handle page proof viewing
  function handleViewProof(event) {
    pageViewerProof.set(event.detail.proof);
  }

  function closePageViewer() {
    pageViewerProof.set(null);
  }

  // Toggle the wallet popup (which contains balance, activity, refill).
  // Click on the header chip no longer resets — refill lives inside the popup.
  function handleToggleWallet() {
    walletPopupOpen.update((v) => !v);
  }

  // Keyboard shortcuts
  // True when the keystroke is destined for a text field — so global single-key
  // shortcuts (like "?") don't hijack normal typing.
  function isTypingTarget(el) {
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  function handleKeydown(e) {
    // Cmd/Ctrl+K → command palette (toggle).
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      commandPaletteOpen.update((v) => !v);
      return;
    }
    // "?" → keyboard shortcuts (only when not typing into a field).
    if (e.key === '?' && !e.ctrlKey && !e.metaKey && !isTypingTarget(e.target)) {
      e.preventDefault();
      shortcutsOpen.set(true);
      return;
    }
    if (e.ctrlKey && e.key === 'n') {
      e.preventDefault();
      createConversation();
    }
    if (e.key === 'Escape' && $pageViewerProof) {
      closePageViewer();
    }
  }

  // Format wallet
  function formatWallet(val) {
    return `$${Number(val).toFixed(2)}`;
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div
  class="app-shell"
  class:sidebar-collapsed={!$sidebarOpen}
  ondragenter={handleDragEnter}
  ondragover={handleDragOver}
  ondragleave={handleDragLeave}
  ondrop={handleDrop}
>
  {#if dragActive}
    <div class="drop-overlay">
      <div class="drop-card">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <div class="drop-title">Drop to attach</div>
        <div class="drop-sub">PDF · DOCX · TXT · MD · CSV · JSON · HTML</div>
      </div>
    </div>
  {/if}

  <Sidebar />

  <main class="main-area">
    <header class="chat-header">
      {#if !$sidebarOpen}
        <!-- Sidebar is collapsed — show the "open" variant of the panel-left
             icon (rectangle + right-pointing arrow inside, hinting that the
             panel will expand outward). When the sidebar is open the close
             variant lives inside the sidebar header itself. -->
        <button
          class="sidebar-open-btn"
          onclick={() => sidebarOpen.set(true)}
          aria-label="Open sidebar"
          title="Open sidebar"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <line x1="9" y1="3" x2="9" y2="21"/>
            <polyline points="13 9 16 12 13 15"/>
          </svg>
        </button>
      {/if}

      <!-- Command palette trigger (also Ctrl/⌘+K) -->
      <button
        class="cmdk-trigger"
        onclick={() => commandPaletteOpen.set(true)}
        title="Search & commands"
        aria-label="Open command palette"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
        </svg>
        <span class="cmdk-label">Search</span>
        <kbd class="cmdk-kbd">{modLabel} K</kbd>
      </button>

      <div class="header-center">
        {#if route.mode === 'rag' && route.collection}
          <span class="rag-badge">RAG</span>
          <span class="header-title">{route.collection}</span>
        {:else}
          <span class="header-title">V07</span>
        {/if}
      </div>

      <div class="header-right">
        <!-- Theme toggle (light / dark) -->
        <button
          class="theme-toggle"
          onclick={toggleTheme}
          aria-label="Toggle color theme"
          title={$theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        >
          {#if $theme === 'dark'}
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
            </svg>
          {:else}
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          {/if}
        </button>

        <!-- Preferences (settings popover) -->
        <div class="settings-display">
          <button
            class="settings-btn"
            class:popup-open={$settingsOpen}
            onclick={() => settingsOpen.update((v) => !v)}
            aria-label="Preferences"
            aria-expanded={$settingsOpen}
            aria-haspopup="dialog"
            title="Preferences"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          {#if $settingsOpen}
            <SettingsPopup />
          {/if}
        </div>

        <!-- Wallet chip — opens the wallet popup with balance + activity + refill -->
        <div class="wallet-display" title="Open wallet">
          <button
            class="wallet-btn"
            class:popup-open={$walletPopupOpen}
            onclick={handleToggleWallet}
            aria-expanded={$walletPopupOpen}
            aria-haspopup="dialog"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/>
              <path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/>
              <path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>
            </svg>
            <span class="wallet-amount" class:low={$walletBalance < 10}>{formatWallet($walletBalance)}</span>
          </button>
          {#if $lastCostCharged > 0}
            {#key $lastCostCharged}
              <span class="wallet-charged">−${$lastCostCharged.toFixed(4)}</span>
            {/key}
          {/if}
          {#if $walletPopupOpen}
            <WalletPopup />
          {/if}
        </div>

        <!-- Model selector chip -->
        <button class="model-chip" onclick={() => modelSelectorOpen.update((v) => !v)}>
          <span class="model-dot" class:smart={$selectedModel.mode === 'smart'}></span>
          <span class="model-chip-label">{$selectedModel.name}</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </div>
    </header>

    <ChatArea
      {route}
      on:send={handleSend}
      on:viewProof={handleViewProof}
      on:regenerate={(e) => handleRegenerate(e.detail.messageId)}
      on:regenerateWith={(e) => handleRegenerateWith(e.detail.messageId, e.detail.model)}
      on:editCommit={(e) => handleEditCommit(e.detail.messageId, e.detail.text)}
      on:editStart={(e) => handleStartEdit(e.detail.messageId)}
      on:editCancel={handleCancelEdit}
      on:reaction={(e) => handleReaction(e.detail.messageId, e.detail.reaction)}
      on:refine={handleQuickRefine}
      on:followUp={handleFollowUpPick}
    />
    <InputBar on:send={handleSend} on:stop={handleStop} {route} />
  </main>

  {#if $modelSelectorOpen}
    <ModelSelector />
  {/if}

  {#if $commandPaletteOpen}
    <CommandPalette />
  {/if}

  {#if $shortcutsOpen}
    <ShortcutsOverlay />
  {/if}

  <!-- Page Viewer overlay for RAG citations -->
  <PageViewer
    proof={$pageViewerProof}
    visible={$pageViewerProof !== null}
    on:close={closePageViewer}
  />

  <!-- Toast notifications -->
  <Toaster />

  <!-- Fullscreen image lightbox -->
  <Lightbox />
</div>

<style>
  .app-shell {
    display: flex;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
    background: var(--bg-primary);
  }

  /* ── Drag-and-drop overlay ───────── */
  .drop-overlay {
    position: fixed;
    inset: 0;
    z-index: 250;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    pointer-events: none; /* purely visual — the drop is handled by .app-shell */
    animation: dropFade 0.15s var(--ease-out);
  }
  @keyframes dropFade { from { opacity: 0; } to { opacity: 1; } }
  .drop-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-10) var(--space-12);
    border: 2px dashed var(--accent-primary);
    border-radius: var(--radius-xl);
    background: rgba(16, 163, 127, 0.1);
    color: var(--accent-primary);
    box-shadow: var(--shadow-lg);
  }
  .drop-title {
    font-size: var(--text-lg);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
  }
  .drop-sub {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    font-family: var(--font-mono);
    letter-spacing: 0.02em;
  }

  .main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    background: var(--surface-chat);
    position: relative;
  }

  /* ── Header ──────────────────────── */
  .chat-header {
    height: var(--header-height);
    display: flex;
    align-items: center;
    padding: 0 var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
    background: var(--surface-chat);
    gap: var(--space-3);
    flex-shrink: 0;
    z-index: 10;
  }

  .sidebar-open-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    transition: background var(--duration-fast), color var(--duration-fast);
    /* Wait for the sidebar to mostly finish collapsing before this button
       fades in, so the two animations don't fight each other. */
    animation: openBtnEnter 0.25s var(--ease-out) 0.2s both;
  }
  .sidebar-open-btn:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  @keyframes openBtnEnter {
    from { opacity: 0; transform: translateX(-6px); }
    to { opacity: 1; transform: translateX(0); }
  }

  /* ── Command palette trigger ─────── */
  .cmdk-trigger {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px 10px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    color: var(--text-tertiary);
    background: var(--surface-card);
    transition: all var(--duration-fast);
    flex-shrink: 0;
  }
  .cmdk-trigger:hover {
    border-color: var(--border-strong);
    color: var(--text-secondary);
    background: var(--surface-glass);
  }
  .cmdk-label { font-size: var(--text-sm); }
  .cmdk-kbd {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-muted);
    background: rgba(var(--overlay-rgb), 0.06);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 1px 5px;
  }

  .header-center {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    justify-content: center;
  }

  .header-title {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
  }

  .rag-badge {
    font-size: var(--text-xs);
    font-weight: var(--weight-bold);
    background: var(--accent-gradient);
    color: white;
    padding: 2px 8px;
    border-radius: var(--radius-full);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  /* ── Header right ───────────────── */
  .header-right {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  /* ── Theme toggle ───────────────── */
  .theme-toggle {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-full);
    border: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    transition: all var(--duration-fast);
  }
  .theme-toggle:hover {
    border-color: var(--border-strong);
    color: var(--text-primary);
    background: var(--surface-glass);
  }

  /* ── Settings ───────────────────── */
  .settings-display {
    position: relative;
    display: flex;
    align-items: center;
  }
  .settings-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-full);
    border: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    transition: all var(--duration-fast);
  }
  .settings-btn:hover {
    border-color: var(--border-strong);
    color: var(--text-primary);
    background: var(--surface-glass);
  }
  .settings-btn.popup-open {
    border-color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.08);
    color: var(--text-primary);
    box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.12);
  }

  /* ── Wallet ─────────────────────── */
  .wallet-display {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    position: relative;
  }

  .wallet-btn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-full);
    font-size: var(--text-sm);
    color: var(--text-secondary);
    transition: all var(--duration-fast);
    font-family: var(--font-mono);
  }
  .wallet-btn:hover {
    border-color: var(--border-strong);
    color: var(--text-primary);
    background: var(--surface-glass);
  }
  .wallet-btn.popup-open {
    border-color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.08);
    color: var(--text-primary);
    box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.12);
  }

  .wallet-amount {
    font-weight: var(--weight-semibold);
    color: var(--success);
  }
  .wallet-amount.low {
    color: var(--warning);
  }

  .wallet-charged {
    position: absolute;
    top: -8px;
    right: -4px;
    font-size: 10px;
    color: var(--error);
    font-family: var(--font-mono);
    font-weight: var(--weight-semibold);
    background: var(--bg-secondary);
    padding: 1px 4px;
    border-radius: var(--radius-sm);
    animation: fadeInUp 0.3s var(--ease-out);
    pointer-events: none;
  }

  /* ── Model chip ──────────────────── */
  .model-chip {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-full);
    font-size: var(--text-sm);
    color: var(--text-secondary);
    transition: all var(--duration-fast);
    white-space: nowrap;
  }
  .model-chip:hover {
    border-color: var(--border-strong);
    color: var(--text-primary);
    background: var(--surface-glass);
  }

  .model-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--tier-moderate);
  }
  .model-dot.smart {
    background: var(--accent-primary);
    box-shadow: 0 0 8px var(--accent-glow);
  }

  .model-chip-label {
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* ── Responsive ──────────────────── */
  @media (max-width: 768px) {
    .app-shell.sidebar-collapsed :global(.sidebar) {
      transform: translateX(-100%);
    }
    .model-chip-label {
      display: none;
    }
    .wallet-charged {
      display: none;
    }
    .cmdk-label,
    .cmdk-kbd {
      display: none;
    }
  }
</style>
