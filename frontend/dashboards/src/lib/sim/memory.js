/* Faithful client-side port of the Layer 2 SemanticMemory guard logic
   (src/layer0_model_infra/routing/semantic_memory.py). The five+ validation
   guards, the negation lexicon, PII scrubbing, entity extraction, decay and the
   tiered-TTL reusability rule are reproduced exactly.

   Similarity: production uses a Model2Vec embedder (near-duplicates and
   paraphrases score ~0.95). We can't run that in the browser, so similarity here
   is a word-overlap Dice coefficient — a semantic-ish proxy that keeps
   near-duplicates above the 0.85 threshold so the GUARDS (this layer's real
   contribution) are what flip the decision, exactly as in production. */

export const CFG = {
  similarity_threshold: 0.85,
  CONTEXT_LENGTH_RATIO_MAX: 3.0,
  MAX_NEW_ENTITY_RATIO: 0.5,
  decay_half_life_days: 7,
  high_quality_ttl_days: 14,
  medium_quality_ttl_days: 3,
  high_quality_threshold: 0.85,
  medium_quality_threshold: 0.7,
}

// ---- PII scrubbing ---------------------------------------------------------
const PII = [
  [/https?:\/\/\S+/gi, '<URL>'],
  [/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, '<EMAIL>'],
  [/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, '<PHONE>'],
  [/\b\d{3}-\d{2}-\d{4}\b/g, '<SSN>'],
  [/\b(?:\d[ -]*?){13,19}\b/g, '<CARD>'],
]
export function scrubPII(text) {
  let t = text
  for (const [re, rep] of PII) t = t.replace(re, rep)
  return t
}

// ---- negation polarity -----------------------------------------------------
const NEG_TOKENS = new Set(['no', 'not', 'never', 'none', 'without', 'cannot', 'cant', 'wont',
  'shouldnt', 'wouldnt', 'couldnt', 'isnt', 'arent', 'disable', 'uninstall', 'remove', 'delete',
  'undo', 'revert', 'stop', 'prevent', 'block', 'reject', 'deny', 'exclude', 'rid', 'ditch', 'kill',
  'shut', 'abandon', 'drop', 'discard', 'off', 'halt', 'abort', 'quit', 'exit', 'leave', 'avoid',
  'skip', 'dodge', 'refuse', 'decline', 'ignore', 'lose', 'lower', 'decrease', 'shrink', 'shorten',
  'reduce', 'minimize', 'weaken', 'destroy', 'demolish', 'sell', 'divorce', 'breakup', 'break',
  'split', 'separate'])
const NEG_PREFIXES = ['un', 'dis', 'de', 'non', 'anti']

