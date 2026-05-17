<script>
  import { createConversation } from '../lib/stores.js';
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher();

  const suggestions = [
    { icon: '💡', title: 'Explain a concept', prompt: 'Explain quantum computing in simple terms', color: '#8b5cf6' },
    { icon: '🧑‍💻', title: 'Write code', prompt: 'Write a Python function for binary search with explanation', color: '#10a37f' },
    { icon: '📊', title: 'Analyze data', prompt: 'Compare the pros and cons of SQL vs NoSQL databases', color: '#0ea5e9' },
    { icon: '✍️', title: 'Help me write', prompt: 'Draft a professional email requesting a project deadline extension', color: '#f59e0b' },
  ];

  function handleSuggestion(prompt) {
    dispatch('suggestion', { message: prompt });
  }
</script>

<div class="welcome">
  <div class="welcome-inner">
    <!-- Floating orbs background -->
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>

    <div class="welcome-content">
      <div class="logo-mark">
        <span class="logo-text">V07</span>
      </div>
      <h1 class="welcome-heading">How can I help you today?</h1>
      <p class="welcome-sub">Powered by intelligent model routing — always the best model for your query.</p>

      <div class="suggestions-grid">
        {#each suggestions as sug, i}
          <button 
            class="suggestion-card" 
            onclick={() => handleSuggestion(sug.prompt)}
            style="--card-accent: {sug.color}; animation-delay: {i * 80}ms"
          >
            <span class="suggestion-icon">{sug.icon}</span>
            <span class="suggestion-title">{sug.title}</span>
            <span class="suggestion-prompt">{sug.prompt}</span>
          </button>
        {/each}
      </div>

      <div class="feature-badges">
        <span class="badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          Smart Routing
        </span>
        <span class="badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
          Rich Responses
        </span>
        <span class="badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          RAG Citations
        </span>
      </div>
    </div>
  </div>
</div>

<style>
  .welcome {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
  }

  .welcome-inner {
    position: relative;
    width: 100%;
    max-width: 680px;
    padding: var(--space-8);
  }

  /* ── Floating orbs ──────────────── */
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.15;
    pointer-events: none;
    animation: float 20s ease-in-out infinite;
  }
  .orb-1 {
    width: 300px; height: 300px;
    background: var(--accent-primary);
    top: -80px; right: -60px;
  }
  .orb-2 {
    width: 250px; height: 250px;
    background: #8b5cf6;
    bottom: -60px; left: -40px;
    animation-delay: -7s;
  }
  .orb-3 {
    width: 200px; height: 200px;
    background: #0ea5e9;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    animation-delay: -14s;
  }

  .welcome-content {
    position: relative;
    z-index: 1;
    text-align: center;
  }

  /* ── Logo ────────────────────────── */
  .logo-mark {
    width: 56px;
    height: 56px;
    margin: 0 auto var(--space-6);
    border-radius: var(--radius-lg);
    background: var(--accent-gradient);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: var(--shadow-glow);
  }
  .logo-text {
    font-size: var(--text-lg);
    font-weight: var(--weight-bold);
    color: white;
    letter-spacing: 0.02em;
  }

  .welcome-heading {
    font-size: var(--text-2xl);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    margin-bottom: var(--space-3);
    line-height: var(--leading-tight);
  }

  .welcome-sub {
    font-size: var(--text-base);
    color: var(--text-secondary);
    margin-bottom: var(--space-8);
    max-width: 480px;
    margin-left: auto;
    margin-right: auto;
  }

  /* ── Suggestion cards ───────────── */
  .suggestions-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--space-3);
    margin-bottom: var(--space-8);
  }

  .suggestion-card {
    text-align: left;
    padding: var(--space-4);
    background: var(--surface-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    transition: all var(--duration-normal) var(--ease-out);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    animation: fadeInUp 0.4s var(--ease-out) both;
  }
  .suggestion-card:hover {
    border-color: var(--card-accent, var(--accent-primary));
    background: rgba(255, 255, 255, 0.06);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  }

  .suggestion-icon {
    font-size: 20px;
    margin-bottom: var(--space-1);
  }

  .suggestion-title {
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
  }

  .suggestion-prompt {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    line-height: var(--leading-relaxed);
  }

  /* ── Feature badges ─────────────── */
  .feature-badges {
    display: flex;
    justify-content: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-full);
  }

  @media (max-width: 600px) {
    .suggestions-grid {
      grid-template-columns: 1fr;
    }
    .welcome-heading {
      font-size: var(--text-xl);
    }
  }
</style>
