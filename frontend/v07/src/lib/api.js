/**
 * V07 API Client — All backend communication
 */

async function request(url, options = {}) {
  const { method = 'GET', body, headers = {}, signal } = options;
  const config = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    signal,
  };
  if (body) config.body = JSON.stringify(body);

  const response = await fetch(url, config);
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

/**
 * Send a chat message and get a rich response.
 */
export async function sendMessage(message, options = {}) {
  const {
    modelId = 'smart_routing',
    temperature = 0.7,
    sessionId = 'v07-demo',
    collectionId = null,
    verifyClaims = false,
    signal = null,
  } = options;

  const isSmartRouting = modelId === 'smart_routing';

  const payload = {
    message,
    temperature,
    demo_mode: true,
    simulation_session_id: sessionId,
  };

  if (!isSmartRouting && modelId) {
    payload.simulation_profile_id = modelId;
  }

  if (collectionId) {
    payload.grounded_collection_id = collectionId;
    payload.grounded_tenant_id = 'default';
  }

  if (verifyClaims) {
    payload.verify_claims = true;
    payload.verification_use_embeddings = true;
  }

  const data = await request('/chat', { method: 'POST', body: payload, signal });

  // Debug: log raw response in dev
  if (import.meta.env.DEV) {
    console.log('[V07] Raw API response:', data);
    console.log('[V07] Simulation:', data.simulation);
  }

  return transformResponse(data, collectionId);
}

// ═══════════════════════════════════════════════════════════
// Smart Data → Chart Detection
// ═══════════════════════════════════════════════════════════

// ── Chart palette + helpers ────────────────────────────────
const CHART_PALETTE = [
  'rgba(16, 163, 127, 0.7)',
  'rgba(14, 165, 233, 0.7)',
  'rgba(139, 92, 246, 0.7)',
  'rgba(245, 158, 11, 0.7)',
  'rgba(239, 68, 68, 0.7)',
  'rgba(236, 72, 153, 0.7)',
  'rgba(34, 197, 94, 0.7)',
  'rgba(168, 85, 247, 0.7)',
];
const CHART_BORDERS = CHART_PALETTE.map((c) => c.replace('0.7', '1'));

// Cell looks numeric after stripping currency, percent, thousands separators
// and an optional magnitude word/suffix (billion, M, etc.).
function isNumericish(v) {
  if (v == null) return false;
  if (typeof v === 'number') return Number.isFinite(v);
  if (typeof v !== 'string') return false;
  const stripped = v
    .replace(/[\$,%]/g, '')
    .replace(/\s*(billion|million|thousand|lakh|crore|trillion)\s*$/i, '')
    .replace(/\s*(M|B|K|T)\s*$/, '')
    .trim();
  return /^-?\d+(\.\d+)?$/.test(stripped);
}

function parseNumericish(v) {
  if (typeof v === 'number') return v;
  if (typeof v !== 'string') return 0;
  const n = parseFloat(v.replace(/[\$,]/g, ''));
  if (!Number.isFinite(n)) return 0;
  const lower = v.toLowerCase();
  if (/\btrillion\b|\bt\s*$/.test(lower)) return n * 1e12;
  if (/\bbillion\b|\bb\s*$/.test(lower)) return n * 1e9;
  if (/\bcrore\b/.test(lower)) return n * 1e7;
  if (/\bmillion\b|\bm\s*$/.test(lower)) return n * 1e6;
  if (/\blakh\b/.test(lower)) return n * 1e5;
  if (/\bthousand\b|\bk\s*$/.test(lower)) return n * 1e3;
  return n;
}

// Years, ISO dates, month names, or quarter labels → time-series x-axis.
function looksLikeTimeLabels(labels) {
  if (!labels.length) return false;
  const trimmed = labels.map((l) => String(l).trim());
  if (trimmed.every((l) => /^(19|20)\d{2}$/.test(l))) return true;
  if (trimmed.every((l) => /^\d{4}-\d{1,2}(-\d{1,2})?$/.test(l))) return true;
  if (trimmed.every((l) => /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(l))) return true;
  if (trimmed.every((l) => /^q[1-4][\s\-/]?(19|20)?\d{0,4}$/i.test(l))) return true;
  return false;
}

function findTitle(text) {
  const m = text.match(/(?:^|\n)#+\s*(.+?)(?:\n|$)/);
  return m ? m[1].trim() : '';
}

// ── Build a chart from a parsed markdown table ─────────────
// Multi-numeric-column tables become grouped bar / multi-line charts.
function buildChartFromTable(table, fullText) {
  if (!table.rows?.length || !table.headers?.length || table.headers.length < 2) return null;

  // A "numeric column" has numeric-ish cells in every data row.
  const numericCols = [];
  for (let c = 1; c < table.headers.length; c++) {
    if (table.rows.every((row) => isNumericish(row[c]))) numericCols.push(c);
  }
  if (!numericCols.length) return null;

  let labels = table.rows.map((row) => (row[0] || '').toString().trim());
  if (labels.some((l) => !l)) return null;

  const isTime = looksLikeTimeLabels(labels);
  const piePref = PIE_PREF_RE.test(fullText);

  // Pre-compute values + "looks like %" for the single-column case so we
  // can decide pie-with-Others below and keep the rest of the function
  // working off the (possibly augmented) labels/data arrays.
  let singleColValues = null;
  let singleColIsPct = false;
  let augmentedOthers = false;
  if (numericCols.length === 1) {
    singleColValues = table.rows.map((row) => parseNumericish(row[numericCols[0]]));
    singleColIsPct = table.rows.every((row) => /%/.test(row[numericCols[0]] || ''));
  }

  // Type selection
  let chartType = 'bar';
  if (isTime) chartType = 'line';
  else if (numericCols.length === 1) {
    const values = singleColValues;
    const sum = values.reduce((a, b) => a + b, 0);
    if ((singleColIsPct && sum > 85 && sum < 115) || (piePref && sum > 85 && sum < 115)) {
      chartType = 'pie';
    } else if (piePref && singleColIsPct && sum >= 25 && sum < 85 && values.length >= 3) {
      // Partial-of-whole pie (e.g. top-N states with % contribution).
      chartType = 'pie';
      labels = [...labels, 'Others'];
      singleColValues = [...values, +(100 - sum).toFixed(2)];
      augmentedOthers = true;
    }
  }

  const datasets = numericCols.map((c, i) => {
    // For the augmented single-column pie case, use the values that already
    // include the synthetic "Others" tail. For everything else fall back to
    // re-parsing the column from the original table rows.
    const data =
      augmentedOthers && i === 0
        ? singleColValues
        : table.rows.map((row) => parseNumericish(row[c]));
    if (chartType === 'pie') {
      return {
        label: table.headers[c] || 'Values',
        data,
        backgroundColor: data.map((_, j) => CHART_PALETTE[j % CHART_PALETTE.length]),
      };
    }
    if (chartType === 'line') {
      return {
        label: table.headers[c] || `Series ${i + 1}`,
        data,
        backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length].replace('0.7', '0.15'),
        borderColor: CHART_BORDERS[i % CHART_BORDERS.length],
        borderWidth: 2,
        fill: numericCols.length === 1,
        tension: 0.3,
      };
    }
    // bar
    return {
      label: table.headers[c] || `Series ${i + 1}`,
      data,
      backgroundColor:
        numericCols.length === 1
          ? data.map((_, j) => CHART_PALETTE[j % CHART_PALETTE.length])
          : CHART_PALETTE[i % CHART_PALETTE.length],
    };
  });

  return {
    type: 'chart',
    chart_type: chartType,
    title: table.headers[0] || (chartType === 'pie' ? 'Distribution' : chartType === 'line' ? 'Trend' : 'Comparison'),
    labels,
    datasets,
  };
}

