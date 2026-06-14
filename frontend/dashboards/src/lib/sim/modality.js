/* Faithful client-side port of the Layer 1 ModalityGate
   (src/layer0_model_infra/routing/modality_gate.py). Reproduces the
   deterministic tiers exactly: the injection validator (HIGH/LOW patterns +
   block rule), the script + Hinglish language tiers, the shebang/fence/signature/
   keyword code tiers, and the structured-data try-parse cascade. The ML Tier-2s
   (lingua-py for language, pygments for code) are reproduced as small
   illustrative keyword detectors and labelled `*`. */

export const CFG = {
  MAX_CHAR_LENGTH: 128000,
  code_threshold: 0.4,
  code_required_threshold: 0.3,
  structured_threshold: 0.5,
  vision_threshold: 0.6,
  multimodal_min_high_signals: 2,
  language_confidence_threshold: 0.55,
  short_query_implies_vision: 15,
}

// ---- injection validator ---------------------------------------------------
const INJ_HIGH = [
  /ignore\s+(all\s+)?previous\s+instructions?/i,
  /disregard\s+(all\s+)?prior\s+(context|instructions?|rules?)/i,
  /forget\s+(everything|all|your)\s+(you|instructions?|rules?)/i,
  /system:\s*override/i,
  /\[system\]|\[admin\]|\[override\]/i,
  /\bDAN\s+mode\b|\bjailbreak\b|developer\s+mode/i,
  /respond\s+without\s+(any\s+)?restrictions?/i,
  /\bunrestricted\s+AI\b/i,
  /override\s+safety\s+protocols?/i,
]
const INJ_LOW = [
  /you\s+are\s+now\s+(a|an|the)?\s*\w+/i,
  /pretend\s+(you('re|\s+are)\s+)/i,
  /do\s+not\s+follow\s+(your|the)\s+(guidelines|rules|instructions)/i,
]

export function validate(text) {
  if (text.length > CFG.MAX_CHAR_LENGTH) {
    return { passed: false, reason: `Input exceeds maximum length (${text.length} chars)`, high: 0, low: 0, score: 0 }
  }
  const high = INJ_HIGH.reduce((n, p) => n + (p.test(text) ? 1 : 0), 0)
  const low = INJ_LOW.reduce((n, p) => n + (p.test(text) ? 1 : 0), 0)
  const total = high + low
  const score = Math.min((high * 2 + low) / 4, 1)
  const block = high >= 1 || low >= 2 || total >= 2
  return {
    passed: !block,
    reason: block ? `Prompt injection detected (${high} high · ${low} low pattern hits)` : '',
    high, low, score,
  }
}

// ---- language detector -----------------------------------------------------
const HINGLISH = new Set(['kya', 'hai', 'aap', 'mujhe', 'tum', 'tumhe', 'kaise', 'kaisa', 'nahi',
  'accha', 'acha', 'bhai', 'yaar', 'kar', 'karna', 'kiya', 'hua', 'hoga', 'mera', 'tera', 'uska',
  'sab', 'kuch', 'bata', 'batao', 'batayega', 'samjha', 'samjhi', 'kaam', 'ghar', 'abhi', 'phir',
  'fir', 'thoda', 'bahut', 'matlab', 'hain', 'hu', 'hoon', 'raha', 'rahi', 'rahe', 'namaste',
  'dhanyavad', 'shukriya', 'namaskar'])

const SCRIPTS = [
  [/[぀-ゟ゠-ヿ]/g, 'ja'],
  [/[가-힣]/g, 'ko'],
  [/[一-鿿]/g, 'zh'],
  [/[؀-ۿ]/g, 'ar'],
  [/[ऀ-ॿ]/g, 'hi'],
  [/[Ѐ-ӿ]/g, 'ru'],
  [/[ঀ-৿]/g, 'bn'],
  [/[஀-௿]/g, 'ta'],
]
// Illustrative lingua-py stand-in (the real path uses a trained detector).
const LINGUA = [
  ['es', ['hola', 'cómo', 'como', 'estás', 'estas', 'qué', 'que', 'gracias', 'por', 'favor', 'amigo', 'está', 'muy', 'dónde']],
  ['fr', ['bonjour', 'comment', 'ça', 'va', 'merci', 'vous', 'je', 'être', 'pour', 'avec', 'oui', 'salut']],
  ['de', ['hallo', 'wie', 'geht', 'danke', 'ist', 'und', 'der', 'die', 'das', 'ich', 'nicht', 'ein']],
  ['pt', ['olá', 'ola', 'como', 'está', 'obrigado', 'não', 'nao', 'você', 'voce', 'muito', 'para', 'bom']],
  ['it', ['ciao', 'come', 'stai', 'grazie', 'sono', 'non', 'per', 'molto', 'bene', 'che']],
]

export function detectLanguage(text) {
  if (!text.trim()) return { lang: 'en', conf: 1, detector: 'default' }
  for (const [re, lang] of SCRIPTS) {
    const m = text.match(re)
    if (m && m.length >= 3) return { lang, conf: 1, detector: 'script' }
  }
  const tokens = new Set((text.toLowerCase().match(/\b[a-z]+\b/g) || []))
  let hing = 0
  for (const t of tokens) if (HINGLISH.has(t)) hing++
  if (hing >= 2) return { lang: 'hi-Latn', conf: Math.min(0.5 + 0.15 * hing, 0.95), detector: 'hinglish_markers' }
  const low = text.toLowerCase()
  let best = null, bestHits = 1
  for (const [lang, words] of LINGUA) {
    const hits = words.reduce((n, w) => n + (low.includes(w) ? 1 : 0), 0)
    if (hits > bestHits) { bestHits = hits; best = lang }
  }
  if (best) return { lang: best, conf: 0.7, detector: 'lingua*' }
  return { lang: 'en', conf: 1, detector: 'default' }
}

// ---- code detector ---------------------------------------------------------
const SHEBANGS = [[/^#!.*\b(bash|sh|zsh)\b/m, 'bash'], [/^#!.*\bpython\d?\b/m, 'python'], [/^#!.*\bnode\b/m, 'javascript'], [/^#!.*\bruby\b/m, 'ruby']]
const FENCE = /```(\w+)/
const SIGNATURES = [
  [/\bdef\s+\w+\s*\([^)]*\)\s*[:\->]/, 'python'],
  [/\bfunction\s+\w+\s*\([^)]*\)\s*\{/, 'javascript'],
  [/\([^)]*\)\s*=>\s*[\{\(\w]/, 'javascript'],
  [/\binterface\s+\w+\s*(?:<\w+>\s*)?\{/, 'typescript'],
  [/\bfn\s+\w+\s*(?:<[^>]*>)?\s*\(/, 'rust'],
  [/\bfunc\s+\w+\s*\(/, 'go'],
  [/\bpublic\s+(?:static\s+)?(?:void|int|String|class)\s+\w+/, 'java'],
]
const KEYWORD_HINTS = [
  ['python', ['def ', 'import ', 'self.', 'if __name__', 'print(', 'from ']],
  ['javascript', ['function ', 'const ', 'let ', '=>', 'console.log', 'var ']],
  ['typescript', ['interface ', ': string', ': number', 'export type', 'as const']],
  ['rust', ['fn ', 'let mut ', 'impl ', 'trait ', 'match ', '::<']],
  ['go', ['func ', 'package ', 'defer ', ' <- ', ':= ', 'go func']],
  ['java', ['public class', 'private ', 'public static void', '@override']],
  ['cpp', ['#include', 'std::', '->', '::operator']],
  ['c', ['#include <', 'int main(', 'void *', 'malloc(', 'printf(']],
  ['sql', ['select ', ' from ', ' where ', 'join ', 'group by', 'insert into']],
  ['dockerfile', ['from ', 'run ', 'copy ', 'workdir ', 'expose ', 'cmd [']],
  ['html', ['<html', '<!doctype', '<body', '<head', '</body>', '</html>']],
]
const ALL_CODE_SIGNALS = [...new Set(KEYWORD_HINTS.flatMap(([, s]) => s))]

export function detectCode(text) {
  if (!text) return { lang: '', detector: 'none' }
  for (const [re, lang] of SHEBANGS) if (re.test(text)) return { lang, detector: 'shebang' }
  const f = text.match(FENCE)
  if (f) return { lang: f[1].toLowerCase(), detector: 'fence' }
  for (const [re, lang] of SIGNATURES) if (re.test(text)) return { lang, detector: 'signature' }
  const low = text.toLowerCase()
  let best = '', bestHits = 1
  for (const [lang, signals] of KEYWORD_HINTS) {
    const hits = signals.reduce((n, s) => n + (low.includes(s) ? 1 : 0), 0)
    if (hits > bestHits) { bestHits = hits; best = lang }
  }
  if (best) return { lang: best, detector: 'keyword' }
  return { lang: '', detector: 'none' }
}

export function codeDensity(text) {
  const low = text.toLowerCase()
  const matches = ALL_CODE_SIGNALS.reduce((n, s) => n + (low.includes(s) ? 1 : 0), 0)
    + SIGNATURES.reduce((n, [re]) => n + (re.test(text) ? 1 : 0), 0)
  const words = text.split(/\s+/).filter(Boolean).length || 1
  return Math.min(matches / Math.max(words / 25, 1), 1)
}

// ---- structured-data detector ---------------------------------------------
export function detectStructured(text) {
  const t = text.trim()
  if (!t) return { format: '', density: 0 }
  try {
    const v = JSON.parse(t)
    if (v && typeof v === 'object') return { format: 'json', density: 1 }
  } catch {}
  if (/^\s*<\?xml/.test(t) || (/^\s*<[a-zA-Z][\w-]*[\s>]/.test(t) && /<\/[a-zA-Z]/.test(t))) {
    return { format: 'xml', density: 0.9 }
  }
  const lines = t.split('\n')
  if (lines.length >= 2 && /\|.*\|/.test(lines[0]) && /\|?\s*:?-{2,}/.test(lines[1] || '')) {
    return { format: 'markdown_table', density: 0.8 }
  }
  const kvLines = lines.filter((l) => /^\s*[\w-]+:\s+\S/.test(l)).length
  if (kvLines >= 2) return { format: 'yaml', density: 0.7 }
  // CSV — hardened so code / stack traces don't match: no code-ish punctuation,
  // ≥2 columns, and EVERY non-empty row must have the same column count.
  const nonEmpty = lines.filter((l) => l.trim())
  if (nonEmpty.length >= 2 && !/[(){};]|=>|::/.test(t)) {
    const cols = nonEmpty[0].split(',').length
    if (cols >= 2 && nonEmpty.every((l) => l.split(',').length === cols)) {
      return { format: 'csv', density: 0.7 }
    }
  }
  return { format: '', density: 0 }
}

// ---- vision reference ------------------------------------------------------
const VISION_RE = /\b(in this (image|picture|photo|screenshot|diagram|chart)|describe (this|the) (image|picture|photo|screenshot)|what(?:'?s| is)?\s+(shown|in this (image|picture)|this)|ocr|screenshot|this (picture|photo|diagram|chart)|the attached (image|file|photo|diagram))\b/i
const DIAGRAM_RE = /\b(diagram|chart|graph|flowchart|architecture|schematic)\b/i

// ---- full analysis ---------------------------------------------------------
export function analyze(text, opts = {}) {
  const { has_images = false, has_audio = false, has_video = false } = opts
  const v = validate(text)
  if (!v.passed) {
    return {
      blocked: true, reason: v.reason, validation_passed: false,
      primary_modality: 'TEXT_ONLY', contains_injection_risk: v.score > 0.3,
      injection: v, language: { lang: 'en', conf: 1, detector: '—' }, code: { lang: '', detector: 'none' },
      code_density: 0, structured: { format: '', density: 0 },
      requires_vision: false, requires_audio: false, requires_code_model: false, multimodal_required: false,
      token_count: Math.round(text.split(/\s+/).filter(Boolean).length * 1.3),
    }
  }

  const language = detectLanguage(text)
  const code = detectCode(text)
  const cd = codeDensity(text)
  const structured = detectStructured(text)
  const wc = text.split(/\s+/).filter(Boolean).length

  const textRefImg = VISION_RE.test(text)
  const diagramKw = DIAGRAM_RE.test(text)
  const visionByText = has_images && (textRefImg || wc <= CFG.short_query_implies_vision)

  const requires_vision = visionByText || (diagramKw && has_images)
  const requires_audio = has_audio
  const requires_code_model = cd >= CFG.code_required_threshold

  const highSignals = [requires_vision, requires_audio, requires_code_model, structured.density >= CFG.structured_threshold].filter(Boolean).length
  const multimodal_required = highSignals >= CFG.multimodal_min_high_signals

  let primary
  if (has_video) primary = 'VIDEO'
  else if (requires_vision && (has_audio || cd >= CFG.code_threshold)) primary = 'MULTIMODAL'
  else if (requires_vision) primary = 'IMAGE'
  else if (has_audio) primary = 'AUDIO'
  else if (cd >= CFG.code_threshold) primary = 'CODE_HEAVY'
  else if (structured.density >= CFG.structured_threshold) primary = 'STRUCTURED'
  else primary = 'TEXT_ONLY'

  return {
    blocked: false, validation_passed: true, primary_modality: primary,
    injection: v, contains_injection_risk: v.score > 0,
    language, code, code_density: cd, structured,
    requires_vision, requires_audio, requires_code_model, multimodal_required,
    token_count: Math.round(wc * (1 + cd * 0.5) * 1.3),
  }
}