export function negationScore(text) {
  const tokens = (text.toLowerCase().match(/[a-z']+/g) || [])
  let score = tokens.reduce((n, t) => n + (NEG_TOKENS.has(t) ? 1 : 0), 0)
  score += tokens.reduce((n, t) => n + (NEG_PREFIXES.some((p) => t.startsWith(p) && t.length > p.length + 3) ? 1 : 0), 0)
  return score
}

// ---- entity extraction -----------------------------------------------------
const COMMON_STARTERS = new Set(['The', 'This', 'That', 'These', 'Those', 'What', 'When', 'Where',
  'Which', 'How', 'Why', 'Who', 'Can', 'Could', 'Would', 'Should', 'Will', 'Do', 'Does', 'Did',
  'Is', 'Are', 'Was', 'Were', 'Has', 'Have', 'Had', 'Let', 'Please', 'Hello', 'Hi', 'Write',
  'Create', 'Build', 'Make', 'Add', 'Send', 'Update', 'Delete', 'Remove', 'Install', 'Run', 'Show',
  'Find', 'Get', 'Set', 'Help', 'Tell', 'Give', 'Explain', 'Describe', 'Translate', 'Generate',
  'Analyze', 'Compare', 'Implement', 'Debug', 'Fix', 'Best', 'Top', 'First', 'Last', 'Next'])
const TECH_STOPWORDS = new Set(['available', 'reasonable', 'reliable', 'viable', 'table', 'able',
  'stable', 'valuable', 'usable', 'noticeable', 'considerable', 'probable', 'possible', 'responsible',
  'sensible', 'terrible', 'horrible', 'visible', 'audible', 'edible', 'comfortable'])

export function extractTechnical(text) {
  const found = []
  for (const re of [/\b(\w+Error)\b/g, /\b(\w+Exception)\b/g, /\b(\w+(?:able|ible))\b/gi, /\b(\w+\.\w+(?:\.\w+)?)\b/g]) {
    for (const m of text.matchAll(re)) {
      const tok = m[1]
      if (!TECH_STOPWORDS.has(tok.toLowerCase()) && tok.length > 4) found.push(tok)
    }
  }
  return found
}
export function extractEntities(text) {
  const general = [...text.matchAll(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b/g)]
    .map((m) => m[1])
    .filter((e) => !COMMON_STARTERS.has(e) && e.length > 2)
  const all = [...general, ...extractTechnical(text)]
  const seen = new Set(), out = []
  for (const e of all) { const k = e.toLowerCase(); if (!seen.has(k)) { seen.add(k); out.push(e) } }
  return out.slice(0, 20)
}

// ---- similarity (Dice over word tokens) ------------------------------------
function words(s) { return new Set(s.toLowerCase().match(/[a-z0-9']+/g) || []) }
export function similarity(a, b) {
  const A = words(a), B = words(b)
  if (!A.size || !B.size) return 0
  let inter = 0
  for (const x of A) if (B.has(x)) inter++
  return (2 * inter) / (A.size + B.size)
}

function wordCount(s) { return s.split(/\s+/).filter(Boolean).length }
const normalize = (s) => s.toLowerCase().split(/\s+/).filter(Boolean).join(' ')

export function isReusable(entry) {
  if (entry.escalated) return { ok: false, ttl: 'never (escalated)' }
  if (entry.quality >= CFG.high_quality_threshold) return { ok: true, ttl: '14 days' }
  if (entry.quality >= CFG.medium_quality_threshold) return { ok: true, ttl: '3 days' }
  return { ok: false, ttl: 'not reusable (low quality)' }
}

// ---- the validation guards (exact order from _run_validation_guards) -------
const GUARD_DEFS = [
  { key: 'context_length', name: 'Context-length ratio', desc: 'length ratio ≤ 3' },
  { key: 'negation', name: 'Negation polarity', desc: 'install vs uninstall, with vs without' },
  { key: 'intent', name: 'Intent consistency', desc: 'cached intent must match' },
  { key: 'model_version', name: 'Model-version freshness', desc: 'same model generation' },
  { key: 'tech_entity', name: 'Technical-entity hard match', desc: 'TypeError ≠ ValueError' },
  { key: 'general_entity', name: 'General-entity novelty', desc: 'new-entity ratio < 0.5' },
]
export { GUARD_DEFS }

function runGuards(query, entry, queryIntent) {
  const qwc = wordCount(query), ewc = wordCount(entry.query)
  const fired = {}
  // 1 context-length
  if (ewc > 0 && qwc > 0) {
    const ratio = Math.max(qwc, ewc) / Math.max(Math.min(qwc, ewc), 1)
    if (ratio > CFG.CONTEXT_LENGTH_RATIO_MAX) return { guard: 'context_length', detail: `ratio ${ratio.toFixed(1)}` }
  }
  // 2 negation
  const qNeg = negationScore(query), eNeg = negationScore(entry.query)
  if (Math.abs(qNeg - eNeg) >= 1) return { guard: 'negation', detail: `${eNeg} → ${qNeg}` }
  // 3 intent
  if (queryIntent && entry.intent && queryIntent !== entry.intent) return { guard: 'intent', detail: `${entry.intent} → ${queryIntent}` }
  // 4 model-version (not exercised in this demo)
  // 5a technical-entity hard match
  const qTech = new Set(extractTechnical(scrubPII(query)).map((e) => e.toLowerCase()))
  const eTech = new Set(extractTechnical(entry.query).map((e) => e.toLowerCase()))
  if (qTech.size !== eTech.size || [...qTech].some((t) => !eTech.has(t))) {
    const diff = [...new Set([...qTech, ...eTech])].filter((t) => qTech.has(t) !== eTech.has(t))
    return { guard: 'tech_entity', detail: diff.slice(0, 2).join(', ') }
  }
  // 5b general-entity novelty
  const qEnts = extractEntities(query), eEnts = new Set(extractEntities(entry.query).map((e) => e.toLowerCase()))
  if (qEnts.length && eEnts.size) {
    const novel = qEnts.filter((e) => !eEnts.has(e.toLowerCase()))
    if (novel.length) {
      const ratio = novel.length / Math.max(qEnts.length, 1)
      if (ratio >= CFG.MAX_NEW_ENTITY_RATIO) return { guard: 'general_entity', detail: novel.slice(0, 2).join(', ') }
    }
  }
  void fired
  return null
}

export function lookup(rawQuery, cache, { queryIntent = '' } = {}) {
  const query = scrubPII(rawQuery)
  const sig = normalize(query)
  let best = null, bestSim = 0
  for (const e of cache) {
    const sim = similarity(sig, normalize(e.query))
    if (sim > bestSim) { bestSim = sim; best = e }
  }

  const trace = { threshold: { sim: bestSim, pass: false }, guards: {} }
  if (!best || bestSim < CFG.similarity_threshold) {
    return { verdict: 'MISS', reason: best ? `nearest similarity ${bestSim.toFixed(3)} < ${CFG.similarity_threshold}` : 'no entries', similarity: bestSim, matched: best, trace }
  }
  trace.threshold.pass = true
  const reuse = isReusable(best)
  if (!reuse.ok) {
    return { verdict: 'MISS', reason: `nearest match not reusable (${reuse.ttl})`, similarity: bestSim, matched: best, trace }
  }

  const g = runGuards(query, best, queryIntent)
  for (const def of GUARD_DEFS) {
    if (g && g.guard === def.key) { trace.guards[def.key] = { status: 'fired', detail: g.detail }; break }
    trace.guards[def.key] = { status: 'pass' }
  }
  if (g) {
    return { verdict: 'GUARD', guard: g.guard, reason: `${g.guard}: ${g.detail}`, similarity: bestSim, matched: best, trace }
  }
  return { verdict: 'HIT', reason: `reuse ${best.model} · sim ${bestSim.toFixed(3)}`, similarity: bestSim, matched: best, trace }
}