// ── Extract list-style data points from prose ──────────────
// Catches two shapes:
//
// A) Line-anchored "Label: value [unit]"
//      * Males: 51.5%
//      - India: 1.4 billion
//      1. China — 1.4B
//      Revenue: $200M
//      2020 → 100
//
// B) Inline parenthesized "Label (value unit)"
//      "…Maharashtra (24.11 lakh crores), Tamil Nadu (15.71 lakh crores)…"
//    Constraint: label must start uppercase (proper-noun signal) and a
//    magnitude unit MUST follow the number. This combo rejects false
//    positives like "she (4 years old)" or "(Figure 2 below)".
// Strip common English filler words (articles, prepositions, copulas) from
// the start of a captured label. Without this, prose like
//   "...the largest oil producers are the United States (20%)..."
// gets caught as "are the United States" → leaking into chart legends.
// We loop because there are often multiple stop-words to peel:
//   "are the United States" → "the United States" → "United States".
const LEADING_STOPWORDS_RE =
  /^(are|is|was|were|be|been|being|the|a|an|of|in|on|at|by|for|to|from|with|and|or|that|which|who|whom|whose|over|out|up|down|as|into|onto)\s+/i;
function cleanLabel(label) {
  let prev = '';
  let cur = (label || '').trim();
  while (cur && cur !== prev && LEADING_STOPWORDS_RE.test(cur)) {
    prev = cur;
    cur = cur.replace(LEADING_STOPWORDS_RE, '').trim();
  }
  return cur;
}

