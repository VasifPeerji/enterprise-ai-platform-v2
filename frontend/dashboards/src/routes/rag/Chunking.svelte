<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { DOC, CHUNKS } from '../../lib/sim/ragdoc.js'

  let mode = $state('structure') // structure | naive

  // naive fixed-window chunks over the concatenated document (ignores structure)
  const full = DOC.pages.map((p) => p.text).join(' ')
  const WIN = 110
  const naive = []
  for (let i = 0; i < full.length; i += WIN) {
    const text = full.slice(i, i + WIN)
    // which articles does this window touch?
    const arts = CHUNKS.filter((c) => {
      const s = full.indexOf(c.text)
      return s < i + WIN && s + c.text.length > i
    }).map((c) => c.article)
    naive.push({ text, arts, spans: arts.length > 1 })
  }

  const strategies = [
    { name: 'Article detection', for: 'legal / regulatory', desc: 'find_article_spans() splits on “Article N”, keeping each article whole and tagged with its number.' },
    { name: 'Section headers', for: 'technical / academic', desc: 'splits on heading hierarchy so a section stays a unit.' },
    { name: 'Paragraph boundaries', for: 'prose', desc: 'preserves natural paragraph breaks rather than cutting mid-thought.' },
    { name: 'Page boundaries', for: 'PDFs', desc: 'chunks never span a page — so every chunk maps cleanly to one page proof.' },
  ]
</script>

<PageHeader
  badge="2"
  eyebrow="RAG + Citation · Step 2"
  title="Structure-Aware Chunking"
  tagline="Splits documents along their natural seams — articles, sections, paragraphs, pages — instead of blind fixed-size windows. A chunk that respects boundaries is a chunk a citation can point at precisely."
  stats={[
    { value: '4', label: 'boundary strategies', tone: 'accent' },
    { value: 'never', label: 'spans a page' },
    { value: 'tagged', label: 'with article / section' },
    { value: 'offset-mapped', label: 'to source text' },
  ]}
/>

<Card eyebrow="Live comparison" title="The same document, two ways to chunk it" glow>
  <div class="modes">
    <button class:on={mode === 'structure'} onclick={() => (mode = 'structure')}>Structure-aware (this system)</button>
    <button class:on={mode === 'naive'} onclick={() => (mode = 'naive')}>Naive fixed-size</button>
  </div>

  {#if mode === 'structure'}
    <div class="chunks">
      {#each CHUNKS as c, i}
        <div class="chunk clean" style="--hue:{i}">
          <div class="chunk-h">
            <Pill tone="accent" mono>{c.article}</Pill>
            <span class="chunk-meta mono">page {c.page} · {c.title}</span>
          </div>
          <p class="chunk-t">{c.text}</p>
        </div>
      {/each}
    </div>
    <div class="note good"><span class="nd"></span> Each chunk is exactly one article on one page — a clean unit a page-proof can wrap.</div>
  {:else}
    <div class="chunks naive">
      {#each naive as c}
        <div class="chunk {c.spans ? 'spans' : ''}">
          <div class="chunk-h">
            {#if c.spans}<Pill tone="red" mono>spans {c.arts.join(' + ')}</Pill>{:else}<Pill tone="neutral" mono>{c.arts[0] || '—'}</Pill>{/if}
          </div>
          <p class="chunk-t small">{c.text}</p>
        </div>
      {/each}
    </div>
    <div class="note bad"><span class="nd"></span> Fixed windows slice mid-article and mid-page. A chunk that straddles two articles can't be cited cleanly — and dilutes the evidence with half-thoughts.</div>
  {/if}
</Card>

<div class="two">
  <Card eyebrow="The strategies" title="A seam for every document type">
    {#each strategies as s}
      <div class="strat">
        <div class="strat-h"><b>{s.name}</b><Pill tone="neutral">{s.for}</Pill></div>
        <p>{s.desc}</p>
      </div>
    {/each}
  </Card>

  <Card eyebrow="Why it's strong" title="Boundaries are precision">
    <p class="body2">
      Chunking quality is upstream of everything: it sets the granularity at which evidence can be
      retrieved and cited. Respecting structure does two jobs at once — it keeps each chunk
      <strong>self-contained</strong> (so retrieval isn't diluted by half-sentences) and keeps it
      <strong>addressable</strong> (so a citation can wrap exactly one article on exactly one page).
    </p>
    <div class="invariant">
      <span class="iv-k">the load-bearing invariant</span>
      <code>a chunk never spans a page</code>
      <span class="iv-n">→ every chunk maps to exactly one page proof</span>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="Where citation precision is decided">
  <p class="body">
    By the time generation cites “Article 5, page 1”, the work that made that precise was done here.
    Structure-aware chunks are why the system can return a tight highlight span instead of a vague
    “somewhere in this document” — and why irrelevant text doesn't crowd the context window and
    weaken the model's grounding.
  </p>
</Card>

<PrevNext current="/rag/chunking" />

<style>
  .modes { display: flex; gap: 8px; margin-bottom: 18px; }
  .modes button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 8px 16px; font-size: 13px; transition: all 0.12s; }
  .modes button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .chunks { display: flex; flex-direction: column; gap: 9px; }
  .chunks.naive { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
  .chunk { background: var(--bg-1); border: 1px solid var(--border-1); border-left: 3px solid var(--accent-2); border-radius: var(--r-md); padding: 12px 14px; animation: fade-up 0.3s ease both; }
  .chunk.spans { border-left-color: var(--red); background: var(--red-soft); }
  .chunk-h { display: flex; align-items: center; gap: 10px; margin-bottom: 7px; }
  .chunk-meta { font-size: 11px; color: var(--text-3); }
  .chunk-t { font-size: 12.5px; color: var(--text-2); line-height: 1.5; }
  .chunk-t.small { font-size: 11px; }
  .note { display: flex; gap: 9px; align-items: center; margin-top: 14px; padding: 11px 14px; border-radius: var(--r-md); font-size: 12.5px; line-height: 1.45; }
  .note.good { background: var(--accent-soft); border: 1px solid var(--accent-line); color: var(--text-1); }
  .note.bad { background: var(--red-soft); border: 1px solid color-mix(in srgb, var(--red) 35%, transparent); color: var(--text-1); }
  .note .nd { flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; }
  .note.good .nd { background: var(--accent-2); }
  .note.bad .nd { background: var(--red); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .strat { padding: 10px 0; border-bottom: 1px solid var(--border-1); }
  .strat:last-child { border-bottom: none; }
  .strat-h { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
  .strat-h b { font-size: 13px; color: var(--text-1); }
  .strat p { font-size: 12px; color: var(--text-3); line-height: 1.5; }

  .body2 { font-size: 13.5px; color: var(--text-2); line-height: 1.6; margin-bottom: 14px; }
  .body2 strong { color: var(--text-1); }
  .invariant { display: flex; flex-direction: column; gap: 5px; padding: 12px 14px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); }
  .iv-k { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-2); font-weight: 700; }
  .invariant code { font-family: var(--font-mono); font-size: 13px; color: var(--text-1); }
  .iv-n { font-size: 11.5px; color: var(--text-3); }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }
  code { font-family: var(--font-mono); }

  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
</style>
