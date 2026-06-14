/* Faithful client-side port of InputSignalExtractor.extract()
   (src/layer0_model_infra/routing/input_signals.py). Every continuous score
   (length, structure, multi-intent, reasoning, instruction count) and the final
   weighted overall_difficulty formula are reproduced exactly. The one
   adjustment: the acronym technical-pattern is matched case-sensitively (its
   evident intent — uppercase acronyms) rather than the source's IGNORECASE,
   which would otherwise flag every multi-letter word. */

const TECHNICAL = [
  /\b[A-Z]{2,}\b/, // acronyms (case-sensitive on purpose)
  /\b(?:algorithm|complexity|architecture|implementation|optimization)\b/i,
  /\b(?:async|await|promise|callback|thread|mutex)\b/i,
  /O\(\w+\)/,
  /\b(?:API|SDK|REST|GraphQL|gRPC|HTTP|SQL|NoSQL|BFS|DFS|Dijkstra)\b/i,
  /\b(?:latency|throughput|scalability|concurrency)\b/i,
  /\b(?:python|java|javascript|c\+\+|typescript|react|node)\b/i,
]
const CONSTRAINTS = ['must', 'should', 'need to', 'required', 'constraint', 'without', 'except',
  'but not', 'only', 'exactly', 'no more than', 'at least', 'at most', 'between', 'limited to',
  'restricted to', 'cannot', 'forbidden']
const REASONING = [
  [/\bif\b.*\bthen\b/i, 0.2],
  [/\bbecause\b|\bsince\b|\btherefore\b|\bthus\b/i, 0.15],
  [/\bcompare\b|\bcontrast\b|\bdifference\b|\bsimilar\b/i, 0.15],
  [/\bwhy\b.*\b(does|is|was|would|should)\b/i, 0.15],
  [/\bprove\b|\bderive\b|\bdemonstrate\b/i, 0.25],
  [/\banalyze\b|\bevaluate\b|\bassess\b|\bcritique\b/i, 0.15],
  [/\btrade-?off\b|\bpros?\s+and\s+cons?\b|\badvantage\b/i, 0.1],
  [/\bhowever\b|\balthough\b|\bnevertheless\b|\bdespite\b/i, 0.1],
]
const NUMERICAL = [
  /\b\d+\s*[+\-*/%^]\s*\d+/,
  /\bcalculate\b|\bcompute\b|\bsolve\b/i,
  /\bhow\s+many\b|\bhow\s+much\b/i,
  /\bpercentage\b|\bratio\b|\bproportion\b/i,
  /\bequation\b|\bformula\b|\bderivative\b|\bintegral\b/i,
  /\bstatistic\b|\bmean\b|\bmedian\b|\bvariance\b/i,
]
const CODE_GEN = ['write a function', 'write code', 'implement', 'create a script', 'write a program',
  'code that', 'build a', 'develop a', 'write a class', 'create a method', 'generate code', 'debug',
  'fix this bug', 'sql query', 'api client', 'rest api', 'reverse a linked list', 'binary search',
  'bfs', 'dfs', 'dijkstra', 'need code', 'code to', 'longest substring']
const CONNECTORS = ['and also', 'but also', 'additionally', 'moreover', 'furthermore',
  'on top of that', 'in addition', 'as well as', 'plus']
const TASK_TYPES = {
  GENERATION: ['write', 'create', 'generate', 'compose', 'draft', 'produce', 'make', 'design', 'build'],
  TRANSFORMATION: ['convert', 'transform', 'translate', 'rewrite', 'refactor', 'restructure', 'format', 'paraphrase', 'summarize'],
  ANALYSIS: ['analyze', 'evaluate', 'assess', 'review', 'examine', 'investigate', 'break down', 'dissect', 'critique'],
  CONVERSATION: ['hello', 'hi', 'hey', 'thanks', 'bye', 'chat', 'how are you', "what's up"],
}
const IMPERATIVES = new Set(['write', 'create', 'list', 'explain', 'describe', 'show', 'find',
  'calculate', 'compare', 'analyze', 'generate', 'build', 'implement', 'design', 'convert', 'translate'])