function extractDataPoints(cleaned) {
  const seen = new Map();

  const tryAdd = (label, valueStr, unitRaw) => {
    label = cleanLabel(label);
    let value = parseFloat((valueStr || '').replace(/,/g, ''));
    if (!label || !Number.isFinite(value)) return;
    const unit = (unitRaw || '').toLowerCase();
    const isPct = unit === '%';
    if (!isPct) {
      if (unit === 'trillion' || unit === 't') value *= 1e12;
      else if (unit === 'billion' || unit === 'b') value *= 1e9;
      else if (unit === 'crore') value *= 1e7;
      else if (unit === 'million' || unit === 'm') value *= 1e6;
      else if (unit === 'lakh') value *= 1e5;
      else if (unit === 'thousand' || unit === 'k') value *= 1e3;
    }
    const key = label.toLowerCase();
    if (!seen.has(key)) seen.set(key, { label, value, isPct });
  };

  // Pattern A — line-anchored "Label: value [unit]"
  const linePattern =
    /(?:^|\n)[ \t]*(?:[*\-•][ \t]+|\d+\.[ \t]+)?([A-Za-z0-9][A-Za-z0-9 ./&'-]{0,40}?)[ \t]*[:\-–—=→][ \t]*\$?([\d,]+\.?\d*)[ \t]*(billion|million|thousand|lakh|crore|trillion|%|M|B|K|T)?\b/gim;
  for (const m of cleaned.matchAll(linePattern)) {
    tryAdd(m[1], m[2], m[3]);
  }

  // Pattern B — inline "ProperNoun (value unit)" — captures cases where the
  // model writes a comma-separated sentence instead of a list.
  const inlinePattern =
    /\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\s*\(\s*\$?([\d,]+(?:\.\d+)?)\s*(billion|million|thousand|lakh|crore|trillion|%)/gi;
  for (const m of cleaned.matchAll(inlinePattern)) {
    tryAdd(m[1], m[2], m[3]);
  }

  return [...seen.values()];
}

// Wording that implies "this is a slice of a complete whole" — used to
// promote bar→pie when the data looks like a top-N ranking of percentages
// (e.g. "Maharashtra contributes 13.46% of India's GDP"). Includes pie
// chart explicit ask plus contribution / share / breakdown vocabulary.
const PIE_PREF_RE =
  /\bpie\s*chart\b|\bshare\b|\bdistribution\b|\bbreakdown\b|\bsplit\b|\bcontribut(?:ion|or|ing|es?)\b|\baccount(?:s|ing|ed)?\s+for\b|\bproportion\b|\bcomposition\b/i;

function buildChartFromPoints(points, fullText) {
  if (points.length < 2) return null;
  let labels = points.map((p) => p.label);
  let values = points.map((p) => p.value);

  const isTime = looksLikeTimeLabels(labels);
  const allPct = points.every((p) => p.isPct);
  const sum = values.reduce((a, b) => a + b, 0);
  const piePref = PIE_PREF_RE.test(fullText);

  let chartType = 'bar';
  if (isTime) chartType = 'line';
  else if (allPct && sum > 85 && sum < 115) chartType = 'pie';
  else if (piePref && sum > 85 && sum < 115) chartType = 'pie';
  // Partial-of-whole: top-N ranking of percentages that don't sum to 100.
  // Adding an "Others" slice for the remainder makes the pie honest — each
  // slice still shows its real contribution, instead of being normalised
  // to fill the circle and inflating Maharashtra from 13% to 28%.
  else if (piePref && allPct && sum >= 25 && sum < 85 && points.length >= 3) {
    chartType = 'pie';
    labels = [...labels, 'Others'];
    values = [...values, +(100 - sum).toFixed(2)];
  }

  const title = findTitle(fullText);
  const dataset =
    chartType === 'line'
      ? {
          label: title || 'Trend',
          data: values,
          backgroundColor: CHART_PALETTE[0].replace('0.7', '0.15'),
          borderColor: CHART_BORDERS[0],
          borderWidth: 2,
          fill: true,
          tension: 0.3,
        }
      : {
          label: title || 'Values',
          data: values,
          backgroundColor: values.map((_, i) => CHART_PALETTE[i % CHART_PALETTE.length]),
        };

  return {
    type: 'chart',
    chart_type: chartType,
    title:
      title ||
      (chartType === 'pie' ? 'Distribution' : chartType === 'line' ? 'Trend' : 'Comparison'),
    labels,
    datasets: [dataset],
  };
}

/**
 * Auto-detect chartable data in a response and return one or more chart blocks.
 *
 * Strategy:
 *   1. Markdown tables → most structured signal; supports multi-series.
 *   2. List-style prose ("Label: value [unit]") → single-series fallback.
 *
 * Chart-type selection:
 *   - Year/month/quarter labels                  → line
 *   - Percentages summing ~100% (or "pie/share
 *     /distribution/breakdown" in the text)      → pie
 *   - Everything else                            → bar
 */
function detectChartData(text, tables = []) {
  const charts = [];

  // 1) Tables first — strongest signal.
  for (const table of tables) {
    const chart = buildChartFromTable(table, text);
    if (chart) charts.push(chart);
  }

  // 2) Strip code blocks / inline code / markdown emphasis, then scan prose.
  //    Emphasis stripping (e.g. **Hindus** → Hindus) is critical: LLMs love
  //    bolding labels in bullet lists, which would otherwise break the regex.
  //    Skip prose pass entirely if tables already produced chart(s).
  if (!charts.length) {
    const cleaned = text
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`[^`\n]+`/g, '')
      .replace(/\*\*([^*\n]+)\*\*/g, '$1')
      .replace(/__([^_\n]+)__/g, '$1')
      .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '$1')
      .replace(/(?<!_)_([^_\n]+)_(?!_)/g, '$1');
    const points = extractDataPoints(cleaned);
    const chart = buildChartFromPoints(points, text);
    if (chart) charts.push(chart);
  }

  return charts;
}

// ═══════════════════════════════════════════════════════════
// Markdown Table Extraction
// ═══════════════════════════════════════════════════════════

function extractMarkdownTables(text) {
  const blocks = [];
  const lines = text.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i].trim();
    if (line.startsWith('|') && line.endsWith('|') && line.includes('|')) {
      const sepLine = (lines[i + 1] || '').trim();
      if (sepLine.match(/^\|[\s\-:]+\|/)) {
        const headers = line.split('|').map(h => h.trim()).filter(h => h.length > 0);
        const rows = [];
        let j = i + 2;
        while (j < lines.length) {
          const rowLine = lines[j].trim();
          if (!rowLine.startsWith('|')) break;
          const cells = rowLine.split('|').map(c => c.trim()).filter(c => c.length > 0);
          if (cells.length > 0) rows.push(cells);
          j++;
        }
        if (headers.length > 0 && rows.length > 0) {
          blocks.push({ type: 'table', headers, rows, startLine: i, endLine: j - 1 });
        }
        i = j;
        continue;
      }
    }
    i++;
  }
  return blocks;
}

function removeTableLines(text, tables) {
  if (!tables.length) return text;
  const lines = text.split('\n');
  const skip = new Set();
  for (const t of tables) {
    for (let l = t.startLine; l <= t.endLine; l++) skip.add(l);
  }
  let result = [];
  let inSkip = false;
  for (let i = 0; i < lines.length; i++) {
    if (skip.has(i)) {
      if (!inSkip) { result.push('__TABLE_BLOCK__'); inSkip = true; }
    } else {
      inSkip = false;
      result.push(lines[i]);
    }
  }
  return result.join('\n');
}

// ═══════════════════════════════════════════════════════════
// RAG citation cleanup
// ═══════════════════════════════════════════════════════════
//
// The backend inlines verbose citation markers in the response, e.g.:
//   "...contributor tools (Citation 1, Source: VINCI.pdf, Page: 1, Section: ...)"
// All of that metadata is also returned structurally in `page_proofs` /
// `citations`, which we render as clickable cards in a Sources block at
// the bottom of the message. Keeping the inline blobs makes the prose
// unreadable — so collapse them to a clean superscript "[N]" that links
// to the matching page proof card.
//
// Also handles a few common variants the model produces:
//   (Citation N, ...) / [Citation N, ...] / (Source N) / [Source N]
function transformRagCitations(text) {
  if (!text) return text;
  return text.replace(
    /\s*[\(\[](?:Citation|Source)\s*(\d+)[^\)\]\n]*[\)\]]/gi,
    (_match, n) =>
      `<sup class="rag-cite"><a class="rag-cite-link" href="#rag-cite-${n}" data-rag-cite="${n}">${n}</a></sup>`,
  );
}

// ═══════════════════════════════════════════════════════════
// Response Transformer
// ═══════════════════════════════════════════════════════════

// Coerce a possibly-missing backend numeric into a real number or null, so the
// routing-insight UI can cleanly distinguish "0" from "not reported".
function numOrNull(v) {
  if (v === null || v === undefined) return null;
  const n = typeof v === 'number' ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

function transformResponse(data, collectionId = null) {
  const content = [];
  const commercialProfile = data.simulation?.commercial_profile || null;

  if (data.response) {
    // Strip the verbose "(Citation N, Source: …, Page: …)" markers down to
    // clean inline [N] superscripts. We do this BEFORE table/chart extraction
    // so the regex patterns there don't see citation noise.
    if (data.grounded || data.citations?.length || data.page_proofs?.length) {
      data.response = transformRagCitations(data.response);
    }
    const tables = extractMarkdownTables(data.response);
    const charts = detectChartData(data.response, tables);

    // Split text around tables
    if (tables.length > 0) {
      const cleanedText = removeTableLines(data.response, tables);
      const textParts = cleanedText.split('__TABLE_BLOCK__');
      for (let i = 0; i < textParts.length; i++) {
        const part = textParts[i].trim();
        if (part) content.push({ type: 'text', text: part });
        if (i < tables.length) {
          content.push({ type: 'table', headers: tables[i].headers, rows: tables[i].rows });
        }
      }
    } else {
      content.push({ type: 'text', text: data.response });
    }

    // Append auto-detected charts
    for (const chart of charts) {
      content.push(chart);
    }
  }

  // Grounded citations
  if (data.grounded && (data.citations?.length || data.page_proofs?.length)) {
    const collId = collectionId || data.grounded_collection_id || null;
    content.push({
      type: 'citations',
      citations: data.citations || [],
      // Stamp the collection/tenant onto each proof so PageViewer can build the
      // original-page-image URL (the page-image endpoint is keyed by collection).
      pageProofs: (data.page_proofs || []).map((p) => ({
        ...p,
        _collection_id: collId,
        _tenant_id: 'default',
      })),
      evidenceGroups: data.evidence_groups || [],
    });
  }

  // Claim verification — per-claim verdicts against the cited evidence,
  // surfaced as a trust panel when verify_claims was requested.
  if (data.verification) {
    content.push({ type: 'verification', report: data.verification });
  }

  // Model info — headline the model the SMART ROUTER picked (its routing
  // decision), NOT the simulated commercial brand or the free backing/fallback
  // model that actually executed. Showcasing the router's decision is the whole
  // point of the project, so `model_used` (= decision.selected_model.display_name,
  // e.g. "GPT-OSS 120B (Groq)", "Claude Opus 4.5") wins.
  const modelName = data.model_used || commercialProfile?.display_name || 'AI Assistant';
  const modelTier = data.routing_decision?.complexity || commercialProfile?.tier || 'moderate';
  const modelProvider = commercialProfile?.provider || 'ai';

  return {
    id: 'msg_' + Date.now(),
    role: 'assistant',
    content,
    model: {
      name: modelName,
      tier: modelTier,
      provider: modelProvider,
      // Backing/fallback model intentionally hidden — the badge shows only the
      // router's pick. To restore the on-hover "routed to / fell back to" reveal,
      // set these from `data.simulation?.actual_execution` again.
      actualModel: null,
      requestedModel: null,
      fellBack: false,
      fallbackReason: null,
    },
    // Full routing transparency — the platform's headline capability. The
    // backend returns *why* this model was picked, the query analysis, a
    // confidence/quality read, and whether a mid-flight escalation fired; we
    // surface all of it (RoutingInsight.svelte) instead of discarding it. This
    // is the routing DECISION, not the free backing model — the display rule
    // (show the router's pick, never the fallback) is preserved.
    routing: {
      mode: commercialProfile ? 'smart' : 'direct',
      reasoning: data.routing_decision?.reasoning || '',
      confidence: data.routing_decision?.confidence_level || '',
      complexity: data.routing_decision?.complexity || '',
      intent: data.routing_decision?.intent || '',
      domain: data.routing_decision?.domain || '',
      modality: data.routing_decision?.modality || '',
      fastPath: !!data.routing_decision?.fast_path,
      memoryHit: !!data.routing_decision?.memory_hit,
      uncertaintyScore: numOrNull(data.routing_decision?.uncertainty_score),
      // Pricing tier of the selected model (premium/moderate/cheap), distinct
      // from the complexity band above. Drives the tier color on the chip.
      tier: commercialProfile?.tier || '',
      // Execution outcome — the deterministic quality gate result and whether
      // Layer 8 climbed the escalation ladder before answering.
      qualityScore: numOrNull(data.escalation?.quality_score),
      qualityPassed: data.escalation?.quality_passed ?? null,
      escalated: !!data.escalation?.escalated,
      escalationCount: data.escalation?.escalation_count || 0,
      escalationAvailable: !!data.escalation?.escalation_available,
      escalationLevels: data.escalation?.escalation_levels_possible || 0,
      latencyMs: numOrNull(data.performance?.total_latency_ms),
      isFree: data.cost?.is_free ?? null,
      fallbackModels: Array.isArray(data.routing_decision?.fallback_models)
        ? data.routing_decision.fallback_models
        : [],
    },
    cost: {
      chargedUsd: data.simulation?.wallet?.charged_usd || data.cost?.total_cost_usd || 0,
      balanceUsd: data.simulation?.wallet?.balance_after_usd ?? null,
    },
    raw: data,
  };
}

// ═══════════════════════════════════════════════════════════
// Public API functions
// ═══════════════════════════════════════════════════════════

// Memoised — the commercial model list is static for a session and is read by
// both the model selector and the per-message "try another model" menu.
let _modelsCache = null;
let _modelsInflight = null;
export async function getModels() {
  if (_modelsCache) return _modelsCache;
  if (_modelsInflight) return _modelsInflight;
  _modelsInflight = (async () => {
    const data = await request('/chat/demo/commercial-models');
    _modelsCache = data.models || [];
    return _modelsCache;
  })();
  try {
    return await _modelsInflight;
  } finally {
    _modelsInflight = null;
  }
}

export async function getWalletBalance(sessionId = 'v07-demo') {
  const data = await request(`/chat/demo/wallet/balance?session_id=${sessionId}`);
  return data.balance_usd ?? 25.0;
}

export async function resetWallet(sessionId = 'v07-demo') {
  const data = await request(`/chat/demo/wallet/reset?session_id=${sessionId}`, { method: 'POST' });
  return data.balance_after_reset_usd ?? 25.0;
}

export async function ragQuery(collectionId, query, options = {}) {
  const { sessionId = 'v07-demo', verifyClaims = false, signal = null } = options;

  const payload = {
    message: query,
    demo_mode: true,
    simulation_session_id: sessionId,
    grounded_collection_id: collectionId,
    grounded_tenant_id: 'default',
    grounded_top_k: 6,
  };

  if (verifyClaims) {
    payload.verify_claims = true;
    payload.verification_use_embeddings = true;
  }

  const data = await request('/chat', { method: 'POST', body: payload, signal });

  const content = [];
  if (data.response) {
    const cleaned = transformRagCitations(data.response);
    content.push({ type: 'text', text: cleaned });
  }
  if (data.page_proofs?.length) {
    content.push({
      type: 'citations',
      citations: data.citations || [],
      pageProofs: data.page_proofs.map((p) => ({
        ...p,
        _collection_id: collectionId,
        _tenant_id: 'default',
      })),
      evidenceGroups: data.evidence_groups || [],
    });
  }
  if (data.verification) {
    content.push({ type: 'verification', report: data.verification });
  }

  return {
    id: 'msg_' + Date.now(),
    role: 'assistant',
    content,
    model: { name: 'RAG Engine', tier: 'grounded', provider: 'rag' },
    routing: { mode: 'rag', reasoning: 'Grounded retrieval from collection', confidence: 'grounded' },
    cost: {
      chargedUsd: data.simulation?.wallet?.charged_usd || 0,
      balanceUsd: data.simulation?.wallet?.balance_after_usd ?? null,
    },
    raw: data,
  };
}

export async function getCollections(tenantId = 'default') {
  const data = await request(`/grounded-documents/collections?tenant_id=${tenantId}`);
  return data.collections || [];
}

// ═══════════════════════════════════════════════════════════
// Smart suggestions (follow-ups + refine actions, one LLM call)
// ═══════════════════════════════════════════════════════════
//
// One LLM round-trip generates BOTH:
//   1. follow_ups   — 4 contextual next-question suggestions
//   2. refine_actions — 3-5 ways to edit/refine the response
//
// Forcing simulation_profile_id='gpt-5.4-flagship' routes the call through
// the premium-tier backing pool, which prefers `groq-llama-3.3-70b-free`
// (Llama 3.3 70B on Groq's fast inference). This gives us top-quality
// reasoning + JSON adherence, fast latency (~200-400ms), and effectively
// zero real cost since the underlying Groq tier is free.

// Module-level caches — dedupe concurrent requests (both FollowUpSuggestions
// and QuickRefine call this for the same message at the same time) and
// memo across re-renders.
const _smartSugCache = new Map();    // msgId → { followUps, refineActions, cost }
const _smartSugInflight = new Map(); // msgId → Promise<...>

/**
 * Parse the LLM's combined JSON output. Survives the usual deviations:
 * ```json fences```, leading "Here is the JSON:" prose, trailing
 * commentary, single-quoted keys, trailing commas.
 */
function parseSmartSuggestions(raw) {
  if (!raw) return { followUps: [], refineActions: [] };
  const unfenced = raw
    .replace(/```(?:json|JSON)?\s*([\s\S]*?)\s*```/g, '$1')
    .trim();

  const tryParse = (s) => {
    try {
      const v = JSON.parse(s);
      if (v && typeof v === 'object') return v;
    } catch {}
    return null;
  };

  // Direct parse first.
  let obj = tryParse(unfenced);

  // If that fails, find the first {...} block in the prose and parse it.
  if (!obj) {
    const match = unfenced.match(/\{[\s\S]*\}/);
    if (match) obj = tryParse(match[0]);
  }

  if (!obj) return { followUps: [], refineActions: [] };

  const followUps = Array.isArray(obj.follow_ups)
    ? obj.follow_ups
        .slice(0, 4)
        .map((s) => String(s || '').trim().replace(/^["']|["']$/g, ''))
        .filter((s) => s.length > 4 && s.length < 220)
    : [];

  const refineActions = Array.isArray(obj.refine_actions)
    ? obj.refine_actions
        .filter((a) => a && typeof a === 'object' && a.label && a.prompt)
        .slice(0, 5)
        .map((a) => ({
          label: String(a.label).trim().slice(0, 32),
          prompt: String(a.prompt).trim(),
        }))
        .filter((a) => a.label && a.prompt.length > 5)
    : [];

  return { followUps, refineActions };
}

/**
 * Build the meta-prompt sent to the LLM. The examples are critical — they
 * teach the model what "good" looks like (use-case-driven, specific, varied)
 * vs what "bad" looks like (generic templates, vague pronouns).
 */
function buildSmartSuggestionsPrompt(userText, responseText) {
  const trimmedUser = (userText || '').slice(0, 600);
  const trimmedResp = (responseText || '').slice(0, 3500);

  return (
    `You're a smart assistant helping a real person continue exploring a topic. Given the user's question and the AI's response below, generate TWO things in a JSON object:\n\n` +
    `1. "follow_ups": exactly 4 follow-up questions the user would naturally want to ask NEXT — actionable, specific, personal.\n` +
    `2. "refine_actions": 3-5 ways to REFINE this specific response — tailored to its actual content, not generic "shorter/longer".\n\n` +
    `──── FOLLOW-UP RULES ────\n` +
    `• Reference SPECIFIC named things from the response (places, terms, numbers, proper nouns)\n` +
    `• Each should be USE-CASE-DRIVEN — what would a real person want to DO with this knowledge?\n` +
    `• Cover 4 different angles: deep-dive on a detail / lateral comparison / practical action / unexpected angle\n` +
    `• Under 70 chars, naturally phrased, ending with "?"\n` +
    `• AVOID generic templates like "Tell me more about X", "Explain Y more", "What is Z?"\n\n` +
    `GOOD examples (for "Best places to visit during winter in India"):\n` +
    `✅ "Plan me a 10-day Kashmir + Himachal winter combo"\n` +
    `✅ "Best week within December for Manali snow?"\n` +
    `✅ "Cheapest winter destinations under ₹30k?"\n` +
    `✅ "Where can I avoid Christmas-week crowds?"\n\n` +
    `BAD examples (too passive / generic / vague):\n` +
    `❌ "Tell me more about Manali"\n` +
    `❌ "What's ice skating like in Shimla?" (passive — what would they do with that?)\n` +
    `❌ "How's Kashmir different from Himachal?" (generic comparison, no payoff)\n\n` +
    `──── REFINE RULES ────\n` +
    `• Each refinement must be TAILORED to this response's content (not "make it shorter")\n` +
    `• "label" = 2-4 word chip label\n` +
    `• "prompt" = full instruction the AI will receive to apply the refinement\n` +
    `• If response is too short or trivial to refine meaningfully, return an empty array []\n\n` +
    `GOOD examples (travel list):\n` +
    `✅ {"label": "Group by region", "prompt": "Reorganize the list by Indian region (North, South, East, West, Northeast)"}\n` +
    `✅ {"label": "Add ₹/day budget", "prompt": "Add approximate per-day budget in INR for each destination"}\n` +
    `✅ {"label": "Adventure only", "prompt": "Filter to only adventure/sports-oriented destinations like skiing or trekking"}\n` +
    `✅ {"label": "Best week", "prompt": "For each destination, specify the best week within winter (e.g. mid-Dec, early-Feb) to visit"}\n\n` +
    `BAD examples (too generic, ignores content):\n` +
    `❌ {"label": "Shorter", "prompt": "Make it shorter"}\n` +
    `❌ {"label": "Examples", "prompt": "Add examples"}\n\n` +
    `──── INPUT ────\n` +
    `User originally asked: "${trimmedUser}"\n\n` +
    `AI replied: "${trimmedResp}"\n\n` +
    `──── OUTPUT ────\n` +
    `Respond with ONLY this JSON object — no preamble, no markdown fences, no commentary:\n` +
    `{\n` +
    `  "follow_ups": ["q1?", "q2?", "q3?", "q4?"],\n` +
    `  "refine_actions": [\n` +
    `    {"label": "...", "prompt": "..."},\n` +
    `    {"label": "...", "prompt": "..."},\n` +
    `    {"label": "...", "prompt": "..."}\n` +
    `  ]\n` +
    `}`
  );
}

/**
 * Generate both follow-ups and refine actions for a given message. Deduped
 * per-message-id — if FollowUpSuggestions and QuickRefine both ask at the
 * same time, the second call awaits the first's in-flight promise.
 *
 * Returns: { followUps: string[], refineActions: {label,prompt}[], cost: {...} }
 */
export async function generateSmartSuggestions({
  messageId,
  userText,
  responseText,
  sessionId = 'v07-demo',
  signal = null,
} = {}) {
  if (!messageId) throw new Error('generateSmartSuggestions: messageId required');

  if (_smartSugCache.has(messageId)) return _smartSugCache.get(messageId);
  if (_smartSugInflight.has(messageId)) return _smartSugInflight.get(messageId);

  const promise = (async () => {
    const prompt = buildSmartSuggestionsPrompt(userText, responseText);

    const data = await request('/chat', {
      method: 'POST',
      body: {
        message: prompt,
        temperature: 0.7,
        demo_mode: true,
        simulation_session_id: sessionId,
        // Force the premium-tier profile so the actual call routes through
        // Groq Llama 3.3 70B (the first option in the premium backing pool).
        // Llama 70B on Groq gives us top reasoning quality + ~200ms latency.
        simulation_profile_id: 'gpt-5.4-flagship',
      },
      signal,
    });

    const parsed = parseSmartSuggestions(data.response || '');
    const result = {
      followUps: parsed.followUps,
      refineActions: parsed.refineActions,
      cost: {
        chargedUsd: data.simulation?.wallet?.charged_usd || 0,
        balanceUsd: data.simulation?.wallet?.balance_after_usd ?? null,
      },
    };
    _smartSugCache.set(messageId, result);
    return result;
  })();

  _smartSugInflight.set(messageId, promise);
  try {
    return await promise;
  } finally {
    _smartSugInflight.delete(messageId);
  }
}

// Back-compat shim for any existing callers expecting the old shape.
export async function generateFollowUps(userText, responseText, options = {}) {
  const id = options.messageId || `temp-${Date.now()}`;
  const result = await generateSmartSuggestions({
    messageId: id,
    userText,
    responseText,
    sessionId: options.sessionId,
    signal: options.signal,
  });
  return { suggestions: result.followUps, cost: result.cost };
}

// ═══════════════════════════════════════════════════════════
// Client-side file preprocessing
// ═══════════════════════════════════════════════════════════
//
// The backend's grounded-documents upload route handles PDF natively but
// falls back to "decode as UTF-8 text" for everything else. That breaks
// for .docx (which is really a ZIP archive of XML) — you get errors like:
//   "Parser detail: 'utf-8' codec can't decode byte 0x91"
//
// Fix: extract the text from .docx files in the browser (via mammoth.js),
// wrap it as a .txt blob, and upload that instead. The backend then sees
// plain text and indexes it cleanly.

/**
 * Normalise a file so the backend can index it. Returns either the original
 * File or a new File with the same data extracted to plain text.
 *
 * Supported conversions:
 *   .docx   → text extraction (mammoth.js, dynamic-imported on demand)
 * Rejected with a clear error:
 *   .doc    (legacy binary Word — mammoth doesn't handle it)
 *   .xls / .xlsx / .ppt / .pptx (binary Office formats)
 * Pass-through (backend handles directly):
 *   .pdf, .txt, .md, .csv, .json, .html, .htm
 */
export async function processFileForUpload(file) {
  const name = (file.name || '').toLowerCase();

  if (name.endsWith('.docx')) {
    // Dynamic import keeps mammoth out of the main bundle for users who
    // never upload a docx.
    const mammoth = await import('mammoth');
    const arrayBuffer = await file.arrayBuffer();
    const result = await mammoth.extractRawText({ arrayBuffer });
    const text = (result?.value || '').trim();
    if (!text) {
      throw new Error(
        `"${file.name}" appears to be empty or contains no extractable text.`,
      );
    }
    const blob = new Blob([text], { type: 'text/plain' });
    const newName = file.name.replace(/\.docx$/i, '.txt');
    return new File([blob], newName, { type: 'text/plain' });
  }

  if (name.endsWith('.doc')) {
    throw new Error(
      `Legacy .doc format isn't supported. Open "${file.name}" in Word and "Save As" .docx, or export to PDF.`,
    );
  }
  if (/\.(xlsx?|pptx?)$/.test(name)) {
    throw new Error(
      `${file.name.split('.').pop().toUpperCase()} files aren't supported yet. Export to PDF or copy the content into a .txt / .md file.`,
    );
  }

  // PDF, plain text, markdown, CSV, JSON, HTML — backend handles directly.
  return file;
}

// ═══════════════════════════════════════════════════════════
// File upload — per-message ephemeral RAG collection
// ═══════════════════════════════════════════════════════════

/**
 * Upload one or more files into a fresh grounded collection so the next chat
 * call can ground its answer on them. Returns the collection id to pass as
 * `collectionId` on the subsequent sendMessage call.
 */
export async function uploadFilesToCollection(files, options = {}) {
  const {
    tenantId = 'default',
    domain = 'general',
    sessionId = 'v07-demo',
    signal = null,
  } = options;

  if (!files || !files.length) throw new Error('No files to upload');

  const collectionId = `attach-${sessionId}-${Date.now().toString(36)}`;
  const formData = new FormData();
  formData.append('collection_id', collectionId);
  formData.append('tenant_id', tenantId);
  formData.append('domain', domain);
  formData.append('generation_mode', 'gateway');
  formData.append('top_k', '6');
  for (const file of files) {
    formData.append('files', file, file.name);
  }

  const resp = await fetch('/grounded-documents/collections/upload', {
    method: 'POST',
    body: formData,
    signal,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `Upload failed (${resp.status})`);
  }
  const summary = await resp.json();
  return { collectionId, summary };
}

// ═══════════════════════════════════════════════════════════
// Web search — pluggable backend, normalised result shape
// ═══════════════════════════════════════════════════════════
//
// All providers return: [{ title, url, snippet }, ...]
//
// Selection precedence (first one configured wins):
//   1. VITE_SEARCH_PROVIDER env var (explicit override)
//   2. tavily   — if VITE_TAVILY_API_KEY is set (best results, 1000/mo free)
//   3. searxng  — if VITE_SEARXNG_URL is set (unlimited, self-host preferred)
//   4. duckduckgo (default, zero setup, but limited to instant answers)
//
// See .env.example for setup instructions.

function pickSearchProvider() {
  const explicit = import.meta.env.VITE_SEARCH_PROVIDER;
  if (explicit) return explicit;
  if (import.meta.env.VITE_TAVILY_API_KEY) return 'tavily';
  if (import.meta.env.VITE_SEARXNG_URL) return 'searxng';
  return 'duckduckgo';
}

// ── Tavily ─────────────────────────────────────────────────
// AI-optimised search. Returns clean snippets, not raw HTML.
// Requires VITE_TAVILY_API_KEY in .env. Routed through Vite proxy
// (/api/tavily) so the key isn't logged in browser network history.
//
// Critical settings for time-sensitive queries:
//   - search_depth: 'advanced' → richer per-page content (1500-2000 chars
//     vs basic's ~300), so things like sports tables and live data make it
//     into the snippet instead of being clipped.
//   - include_answer: 'advanced' → Tavily's own LLM reads the top pages
//     and synthesizes a current-state answer. This is the bit that turns
//     "the search results don't mention the current standings" into
//     "the current standings are X, Y, Z".
//   - topic: 'news' + time_range: 'week' for queries asking about right-now
//     state (current, latest, today, this week, …).

// Heuristic — does this query care about freshness? If so, scope to news.
function isTimeSensitive(query) {
  return /\b(current|currently|now|today|tonight|tomorrow|yesterday|latest|recent|recently|live|breaking|this\s+(week|month|year|season)|right\s+now|at\s+the\s+moment|so\s+far|update|standings|score|results)\b/i.test(
    query,
  );
}

async function searchTavily(query, { limit = 7, signal = null } = {}) {
  const timeSensitive = isTimeSensitive(query);

  const body = {
    api_key: import.meta.env.VITE_TAVILY_API_KEY,
    query,
    max_results: limit,
    search_depth: 'advanced',
    include_answer: 'advanced',
    // News topic gets recency-weighted results from news-class sources.
    // Scope to the last week for time-sensitive queries so we don't get
    // a 6-month-old article ranked at the top by raw relevance score.
    ...(timeSensitive ? { topic: 'news', time_range: 'week' } : { topic: 'general' }),
  };

  const resp = await fetch('/api/tavily/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const err = await resp.text().catch(() => '');
    throw new Error(`Tavily search failed (${resp.status}) ${err}`);
  }
  const data = await resp.json();

  const results = (data.results || []).map((r) => ({
    title: r.title || r.url,
    url: r.url,
    snippet: (r.content || '').slice(0, 1800).trim(),
    publishedDate: r.published_date || null,
  }));

  // Attach Tavily's synthesized answer so the prompt builder can lead with
  // it. We stash it on the array as a non-enumerable-ish property so the
  // shape stays compatible with the other providers that don't have one.
  if (data.answer) {
    results.synthesizedAnswer = data.answer;
  }
  return results;
}

// ── SearXNG ────────────────────────────────────────────────
// Free, no key, real-time meta-search. Best if self-hosted; public
// instances often disable JSON output or rate-limit aggressively.
// VITE_SEARXNG_URL points to the base URL (e.g. http://localhost:8888).
async function searchSearxng(query, { limit = 5, signal = null } = {}) {
  // Routed via Vite proxy at /api/searxng to dodge CORS.
  const url = `/api/searxng/search?q=${encodeURIComponent(query)}&format=json&safesearch=1`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`SearXNG search failed (${resp.status})`);
  const data = await resp.json();
  return (data.results || []).slice(0, limit).map((r) => ({
    title: r.title || r.url,
    url: r.url,
    snippet: (r.content || '').slice(0, 600).trim(),
  }));
}

// ── DuckDuckGo Instant Answer ──────────────────────────────
// Free, no key, CORS-friendly. Caveat: it returns instant-answer
// summaries + related topics, not full SERP. Great for definitions
// and well-known entities; weak for breaking news.
async function searchDuckDuckGo(query, { limit = 5, signal = null } = {}) {
  const url =
    'https://api.duckduckgo.com/?' +
    `q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1&t=v07`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`DuckDuckGo search failed (${resp.status})`);
  const data = await resp.json();

  const out = [];
  if (data.AbstractText && data.AbstractURL) {
    out.push({
      title: data.Heading || query,
      url: data.AbstractURL,
      snippet: data.AbstractText.slice(0, 600).trim(),
    });
  }
  // RelatedTopics contains both flat entries and nested groups — flatten.
  const topics = [];
  for (const t of data.RelatedTopics || []) {
    if (t.Text && t.FirstURL) topics.push(t);
    if (Array.isArray(t.Topics)) {
      for (const sub of t.Topics) {
        if (sub.Text && sub.FirstURL) topics.push(sub);
      }
    }
  }
  for (const t of topics) {
    if (out.length >= limit) break;
    out.push({
      title: (t.Text || '').split(' - ')[0].slice(0, 100),
      url: t.FirstURL,
      snippet: (t.Text || '').slice(0, 600).trim(),
    });
  }
  return out.slice(0, limit);
}

