/* Faithful port of QualityEvaluator's cost-free path (Stages 1-2) from
   src/layer0_model_infra/routing/quality_evaluator.py. The LLM judge (Stage 3)
   is OFF in production — evaluate() is called without use_judge — so the quality
   signal is purely deterministic + heuristic, i.e. $0 per query. This reproduces
   exactly that path. */

export const MIN_QUALITY = 0.7

const REFUSAL = [
  /i cannot|i can't|i'm unable|i am unable/i,
  /i don't have|i do not have/i,
  /as an ai|as a language model/i,
  /i apologize, but|i'm sorry, but/i,
  /sorry, i cannot|sorry, i can't/i,
  /i'm not able to|i am not able to/i,
]
const HEDGING = [/maybe|perhaps|possibly|might be/i, /i think|i believe|in my opinion/i, /it seems|it appears|it looks like/i]
const HALLUCINATION = [/according to .* sources/i, /studies show|research indicates|experts say/i, /in a study published in/i, /as documented in/i]
const TRUNCATION = [/\.{3}\s*$/, /(?:and|but|or|the|a|in)\s*$/i, /```\s*$/, /\{\s*$/, /\[\s*$/]

function completeness(response, query) {
  if (response.length < 20) return 0.3
  const qlen = query.split(/\s+/).filter(Boolean).length
  const rlen = response.split(/\s+/).filter(Boolean).length
  if (rlen < qlen * 0.5) return 0.5
  if (/(\.\.\.|\band\b|\bbut\b|\bor\b|\bthe\b|\ba)$/.test(response.trimEnd())) return 0.6
  return 1.0
}
function coherence(response) {
  const low = response.toLowerCase()
  const contradiction = (low.includes('however') && low.includes('but') && (low.match(/however/g) || []).length > 1)
    || (low.startsWith('yes') && low.split('.')[0].includes('no'))
  if (contradiction) return 0.6
  const hedges = HEDGING.reduce((n, p) => n + (p.test(response) ? 1 : 0), 0)
  if (hedges > 3) return 0.7
  return 1.0
}
function detectRefusal(response) {
  const first = response.slice(0, 200)
  return REFUSAL.some((p) => p.test(first))
}
function hallucinationRisk(response) {
  let risk = HALLUCINATION.reduce((n, p) => n + (p.test(response) ? 0.2 : 0), 0)
  if ((response.match(/\d+/g) || []).length === 0 && response.length > 200) risk += 0.1
  return Math.min(risk, 1)
}
function detectTruncation(response) {
  if (!response) return true
  if (TRUNCATION.some((p) => p.test(response))) return true
  if ((response.match(/```/g) || []).length % 2 !== 0) return true
  if ((response.match(/\{/g) || []).length > (response.match(/\}/g) || []).length) return true
  return false
}

export function evaluate(response, query = 'Answer the question accurately.') {
  const refusal = detectRefusal(response)
  const comp = completeness(response, query)
  const coh = coherence(response)
  const halluc = hallucinationRisk(response)
  const truncated = detectTruncation(response)
  const formatMissing = false
  const validator = 1.0 // no required format → neutral pass

  const heuristic = refusal ? 0 : (comp * 0.3 + coh * 0.25 + (1 - halluc) * 0.2 + (truncated ? 0 : 1) * 0.15 + (formatMissing ? 0 : 1) * 0.1)
  const overall = refusal ? 0 : validator * 0.35 + heuristic * 0.65
  const passes = overall >= MIN_QUALITY && !refusal
  const needs_escalation = !passes || overall < 0.6

  return {
    overall, heuristic, validator, needs_escalation, passes,
    signals: {
      refusal_detected: refusal,
      truncated,
      completeness: comp,
      coherence: coh,
      hallucination_risk: halluc,
    },
    // contribution components for the breakdown
    components: refusal ? [] : [
      { key: 'completeness', label: 'Completeness', raw: comp, weight: 0.3 },
      { key: 'coherence', label: 'Coherence', raw: coh, weight: 0.25 },
      { key: 'grounding', label: 'Low hallucination', raw: 1 - halluc, weight: 0.2 },
      { key: 'complete_gen', label: 'Not truncated', raw: truncated ? 0 : 1, weight: 0.15 },
      { key: 'format', label: 'Format present', raw: formatMissing ? 0 : 1, weight: 0.1 },
    ],
  }
}
