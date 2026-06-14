/* Reproduces the query-aware retrieval strategies from vector_index.py
   (documented in RAG_WITH_CITATION.md): hybrid ANN + the five intent-driven
   strategies that bias which chunks come back. Similarity is the same
   content-word proxy used elsewhere (the real path uses ANN over embeddings). */

import { CHUNKS, similarity } from './ragdoc.js'

const EXTRA = [
  { id: 'med1', article: '§ Dosing', page: 1, title: 'Pediatric Ibuprofen Dose', content_type: 'clinical', text: 'Ibuprofen pediatric dose: for children under 50 kg administer 10 mg/kg every 6 to 8 hours. Do not exceed 40 mg/kg per day.' },
  { id: 'gen1', article: 'Schedule', page: 4, title: 'Project Timeline', content_type: 'general', text: 'The project timeline spans eighteen months with three milestones and a final handover review.' },
]
export const RCORPUS = [...CHUNKS, ...EXTRA]

export const STRATEGIES = [
  { key: 'multi', name: 'Multi-evidence', re: /\b(compare|list|summari[sz]e|all|differences?|between)\b/i, effect: 'retrieve a higher K with a broader threshold — the answer needs several sources' },
  { key: 'article', name: 'Article-reference', re: /article\s+\d+/i, effect: 'bias toward the chunk tagged with the requested article number' },
  { key: 'dose', name: 'Dose targeting', re: /\b(dose|dosage|mg|mg\/kg|daily dose)\b/i, effect: 'bias toward chunks that contain numeric dose information' },
  { key: 'quoted', name: 'Quoted-text exact', re: /"[^"]+"|'[^']+'/, effect: 'prioritise chunks containing the exact quoted string' },
  { key: 'title', name: 'Article-title', re: /\b(deals with|about|under)\b/i, effect: 'interpret the captured phrase as a section/article title to match' },
]

export function retrieve(query) {
  const fired = STRATEGIES.filter((s) => s.re.test(query))
  const firedKeys = new Set(fired.map((f) => f.key))
  const K = firedKeys.has('multi') ? 5 : 3
  const artMatch = (query.match(/article\s+(\d+)/i) || [])[1]
  const qm = query.match(/"([^"]+)"|'([^']+)'/) || []
  const quoted = qm[1] || qm[2]

  const scored = RCORPUS.map((c) => {
    const base = similarity(query, c.text + ' ' + c.title)
    let boost = 0
    const reasons = []
    if (artMatch && c.article.includes(artMatch)) { boost += 0.4; reasons.push('article match') }
    if (firedKeys.has('dose') && /\bmg\b|mg\/kg|dose/i.test(c.text)) { boost += 0.35; reasons.push('has dose') }
    if (quoted && c.text.toLowerCase().includes(quoted.toLowerCase())) { boost += 0.5; reasons.push('exact quote') }
    return { c, base, boost, reasons, score: Math.min(base + boost, 1) }
  }).sort((a, b) => b.score - a.score).slice(0, K)

  return { fired, K, chunks: scored }
}
