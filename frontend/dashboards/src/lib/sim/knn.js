/* Representative client-side reproduction of the Layer 3 benchmark-grounded kNN
   router (src/layer0_model_infra/routing/knn_router.py). The ALGORITHM is
   faithful — embed the query, find the nearest benchmark questions whose
   per-model outcomes are known, predict each model's quality as a
   similarity-weighted mean of those neighbour outcomes, take the cheapest model
   above a quality floor, and escalate when neighbour-confidence is low.

   What's representative (not the live system): the corpus is a curated set of
   ~12 benchmark questions instead of the 14,922-point Qdrant collection, and
   similarity is a word-overlap proxy instead of the MiniLM encoder. The decision
   logic, floor, confidence signal and escalation are reproduced as in the real
   _predict_qualities / _choose. */

export const CFG = {
  k: 5,
  min_similarity: 0.12,
  floor_base: 0.65,
  floor_high_risk: 0.75,
  hard_penalty: 0.1,
  ceiling: 0.95,
  escalate_below_confidence: 0.5,
  w_coverage: 0.34,
  w_agreement: 0.33,
  w_proximity: 0.33,
  full_confidence_neighbors: 5,
}

// Active free models (+ one keyless premium) ordered by compute cost (params).
export const MODELS = [
  { id: 'llama-3.1-8b', label: 'Llama 3.1 8B', size: 8, active: true, prior: 0.39 },
  { id: 'llama-4-scout-17b', label: 'Llama 4 Scout 17B', size: 17, active: true, prior: 0.52 },
  { id: 'gpt-oss-20b', label: 'GPT-OSS 20B', size: 20, active: true, prior: 0.39 },
  { id: 'qwen3-32b', label: 'Qwen3 32B', size: 32, active: true, prior: 0.37 },
  { id: 'llama-3.3-70b', label: 'Llama 3.3 70B', size: 70, active: true, prior: 0.5 },
  { id: 'qwen-2.5-72b', label: 'Qwen2.5 72B', size: 72, active: true, prior: 0.55 },
  { id: 'gpt-oss-120b', label: 'GPT-OSS 120B', size: 120, active: true, prior: 0.65 },
  { id: 'claude-opus', label: 'Claude Opus', size: 999, active: false, prior: 0.73 },
]

// Benchmark corpus. quality[] follows MODELS order. pos = stylised 2D embedding
// position (domain-clustered) for the neighbour map. difficulty in 0..1.
export const CORPUS = [
  { id: 'cap_fr', text: 'What is the capital of France?', domain: 'factual', difficulty: 0.1, pos: [16, 24], quality: [0.95, 0.96, 0.97, 0.96, 0.98, 0.98, 0.99, 0.99] },
  { id: 'arith', text: 'What is 12 times 8?', domain: 'factual', difficulty: 0.1, pos: [24, 36], quality: [0.9, 0.93, 0.95, 0.95, 0.96, 0.97, 0.98, 0.98] },
  { id: 'translate', text: 'Translate good morning into French', domain: 'language', difficulty: 0.15, pos: [30, 28], quality: [0.92, 0.93, 0.94, 0.94, 0.95, 0.96, 0.97, 0.98] },
  { id: 'add_fn', text: 'Write a function to add two numbers', domain: 'code', difficulty: 0.2, pos: [74, 24], quality: [0.9, 0.92, 0.93, 0.93, 0.95, 0.95, 0.97, 0.98] },
  { id: 'reverse_ll', text: 'Reverse a linked list in Python', domain: 'code', difficulty: 0.5, pos: [82, 36], quality: [0.6, 0.68, 0.72, 0.74, 0.82, 0.83, 0.88, 0.93] },
  { id: 'sky_blue', text: 'Explain why the sky is blue', domain: 'reasoning', difficulty: 0.4, pos: [56, 48], quality: [0.7, 0.74, 0.78, 0.78, 0.85, 0.86, 0.9, 0.94] },
  { id: 'haiku', text: 'Write a haiku about autumn leaves', domain: 'creative', difficulty: 0.35, pos: [46, 44], quality: [0.8, 0.82, 0.84, 0.84, 0.87, 0.88, 0.9, 0.93] },
  { id: 'sqrt2', text: 'Prove that the square root of 2 is irrational', domain: 'math', difficulty: 0.82, pos: [78, 72], quality: [0.28, 0.4, 0.5, 0.52, 0.72, 0.74, 0.82, 0.93] },
  { id: 'rate_limiter', text: 'Design a distributed rate limiter for an API', domain: 'systems', difficulty: 0.85, pos: [86, 80], quality: [0.25, 0.38, 0.46, 0.5, 0.7, 0.72, 0.8, 0.9] },
  { id: 'number_theory', text: 'Solve this competition number theory problem about primes', domain: 'math', difficulty: 0.9, pos: [80, 86], quality: [0.2, 0.32, 0.42, 0.46, 0.66, 0.68, 0.78, 0.9] },
  { id: 'ibuprofen', text: 'What is the correct ibuprofen dose for a young child?', domain: 'medical', difficulty: 0.6, pos: [20, 74], quality: [0.55, 0.6, 0.65, 0.66, 0.78, 0.8, 0.85, 0.93] },
  { id: 'contract', text: 'Is a verbal contract legally binding in court?', domain: 'legal', difficulty: 0.6, pos: [30, 82], quality: [0.6, 0.64, 0.68, 0.69, 0.8, 0.82, 0.87, 0.94] },
]