function countMatches(re, s) { return (s.match(new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g')) || []).length }

function instructionCount(query, low) {
  let count = 0
  count += countMatches(/\d+\.\s+/g, low)
  count += countMatches(/(?:first|second|third|then|next|finally|lastly)/g, low)
  count += countMatches(/step\s+\d+/g, low)
  count += countMatches(/\n\s*[-*•]\s+/g, low)
  for (const line of query.trim().split('\n')) {
    const fw = line.trim().split(/\s+/)[0]?.toLowerCase() || ''
    if (IMPERATIVES.has(fw)) count++
  }
  return Math.max(count, 1)
}

function multiIntent(low, questionCount, instr) {
  let score = 0
  if (questionCount >= 2) score += 0.3
  if (questionCount >= 4) score += 0.2
  const conn = CONNECTORS.reduce((n, c) => n + (low.includes(c) ? 1 : 0), 0)
  score += Math.min(conn * 0.2, 0.4)
  const seq = ['first', 'then', 'next', 'finally', 'after that'].reduce((n, m) => n + (low.includes(m) ? 1 : 0), 0)
  if (seq >= 2) score += 0.25
  if (instr >= 3) score += 0.2
  if (instr >= 5) score += 0.1
  return Math.min(score, 1)
}

function reasoningDepth(query) {
  let d = 0
  for (const [re, w] of REASONING) if (re.test(query)) d += w
  return Math.min(d, 1)
}

function lengthScore(wc) {
  if (wc < 10) return 0.1
  if (wc < 30) return 0.3
  if (wc < 100) return 0.5
  if (wc < 200) return 0.7
  if (wc < 500) return 0.85
  return 0.95
}

function structureScore(questionCount, hasCode, hasLists, multiPart, instr, hasConstraints) {
  let s = 0
  if (questionCount > 1) s += 0.2
  if (hasCode) s += 0.2
  if (hasLists) s += 0.15
  if (multiPart) s += 0.15
  if (instr >= 3) s += 0.15
  if (hasConstraints) s += 0.15
  return Math.min(s, 1)
}

function classifyTask(low) {
  let best = null, bestScore = 0
  for (const [t, kws] of Object.entries(TASK_TYPES)) {
    const s = kws.reduce((n, k) => n + (low.includes(k) ? 1 : 0), 0)
    if (s > bestScore) { bestScore = s; best = t }
  }
  return best || 'QA'
}

export function extract(query) {
  const low = query.toLowerCase()
  const char_count = query.length
  const word_count = query.split(/\s+/).filter(Boolean).length
  const sentence_count = Math.max(query.split(/[.!?]+/).filter((s) => s.trim()).length, query.trim() ? 1 : 0)
  const question_count = countMatches(/\?/g, query)
  const code_block_count = (query.match(/```[\s\S]*?```/g) || []).length
  const has_code_blocks = code_block_count > 0
  const has_lists = /(?:^|\n)\s*(?:[-*•]|\d+\.)\s+/.test(query)

  const has_technical_terms = TECHNICAL.some((re) => re.test(query))
  const has_constraints = CONSTRAINTS.some((k) => low.includes(k))
  const instruction_count = instructionCount(query, low)
  const multi_intent_score = multiIntent(low, question_count, instruction_count)
  const has_multi_part = multi_intent_score > 0.3
  const task_type = classifyTask(low)
  const reasoning_depth = reasoningDepth(query)
  const numerical_reasoning_flag = NUMERICAL.some((re) => re.test(query))
  const code_generation_flag = CODE_GEN.some((k) => low.includes(k))
  const length_score = lengthScore(word_count)
  const structure_score = structureScore(question_count, has_code_blocks, has_lists, has_multi_part, instruction_count, has_constraints)

  // The 9 weighted components of overall_difficulty (weights sum to 1.0).
  const components = [
    { key: 'length', label: 'Length', raw: length_score, weight: 0.15 },
    { key: 'structure', label: 'Structure', raw: structure_score, weight: 0.15 },
    { key: 'technical', label: 'Technical terms', raw: has_technical_terms ? 1 : 0, weight: 0.1 },
    { key: 'constraints', label: 'Constraints', raw: has_constraints ? 1 : 0, weight: 0.1 },
    { key: 'multi_intent', label: 'Multi-intent', raw: multi_intent_score, weight: 0.1 },
    { key: 'reasoning', label: 'Reasoning depth', raw: reasoning_depth, weight: 0.15 },
    { key: 'numerical', label: 'Numerical', raw: numerical_reasoning_flag ? 1 : 0, weight: 0.1 },
    { key: 'code_gen', label: 'Code generation', raw: code_generation_flag ? 1 : 0, weight: 0.05 },
    { key: 'instructions', label: 'Instruction count', raw: Math.min(instruction_count / 5, 1), weight: 0.1 },
  ]
  const overall_difficulty = components.reduce((s, c) => s + c.raw * c.weight, 0)

  return {
    char_count, word_count, sentence_count, question_count, code_block_count, has_code_blocks,
    has_lists, has_technical_terms, has_constraints, instruction_count, multi_intent_score,
    has_multi_part, task_type, reasoning_depth, numerical_reasoning_flag, code_generation_flag,
    length_score, structure_score, components, overall_difficulty: Math.round(overall_difficulty * 1e4) / 1e4,
  }
}

export function band(d) {
  if (d < 0.33) return { label: 'low', tone: 'green' }
  if (d < 0.6) return { label: 'moderate', tone: 'amber' }
  return { label: 'high', tone: 'red' }
}
