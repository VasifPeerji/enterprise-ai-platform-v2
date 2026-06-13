<script>
  import { createEventDispatcher } from 'svelte';
  import {
    isLoading,
    isStreaming,
    selectedModel,
    modelSelectorOpen,
    attachedFiles,
    webSearchEnabled,
    verifyClaimsEnabled,
  } from '../lib/stores.js';
  import { processFileForUpload } from '../lib/api.js';

  let { route = { mode: 'chat', collection: null } } = $props();

  const dispatch = createEventDispatcher();

  let message = $state('');
  let textarea = $state(null);
  let isListening = $state(false);
  let recognition = $state(null);
  let fileInput = $state(null);
  let isProcessingFiles = $state(false);
  let fileError = $state('');
  let fileErrorTimer = null;

  // Accepted file types for the RAG upload — matches what the backend can
  // parse, plus .docx which we convert to text client-side via mammoth.js
  // before upload (the backend can't parse the binary .docx ZIP itself).
  const ACCEPTED_TYPES = '.pdf,.txt,.md,.html,.htm,.csv,.json,.docx';

  function openFilePicker() {
    if ($isLoading || $isStreaming || isProcessingFiles) return;
    fileInput?.click();
  }

  function showFileError(msg) {
    fileError = msg;
    clearTimeout(fileErrorTimer);
    fileErrorTimer = setTimeout(() => (fileError = ''), 7000);
  }

  async function handleFileSelected(event) {
    const picked = Array.from(event.target.files || []);
    // Reset the input first so the same file can be picked again later.
    event.target.value = '';
    if (!picked.length) return;

    isProcessingFiles = true;
    const processed = [];
    const errors = [];
    for (const raw of picked) {
      try {
        const out = await processFileForUpload(raw);
        processed.push(out);
      } catch (e) {
        errors.push(e.message);
      }
    }
    isProcessingFiles = false;

    if (processed.length) {
      attachedFiles.update((curr) => [...curr, ...processed]);
    }
    if (errors.length) {
      // Multiple errors are joined; first one usually says everything useful.
      showFileError(errors.join('  ·  '));
    }
  }

  function removeFile(index) {
    attachedFiles.update((curr) => curr.filter((_, i) => i !== index));
  }

  function toggleWebSearch() {
    if ($isLoading || $isStreaming) return;
    webSearchEnabled.update((v) => !v);
  }

  function toggleVerify() {
    if ($isLoading || $isStreaming) return;
    verifyClaimsEnabled.update((v) => !v);
  }

  function humanSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  // Auto-resize textarea
  function autoResize() {
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
  }

  function handleInput() {
    autoResize();
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSend() {
    const text = message.trim();
    if (!text || $isLoading || $isStreaming) return;
    dispatch('send', { message: text });
    message = '';
    if (textarea) {
      textarea.style.height = 'auto';
    }
  }

  function handleStop() {
    dispatch('stop');
  }

  // ── Speech-to-Text (Web Speech API) ────────────────
  function toggleListening() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Speech recognition is not supported in this browser.');
      return;
    }

    if (isListening && recognition) {
      recognition.stop();
      isListening = false;
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (event) => {
      let transcript = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      message = transcript;
      autoResize();
    };

    recognition.onend = () => {
      isListening = false;
    };

    recognition.onerror = () => {
      isListening = false;
    };

    recognition.start();
    isListening = true;
  }
</script>