// ── Wikipedia (deepest fallback) ───────────────────────────
async function searchWikipedia(query, { limit = 3, signal = null } = {}) {
  const sUrl =
    'https://en.wikipedia.org/w/api.php?action=query&list=search' +
    `&srsearch=${encodeURIComponent(query)}&srlimit=${limit}&format=json&origin=*`;
  const sResp = await fetch(sUrl, { signal });
  if (!sResp.ok) throw new Error(`Wikipedia search failed (${sResp.status})`);
  const hits = (await sResp.json()).query?.search || [];
  if (!hits.length) return [];

  const titles = hits.map((h) => h.title).join('|');
  const eUrl =
    'https://en.wikipedia.org/w/api.php?action=query&prop=extracts|info' +
    '&exintro=1&explaintext=1&inprop=url' +
    `&titles=${encodeURIComponent(titles)}&format=json&origin=*`;
  const eResp = await fetch(eUrl, { signal });
  if (!eResp.ok) throw new Error(`Wikipedia extract fetch failed (${eResp.status})`);
  const pages = (await eResp.json()).query?.pages || {};
  const titleOrder = new Map(hits.map((h, i) => [h.title, i]));
  return Object.values(pages)
    .map((p) => ({
      title: p.title,
      url:
        p.fullurl ||
        `https://en.wikipedia.org/wiki/${encodeURIComponent((p.title || '').replace(/ /g, '_'))}`,
      snippet: (p.extract || '').slice(0, 600).trim(),
    }))
    .filter((r) => r.snippet)
    .sort((a, b) => (titleOrder.get(a.title) ?? 99) - (titleOrder.get(b.title) ?? 99));
}

