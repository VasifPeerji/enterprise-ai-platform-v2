/* Faithful client-side port of FastPathAnalyzer.analyze()
   (src/layer0_model_infra/routing/fast_path.py). The deterministic Tier-1
   cascade is reproduced exactly — same registries, regexes, ordering and
   confidence values. Tier-2 (Model2Vec prototype similarity) can't run a neural
   embedder in the browser, so it's reproduced as a small illustrative paraphrase
   matcher and clearly labelled.

   analyze(query) returns { decision, trace } where trace is the ordered list of
   checks the real cascade evaluates, so the UI can show exactly which rule fired. */

export const CAT = {
  GREETING: 'trivial_greeting',
  ACK: 'trivial_acknowledgment',
  FAREWELL: 'trivial_farewell',
  ARITHMETIC: 'pure_arithmetic',
  DEFINITION: 'simple_definition',
  FACTUAL: 'simple_factual',
  MALFORMED: 'malformed',
  NONE: 'none',
}

export const CONFIG = {
  min_greeting_confidence: 0.9,
  min_arithmetic_confidence: 0.95,
  min_factual_confidence: 0.8,
  max_greeting_words: 8,
  semantic_threshold: 0.8,
  semantic_max_words: 12,
  chat_chain: ['groq-llama-3.1-8b', 'groq-llama-3.3-70b', 'ollama-phi3-mini'],
  arithmetic_chain: ['groq-llama-3.1-8b', 'ollama-phi3-mini'],
  factual_chain: ['groq-llama-3.1-8b', 'groq-llama-3.3-70b', 'ollama-phi3-mini'],
}

const GREETINGS = {
  en: ['hi', 'hello', 'hey', 'hiya', 'howdy', 'yo', 'sup', 'greetings', 'salutations'],
  es: ['hola', 'buenos', 'buenas'], fr: ['bonjour', 'salut', 'coucou', 'bonsoir'],
  de: ['hallo', 'hi', 'moin', 'servus', 'tag'], it: ['ciao', 'salve', 'buongiorno', 'buonasera'],
  pt: ['olá', 'ola', 'oi'], ru: ['привет', 'здравствуйте'], zh: ['你好', '您好', '嗨'],
  ja: ['こんにちは', 'もしもし', 'やあ'], ko: ['안녕', '안녕하세요'], ar: ['مرحبا', 'أهلا', 'السلام'],
  hi: ['नमस्ते', 'नमस्कार', 'namaste', 'namaskar'], tr: ['merhaba', 'selam'], nl: ['hallo', 'hoi'],
  pl: ['cześć', 'witaj'],
}
const ACKS = {
  en: ['thanks', 'thx', 'ty', 'appreciated', 'appreciate', 'ok', 'okay', 'kk', 'alright', 'understood', 'noted'],
  es: ['gracias', 'vale'], fr: ['merci', 'ok'], de: ['danke', 'ok'], it: ['grazie', 'ok'],
  pt: ['obrigado', 'obrigada', 'valeu'], ru: ['спасибо', 'ок'], zh: ['谢谢', '好的'],
  ja: ['ありがとう', 'ありがとうございます', '了解'], ko: ['감사합니다', '고마워', '고맙습니다'],
  ar: ['شكرا'], hi: ['धन्यवाद', 'shukriya', 'shukran', 'dhanyavad'], tr: ['teşekkürler', 'sağol'],
  nl: ['bedankt', 'dank'], pl: ['dzięki', 'dziękuję'],
}
const FAREWELLS = {
  en: ['bye', 'goodbye', 'cya', 'farewell', 'later'], es: ['adiós', 'adios', 'chao'],
  fr: ['au revoir', 'salut', 'adieu'], de: ['tschüss', 'tschuess', 'auf wiedersehen'],
  it: ['arrivederci', 'ciao'], pt: ['tchau', 'adeus'], ru: ['пока', 'до свидания'],
  zh: ['再见', '拜拜'], ja: ['さようなら', 'じゃあね', 'バイバイ'], ko: ['안녕히', '잘가'],
  ar: ['وداعا'], hi: ['अलविदा', 'alvida'], tr: ['hoşçakal', 'güle güle'], nl: ['doei', 'tot'],
  pl: ['pa', 'do widzenia'],
}

const TOKEN_INDEX = {}
for (const [label, source] of [['greeting', GREETINGS], ['ack', ACKS], ['farewell', FAREWELLS]]) {
  for (const [lang, toks] of Object.entries(source)) {
    for (const tok of toks) {
      ;(TOKEN_INDEX[tok] ||= []).push({ lang, label })
    }
  }
}

