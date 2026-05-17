<script>
  import { onMount } from 'svelte';
  import { selectedModel, modelSelectorOpen } from '../lib/stores.js';
  import { getModels } from '../lib/api.js';

  let models = $state([]);
  let search = $state('');
  let loading = $state(true);
  let panelEl = $state(null);

  // ── Provider → inline SVG + brand color + display label ──────
  //
  // SVG paths are inlined so we don't depend on an external icon CDN. Each
  // path is sized for a 24×24 viewBox and uses fill="currentColor", which
  // means the SVG inherits whatever `color:` the parent has — we set it to
  // white in CSS, so all logos appear white-on-brand-colored-chip.
  const PROVIDER_LOGO = {
    openai: {
      label: 'OpenAI',
      color: '#000000',
      svg:
        '<path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5Z"/>',
    },
    // Anthropic + Claude both render as the **Claude product mark** — the
    // 11-ray asymmetric sunburst, which is far more recognisable to users
    // than the Anthropic corporate A-wedge. 11 trapezoidal rays radiating
    // from center; equal angular spacing (360°/11 ≈ 32.73°). Tapered
    // (wider at base, narrower at tip) to match the brand's hand-drawn feel.
    anthropic: {
      label: 'Claude',
      color: '#CC785C',
      svg:
        '<g transform="translate(12 12)">' +
        ['<polygon points="-0.85,-1 0.85,-1 0.4,-11 -0.4,-11"/>']
          .concat(
            [32.73, 65.45, 98.18, 130.91, 163.64, 196.36, 229.09, 261.82, 294.55, 327.27]
              .map((a) => `<polygon points="-0.85,-1 0.85,-1 0.4,-11 -0.4,-11" transform="rotate(${a})"/>`),
          )
          .join('') +
        '</g>',
    },
    claude: {
      label: 'Claude',
      color: '#CC785C',
      svg:
        '<g transform="translate(12 12)">' +
        ['<polygon points="-0.85,-1 0.85,-1 0.4,-11 -0.4,-11"/>']
          .concat(
            [32.73, 65.45, 98.18, 130.91, 163.64, 196.36, 229.09, 261.82, 294.55, 327.27]
              .map((a) => `<polygon points="-0.85,-1 0.85,-1 0.4,-11 -0.4,-11" transform="rotate(${a})"/>`),
          )
          .join('') +
        '</g>',
    },
    // Google + Gemini both render as the **Gemini product mark** — the
    // 4-point diamond "spark" with concave (inward-bulging) sides. The
    // tips reach to viewBox edges; cubic bezier control points pull the
    // sides toward center to create the pinched-waist look.
    google: {
      label: 'Gemini',
      color: '#1F6FEB',
      svg: '<path d="M12 1 C 13 8, 16 11, 23 12 C 16 13, 13 16, 12 23 C 11 16, 8 13, 1 12 C 8 11, 11 8, 12 1 Z"/>',
    },
    gemini: {
      label: 'Gemini',
      color: '#1F6FEB',
      svg: '<path d="M12 1 C 13 8, 16 11, 23 12 C 16 13, 13 16, 12 23 C 11 16, 8 13, 1 12 C 8 11, 11 8, 12 1 Z"/>',
    },
    meta: {
      label: 'Meta',
      color: '#0866FF',
      // Meta's infinity/ribbon mark — simplified single path.
      svg: '<path d="M6.897 4C3.179 4 1 7.187 1 11.913 1 16.482 3.121 20 6.778 20c2.176 0 3.748-1.16 6.378-5.726 0 0 1.073-1.937 1.811-3.247.255.42.527.888.81 1.394l1.198 2.108C19.235 18.06 20.703 20 23.045 20 26.609 20 28 16.566 28 11.945 28 7.118 25.769 4 22.155 4c-1.904 0-3.421 1.405-5.084 3.71-1.151-1.587-2.158-3.71-4.916-3.71-2.769 0-4.829 1.916-6.518 4.92C4.378 11.196 2.768 14.42 2.768 16.5c0 .872.213 1.51.572 1.94L4.7 16.913c-.06-.18-.103-.392-.103-.665 0-.872.467-2.149 1.337-3.624.949-1.61 1.79-2.46 2.595-2.46 1.108 0 2.061 1.276 3.337 3.413l.85 1.422c-1.7 2.83-2.96 4.42-3.776 4.42-1.06 0-1.685-.972-1.685-2.704 0-2.704 1.234-5.715 3.275-5.715z"/>',
    },
    mistral: {
      label: 'Mistral AI',
      color: '#FA520F',
      // 3-bar geometric shape — recalls the Mistral "wind" mark.
      svg: '<path d="M3 4h4v4H3V4zm0 6h4v4H3v-4zm0 6h4v4H3v-4zm6-12h4v4H9V4zm0 12h4v4H9v-4zm6-12h4v4h-4V4zm0 6h4v4h-4v-4zm0 6h4v4h-4v-4z"/>',
    },
    mistralai: {
      label: 'Mistral AI',
      color: '#FA520F',
      svg: '<path d="M3 4h4v4H3V4zm0 6h4v4H3v-4zm0 6h4v4H3v-4zm6-12h4v4H9V4zm0 12h4v4H9v-4zm6-12h4v4h-4V4zm0 6h4v4h-4v-4zm0 6h4v4h-4v-4z"/>',
    },
    xai: {
      label: 'xAI',
      color: '#000000',
      svg: '<path d="M4 4l7.5 8.5L4 20h3l6-6.75L19 20h2.5l-7.5-8.5L21.5 4H19l-5.75 6.5L7.5 4H4z"/>',
    },
    grok: {
      label: 'xAI',
      color: '#000000',
      svg: '<path d="M4 4l7.5 8.5L4 20h3l6-6.75L19 20h2.5l-7.5-8.5L21.5 4H19l-5.75 6.5L7.5 4H4z"/>',
    },
    cohere: {
      label: 'Cohere',
      color: '#FF7759',
      // Stylised "C" with negative-space cutout.
      svg: '<path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10c2.652 0 5.196-1.054 7.07-2.93l-2.121-2.12A6.962 6.962 0 0 1 12 19a7 7 0 1 1 0-14c1.866 0 3.66.742 4.95 2.05l2.12-2.121A9.996 9.996 0 0 0 12 2zm-1 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"/>',
    },
    perplexity: {
      label: 'Perplexity',
      color: '#21B0CD',
      // Stylised "P" mark.
      svg: '<path d="M6 3h7a5 5 0 0 1 0 10H9v8H6V3zm3 3v4h4a2 2 0 1 0 0-4H9z"/>',
    },
    microsoft: {
      label: 'Microsoft',
      color: '#0078D4',
      svg: '<path d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zM24 11.4H12.6V0H24v11.4z"/>',
    },
    deepseek: {
      label: 'DeepSeek',
      color: '#4D6BFE',
      // Stylised swirl / wave mark recalling the DeepSeek whale silhouette.
      svg: '<path d="M21 7c-1.5 0-2.7.7-3.5 1.8C16.7 7.7 15.5 7 14 7H8C5 7 3 9.5 3 13s2 6 5 6h1.5c2 0 3.8-1 5-2.5L17 19c.5.5 1.5.5 2 0 .5-.5.5-1.3 0-1.8l-1.3-1.3c1.3-.9 2.3-2.5 2.3-4.4 0-2.3-1-3.8-2-4.5h3c.5 0 1-.5 1-1s-.5-1-1-1zm-7 9H8c-1.7 0-3-1.5-3-3s1.3-3 3-3h6c1.7 0 3 1.5 3 3s-1.3 3-3 3zm-1-4a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/>',
    },
    alibaba: {
      label: 'Alibaba',
      color: '#FF6A00',
      // Stylised twin-mountain Alibaba mark, simplified.
      svg: '<path d="M3 5h5l3 5-4 7H3l4-7L3 5zm8 0h5l4 7-4 7h-5l4-7-4-7z"/>',
    },
    qwen: {
      label: 'Alibaba (Qwen)',
      color: '#FF6A00',
      svg: '<path d="M3 5h5l3 5-4 7H3l4-7L3 5zm8 0h5l4 7-4 7h-5l4-7-4-7z"/>',
    },
    yi: {
      label: '01.AI (Yi)',
      color: '#1A1A2E',
      // The Yi mark is the digits "01" — stylised as a 0 + 1 monogram.
      svg: '<path d="M3 5a3 3 0 0 1 3-3h2a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V5zm3-1a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1H6zm10 0v14a1 1 0 0 0 1 1h2a1 1 0 0 0 0-2h-1V4a1 1 0 0 0-1-1h-3a1 1 0 0 0 0 2h2z"/>',
    },
    '01ai': {
      label: '01.AI (Yi)',
      color: '#1A1A2E',
      svg: '<path d="M3 5a3 3 0 0 1 3-3h2a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V5zm3-1a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1H6zm10 0v14a1 1 0 0 0 1 1h2a1 1 0 0 0 0-2h-1V4a1 1 0 0 0-1-1h-3a1 1 0 0 0 0 2h2z"/>',
    },
    ibm: {
      label: 'IBM',
      color: '#0F62FE',
      svg: '<path d="M2 4h6v2H2V4zm8 0h12v2H10V4zM2 7h6v2H2V7zm8 0h4v2h-4V7zm6 0h6v2h-6V7zM2 10h6v2H2v-2zm8 0h4v2h-4v-2zm6 0h6v2h-6v-2zM2 13h6v2H2v-2zm8 0h12v2H10v-2zM2 16h6v2H2v-2zm8 0h12v2H10v-2zM2 19h6v2H2v-2zm8 0h12v2H10v-2z"/>',
    },
    nvidia: {
      label: 'NVIDIA',
      color: '#76B900',
      svg: '<path d="M9.6 4l-2.4 8 2.4 8h2.4l-2.4-8 2.4-8H9.6zm4.8 0L12 12l2.4 8h2.4l-2.4-8 2.4-8h-2.4z"/>',
    },
  };

  // Render the raw provider string as a properly cased brand name. Falls
  // back to title-casing the raw value when we don't have a mapping.
  function formatProvider(rawProvider, pKey) {
    if (pKey && PROVIDER_LOGO[pKey]?.label) return PROVIDER_LOGO[pKey].label;
    const raw = (rawProvider || '').trim();
    if (!raw) return '';
    return raw.charAt(0).toUpperCase() + raw.slice(1);
  }

  // Resolve a logo from the provider field first, then fall back to scanning
  // the display name for known model-family substrings (since v07 sometimes
  // has "openai" as provider, sometimes just "gpt-4o" as a display string).
  function providerKey(provider, displayName) {
    const p = (provider || '').toLowerCase().trim();
    const d = (displayName || '').toLowerCase();

    if (PROVIDER_LOGO[p]) return p;
    for (const key of Object.keys(PROVIDER_LOGO)) {
      if (p && p.includes(key)) return key;
    }
    if (/\b(gpt|chatgpt|o1|o3|o4)\b/.test(d)) return 'openai';
    if (/\bclaude\b/.test(d)) return 'claude';
    if (/\b(gemini|palm|bard)\b/.test(d)) return 'gemini';
    if (/\bllama\b/.test(d)) return 'meta';
    if (/\b(mistral|mixtral|codestral)\b/.test(d)) return 'mistral';
    if (/\bgrok\b/.test(d)) return 'xai';
    if (/\bcommand-?[rln]?\b|\bcohere\b/.test(d)) return 'cohere';
    if (/\bphi[-\s]?\d|copilot\b/.test(d)) return 'microsoft';
    if (/\bdeepseek\b/.test(d)) return 'deepseek';
    if (/\bqwen\b/.test(d)) return 'alibaba';
    // Yi models from 01.AI — match "yi" as a whole word OR "01.ai".
    if (/\b(yi(-\d+)?|01\.?ai|01-ai)\b/.test(d) || /^yi[-_]/.test(d)) return 'yi';
    if (/\b(perplexity|sonar)\b/.test(d)) return 'perplexity';
    return null;
  }

  // (no CDN to fail on any more — SVGs are inlined.)

  onMount(async () => {
    try {
      models = await getModels();
    } catch (e) {
      console.error('Failed to load models:', e);
    } finally {
      loading = false;
    }

    // Click outside to close
    function handleClick(e) {
      if (panelEl && !panelEl.contains(e.target)) {
        modelSelectorOpen.set(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  });

  let filtered = $derived.by(() => {
    if (!search.trim()) return models;
    const q = search.toLowerCase();
    return models.filter(m =>
      m.display_name.toLowerCase().includes(q) ||
      m.provider.toLowerCase().includes(q) ||
      m.tier.toLowerCase().includes(q)
    );
  });

  let grouped = $derived.by(() => {
    const groups = {};
    for (const m of filtered) {
      const tier = m.tier || 'other';
      if (!groups[tier]) groups[tier] = [];
      groups[tier].push(m);
    }
    // Sort each tier by cost descending — most expensive (typically most
    // capable) model first within the tier so the strongest option is the
    // user's default eye-line. Missing-cost entries sink to the bottom.
    for (const tier of Object.keys(groups)) {
      groups[tier].sort(
        (a, b) => (b.cost_per_1k_tokens ?? -Infinity) - (a.cost_per_1k_tokens ?? -Infinity),
      );
    }
    return groups;
  });

  const tierOrder = ['premium', 'moderate', 'cheap'];
  const tierMeta = {
    premium: { emoji: '🔴', label: 'Premium', color: 'var(--tier-premium)' },
    moderate: { emoji: '🟡', label: 'Moderate', color: 'var(--tier-moderate)' },
    cheap: { emoji: '🟢', label: 'Budget', color: 'var(--tier-cheap)' },
  };

  function selectModel(model) {
    selectedModel.set({
      id: model.model_id,
      name: model.display_name,
      mode: 'manual',
      tier: model.tier,
      provider: model.provider,
    });
    modelSelectorOpen.set(false);
  }

  function selectSmartRouting() {
    selectedModel.set({ id: 'smart_routing', name: 'Smart Routing', mode: 'smart' });
    modelSelectorOpen.set(false);
  }

  function formatCost(cost) {
    if (cost < 0.001) return `$${(cost * 1000).toFixed(2)}/M`;
    return `$${cost.toFixed(4)}/1K`;
  }
</script>

<div class="model-overlay">
  <div class="model-panel animate-slide-down" bind:this={panelEl}>
    <div class="panel-header">
      <h3>Select Model</h3>
      <button class="close-btn" onclick={() => modelSelectorOpen.set(false)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
    </div>

    <div class="search-box">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
      </svg>
      <input 
        type="text" 
        placeholder="Search models..." 
        bind:value={search}
      />
    </div>

    <div class="model-list">
      <!-- Smart Routing option -->
      <button 
        class="model-item smart-routing" 
        class:active={$selectedModel.mode === 'smart'}
        onclick={selectSmartRouting}
      >
        <div class="model-icon smart-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
          </svg>
        </div>
        <div class="model-info">
          <div class="model-name">Smart Routing</div>
          <div class="model-desc">AI selects the optimal model per query</div>
        </div>
        {#if $selectedModel.mode === 'smart'}
          <div class="active-check">✓</div>
        {/if}
      </button>

      <div class="divider"></div>

      {#if loading}
        <div class="loading-models">
          {#each [1,2,3] as _}
            <div class="skeleton" style="height: 56px; margin-bottom: 8px;"></div>
          {/each}
        </div>
      {:else}
        {#each tierOrder as tier}
          {#if grouped[tier]?.length}
            <div class="tier-group">
              <div class="tier-label" style="--tier-color: {tierMeta[tier]?.color}">
                <span>{tierMeta[tier]?.emoji}</span>
                <span>{tierMeta[tier]?.label} Tier</span>
              </div>

              {#each grouped[tier] as model}
                {@const pKey = providerKey(model.provider, model.display_name)}
                {@const logo = pKey ? PROVIDER_LOGO[pKey] : null}
                <button
                  class="model-item"
                  class:active={$selectedModel.id === model.model_id}
                  onclick={() => selectModel(model)}
                >
                  {#if logo}
                    <div class="model-icon brand-icon" style="background: {logo.color};">
                      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        {@html logo.svg}
                      </svg>
                    </div>
                  {:else}
                    <div class="model-icon" style="background: {tierMeta[tier]?.color}22; color: {tierMeta[tier]?.color};">
                      {model.display_name[0]}
                    </div>
                  {/if}
                  <div class="model-info">
                    <div class="model-name">{model.display_name}</div>
                    <div class="model-desc">
                      {formatProvider(model.provider, pKey)} · {formatCost(model.cost_per_1k_tokens)}
                    </div>
                  </div>
                  {#if $selectedModel.id === model.model_id}
                    <div class="active-check">✓</div>
                  {/if}
                </button>
              {/each}
            </div>
          {/if}
        {/each}

        {#if filtered.length === 0}
          <div class="no-results">No models match "{search}"</div>
        {/if}
      {/if}
    </div>
  </div>
</div>

<style>
  .model-overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 60px;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
  }

  .model-panel {
    width: 420px;
    max-height: calc(100vh - 120px);
    background: var(--bg-secondary);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border-subtle);
  }
  .panel-header h3 {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    margin: 0;
  }

  .close-btn {
    width: 32px;
    height: 32px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    transition: all var(--duration-fast);
  }
  .close-btn:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  /* ── Search ─────────────────────── */
  .search-box {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-3) var(--space-4);
    padding: var(--space-3);
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    color: var(--text-muted);
  }
  .search-box:focus-within {
    border-color: var(--accent-primary);
  }
  .search-box input {
    flex: 1;
    color: var(--text-primary);
    font-size: var(--text-sm);
    background: transparent;
    /* Strip the browser default border + focus outline — the parent
       .search-box already shows focus state via :focus-within. */
    border: none;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
    padding: 0;
  }
  .search-box input:focus {
    outline: none;
    box-shadow: none;
  }
  .search-box input::placeholder {
    color: var(--text-muted);
  }

  /* ── Model list ─────────────────── */
  .model-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 var(--space-3) var(--space-3);
  }

  .model-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    text-align: left;
    transition: background var(--duration-fast);
    margin-bottom: 2px;
  }
  .model-item:hover {
    background: var(--bg-hover);
  }
  .model-item.active {
    background: rgba(16, 163, 127, 0.08);
  }

  .model-icon {
    width: 36px;
    height: 36px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--text-sm);
    font-weight: var(--weight-bold);
    flex-shrink: 0;
    background: var(--surface-glass);
    overflow: hidden;
  }
  /* SVG provider mark: pure white via currentColor on a brand-coloured chip. */
  .model-icon.brand-icon { color: #ffffff; }
  .model-icon.brand-icon svg {
    width: 22px;
    height: 22px;
    display: block;
  }
  .smart-icon {
    background: var(--accent-gradient) !important;
    color: white !important;
  }

  .model-info {
    flex: 1;
    min-width: 0;
  }
  .model-name {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .model-desc {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    margin-top: 1px;
  }

  .active-check {
    color: var(--accent-primary);
    font-weight: var(--weight-bold);
    font-size: var(--text-md);
    flex-shrink: 0;
  }

  /* ── Tier groups ────────────────── */
  .divider {
    height: 1px;
    background: var(--border-subtle);
    margin: var(--space-2) var(--space-3);
  }

  .tier-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    font-weight: var(--weight-semibold);
    color: var(--text-muted);
    padding: var(--space-3) var(--space-3) var(--space-1);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .no-results {
    text-align: center;
    padding: var(--space-8);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }

  .loading-models {
    padding: var(--space-2) var(--space-3);
  }

  .smart-routing {
    border: 1px solid rgba(16, 163, 127, 0.15);
    background: rgba(16, 163, 127, 0.04);
    margin-bottom: var(--space-1);
  }

  @media (max-width: 480px) {
    .model-panel {
      width: calc(100vw - 32px);
      max-height: calc(100vh - 80px);
    }
  }
</style>