/**
 * Dispatch to the configured search provider. On failure, fall through to
 * the next-best option so a misconfigured Tavily key / down SearXNG instance
 * doesn't break the chat — Wikipedia is the guaranteed last resort.
 */
export async function searchWeb(query, options = {}) {
  if (!query?.trim()) return [];

  const provider = pickSearchProvider();
  const attempts = [];
  if (provider === 'tavily') attempts.push(['tavily', searchTavily]);
  if (provider === 'searxng') attempts.push(['searxng', searchSearxng]);
  if (provider === 'duckduckgo') attempts.push(['duckduckgo', searchDuckDuckGo]);
  // Wikipedia is always the last-resort backstop.
  attempts.push(['wikipedia', searchWikipedia]);

  let lastErr;
  for (const [name, fn] of attempts) {
    try {
      const results = await fn(query, options);
      if (results.length) {
        if (import.meta.env.DEV) console.log(`[V07] Web search via ${name} → ${results.length} results`);
        return results;
      }
    } catch (e) {
      if (e.name === 'AbortError') throw e;
      lastErr = e;
      console.warn(`[V07] Web search provider "${name}" failed, falling back:`, e.message);
    }
  }
  if (lastErr) throw lastErr;
  return [];
}

export function getSearchProvider() {
  return pickSearchProvider();
}