const HIGH_RISK = {
  medical: ['dose', 'dosage', 'mg', 'symptom', 'treat', 'medicine', 'medication', 'pain', 'fever', 'overdose', 'child', 'infant', 'wound', 'cut', 'bleeding'],
  legal: ['contract', 'legally', 'lawsuit', 'court', 'liable', 'sue', 'rights', 'illegal', 'attorney'],
  financial: ['invest', 'tax', 'mortgage', 'retirement', 'stocks', 'loan'],
}

// Stopwords are dropped before matching so similarity keys off content words
// (a coarse stand-in for what the sentence encoder does semantically) — this
// stops "the / of / a" from creating spurious neighbours.
const STOP = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'of', 'to', 'in',
  'on', 'at', 'for', 'and', 'or', 'but', 'with', 'as', 'by', 'from', 'what', 'how', 'do', 'does',
  'did', 'i', 'my', 'me', 'we', 'it', 'its', 'this', 'that', 'these', 'those', 'you', 'your', 'can',
  'could', 'would', 'should', 'will', 'please', 'there', 'here', 'about', 'into', 'if', 'then', 's'])
function words(s) {
  return new Set((s.toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => t.length > 1 && !STOP.has(t)))
}
export function similarity(a, b) {
  const A = words(a), B = words(b)
  if (!A.size || !B.size) return 0
  let inter = 0
  for (const x of A) if (B.has(x)) inter++
  return (2 * inter) / (A.size + B.size)
}

// High-risk is detected from the query text (as the real bge classifier does),
// not from weakly-similar neighbours.
function detectHighRisk(query) {
  const low = query.toLowerCase()
  for (const [domain, kws] of Object.entries(HIGH_RISK)) {
    if (kws.some((k) => low.includes(k))) return domain
  }
  return null
}

export function route(query) {
  const sims = CORPUS.map((c) => ({ c, sim: similarity(query, c.text) })).sort((a, b) => b.sim - a.sim)
  const neighbors = sims.filter((s) => s.sim >= CFG.min_similarity).slice(0, CFG.k)

  if (neighbors.length === 0) {
    // Stage D fallback — prior-based over the catalog.
    const perModel = MODELS.map((m) => ({ model: m, predicted: m.prior, prior_used: true, confidence: 0.2 }))
    const qualifying = perModel.filter((p) => p.predicted >= CFG.floor_base).sort((a, b) => a.model.size - b.model.size)
    const selected = (qualifying[0] || perModel.filter((p) => p.model.active).sort((a, b) => b.predicted - a.predicted)[0])
    return { neighbors, perModel, floor: CFG.floor_base, highRisk: null, hard: false, source: 'fallback', selected, escalated: false, queryPos: [50, 55] }
  }

  const totalW = neighbors.reduce((s, n) => s + n.sim, 0)
  const meanDiff = neighbors.reduce((s, n) => s + n.sim * n.c.difficulty, 0) / totalW
  const topSim = neighbors[0].sim
  const coverage = Math.min(neighbors.length / CFG.full_confidence_neighbors, 1)
  const proximity = Math.min(Math.max((topSim - CFG.min_similarity) / (1 - CFG.min_similarity), 0), 1)

  const perModel = MODELS.map((m, i) => {
    const predicted = neighbors.reduce((s, n) => s + n.sim * n.c.quality[i], 0) / totalW
    // agreement = 1 - 2*weighted std of neighbour outcomes for this model
    const variance = neighbors.reduce((s, n) => s + n.sim * (n.c.quality[i] - predicted) ** 2, 0) / totalW
    const agreement = Math.max(0, 1 - 2 * Math.sqrt(variance))
    const confidence = CFG.w_coverage * coverage + CFG.w_agreement * agreement + CFG.w_proximity * proximity
    return { model: m, predicted, confidence, prior_used: false }
  })

  const highRisk = detectHighRisk(query)
  const hard = meanDiff > 0.6
  let floor = (highRisk ? CFG.floor_high_risk : CFG.floor_base) + (hard ? CFG.hard_penalty : 0)
  floor = Math.min(floor, CFG.ceiling)

  const qualifying = perModel.filter((p) => p.predicted >= floor).sort((a, b) => a.model.size - b.model.size)
  let selected, escalated = false, source = 'knn_corpus'
  if (qualifying.length) {
    selected = qualifying[0]
    // risk-aware escalation: low confidence + alternatives → strongest EXECUTABLE
    // (active) qualifier (escalating to a keyless model would just fall back).
    if (selected.confidence < CFG.escalate_below_confidence && qualifying.length >= 2) {
      const strongest = qualifying.filter((p) => p.model.active).sort((a, b) => b.predicted - a.predicted)[0]
      if (strongest && strongest.predicted > selected.predicted) { selected = strongest; escalated = true }
    }
  } else {
    source = 'fallback'
    selected = perModel.filter((p) => p.model.active).sort((a, b) => b.predicted - a.predicted)[0]
  }

  // query position = similarity-weighted centroid of neighbours
  const qx = neighbors.reduce((s, n) => s + n.sim * n.c.pos[0], 0) / totalW
  const qy = neighbors.reduce((s, n) => s + n.sim * n.c.pos[1], 0) / totalW

  return { neighbors, perModel, floor, highRisk, hard, source, selected, escalated, queryPos: [qx, qy], meanDiff, topSim }
}
