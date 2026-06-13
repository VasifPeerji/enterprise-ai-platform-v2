<script>
  import { marked } from 'marked';
  import hljs from 'highlight.js/lib/core';
  import javascript from 'highlight.js/lib/languages/javascript';
  import typescript from 'highlight.js/lib/languages/typescript';
  import python from 'highlight.js/lib/languages/python';
  import sql from 'highlight.js/lib/languages/sql';
  import json from 'highlight.js/lib/languages/json';
  import bash from 'highlight.js/lib/languages/bash';
  import xml from 'highlight.js/lib/languages/xml';
  import css from 'highlight.js/lib/languages/css';
  import yaml from 'highlight.js/lib/languages/yaml';
  import go from 'highlight.js/lib/languages/go';
  import rust from 'highlight.js/lib/languages/rust';
  import java from 'highlight.js/lib/languages/java';
  import cpp from 'highlight.js/lib/languages/cpp';
  import csharp from 'highlight.js/lib/languages/csharp';
  import ruby from 'highlight.js/lib/languages/ruby';
  import php from 'highlight.js/lib/languages/php';
  import markdownLang from 'highlight.js/lib/languages/markdown';
  import Chart from 'chart.js/auto';
  import { onMount } from 'svelte';
  import { lightboxImage } from '../lib/stores.js';

  hljs.registerLanguage('javascript', javascript);
  hljs.registerLanguage('js', javascript);
  hljs.registerLanguage('jsx', javascript);
  hljs.registerLanguage('typescript', typescript);
  hljs.registerLanguage('ts', typescript);
  hljs.registerLanguage('tsx', typescript);
  hljs.registerLanguage('python', python);
  hljs.registerLanguage('py', python);
  hljs.registerLanguage('sql', sql);
  hljs.registerLanguage('json', json);
  hljs.registerLanguage('bash', bash);
  hljs.registerLanguage('sh', bash);
  hljs.registerLanguage('shell', bash);
  hljs.registerLanguage('zsh', bash);
  hljs.registerLanguage('xml', xml);
  hljs.registerLanguage('html', xml);
  hljs.registerLanguage('svg', xml);
  hljs.registerLanguage('css', css);
  hljs.registerLanguage('scss', css);
  hljs.registerLanguage('yaml', yaml);
  hljs.registerLanguage('yml', yaml);
  hljs.registerLanguage('go', go);
  hljs.registerLanguage('golang', go);
  hljs.registerLanguage('rust', rust);
  hljs.registerLanguage('rs', rust);
  hljs.registerLanguage('java', java);
  hljs.registerLanguage('cpp', cpp);
  hljs.registerLanguage('c++', cpp);
  hljs.registerLanguage('c', cpp);
  hljs.registerLanguage('csharp', csharp);
  hljs.registerLanguage('cs', csharp);
  hljs.registerLanguage('ruby', ruby);
  hljs.registerLanguage('rb', ruby);
  hljs.registerLanguage('php', php);
  hljs.registerLanguage('markdown', markdownLang);
  hljs.registerLanguage('md', markdownLang);

  // ── Code-artifact metadata ──────────────────────────────
  // Human-readable display name keyed by lowercase fence tag.
  const LANG_DISPLAY = {
    js: 'JavaScript', javascript: 'JavaScript', jsx: 'JSX',
    ts: 'TypeScript', typescript: 'TypeScript', tsx: 'TSX',
    py: 'Python', python: 'Python',
    sql: 'SQL', json: 'JSON',
    bash: 'Bash', sh: 'Shell', shell: 'Shell', zsh: 'Zsh',
    html: 'HTML', xml: 'XML', svg: 'SVG',
    css: 'CSS', scss: 'SCSS',
    yaml: 'YAML', yml: 'YAML',
    go: 'Go', golang: 'Go',
    rust: 'Rust', rs: 'Rust',
    java: 'Java',
    cpp: 'C++', 'c++': 'C++', c: 'C',
    csharp: 'C#', cs: 'C#',
    ruby: 'Ruby', rb: 'Ruby',
    php: 'PHP',
    markdown: 'Markdown', md: 'Markdown',
    plaintext: 'Plain text', text: 'Plain text',
  };
  // GitHub-style language colors for the small dot next to the language name.
  const LANG_COLOR = {
    javascript: '#F7DF1E', js: '#F7DF1E', jsx: '#F7DF1E',
    typescript: '#3178C6', ts: '#3178C6', tsx: '#3178C6',
    python: '#3776AB', py: '#3776AB',
    sql: '#E38C00', json: '#90A4AE',
    bash: '#4EAA25', sh: '#4EAA25', shell: '#4EAA25', zsh: '#4EAA25',
    html: '#E34F26', xml: '#0060AC', svg: '#FFB13B',
    css: '#1572B6', scss: '#CC6699',
    yaml: '#CB171E', yml: '#CB171E',
    go: '#00ADD8', golang: '#00ADD8',
    rust: '#CE422B', rs: '#CE422B',
    java: '#B07219',
    cpp: '#F34B7D', 'c++': '#F34B7D', c: '#555555',
    csharp: '#239120', cs: '#239120',
    ruby: '#CC342D', rb: '#CC342D',
    php: '#777BB4',
    markdown: '#083FA1', md: '#083FA1',
  };
  // File extension for the "Download" action.
  const LANG_EXT = {
    javascript: 'js', js: 'js', jsx: 'jsx',
    typescript: 'ts', ts: 'ts', tsx: 'tsx',
    python: 'py', py: 'py',
    sql: 'sql', json: 'json',
    bash: 'sh', sh: 'sh', shell: 'sh', zsh: 'sh',
    html: 'html', xml: 'xml', svg: 'svg',
    css: 'css', scss: 'scss',
    yaml: 'yml', yml: 'yml',
    go: 'go', golang: 'go',
    rust: 'rs', rs: 'rs',
    java: 'java',
    cpp: 'cpp', 'c++': 'cpp', c: 'c',
    csharp: 'cs', cs: 'cs',
    ruby: 'rb', rb: 'rb',
    php: 'php',
    markdown: 'md', md: 'md',
  };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  let { content = [], role = 'assistant', streaming = false } = $props();

  // Configure marked
  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  // Inline SVG icons used by the artifact header buttons. Declared once
  // here so the renderer below stays readable.
  const ICON_COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const ICON_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>';
  const ICON_WRAP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><path d="M3 12h15a3 3 0 0 1 0 6h-4"/><polyline points="16 16 14 18 16 20"/><line x1="3" y1="18" x2="10" y2="18"/></svg>';
  const ICON_DOWNLOAD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';

  // Override marked's code-fence renderer to produce a full "code artifact"
  // — a card with a header bar (language tag + action buttons) and a body
  // containing syntax-highlighted code. The buttons carry data-attribute
  // actions that an event-delegated handler on the message wrapper picks
  // up (clicks can't bind directly because the HTML lives inside @html).
  marked.use({
    renderer: {
      code(token) {
        const text = token?.text ?? '';
        // Fence tag can include a filename hint: ```js:app.js → lang "js" + name "app.js"
        const langRaw = (token?.lang ?? '').toLowerCase().trim();
        const [lang = '', filename = ''] = langRaw.split(':');

        let highlighted;
        try {
          if (lang && hljs.getLanguage(lang)) {
            highlighted = hljs.highlight(text, { language: lang, ignoreIllegals: true }).value;
          } else if (text.length < 4000) {
            // Auto-detection is acceptable for short snippets but can be
            // slow and unreliable on large blocks — fall back to plain
            // escaped text for those.
            highlighted = hljs.highlightAuto(text).value;
          } else {
            highlighted = escapeHtml(text);
          }
        } catch {
          highlighted = escapeHtml(text);
        }

        const displayLang = LANG_DISPLAY[lang] || (lang ? lang.toUpperCase() : 'Plain text');
        const langColor = LANG_COLOR[lang] || '#8E8E93';
        const labelText = filename || displayLang;

        return (
          `<div class="code-artifact" data-lang="${escapeHtml(lang)}">` +
            `<div class="artifact-header">` +
              `<div class="artifact-lang-tag">` +
                `<span class="artifact-lang-dot" style="background:${langColor}"></span>` +
                `<span class="artifact-lang-name">${escapeHtml(labelText)}</span>` +
              `</div>` +
              `<div class="artifact-actions">` +
                `<button type="button" class="artifact-btn" data-artifact-action="wrap" title="Toggle word wrap" aria-label="Toggle word wrap">${ICON_WRAP}</button>` +
                `<button type="button" class="artifact-btn" data-artifact-action="download" title="Download" aria-label="Download as file">${ICON_DOWNLOAD}</button>` +
                `<button type="button" class="artifact-btn artifact-btn-copy" data-artifact-action="copy" title="Copy to clipboard" aria-label="Copy code to clipboard">` +
                  `<span class="artifact-icon copy-icon">${ICON_COPY}</span>` +
                  `<span class="artifact-icon check-icon">${ICON_CHECK}</span>` +
                  `<span class="artifact-btn-label">Copy</span>` +
                `</button>` +
              `</div>` +
            `</div>` +
            `<pre class="artifact-body"><code class="hljs language-${escapeHtml(lang || 'plaintext')}">${highlighted}</code></pre>` +
          `</div>`
        );
      },
      // Inline `code spans` keep a simple style — no artifact chrome.
      codespan(token) {
        return `<code class="inline-code">${escapeHtml(token?.text ?? '')}</code>`;
      },
    },
  });

  // Svelte action for Chart.js
  // Compact-format large numbers as K/M/B/T so a 17-trillion-USD bar's
  // axis tick reads "17T" instead of "17,000,000,000,000". Decimals are
  // kept only when they add information ("1.5K", not "1.0K").
  function formatLargeNumber(n) {
    if (n == null || Number.isNaN(n) || !Number.isFinite(n)) return '';
    const abs = Math.abs(n);
    const sign = n < 0 ? '-' : '';
    const trim = (s) => s.replace(/\.?0+$/, '');
    if (abs >= 1e12) return sign + trim((abs / 1e12).toFixed(2)) + 'T';
    if (abs >= 1e9)  return sign + trim((abs / 1e9).toFixed(2))  + 'B';
    if (abs >= 1e6)  return sign + trim((abs / 1e6).toFixed(2))  + 'M';
    if (abs >= 1e3)  return sign + trim((abs / 1e3).toFixed(2))  + 'K';
    if (abs >= 1)    return sign + (Number.isInteger(abs) ? abs.toString() : abs.toFixed(2));
    return sign + abs.toFixed(2);
  }

  // Snap a value to a "nice" multiple (1/2/5 × 10^k) — used so axis bounds
  // land on readable round numbers instead of awkward fractions.
  function niceStep(range) {
    if (range <= 0) return 1;
    const rough = range / 5; // target ~5 gridlines between bounds
    const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
    const n = rough / magnitude;
    const mult = n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10;
    return mult * magnitude;
  }

  // If all values cluster tightly far from zero (e.g. mountain heights
  // 8485–8848 m), starting the axis at 0 squashes every bar into the same
  // visual height. Return { min, max } that zooms the axis to the data band
  // with a little padding. Returns null when default beginAtZero is fine.
  function computeSmartYRange(datasets) {
    const values = (datasets || [])
      .flatMap((ds) => ds?.data || [])
      .filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (values.length < 2) return null;

    const min = Math.min(...values);
    const max = Math.max(...values);
    if (min === max) return null;
    // Mixed-sign or already-near-zero data → beginAtZero is the right default.
    if (min <= 0) return null;
    // Only zoom when values share a magnitude band (min is ≥ 60% of max).
    // Otherwise the data naturally spans zero-ish and zero is a fair baseline.
    if (min / max > 0.6 === false) return null;

    const range = max - min;
    const step = niceStep(range);
    const yMin = Math.floor((min - range * 0.25) / step) * step;
    const yMax = Math.ceil((max + range * 0.15) / step) * step;
    return { min: Math.max(0, yMin), max: yMax };
  }

  function initChart(node, params) {
    let chart;
    function create() {
      const config = params?.config || {};
      const chartType = config.chart_type || config.chartType || 'bar';
      const isCircular = chartType === 'pie' || chartType === 'doughnut';
      const smartY = isCircular ? null : computeSmartYRange(config.datasets);
      const datasetCount = (config.datasets || []).length;

      // Show the legend only when it adds information:
      //   - Pie/doughnut: yes — it labels each slice.
      //   - Bar/line with 2+ datasets: yes — distinguishes the series.
      //   - Bar/line with a single dataset: no — it would just repeat the
      //     chart title with a redundant color block.
      const showLegend = isCircular || datasetCount > 1;

      chart = new Chart(node, {
        type: chartType,
        data: {
          labels: config.labels || [],
          datasets: (config.datasets || []).map(ds => ({
            ...ds,
            backgroundColor: ds.backgroundColor || [
              'rgba(16, 163, 127, 0.6)',
              'rgba(14, 165, 233, 0.6)',
              'rgba(139, 92, 246, 0.6)',
              'rgba(245, 158, 11, 0.6)',
              'rgba(239, 68, 68, 0.6)',
            ],
            borderColor: ds.borderColor || 'rgba(16, 163, 127, 1)',
            borderWidth: ds.borderWidth ?? (chartType === 'line' ? 2 : 1),
            // A line chart filled to 'origin' (y=0) looks broken when the
            // axis has been zoomed away from zero — switch the fill anchor
            // to the visible bottom so the area chart still reads correctly.
            ...(chartType === 'line' && smartY && ds.fill ? { fill: 'start' } : {}),
          })),
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          plugins: {
            legend: {
              display: showLegend,
              labels: { color: '#b4b4b4', font: { family: 'Inter' } },
            },
            tooltip: {
              padding: 10,
              titleFont: { weight: '600', size: 13 },
              bodyFont: { size: 12 },
              callbacks: {
                // Pie/doughnut: drop the misleading "Values: " prefix; show
                // the abbreviated value and its percentage of the whole.
                // Bar/line: show the dataset series label (only when it's
                // meaningful — generic placeholders like "Values" are
                // suppressed so the tooltip reads cleanly).
                label: (ctx) => {
                  if (isCircular) {
                    const v = ctx.parsed;
                    const total = (ctx.dataset.data || []).reduce(
                      (a, b) => a + (Number(b) || 0),
                      0,
                    );
                    const pct = total > 0 ? ((v / total) * 100).toFixed(1) : '0';
                    return `  ${formatLargeNumber(v)}  ·  ${pct}%`;
                  }
                  const v = typeof ctx.parsed === 'object'
                    ? (ctx.parsed.y ?? ctx.parsed)
                    : ctx.parsed;
                  const ds = ctx.dataset.label;
                  const GENERIC = new Set(['Values', 'Trend', 'Comparison', 'Distribution']);
                  if (ds && !GENERIC.has(ds)) {
                    return `  ${ds}: ${formatLargeNumber(v)}`;
                  }
                  return `  ${formatLargeNumber(v)}`;
                },
              },
            },
          },
          // Circular charts (pie/doughnut) don't use cartesian axes — omit
          // scales so Chart.js doesn't render or warn about them.
          ...(isCircular
            ? {}
            : {
                scales: {
                  x: { ticks: { color: '#8e8e8e' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                  y: {
                    ticks: {
                      color: '#8e8e8e',
                      // Abbreviate large numbers so the axis reads "17T"
                      // instead of "17,000,000,000,000".
                      callback: (value) => formatLargeNumber(value),
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ...(smartY ? { min: smartY.min, max: smartY.max, beginAtZero: false } : {}),
                  },
                },
              }),
          ...(config.options || {}),
        },
      });
    }
    create();
    return { destroy() { if (chart) chart.destroy(); } };
  }

  // Svelte action for Leaflet maps
  function initMap(node, params) {
    let mapInst;
    async function create() {
      const L = (await import('leaflet')).default;
      const lat = params?.lat || 40.7128;
      const lng = params?.lng || -74.0060;
      const zoom = params?.zoom || 13;
      mapInst = L.map(node).setView([lat, lng], zoom);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
      }).addTo(mapInst);
      if (params?.label) {
        L.marker([lat, lng]).addTo(mapInst).bindPopup(params.label).openPopup();
      } else {
        L.marker([lat, lng]).addTo(mapInst);
      }
    }
    create();
    return { destroy() { if (mapInst) mapInst.remove(); } };
  }

  // marked.parseInline renders bold/italic/code/links/etc. without wrapping
  // the result in a <p>. Use this anywhere we drop a string into the
  // template that might contain markdown — table cells, captions, chart
  // titles, list items in rich blocks. parse() (block-level) is for full
  // multi-paragraph text content only.
  function renderInline(text) {
    return marked.parseInline(text == null ? '' : String(text));
  }

  function renderMarkdown(text, appendCursor = false) {
    const html = marked.parse(text || '');
    if (!appendCursor) return html;
    // Inject a blinking cursor at the end of the last block element so it
    // sits inline right after the last word being streamed.
    const cursor = '<span class="streaming-cursor"></span>';
    const insertBefore = html.lastIndexOf('</p>');
    if (insertBefore >= 0) {
      return html.slice(0, insertBefore) + cursor + html.slice(insertBefore);
    }
    return html + cursor;
  }

  // Index of the last text block — used to anchor the streaming cursor.
  let lastTextIdx = $derived.by(() => {
    for (let i = content.length - 1; i >= 0; i--) {
      if (content[i]?.type === 'text') return i;
    }
    return -1;
  });

  function copyCode(code) {
    navigator.clipboard.writeText(code).catch(() => {});
  }

  // Open an image block in the fullscreen lightbox.
  function openLightbox(block) {
    lightboxImage.set({
      src: block.url || block.src,
      alt: block.alt || '',
      caption: block.caption || '',
    });
  }

  // Inline RAG citations are rendered as <a class="rag-cite-link" data-rag-cite="N">
  // anchor elements inside the @html markdown output, so we intercept clicks
  // via delegation on the wrapper and dispatch viewProof for the matching
  // page proof. Falls through to the default anchor scroll if no proof
  // matches (rare — only when the model references a citation index the
  // backend didn't actually return).
  function handleContentClick(event) {
    // ── Inline RAG citation link → open the matching page proof ──
    const link = event.target.closest('.rag-cite-link');
    if (link) {
      const n = parseInt(link.dataset.ragCite, 10);
      if (!Number.isFinite(n)) return;
      const citationsBlock = content.find((b) => b?.type === 'citations');
      const proof = citationsBlock?.pageProofs?.[n - 1];
      if (proof) {
        event.preventDefault();
        dispatch('viewProof', { proof, index: n - 1 });
      }
      return;
    }

    // ── Code-artifact button → copy / wrap / download ──
    const artifactBtn = event.target.closest('[data-artifact-action]');
    if (artifactBtn) {
      event.preventDefault();
      handleArtifactAction(artifactBtn);
    }
  }

  // Resolve the artifact wrapper and execute the requested action. Each
  // button reads its raw code from the rendered <code> element, which
  // means we never have to worry about escaping the source into a data
  // attribute or keeping a parallel copy of it in memory.
  async function handleArtifactAction(btn) {
    const action = btn.dataset.artifactAction;
    const artifact = btn.closest('.code-artifact');
    if (!artifact) return;
    const codeEl = artifact.querySelector('pre code');
    const text = codeEl?.textContent || '';

    if (action === 'copy') {
      try {
        await navigator.clipboard.writeText(text);
        flashCopyButton(btn, true);
      } catch {
        flashCopyButton(btn, false);
      }
      return;
    }

    if (action === 'wrap') {
      artifact.classList.toggle('wrapped');
      btn.classList.toggle('active');
      return;
    }

    if (action === 'download') {
      const lang = artifact.dataset.lang || '';
      const ext = LANG_EXT[lang] || (lang || 'txt');
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `snippet.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Revoke after a tick so the browser has time to read it.
      setTimeout(() => URL.revokeObjectURL(url), 200);
    }
  }

  function flashCopyButton(btn, success) {
    const label = btn.querySelector('.artifact-btn-label');
    const original = label?.textContent;
    btn.classList.add(success ? 'copied' : 'copy-failed');
    if (label) label.textContent = success ? 'Copied!' : 'Failed';
    setTimeout(() => {
      btn.classList.remove('copied', 'copy-failed');
      if (label && original != null) label.textContent = original;
    }, 1500);
  }

  // Star rating state
  let ratings = $state({});
  function setRating(blockIdx, stars) {
    ratings[blockIdx] = stars;
  }

  // Thumbs state
  let thumbs = $state({});
  function setThumb(blockIdx, val) {
    thumbs[blockIdx] = thumbs[blockIdx] === val ? null : val;
  }

  // Carousel state
  let carouselPositions = $state({});
  function scrollCarousel(blockIdx, dir) {
    const el = document.querySelector(`[data-carousel="${blockIdx}"]`);
    if (el) {
      el.scrollBy({ left: dir * 280, behavior: 'smooth' });
    }
  }

  // Form state
  let formData = $state({});

  // Quick reply handler
  import { createEventDispatcher } from 'svelte';
  const dispatch = createEventDispatcher();
  function handleQuickReply(text) {
    dispatch('quickReply', { message: text });
  }

  // ── Claim verification rendering ────────────────────────────
  // Maps the backend ClaimVerifier verdicts to a label + colour + soft
  // background. Mirrors the verdict taxonomy from claim_verifier.py.
  const VERDICT_META = {
    supported:    { label: 'Supported',    color: 'var(--success)',    bg: 'rgba(16, 185, 129, 0.14)' },
    partial:      { label: 'Partial',      color: 'var(--warning)',    bg: 'rgba(245, 158, 11, 0.14)' },
    contradicted: { label: 'Contradicted', color: 'var(--error)',      bg: 'rgba(239, 68, 68, 0.14)' },
    unsupported:  { label: 'Unsupported',  color: 'var(--text-muted)', bg: 'rgba(142, 142, 142, 0.16)' },
    inferred:     { label: 'Inferred',     color: 'var(--info)',       bg: 'rgba(59, 130, 246, 0.14)' },
  };
  function verdictMeta(v) {
    return VERDICT_META[v] || VERDICT_META.unsupported;
  }
  function scoreColor(s) {
    if (s >= 75) return 'var(--success)';
    if (s >= 50) return 'var(--warning)';
    return 'var(--error)';
  }
  // Non-zero verdict tallies, in severity order, for the summary pills.
  function verdictBreakdown(v) {
    return [
      ['supported', v.supported_count],
      ['partial', v.partial_count],
      ['contradicted', v.contradicted_count],
      ['unsupported', v.unsupported_count],
      ['inferred', v.inferred_count],
    ]
      .filter(([, c]) => (c || 0) > 0)
      .map(([k, c]) => ({ count: c, ...VERDICT_META[k] }));
  }

  // ── LLM Jury block ────────────────────────────────────────
  // A message has at most one jury block, so a single expand flag + a
  // per-juror open map are enough state for this renderer instance.
  let juryExpanded = $state(false);
  let openJurors = $state({});
  function toggleJuror(i) {
    openJurors = { ...openJurors, [i]: !openJurors[i] };
  }
  function juryTierColor(tier) {
    if (tier === 'premium') return 'var(--tier-premium)';
    if (tier === 'moderate') return 'var(--tier-moderate)';
    if (tier === 'cheap') return 'var(--tier-cheap)';
    return 'var(--text-muted)';
  }
  function juryCost(v) {
    if (v === null || v === undefined) return null;
    if (v === 0) return 'Free';
    if (v < 0.0001) return '<$0.0001';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    return `$${v.toFixed(2)}`;
  }
  function juryLatency(ms) {
    if (ms === null || ms === undefined) return null;
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }
</script>

<div class="message-content" class:user-content={role === 'user'} onclick={handleContentClick} role="presentation">
  {#if streaming && lastTextIdx === -1}
    <!-- Streaming has begun but the first revealed block isn't text yet —
         show a standalone cursor so the bubble isn't empty. -->
    <span class="streaming-cursor"></span>
  {/if}
  {#each content as block, idx}
    {#if block.type === 'text'}
      <div class="block-text">
        {@html renderMarkdown(block.text, streaming && idx === lastTextIdx)}
      </div>

    {:else if block.type === 'attachments'}
      <div class="block-attachments">
        {#each (block.files || []) as f}
          <span class="attached-file-chip" title={f.name}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
              <path d="M14 2v6h6"/>
            </svg>
            <span class="attached-file-name">{f.name}</span>
          </span>
        {/each}
      </div>

    {:else if block.type === 'web_search_indicator'}
      <div class="block-web-search">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>
        </svg>
        <span>Web search</span>
      </div>

    {:else if block.type === 'image'}
      <div class="block-image rich-block">
        <img
          src={block.url || block.src}
          alt={block.alt || 'Image'}
          loading="lazy"
          role="button"
          tabindex="0"
          title="Click to enlarge"
          onclick={() => openLightbox(block)}
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              openLightbox(block);
            }
          }}
        />
        {#if block.caption}
          <div class="image-caption">{@html renderInline(block.caption)}</div>
        {/if}
      </div>

    {:else if block.type === 'video'}
      <div class="block-video rich-block">
        <video controls preload="metadata" src={block.url || block.src}>
          <track kind="captions" />
        </video>
      </div>

    {:else if block.type === 'chart'}
      <!-- Chart.js rendered via action -->
      {@const chartId = `chart-${idx}-${Date.now()}`}
      <div class="block-chart rich-block">
        {#if block.title}
          <div class="chart-title">{@html renderInline(block.title)}</div>
        {/if}
        <canvas id={chartId} use:initChart={{ config: block, canvasId: chartId }}></canvas>
      </div>

    {:else if block.type === 'table'}
      <div class="block-table rich-block">
        <table>
          <thead>
            <tr>
              {#each (block.headers || []) as header}
                <th>{@html renderInline(header)}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each (block.rows || []) as row}
              <tr>
                {#each row as cell}
                  <td>{@html renderInline(cell)}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

    {:else if block.type === 'quick_replies'}
      <div class="block-quick-replies">
        {#each (block.options || []) as option}
          <button class="chip" onclick={() => handleQuickReply(typeof option === 'string' ? option : option.text)}>
            {@html renderInline(typeof option === 'string' ? option : option.text)}
          </button>
        {/each}
      </div>

    {:else if block.type === 'carousel'}
      <div class="block-carousel rich-block">
        <div class="carousel-track" data-carousel={idx}>
          {#each (block.cards || []) as card}
            <div class="carousel-card">
              {#if card.image}
                <img src={card.image} alt={card.title || ''} />
              {/if}
              <div class="carousel-card-body">
                <div class="carousel-card-title">{@html renderInline(card.title || '')}</div>
                {#if card.description}
                  <div class="carousel-card-desc">{@html renderInline(card.description)}</div>
                {/if}
                {#if card.action}
                  <button class="carousel-card-action">{@html renderInline(card.action.label || 'View')}</button>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </div>

    {:else if block.type === 'cta_button'}
      <div class="block-cta rich-block">
        <button class="cta-btn" onclick={() => block.url && window.open(block.url, '_blank')}>
          {#if block.icon}<span>{block.icon}</span>{/if}
          {@html renderInline(block.label || 'Click Here')}
        </button>
      </div>

    {:else if block.type === 'feedback'}
      <div class="block-feedback rich-block">
        <span class="feedback-label">{@html renderInline(block.label || 'Rate this response')}</span>
        {#if block.style === 'thumbs'}
          <button class="thumb" class:selected={thumbs[idx] === 'up'} onclick={() => setThumb(idx, 'up')}>👍</button>
          <button class="thumb" class:selected={thumbs[idx] === 'down'} onclick={() => setThumb(idx, 'down')}>👎</button>
        {:else}
          <div class="feedback-stars">
            {#each [1,2,3,4,5] as star}
              <span 
                class="feedback-star" 
                class:active={star <= (ratings[idx] || 0)}
                onclick={() => setRating(idx, star)}
                role="button"
                tabindex="0"
              >⭐</span>
            {/each}
          </div>
        {/if}
      </div>

    {:else if block.type === 'html_element'}
      <div class="block-html rich-block">
        <iframe 
          srcdoc={block.html || ''} 
          sandbox="allow-scripts allow-same-origin" 
          style="height: {block.height || 300}px"
          title="Custom web element"
        ></iframe>
      </div>

    {:else if block.type === 'audio'}
      <div class="block-audio rich-block">
        <button class="audio-play-btn">▶</button>
        <div class="audio-waveform">
          {#each Array(30) as _, i}
            <div class="audio-bar" style="height: {8 + Math.random() * 20}px"></div>
          {/each}
        </div>
        <span class="audio-time">{block.duration || '0:00'}</span>
      </div>

    {:else if block.type === 'map'}
      <div class="block-map rich-block" use:initMap={{ lat: block.lat, lng: block.lng, zoom: block.zoom, label: block.label }}>
      </div>

    {:else if block.type === 'file'}
      <div class="block-file rich-block">
        <div class="file-icon">📄</div>
        <div class="file-info">
          <div class="file-name">{@html renderInline(block.name || 'Document')}</div>
          <div class="file-size">{block.size || ''}</div>
        </div>
        <button class="file-download-btn" onclick={() => block.url && window.open(block.url)}>Download</button>
      </div>

    {:else if block.type === 'vcard'}
      <div class="block-vcard rich-block">
        <div class="vcard-avatar">{(block.name || 'U')[0]}</div>
        <div class="vcard-info">
          <div class="vcard-name">{@html renderInline(block.name || 'Contact')}</div>
          {#if block.phone}<div class="vcard-detail">📱 {block.phone}</div>{/if}
          {#if block.email}<div class="vcard-detail">✉️ {block.email}</div>{/if}
        </div>
        <button class="vcard-action">Add Contact</button>
      </div>

    {:else if block.type === 'calendar'}
      {@const d = block.date ? new Date(block.date) : new Date()}
      <div class="block-calendar rich-block">
        <div class="cal-date-box">
          <div class="cal-month">{d.toLocaleString('en', { month: 'short' })}</div>
          <div class="cal-day">{d.getDate()}</div>
        </div>
        <div class="cal-info">
          <div class="cal-title">{@html renderInline(block.title || 'Event')}</div>
          <div class="cal-time">{block.time || d.toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' })}</div>
        </div>
        <button class="cal-add-btn">Add to Calendar</button>
      </div>

    {:else if block.type === 'form'}
      <div class="block-form rich-block">
        {#if block.title}
          <div class="form-title">{@html renderInline(block.title)}</div>
        {/if}
        {#each (block.fields || []) as field}
          <div class="form-group">
            <label>{field.label || field.name}</label>
            {#if field.type === 'select'}
              <select bind:value={formData[field.name]}>
                {#each (field.options || []) as opt}
                  <option value={opt}>{opt}</option>
                {/each}
              </select>
            {:else if field.type === 'textarea'}
              <textarea rows="3" placeholder={field.placeholder || ''} bind:value={formData[field.name]}></textarea>
            {:else if field.type === 'checkbox'}
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={formData[field.name]} />
                {field.checkLabel || ''}
              </label>
            {:else}
              <input type={field.type || 'text'} placeholder={field.placeholder || ''} bind:value={formData[field.name]} />
            {/if}
          </div>
        {/each}
        <button class="form-submit">Submit</button>
      </div>

    {:else if block.type === 'payment'}
      <div class="block-payment rich-block">
        <div class="payment-amount">{block.amount || '$0.00'}</div>
        <button class="payment-btn">
          <span class="apple-icon"></span>
          {block.label || 'Pay with Apple Pay'}
        </button>
        <div class="payment-label">Secure payment mockup — demo only</div>
      </div>

    {:else if block.type === 'progress'}
      <div class="block-progress rich-block">
        <div class="progress-label">
          <span>{@html renderInline(block.label || 'Processing')}</span>
          <span>{block.value || 0}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width: {block.value || 0}%"></div>
        </div>
      </div>

    {:else if block.type === 'web_sources'}
      <div class="web-sources-block">
        <div class="web-sources-header">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20"/>
          </svg>
          <span>Sources ({(block.sources || []).length})</span>
        </div>
        <div class="web-sources-list">
          {#each (block.sources || []) as src}
            <a
              class="web-source-item"
              href={src.url}
              target="_blank"
              rel="noopener noreferrer"
              title={src.snippet || src.title}
            >
              <span class="web-source-num">{src.n}</span>
              <span class="web-source-info">
                <span class="web-source-title">{@html renderInline(src.title)}</span>
                <span class="web-source-host">{(() => {
                  try { return new URL(src.url).hostname.replace(/^www\./, ''); }
                  catch { return src.url; }
                })()}</span>
              </span>
            </a>
          {/each}
        </div>
      </div>

    {:else if block.type === 'citations'}
      <div class="citations-block">
        <div class="citations-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <span>Sources ({block.citations?.length || 0})</span>
        </div>
        {#each (block.pageProofs || []) as proof, pIdx}
          <div
            id="rag-cite-{pIdx + 1}"
            class="block-citation"
            onclick={() => dispatch('viewProof', { proof, index: pIdx })}
          >
            <div class="citation-badge">
              <span>📄</span>
              <span>Source {pIdx + 1}</span>
            </div>
            <div class="citation-title">{@html renderInline(proof.title || 'Untitled')}</div>
            <div class="citation-snippet">
              {@html renderInline(proof.highlights?.[0]?.text || 'Click to view highlighted page proof')}
            </div>
            <div class="citation-page">Page {proof.page_number || '—'}</div>
          </div>
        {/each}
      </div>

    {:else if block.type === 'verification'}
      {@const v = block.report || {}}
      {@const skipped = v.method === 'skipped_no_citations'}
      {@const score = Math.max(0, Math.min(100, Math.round(Number(v.verifiability_score || 0))))}
      <div class="verification-block">
        <div class="verification-head">
          <div
            class="ver-ring"
            style="background: conic-gradient({skipped ? 'var(--border-default)' : scoreColor(score)} {score}%, var(--bg-elevated) 0)"
          >
            <div class="ver-ring-inner">
              <span class="ver-ring-score">{skipped ? '—' : score}</span>
              <span class="ver-ring-cap">score</span>
            </div>
          </div>
          <div class="ver-summary">
            <div class="ver-summary-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                <path d="M9 12l2 2 4-4"/>
              </svg>
              <span>{skipped ? 'Answer not grounded in sources' : 'Claim verification'}</span>
            </div>
            <div class="ver-summary-text">
              {v.summary ||
                (skipped
                  ? 'This answer was not backed by retrieved sources, so there is nothing to verify it against. Attach a document or open a grounded collection for per-claim checks.'
                  : '')}
            </div>
            {#if !skipped && verdictBreakdown(v).length}
              <div class="ver-pills">
                {#each verdictBreakdown(v) as p}
                  <span class="ver-pill" style="color: {p.color}; background: {p.bg}">{p.count} {p.label.toLowerCase()}</span>
                {/each}
              </div>
            {/if}
            <div class="ver-meta">
              {v.total_claims || 0} claim{(v.total_claims || 0) === 1 ? '' : 's'}
              {#if v.latency_ms} · {Number(v.latency_ms).toFixed(0)}ms{/if}
              {#if v.method} · {v.method}{/if}
            </div>
          </div>
        </div>

        {#if (v.claims || []).length}
          <div class="ver-claims">
            {#each v.claims as claim}
              {@const m = verdictMeta(claim.verdict)}
              <div class="ver-claim" style="border-left-color: {m.color}">
                <div class="ver-claim-row">
                  <span class="ver-claim-text">{claim.text}</span>
                  <span class="ver-claim-verdict" style="color: {m.color}; background: {m.bg}">{m.label}</span>
                </div>
                <div class="ver-claim-meta">
                  {claim.best_citation_index != null && claim.best_citation_index >= 0
                    ? `Citation ${claim.best_citation_index + 1}`
                    : 'No citation'}
                  {#if claim.confidence != null} · conf {Number(claim.confidence).toFixed(2)}{/if}
                  {#if claim.numeric_match === false} · <span class="ver-numeric-bad">numeric mismatch</span>{/if}
                </div>
                {#if claim.reasoning}
                  <div class="ver-claim-reason">{claim.reasoning}</div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </div>

    {:else if block.type === 'jury'}
      {@const jurors = block.jurors || []}
      <div class="jury-block">
        <button class="jury-bar" onclick={() => (juryExpanded = !juryExpanded)} aria-expanded={juryExpanded}>
          <span class="jury-bar-emblem">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3v18M3 7h18M7 7l-3 7a3 3 0 0 0 6 0l-3-7zM17 7l-3 7a3 3 0 0 0 6 0l-3-7z"/>
            </svg>
          </span>
          <span class="jury-bar-text">
            <span class="jury-bar-title">Synthesized by LLM Jury</span>
            <span class="jury-bar-sub">
              Combined {block.okCount ?? jurors.length} of {block.memberCount ?? jurors.length} models{#if block.synthesizer?.name} · via {block.synthesizer.name}{/if}{#if block.synthesizer?.fallback} · synthesis unavailable, showing top answer{/if}
            </span>
          </span>
          <svg class="jury-bar-caret" class:open={juryExpanded} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
        </button>

        {#if juryExpanded}
          <div class="jury-jurors">
            {#each jurors as juror, ji}
              <div class="jury-juror" class:has-error={!!juror.error}>
                <button class="jury-juror-head" onclick={() => toggleJuror(ji)} aria-expanded={!!openJurors[ji]} disabled={!juror.text}>
                  <span class="jury-juror-dot" style="background: {juryTierColor(juror.tier)}"></span>
                  <span class="jury-juror-name">{juror.name}</span>
                  <span class="jury-juror-meta">
                    {#if juror.error}
                      <span class="jury-juror-err">{juror.error}</span>
                    {:else}
                      {#if juryLatency(juror.latencyMs)}<span>{juryLatency(juror.latencyMs)}</span>{/if}
                      {#if juryCost(juror.cost)}<span class="jury-juror-cost">{juryCost(juror.cost)}</span>{/if}
                    {/if}
                  </span>
                  {#if juror.text}
                    <svg class="jury-juror-caret" class:open={openJurors[ji]} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
                  {/if}
                </button>
                {#if openJurors[ji] && juror.text}
                  <div class="jury-juror-body">
                    {@html renderMarkdown(juror.text, false)}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {/each}
</div>


<style>
  .message-content {
    font-size: var(--text-base);
    line-height: var(--leading-relaxed);
    color: var(--text-primary);
  }

  .user-content {
    color: var(--text-primary);
  }

  /* ── Attachment / search indicators (on user bubbles) ── */
  .block-attachments {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .attached-file-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 3px var(--space-2);
    border-radius: var(--radius-full);
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid var(--border-subtle);
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }
  .attached-file-name {
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .block-web-search {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 3px var(--space-2);
    border-radius: var(--radius-full);
    background: rgba(16, 163, 127, 0.12);
    border: 1px solid rgba(16, 163, 127, 0.4);
    color: var(--accent-primary);
    font-size: var(--text-xs);
    margin-top: var(--space-2);
    width: fit-content;
  }

  /* ── Streaming cursor ───────────── */
  .message-content :global(.streaming-cursor) {
    display: inline-block;
    width: 8px;
    height: 1.05em;
    margin-left: 2px;
    vertical-align: text-bottom;
    background: var(--accent-primary);
    border-radius: 1px;
    animation: streamingBlink 1s steps(2, start) infinite;
  }
  @keyframes streamingBlink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }

  /* ── Text block markdown ────────── */
  .block-text {
    overflow-wrap: break-word;
    word-break: break-word;
  }

  .block-text :global(p) {
    margin-bottom: 0.75em;
  }
  .block-text :global(p:last-child) {
    margin-bottom: 0;
  }

  .block-text :global(h1),
  .block-text :global(h2),
  .block-text :global(h3) {
    margin-top: 1.2em;
    margin-bottom: 0.5em;
    font-weight: var(--weight-semibold);
  }
  .block-text :global(h1) { font-size: var(--text-xl); }
  .block-text :global(h2) { font-size: var(--text-lg); }
  .block-text :global(h3) { font-size: var(--text-md); }

  .block-text :global(ul),
  .block-text :global(ol) {
    padding-left: 1.5em;
    margin-bottom: 0.75em;
  }
  .block-text :global(li) {
    margin-bottom: 0.3em;
  }

  /* ── Inline code (single backticks) ────────────────── */
  .block-text :global(code.inline-code),
  .block-text :global(:not(pre) > code) {
    background: rgba(255, 255, 255, 0.07);
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 0.88em;
    font-family: var(--font-mono);
    color: #e6c07b;
  }

  /* ── Code artifact (fenced code blocks) ─────────────
     Replaces the bare <pre><code> render with a card that has a header
     bar (language tag + actions) and a syntax-highlighted body. */
  .block-text :global(.code-artifact) {
    margin: 0.85em 0;
    background: #0d1117;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: 0 1px 0 rgba(255, 255, 255, 0.02);
  }
  .block-text :global(.artifact-header) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 8px 6px 12px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.02) 100%);
    border-bottom: 1px solid var(--border-subtle);
    flex-wrap: wrap;
    gap: 4px;
  }
  .block-text :global(.artifact-lang-tag) {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-secondary);
    letter-spacing: 0.02em;
  }
  .block-text :global(.artifact-lang-dot) {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.08);
  }
  .block-text :global(.artifact-lang-name) {
    font-weight: 600;
  }
  .block-text :global(.artifact-actions) {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .block-text :global(.artifact-btn) {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: var(--radius-sm);
    color: var(--text-tertiary);
    font-size: 11px;
    background: transparent;
    border: none;
    cursor: pointer;
    transition: all var(--duration-fast);
    font-family: var(--font-sans);
  }
  .block-text :global(.artifact-btn:hover) {
    background: rgba(255, 255, 255, 0.07);
    color: var(--text-primary);
  }
  .block-text :global(.artifact-btn svg) {
    width: 13px;
    height: 13px;
    flex-shrink: 0;
    display: block;
  }
  .block-text :global(.artifact-btn.active) {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.1);
  }
  /* Copy button: icon swap on success — show check, hide copy icon. */
  .block-text :global(.artifact-btn-copy .check-icon) { display: none; }
  .block-text :global(.artifact-btn-copy.copied .copy-icon) { display: none; }
  .block-text :global(.artifact-btn-copy.copied .check-icon) { display: inline-flex; }
  .block-text :global(.artifact-btn-copy.copied) {
    color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.1);
  }
  .block-text :global(.artifact-btn-copy.copy-failed) {
    color: var(--error, #ef4444);
    background: rgba(239, 68, 68, 0.1);
  }

  /* Body: the actual <pre><code> with syntax highlight. Reset every
     existing pre/code style so this is the single source of truth. */
  .block-text :global(.artifact-body) {
    margin: 0;
    padding: 14px 16px;
    background: transparent;
    border: none;
    border-radius: 0;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
    color: #abb2bf;
  }
  .block-text :global(.artifact-body code) {
    background: none;
    padding: 0;
    border-radius: 0;
    color: inherit;
    font-size: inherit;
    display: block;
  }
  /* Word-wrap toggle: when on, long lines wrap at the body width. */
  .block-text :global(.code-artifact.wrapped .artifact-body) {
    overflow-x: visible;
  }
  .block-text :global(.code-artifact.wrapped .artifact-body code) {
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* ── highlight.js — atom-one-dark palette (single-color theme).
     Tuned to read well on the #0d1117 artifact body. */
  .block-text :global(.hljs)                   { background: transparent; color: #abb2bf; }
  .block-text :global(.hljs-keyword),
  .block-text :global(.hljs-selector-tag),
  .block-text :global(.hljs-literal),
  .block-text :global(.hljs-section),
  .block-text :global(.hljs-link)              { color: #c678dd; }
  .block-text :global(.hljs-string),
  .block-text :global(.hljs-attr),
  .block-text :global(.hljs-symbol),
  .block-text :global(.hljs-bullet),
  .block-text :global(.hljs-addition)          { color: #98c379; }
  .block-text :global(.hljs-comment),
  .block-text :global(.hljs-quote)             { color: #5c6370; font-style: italic; }
  .block-text :global(.hljs-number),
  .block-text :global(.hljs-meta)              { color: #d19a66; }
  .block-text :global(.hljs-title),
  .block-text :global(.hljs-name),
  .block-text :global(.hljs-class .hljs-title),
  .block-text :global(.hljs-built_in),
  .block-text :global(.hljs-title.function_)   { color: #61afef; }
  .block-text :global(.hljs-variable),
  .block-text :global(.hljs-template-variable),
  .block-text :global(.hljs-deletion)          { color: #e06c75; }
  .block-text :global(.hljs-type),
  .block-text :global(.hljs-params)            { color: #56b6c2; }
  .block-text :global(.hljs-tag),
  .block-text :global(.hljs-selector-id),
  .block-text :global(.hljs-selector-class)    { color: #e06c75; }
  .block-text :global(.hljs-regexp),
  .block-text :global(.hljs-strong),
  .block-text :global(.hljs-attribute),
  .block-text :global(.hljs-formula)           { color: #e6c07b; }
  .block-text :global(.hljs-emphasis)          { font-style: italic; }
  .block-text :global(.hljs-strong)            { font-weight: 700; }

  @media (max-width: 600px) {
    .block-text :global(.artifact-btn-label) { display: none; }
    .block-text :global(.artifact-body) { padding: 12px; font-size: 12px; }
  }

  .block-text :global(blockquote) {
    border-left: 3px solid var(--accent-primary);
    padding-left: var(--space-4);
    margin: 0.75em 0;
    color: var(--text-secondary);
  }

  .block-text :global(a) {
    color: var(--accent-primary);
    text-decoration: underline;
    text-decoration-color: rgba(16, 163, 127, 0.3);
    text-underline-offset: 2px;
  }
  .block-text :global(a:hover) {
    text-decoration-color: var(--accent-primary);
  }

  .block-text :global(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 0.75em 0;
    font-size: var(--text-sm);
  }
  .block-text :global(th),
  .block-text :global(td) {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border-subtle);
    text-align: left;
  }
  .block-text :global(th) {
    background: rgba(255, 255, 255, 0.04);
    font-weight: var(--weight-semibold);
  }

  .block-text :global(strong) {
    font-weight: var(--weight-semibold);
  }

  .block-text :global(hr) {
    border: none;
    border-top: 1px solid var(--border-subtle);
    margin: 1em 0;
  }

  /* ── Inline citations [1] [2] … — shared by web search + RAG ── */
  .message-content :global(.cite-sup),
  .message-content :global(.rag-cite) {
    font-size: 0.7em;
    line-height: 1;
    vertical-align: super;
    margin: 0 1px;
  }
  .message-content :global(.cite-link),
  .message-content :global(.rag-cite-link) {
    display: inline-block;
    min-width: 16px;
    padding: 0 4px;
    border-radius: var(--radius-sm);
    background: rgba(16, 163, 127, 0.15);
    color: var(--accent-primary);
    text-decoration: none !important;
    font-weight: var(--weight-semibold);
    transition: background var(--duration-fast);
    cursor: pointer;
  }
  .message-content :global(.cite-link:hover),
  .message-content :global(.rag-cite-link:hover) {
    background: rgba(16, 163, 127, 0.3);
    color: var(--accent-primary);
  }

  /* ── Web sources block ──────────── */
  .web-sources-block {
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border-subtle);
  }
  .web-sources-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-secondary);
    margin-bottom: var(--space-3);
  }
  .web-sources-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: var(--space-2);
  }
  .web-source-item {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--surface-glass);
    text-decoration: none !important;
    color: var(--text-secondary);
    transition: all var(--duration-fast);
    min-width: 0;
  }
  .web-source-item:hover {
    border-color: var(--accent-primary);
    background: rgba(16, 163, 127, 0.06);
    color: var(--text-primary);
  }
  .web-source-num {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: rgba(16, 163, 127, 0.15);
    color: var(--accent-primary);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: var(--weight-bold);
    font-family: var(--font-mono);
  }
  .web-source-info {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 2px;
  }
  .web-source-title {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }
  .web-source-host {
    font-size: 11px;
    color: var(--text-muted);
    font-family: var(--font-mono);
  }

  /* ── Citations block ────────────── */
  .citations-block {
    margin-top: var(--space-4);
    border-top: 1px solid var(--border-subtle);
    padding-top: var(--space-3);
  }

  .citations-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-secondary);
    margin-bottom: var(--space-3);
  }

  /* ── Claim verification block ───────────────── */
  .verification-block {
    margin-top: var(--space-4);
    border-top: 1px solid var(--border-subtle);
    padding-top: var(--space-3);
  }
  .verification-head {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
  }
  .ver-ring {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .ver-ring-inner {
    width: 46px;
    height: 46px;
    border-radius: 50%;
    background: var(--surface-chat);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .ver-ring-score {
    font-size: var(--text-md);
    font-weight: var(--weight-bold);
    font-family: var(--font-mono);
    color: var(--text-primary);
    line-height: 1;
  }
  .ver-ring-cap {
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
  }
  .ver-summary { flex: 1; min-width: 0; }
  .ver-summary-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-secondary);
  }
  .ver-summary-title svg { color: var(--accent-primary); flex-shrink: 0; }
  .ver-summary-text {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    line-height: var(--leading-normal);
    margin-top: 3px;
  }
  .ver-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: var(--space-2);
  }
  .ver-pill {
    font-size: 10px;
    font-weight: var(--weight-semibold);
    padding: 2px 8px;
    border-radius: var(--radius-full);
  }
  .ver-meta {
    font-size: 10px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    margin-top: var(--space-2);
  }
  .ver-claims {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-3);
  }
  .ver-claim {
    background: var(--surface-card);
    border: 1px solid var(--border-subtle);
    border-left: 3px solid var(--text-muted);
    border-radius: var(--radius-sm);
    padding: var(--space-2) var(--space-3);
  }
  .ver-claim-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .ver-claim-text {
    font-size: var(--text-sm);
    color: var(--text-primary);
    line-height: var(--leading-normal);
    flex: 1;
  }
  .ver-claim-verdict {
    font-size: 10px;
    font-weight: var(--weight-semibold);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 2px 8px;
    border-radius: var(--radius-full);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .ver-claim-meta {
    font-size: 10px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    margin-top: 5px;
  }
  .ver-numeric-bad { color: var(--error); font-weight: var(--weight-semibold); }
  .ver-claim-reason {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    font-style: italic;
    margin-top: 4px;
    line-height: var(--leading-normal);
  }

  /* ── LLM Jury block ─────────────────────────── */
  .jury-block {
    margin-top: var(--space-3);
    border: 1px solid rgba(139, 92, 246, 0.25);
    border-radius: var(--radius-lg);
    overflow: hidden;
    background: rgba(139, 92, 246, 0.05);
  }
  .jury-bar {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    text-align: left;
    transition: background var(--duration-fast);
  }
  .jury-bar:hover { background: rgba(139, 92, 246, 0.08); }
  .jury-bar-emblem {
    width: 30px;
    height: 30px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #8b5cf6, #6366f1);
    color: #fff;
    flex-shrink: 0;
  }
  .jury-bar-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .jury-bar-title {
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
  }
  .jury-bar-sub { font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.4; }
  .jury-bar-caret { color: var(--text-muted); flex-shrink: 0; transition: transform var(--duration-fast); }
  .jury-bar-caret.open { transform: rotate(180deg); }

  .jury-jurors {
    border-top: 1px solid rgba(139, 92, 246, 0.18);
    padding: var(--space-2);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .jury-juror {
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
    overflow: hidden;
  }
  .jury-juror.has-error { opacity: 0.7; }
  .jury-juror-head {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    text-align: left;
    transition: background var(--duration-fast);
  }
  .jury-juror-head:hover:not(:disabled) { background: var(--bg-hover); }
  .jury-juror-head:disabled { cursor: default; }
  .jury-juror-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .jury-juror-name {
    flex: 1;
    min-width: 0;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .jury-juror-meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    font-family: var(--font-mono);
    color: var(--text-muted);
    flex-shrink: 0;
  }
  .jury-juror-cost { color: var(--text-tertiary); }
  .jury-juror-err { color: var(--error); font-family: var(--font-sans); }
  .jury-juror-caret { color: var(--text-muted); flex-shrink: 0; transition: transform var(--duration-fast); }
  .jury-juror-caret.open { transform: rotate(180deg); }
  .jury-juror-body {
    padding: var(--space-2) var(--space-3) var(--space-3);
    border-top: 1px solid var(--border-subtle);
    font-size: var(--text-sm);
    color: var(--text-secondary);
    line-height: var(--leading-relaxed);
    max-height: 360px;
    overflow-y: auto;
  }
</style>