/**
 * Format search results as a context block to prepend to a user's message.
 *
 * Key shape choices that make the model actually USE the results instead of
 * hedging with "I don't have real-time data":
 *   - Today's date is stated explicitly so the model knows the snippets are
 *     fresh and dated, not stale training data.
 *   - Tavily's synthesized answer (when available) goes FIRST, framed as
 *     "current state". The model is far more likely to trust it than to
 *     re-derive from raw snippets.
 *   - Per-source snippets follow with their published_date so the model can
 *     cite specific sources and gauge recency.
 *   - The instructions are imperative ("DO use", "DO NOT say you lack
 *     real-time data") because hedging is the dominant failure mode.
 */
export function formatSearchContext(results, originalQuery) {
  if (!results?.length) return originalQuery;

  const today = new Date().toISOString().slice(0, 10);
  const synthesized = results.synthesizedAnswer;

  const sourceBlock = results
    .map((r, i) => {
      const dateLine = r.publishedDate ? `\nPublished: ${r.publishedDate}` : '';
      return `[${i + 1}] ${r.title}${dateLine}\n${r.snippet}\nSource: ${r.url}`;
    })
    .join('\n\n');

  const synthesizedBlock = synthesized
    ? `\n\nSYNTHESIZED ANSWER (generated just now from the top web sources):\n${synthesized}\n`
    : '';

  return (
    `You have just been given live web search results retrieved on ${today}. ` +
    `Treat this context as authoritative current information.\n\n` +
    `Instructions:\n` +
    `- DO use the search results below as your primary source of truth for ` +
    `time-sensitive facts (standings, prices, news, "current" anything).\n` +
    `- DO cite source numbers inline like [1], [2] when stating specific facts.\n` +
    `- DO NOT respond with "I don't have real-time information" — you DO ` +
    `have it, it's right here below this paragraph.\n` +
    `- DO NOT include a "Sources:", "References:", or similar URL list at ` +
    `the end of your response — the UI renders the source list separately ` +
    `from your prose. Just use inline [N] markers.\n` +
    `- If asked for data that can be charted (rankings, percentages, ` +
    `comparisons), present each item with its numeric value clearly so the ` +
    `UI can auto-generate a chart (e.g. "Maharashtra (24.11 lakh crores)").\n` +
    `- If the snippets genuinely don't answer the question, say what they ` +
    `DO say and point the user to the source URLs.\n` +
    `${synthesizedBlock}\n` +
    `WEB SEARCH RESULTS:\n\n${sourceBlock}\n\n---\n\n` +
    `Today's date: ${today}\nUser question: ${originalQuery}`
  );
}