<div class="input-bar-wrapper">
  <div class="input-bar">
    {#if fileError}
      <div class="file-error-banner" role="alert">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 8v4M12 16h.01"/>
        </svg>
        <span>{fileError}</span>
        <button class="error-dismiss" onclick={() => (fileError = '')} aria-label="Dismiss">×</button>
      </div>
    {/if}

    {#if isProcessingFiles}
      <div class="processing-banner">
        <span class="processing-spinner"></span>
        <span>Preparing files…</span>
      </div>
    {/if}

    {#if $attachedFiles.length > 0 || $webSearchEnabled || $verifyClaimsEnabled}
      <div class="attachments-row">
        {#if $webSearchEnabled}
          <span class="attachment-chip web-chip" title="Web search active">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>
            </svg>
            <span>Web search</span>
            <button class="chip-remove" onclick={toggleWebSearch} aria-label="Disable web search">×</button>
          </span>
        {/if}
        {#if $verifyClaimsEnabled}
          <span class="attachment-chip verify-chip" title="Claim verification active">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              <path d="M9 12l2 2 4-4"/>
            </svg>
            <span>Verify claims</span>
            <button class="chip-remove" onclick={toggleVerify} aria-label="Disable claim verification">×</button>
          </span>
        {/if}
        {#each $attachedFiles as file, idx}
          <span class="attachment-chip file-chip" title={file.name}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
              <path d="M14 2v6h6"/>
            </svg>
            <span class="chip-name">{file.name}</span>
            <span class="chip-size">{humanSize(file.size)}</span>
            <button class="chip-remove" onclick={() => removeFile(idx)} aria-label="Remove file">×</button>
          </span>
        {/each}
      </div>
    {/if}

    <input
      type="file"
      bind:this={fileInput}
      onchange={handleFileSelected}
      accept={ACCEPTED_TYPES}
      multiple
      style="display: none"
    />

    <div class="input-row">
      <textarea
        bind:this={textarea}
        bind:value={message}
        oninput={handleInput}
        onkeydown={handleKeydown}
        placeholder={route.mode === 'rag' ? `Ask about ${route.collection || 'documents'}...` : 'Message V07...'}
        rows="1"
        disabled={$isLoading || $isStreaming}
      ></textarea>

      <div class="input-actions">
        <!-- Microphone (STT) -->
        <button
          class="action-btn mic-btn"
          class:listening={isListening}
          onclick={toggleListening}
          aria-label="Voice input"
          title="Voice input"
        >
          {#if isListening}
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2"/>
            </svg>
          {:else}
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/>
              <path d="M19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8"/>
            </svg>
          {/if}
        </button>

        <!-- Web search toggle -->
        <button
          class="action-btn web-btn"
          class:active={$webSearchEnabled}
          onclick={toggleWebSearch}
          aria-label="Toggle web search"
          aria-pressed={$webSearchEnabled}
          title={$webSearchEnabled ? 'Web search on (click to disable)' : 'Web search off (click to enable)'}
          disabled={$isLoading || $isStreaming}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>
          </svg>
        </button>

        <!-- Verify claims toggle -->
        <button
          class="action-btn verify-btn"
          class:active={$verifyClaimsEnabled}
          onclick={toggleVerify}
          aria-label="Toggle claim verification"
          aria-pressed={$verifyClaimsEnabled}
          title={$verifyClaimsEnabled ? 'Claim verification on (click to disable)' : 'Verify the answer against its sources'}
          disabled={$isLoading || $isStreaming}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
        </button>

        <!-- Attach file -->
        <button
          class="action-btn"
          onclick={openFilePicker}
          aria-label="Attach file"
          title="Attach file"
          disabled={$isLoading || $isStreaming || isProcessingFiles || route.mode === 'rag'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
          </svg>
        </button>

        {#if $isLoading || $isStreaming}
          <!-- Stop response generation -->
          <button
            class="stop-btn"
            onclick={handleStop}
            aria-label="Stop generating"
            title="Stop generating"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="5" y="5" width="14" height="14" rx="2"/>
            </svg>
          </button>
        {:else}
          <!-- Send -->
          <button
            class="send-btn"
            onclick={handleSend}
            disabled={!message.trim()}
            aria-label="Send message"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
            </svg>
          </button>
        {/if}
      </div>
    </div>

    <div class="input-footer">
      <button class="model-switch" onclick={() => modelSelectorOpen.update(v => !v)}>
        <span class="model-switch-dot" class:smart={$selectedModel.mode === 'smart'}></span>
        <span>{$selectedModel.name}</span>
      </button>
      <span class="footer-hint">
        {#if route.mode === 'rag'}
          RAG Mode · {route.collection}
        {:else}
          Enter ↵ to send · Shift + Enter ↵ for new line
        {/if}
      </span>
    </div>
  </div>
</div>

<style>
  .input-bar-wrapper {
    padding: 0 var(--space-4) var(--space-4);
    background: var(--surface-chat);
    flex-shrink: 0;
  }

  .input-bar {
    max-width: var(--input-max-width);
    margin: 0 auto;
    background: var(--surface-input);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-xl);
    overflow: hidden;
    transition: border-color var(--duration-fast);
  }
  .input-bar:focus-within {
    border-color: var(--border-strong);
  }

  .input-row {
    display: flex;
    align-items: flex-end;
    padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
    gap: var(--space-2);
  }

  textarea {
    flex: 1;
    background: transparent;
    color: var(--text-primary);
    font-size: var(--text-base);
    line-height: var(--leading-normal);
    padding: var(--space-2) 0;
    max-height: 200px;
    min-height: 24px;
    border: none;
    outline: none;
    resize: none;
    font-family: var(--font-sans);
  }
  textarea::placeholder {
    color: var(--text-muted);
  }
  textarea:disabled {
    opacity: 0.5;
  }

  /* ── Actions ────────────────────── */
  .input-actions {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
  }

  .action-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .action-btn:hover:not(:disabled) {
    color: var(--text-primary);
    background: rgba(var(--overlay-rgb), 0.06);
  }
  .action-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .action-btn.web-btn.active {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.12);
  }
  .action-btn.web-btn.active:hover:not(:disabled) {
    background: rgba(16, 163, 127, 0.2);
  }
  .action-btn.verify-btn.active {
    color: var(--info);
    background: rgba(59, 130, 246, 0.12);
  }
  .action-btn.verify-btn.active:hover:not(:disabled) {
    background: rgba(59, 130, 246, 0.2);
  }

  /* ── File error + processing banners ─────────────────── */
  .file-error-banner {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    margin: var(--space-2) var(--space-3) 0;
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: var(--radius-md);
    color: var(--error, #ef4444);
    font-size: var(--text-xs);
    animation: bannerSlide 0.25s var(--ease-out);
  }
  .file-error-banner span {
    flex: 1;
    min-width: 0;
    color: var(--text-primary);
    line-height: 1.4;
  }
  .error-dismiss {
    flex-shrink: 0;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    color: var(--text-muted);
    font-size: 16px;
    line-height: 1;
    transition: all var(--duration-fast);
  }
  .error-dismiss:hover {
    background: rgba(var(--overlay-rgb), 0.06);
    color: var(--text-primary);
  }
  .processing-banner {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 4px var(--space-3);
    margin: var(--space-2) var(--space-3) 0;
    background: rgba(16, 163, 127, 0.08);
    border: 1px solid rgba(16, 163, 127, 0.3);
    border-radius: var(--radius-full);
    color: var(--accent-primary);
    font-size: var(--text-xs);
    width: fit-content;
    animation: bannerSlide 0.25s var(--ease-out);
  }
  .processing-spinner {
    width: 11px;
    height: 11px;
    border-radius: 50%;
    border: 1.5px solid rgba(16, 163, 127, 0.25);
    border-top-color: var(--accent-primary);
    animation: spin 0.8s linear infinite;
  }
  @keyframes bannerSlide {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ── Attachment chips ───────────── */
  .attachments-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3) 0;
  }
  .attachment-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 4px var(--space-2);
    background: rgba(var(--overlay-rgb), 0.06);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-full);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    max-width: 280px;
  }
  .attachment-chip.web-chip {
    background: rgba(16, 163, 127, 0.12);
    border-color: rgba(16, 163, 127, 0.4);
    color: var(--accent-primary);
  }
  .attachment-chip.verify-chip {
    background: rgba(59, 130, 246, 0.12);
    border-color: rgba(59, 130, 246, 0.4);
    color: var(--info);
  }
  .chip-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 160px;
  }
  .chip-size {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .chip-remove {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 14px;
    line-height: 1;
    transition: all var(--duration-fast);
  }
  .chip-remove:hover {
    background: rgba(var(--overlay-rgb), 0.1);
    color: var(--text-primary);
  }

  .mic-btn.listening {
    color: var(--error);
    background: rgba(239, 68, 68, 0.1);
    animation: micPulse 1.5s infinite;
  }

  .send-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--accent-primary);
    color: white;
    transition: all var(--duration-fast) var(--ease-out);
  }
  .send-btn:hover:not(:disabled) {
    background: var(--accent-hover);
    transform: scale(1.05);
  }
  .send-btn:disabled {
    background: var(--bg-hover);
    color: var(--text-muted);
    cursor: not-allowed;
  }

  /* ── Stop button ────────────────── */
  .stop-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--text-primary);
    color: var(--surface-chat);
    transition: all var(--duration-fast) var(--ease-out);
    animation: stopPulse 1.6s ease-in-out infinite;
  }
  .stop-btn:hover {
    transform: scale(1.05);
    opacity: 0.9;
  }
  @keyframes stopPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(var(--overlay-rgb), 0.25); }
    50% { box-shadow: 0 0 0 6px rgba(var(--overlay-rgb), 0); }
  }

  /* ── Footer ─────────────────────── */
  .input-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-4) var(--space-3);
    gap: var(--space-3);
  }

  .model-switch {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-full);
    transition: all var(--duration-fast);
  }
  .model-switch:hover {
    color: var(--text-secondary);
    background: rgba(var(--overlay-rgb), 0.04);
  }

  .model-switch-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--tier-moderate);
  }
  .model-switch-dot.smart {
    background: var(--accent-primary);
    box-shadow: 0 0 6px var(--accent-glow);
  }

  .footer-hint {
    font-size: var(--text-xs);
    color: var(--text-muted);
  }

  @media (max-width: 600px) {
    .input-bar-wrapper {
      padding: 0 var(--space-2) var(--space-2);
    }
    .footer-hint {
      display: none;
    }
  }
</style>