export const LANG_COUNT = new Set([
  ...Object.keys(GREETINGS), ...Object.keys(ACKS), ...Object.keys(FAREWELLS),
]).size

const POLITE_FILLERS = new Set([
  'for', 'your', 'the', 'a', 'an', 'to', 'you', 'me', 'us', 'help', 'helping', 'again', 'now',
  'really', 'much', 'so', 'very', 'lot', 'lots', 'alot', 'kindly', 'please', 'too', 'all',
  'there', 'everyone', 'guys', 'folks', 'team', 'buddy', 'today', 'morning', 'afternoon',
  'evening', 'night', 'doing', 'lately', 'recently', 'friend', 'doc', 'mate', 'man', 'dude',
  'bro', 'sister', 'love', 'dear', 'fam', 'bestie', 'muchas', 'mucho', 'por', 'favor', 'amigo',
  'amigos', 'todo', 'todos', 'beaucoup', 'tout', 'tous', 'le', 'la', 'monde', 'très', 'viel',
  'vielen', 'danke', 'schön', 'schoen', 'guten', 'tanto', 'tante', 'grazie', 'mille', 'muito',
  'muita', 'obrigado', 'obrigada',
])

const PHRASES = [
  [/^\s*how\s*(?:'?s|s|\s+is|\s+are)\s+(?:you|it\s+going|things|life|your\s+day)\b/i, 'greeting_phrase:how_are_you', 'en', CAT.GREETING],
  [/^\s*what\s*(?:'?s|s|\s+is)\s+up\b/i, 'greeting_phrase:whats_up', 'en', CAT.GREETING],
  [/^\s*(?:good\s+(?:morning|afternoon|evening|night))\b/i, 'greeting_phrase:time_of_day', 'en', CAT.GREETING],
  [/^\s*(?:see\s+(?:you|ya)|catch\s+you\s+later)\b/i, 'farewell_phrase:see_you', 'en', CAT.FAREWELL],
  [/^\s*(?:got\s+it|understood|sounds\s+good|fair\s+enough|noted)\b/i, 'ack_phrase', 'en', CAT.ACK],
  [/^\s*(?:thank\s+you(?:\s+so\s+much|\s+very\s+much)?|appreciate(?:d|\s+it)|much\s+appreciated)\b/i, 'ack_phrase:thank_you', 'en', CAT.ACK],
  [/^\s*buenos\s+d[ií]as\b/i, 'greeting_phrase:buenos_dias', 'es', CAT.GREETING],
  [/^\s*guten\s+(?:tag|morgen|abend)\b/i, 'greeting_phrase:guten', 'de', CAT.GREETING],
  [/^\s*au\s+revoir\b/i, 'farewell_phrase:au_revoir', 'fr', CAT.FAREWELL],
]

const ARITH_RE = /^\s*[\d\s.+\-*/()^%]+\s*\??\s*$/
const ARITH_PREFIX_RE = /^\s*(?:what\s*(?:'?s|s|\s+is)|calculate|compute|solve)\s+[\d\s.+\-*/()^%]+\s*\??\s*$/i

const FACTUAL = [
  [/^\s*what\s*(?:'?s|s|\s+is)\s+the\s+capital\s+of\s+\w/i, 'factual:capital_of', CAT.FACTUAL],
  [/^\s*who\s+(?:is|was)\s+the\s+(?:president|prime\s+minister|ceo|founder|king|queen)\s+of\s+\w/i, 'factual:leader_of', CAT.FACTUAL],
  [/^\s*define\s+\w+\??\s*$/i, 'factual:define', CAT.DEFINITION],
  [/^\s*what\s+does\s+\w+\s+mean\??\s*$/i, 'factual:meaning_of', CAT.DEFINITION],
  [/^\s*how\s+many\s+\w+\s+in\s+(?:a|an|one)\s+\w+\??\s*$/i, 'factual:unit_conversion', CAT.FACTUAL],
  [/^\s*when\s+(?:is|was)\s+\w+(?:'s)?\s+\w+\??\s*$/i, 'factual:date_simple', CAT.FACTUAL],
]

// Tier-2 illustrative paraphrase prototypes (real path uses Model2Vec @0.80).
const TIER2_PROTOS = [
  ['cheers mate', CAT.ACK], ['no worries', CAT.ACK], ['appreciate ya', CAT.ACK],
  ['much obliged', CAT.ACK], ['yo whats good', CAT.GREETING], ['hows everything', CAT.GREETING],
  ['long time no see', CAT.GREETING], ['take care', CAT.FAREWELL], ['catch you around', CAT.FAREWELL],
  ['peace out', CAT.FAREWELL], ['my thanks', CAT.ACK], ['nice to meet you', CAT.GREETING],
]

const SCRIPT_HINTS = [
  [/[ऀ-ॿ]/, 'hi'], [/[一-鿿]/, 'zh'], [/[぀-ヿ]/, 'ja'],
  [/[가-힯]/, 'ko'], [/[؀-ۿ]/, 'ar'], [/[Ѐ-ӿ]/, 'ru'],
]

function detectScript(q) {
  for (const [re, lang] of SCRIPT_HINTS) if (re.test(q)) return lang
  return null
}
function tokenise(s) {
  return (s.toLowerCase().match(/[\p{L}\p{N}_-]+/gu) || [])
}
function trigrams(s) {
  const t = ' ' + s.replace(/\s+/g, ' ').trim() + ' '
  const out = new Set()
  for (let i = 0; i < t.length - 2; i++) out.add(t.slice(i, i + 3))
  return out
}
function jaccard(a, b) {
  const A = trigrams(a), B = trigrams(b)
  let inter = 0
  for (const x of A) if (B.has(x)) inter++
  return inter / (A.size + B.size - inter || 1)
}

function checkMalformed(raw) {
  const s = raw.trim()
  if (!s || s.length > 40) return null
  if (![...s].some((c) => /[\p{L}\p{N}]/u.test(c))) return 'malformed:no_alnum'
  if (s.length >= 3 && new Set(s).size === 1) return 'malformed:single_char_repeated'
  return null
}
function checkArithmetic(raw) {
  const s = raw.trim()
  if (!s) return null
  if (![...s].some((c) => c >= '0' && c <= '9')) return null
  if (![...s].some((c) => '+-*/^%'.includes(c))) return null
  if (ARITH_RE.test(s)) return 'arithmetic_regex'
  if (ARITH_PREFIX_RE.test(s)) return 'arithmetic_with_prefix'
  return null
}
function checkPhrase(raw) {
  for (const [re, label, lang, cat] of PHRASES) {
    const m = raw.match(re)
    if (!m) continue
    const remainder = raw.slice(m[0].length).trim()
    if (remainder) {
      const nonFiller = tokenise(remainder).filter((t) => !POLITE_FILLERS.has(t))
      if (nonFiller.length) continue
    }
    return { cat, label, lang }
  }
  return null
}
function checkToken(raw) {
  const wc = raw.trim().split(/\s+/).filter(Boolean).length
  if (wc === 0 || wc > CONFIG.max_greeting_words) return null
  const tokens = tokenise(raw)
  if (!tokens.length) return null
  const labels = new Set(), langs = [], matched = []
  for (const tok of tokens) {
    const hits = TOKEN_INDEX[tok]
    if (!hits) {
      if (POLITE_FILLERS.has(tok)) continue
      return null
    }
    for (const h of hits) {
      labels.add(h.label)
      if (!langs.includes(h.lang)) langs.push(h.lang)
    }
    matched.push(tok)
  }
  if (!matched.length) return null
  let cat
  if (labels.has('greeting')) cat = CAT.GREETING
  else if (labels.has('ack')) cat = CAT.ACK
  else if (labels.has('farewell')) cat = CAT.FAREWELL
  else return null
  const lang = langs.includes('en') ? 'en' : langs[0] || 'en'
  return { cat, label: `token:${matched.join(',')}`, lang }
}
function checkFactual(raw) {
  for (const [re, label, cat] of FACTUAL) if (re.test(raw)) return { cat, label }
  return null
}
function checkTier2(raw) {
  const wc = raw.trim().split(/\s+/).filter(Boolean).length
  if (wc === 0 || wc > CONFIG.semantic_max_words) return null
  let best = 0, bestCat = null, bestProto = null
  for (const [proto, cat] of TIER2_PROTOS) {
    const sim = jaccard(raw, proto)
    if (sim > best) { best = sim; bestCat = cat; bestProto = proto }
  }
  if (best >= CONFIG.semantic_threshold) {
    return { cat: bestCat, label: `tier2:~${bestProto}`, sim: best }
  }
  return null
}

const STEP_DEFS = [
  { key: 'empty', name: 'Empty / blank', desc: 'Hand to full pipeline' },
  { key: 'malformed', name: 'Malformed noise', desc: 'No alnum / repeated char (AutoMix)' },
  { key: 'arithmetic', name: 'Pure arithmetic', desc: 'Digit + operator, deterministic' },
  { key: 'phrase', name: 'Conversational phrase', desc: '14 start-anchored multi-word regexes' },
  { key: 'token', name: 'Greeting / ack / farewell', desc: 'Multilingual token index + polite fillers' },
  { key: 'factual', name: 'Simple factual / definition', desc: '6 word-boundary patterns' },
  { key: 'tier2', name: 'Tier-2 semantic', desc: 'Model2Vec prototype similarity ≥ 0.80' },
]

function modelFor(chain) {
  return { model: chain[0], chain }
}

export function analyze(query) {
  const trace = []
  const mark = (key, status, detail = '') => trace.push({ key, status, detail })
  const raw = (query || '').trim()

  // (empty)
  if (!raw) {
    mark('empty', 'fired', 'no content')
    for (const s of STEP_DEFS.slice(1)) mark(s.key, 'skipped')
    return {
      decision: { bypass: false, category: CAT.NONE, reason: 'Empty query — full pipeline will handle', confidence: 1.0 },
      trace,
    }
  }
  mark('empty', 'pass')

  const mal = checkMalformed(raw)
  if (mal) {
    mark('malformed', 'fired', mal)
    for (const s of STEP_DEFS.slice(2)) mark(s.key, 'skipped')
    return { decision: bypass(CAT.MALFORMED, modelFor(CONFIG.chat_chain), mal, null, CONFIG.min_greeting_confidence, 'Malformed — cheap response is sufficient'), trace }
  }
  mark('malformed', 'pass')

  const ar = checkArithmetic(raw)
  if (ar) {
    mark('arithmetic', 'fired', ar)
    for (const s of STEP_DEFS.slice(3)) mark(s.key, 'skipped')
    return { decision: bypass(CAT.ARITHMETIC, modelFor(CONFIG.arithmetic_chain), ar, null, CONFIG.min_arithmetic_confidence, 'Pure arithmetic — deterministic compute'), trace }
  }
  mark('arithmetic', 'pass')

  const ph = checkPhrase(raw)
  if (ph) {
    mark('phrase', 'fired', ph.label)
    for (const s of STEP_DEFS.slice(4)) mark(s.key, 'skipped')
    return { decision: bypass(ph.cat, modelFor(CONFIG.chat_chain), ph.label, ph.lang, CONFIG.min_greeting_confidence, `Conversational phrase (${ph.cat}, ${ph.lang})`), trace }
  }
  mark('phrase', 'pass')

  const tk = checkToken(raw)
  if (tk) {
    mark('token', 'fired', tk.label)
    for (const s of STEP_DEFS.slice(5)) mark(s.key, 'skipped')
    return { decision: bypass(tk.cat, modelFor(CONFIG.chat_chain), tk.label, tk.lang, CONFIG.min_greeting_confidence, `${tk.cat} (${tk.lang})`), trace }
  }
  mark('token', 'pass')

  const fa = checkFactual(raw)
  if (fa) {
    mark('factual', 'fired', fa.label)
    for (const s of STEP_DEFS.slice(6)) mark(s.key, 'skipped')
    return { decision: bypass(fa.cat, modelFor(CONFIG.factual_chain), fa.label, detectScript(raw) || 'en', CONFIG.min_factual_confidence, `Simple ${fa.cat.replace('_', ' ')}`), trace }
  }
  mark('factual', 'pass')

  const t2 = checkTier2(raw)
  if (t2) {
    mark('tier2', 'fired', `${t2.label} · sim ${t2.sim.toFixed(2)}`)
    return { decision: bypass(t2.cat, modelFor(CONFIG.chat_chain), t2.label, detectScript(raw) || 'en', Math.min(0.99, t2.sim), `Tier-2 semantic match (${t2.cat})`), tier2: true, trace }
  }
  mark('tier2', 'pass')

  return {
    decision: { bypass: false, category: CAT.NONE, reason: 'Query requires full pipeline analysis', confidence: 0.0 },
    trace,
  }
}

function bypass(category, { model, chain }, pattern, language, confidence, reason) {
  return { bypass: true, category, recommended_model: model, fallback_chain: chain, matched_pattern: pattern, detected_language: language, confidence, reason }
}

export { STEP_DEFS }
