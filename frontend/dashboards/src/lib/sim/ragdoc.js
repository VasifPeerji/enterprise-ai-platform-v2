/* A small, coherent sample corpus used across the RAG dashboards so the same
   document threads through parsing → chunking → retrieval → assembly →
   verification → citation. Mirrors the real structure-aware chunking (one chunk
   per article, page-bounded) and page-proof shape from RAG_WITH_CITATION.md. */

export const DOC = {
  source_uri: 'VINCI_Contract.pdf',
  domain: 'legal',
  pages: [
    {
      page: 1,
      text: 'Article 5 — Contractor Obligations. The contractor shall complete all works in accordance with the approved drawings and specifications. The contractor must maintain insurance coverage of at least 2,000,000 EUR throughout the project term.',
    },
    {
      page: 2,
      text: 'Article 6 — Payment Terms. Payment shall be made within 30 days of invoice receipt. Late payment accrues interest at 4% per annum on the outstanding balance.',
    },
    {
      page: 3,
      text: 'Article 7 — Termination. Either party may terminate this agreement with 60 days written notice. Upon termination the contractor shall hand over all completed works and documentation.',
    },
  ],
}

// Structure-aware chunks — one per article, never spanning a page.
export const CHUNKS = [
  { id: 'c5', article: 'Article 5', page: 1, title: 'Contractor Obligations', content_type: 'legal', text: DOC.pages[0].text },
  { id: 'c6', article: 'Article 6', page: 2, title: 'Payment Terms', content_type: 'legal', text: DOC.pages[1].text },
  { id: 'c7', article: 'Article 7', page: 3, title: 'Termination', content_type: 'legal', text: DOC.pages[2].text },
]

const STOP = new Set(['the', 'a', 'an', 'is', 'are', 'of', 'to', 'in', 'on', 'for', 'and', 'or', 'with', 'what', 'does', 'do', 'this', 'that', 'shall', 'must', 'any', 'all', 'at', 'be'])
function words(s) {
  return new Set((s.toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => t.length > 1 && !STOP.has(t)))
}
export function similarity(a, b) {
  const A = words(a), B = words(b)
  if (!A.size || !B.size) return 0
  let i = 0
  for (const x of A) if (B.has(x)) i++
  return (2 * i) / (A.size + B.size)
}

/** Find the [start,end] char span of `needle` within `hay` (first occurrence). */
export function findSpan(hay, needle) {
  const start = hay.toLowerCase().indexOf(needle.toLowerCase())
  if (start < 0) return null
  return { start_char: start, end_char: start + needle.length }
}
