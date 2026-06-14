<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { DOC, findSpan } from '../../lib/sim/ragdoc.js'

  const citations = [
    { n: 1, page: 1, section: 'Article 5', highlight: 'maintain insurance coverage of at least 2,000,000 EUR' },
    { n: 2, page: 2, section: 'Article 6', highlight: 'Payment shall be made within 30 days of invoice receipt' },
  ]

  // The answer, with citation markers interleaved.
  const answer = [
    { t: 'The contractor must maintain insurance coverage of at least €2,000,000 throughout the project term' },
    { c: 1 },
    { t: '. Payment is due within 30 days of invoice receipt' },
    { c: 2 },
    { t: '.' },
  ]

  let selected = $state(1)
  const sel = $derived(citations.find((c) => c.n === selected))
  const page = $derived(DOC.pages[sel.page - 1])
  const span = $derived(findSpan(page.text, sel.highlight))
</script>

<PageHeader
  badge="9"
  eyebrow="RAG + Citation · Step 9 · the payoff"
  title="Citation Packaging & Highlighting"
  tagline="Where it all pays off. The answer's inline markers become clean superscripts, each citation a card, and each card a page proof you can open — landing on the exact highlighted span of the source page, down to the character offset."
  stats={[
    { value: '[N]', label: 'clean superscripts', tone: 'accent' },
    { value: 'char-offset', label: 'highlights' },
    { value: 'page proofs', label: 'per citation' },
    { value: 'rendered', label: 'page rects' },
  ]}
/>

<Card eyebrow="The finished answer" title="Click a citation — land on the exact source span" glow>
  <div class="answer">
    {#each answer as part}
      {#if part.t}{part.t}{:else}<button class="cite" class:on={selected === part.c} onclick={() => (selected = part.c)}>{part.c}</button>{/if}
    {/each}
  </div>

  <div class="cards">
    {#each citations as c}
      <button class="ccard" class:on={selected === c.n} onclick={() => (selected = c.n)}>
        <span class="cn">[{c.n}]</span>
        <span class="ctext">
          <span class="csrc">{DOC.source_uri}</span>
          <span class="cmeta">{c.section} · page {c.page}</span>
        </span>
      </button>
    {/each}
  </div>
</Card>

<Card eyebrow="The showpiece · page proof" title="The actual source page, highlighted">
  <div class="proof-grid">
    <div class="page">
      <div class="page-bar"><span>{DOC.source_uri}</span><span>page {sel.page}</span></div>
      <p class="page-body">
        {#if span}{page.text.slice(0, span.start_char)}<mark>{page.text.slice(span.start_char, span.end_char)}</mark>{page.text.slice(span.end_char)}{:else}{page.text}{/if}
      </p>
    </div>
    <div class="proof-meta">
      <div class="pm-h">PageProof</div>
      <div class="pm-row"><span>citation</span><b class="mono">[{sel.n}]</b></div>
      <div class="pm-row"><span>source_uri</span><b class="mono">{DOC.source_uri}</b></div>
      <div class="pm-row"><span>page_number</span><b class="mono">{sel.page}</b></div>
      <div class="pm-row"><span>section</span><b class="mono">{sel.section}</b></div>
      <div class="pm-row"><span>start_char</span><b class="mono">{span ? span.start_char : '—'}</b></div>
      <div class="pm-row"><span>end_char</span><b class="mono">{span ? span.end_char : '—'}</b></div>
      <p class="pm-note">On a real PDF those offsets become normalized rectangles drawn over the rendered page image — so the highlight lands on the exact physical line, even on rotated pages.</p>
    </div>
  </div>
</Card>

<Card eyebrow="How it shapes the final output" title="The promise, delivered">
  <p class="body">
    This is the whole subsystem's reason for being. Every step before it — page-bounded parsing,
    structure-aware chunks, pre-bound citation slots, claim verification — exists so that this last step
    can be true: a reader clicks <strong>[1]</strong> and lands on the exact sentence on the exact page
    that backs the claim. Not “somewhere in this document”. <strong>Page 1, characters
    {span ? `${span.start_char}–${span.end_char}` : '…'}.</strong> That's the difference between an
    answer you have to trust and one you can check.
  </p>
</Card>

<PrevNext current="/rag/citation" />

<style>
  .answer { font-size: 16px; line-height: 1.8; color: var(--text-1); padding: 6px 2px 4px; }
  .cite { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; padding: 0 4px; vertical-align: super; font-size: 10px; font-weight: 700; border-radius: 4px; background: var(--accent-soft); color: var(--accent-2); border: 1px solid var(--accent-line); margin: 0 1px; transition: all 0.12s; }
  .cite:hover { background: var(--accent-2); color: var(--text-on-accent); }
  .cite.on { background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); color: var(--text-on-accent); border-color: transparent; }

  .cards { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
  .ccard { display: flex; align-items: center; gap: 12px; text-align: left; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 11px 14px; transition: all 0.12s; }
  .ccard:hover { background: var(--surface-hover); }
  .ccard.on { background: var(--accent-soft); border-color: var(--accent-line); }
  .cn { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--accent-2); }
  .ctext { display: flex; flex-direction: column; }
  .csrc { font-size: 13px; color: var(--text-1); font-weight: 600; }
  .cmeta { font-size: 11.5px; color: var(--text-3); }

  .proof-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 18px; }
  .page { background: #f6f4ec; border-radius: var(--r-md); padding: 0; overflow: hidden; box-shadow: 0 12px 30px -10px rgba(0,0,0,0.5); border: 1px solid rgba(0,0,0,0.2); }
  .page-bar { display: flex; justify-content: space-between; padding: 8px 16px; background: #e7e3d6; border-bottom: 1px solid rgba(0,0,0,0.12); font-size: 11px; color: #6b6555; font-family: var(--font-mono); }
  .page-body { padding: 22px 20px 28px; font-family: Georgia, 'Times New Roman', serif; font-size: 14.5px; line-height: 1.85; color: #2b2b2b; }
  .page-body mark { background: #fde68a; color: #3a2e00; padding: 1px 2px; border-radius: 2px; box-shadow: 0 0 0 1px #f59e0b55; }

  .proof-meta { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 16px; }
  .pm-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-3); font-weight: 700; margin-bottom: 12px; }
  .pm-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border-1); font-size: 12px; }
  .pm-row span { color: var(--text-3); font-family: var(--font-mono); }
  .pm-row b { color: var(--text-1); font-weight: 600; }
  .pm-note { font-size: 11.5px; color: var(--text-3); line-height: 1.5; margin-top: 12px; }

  .body { color: var(--text-2); font-size: 14.5px; line-height: 1.7; }
  .body strong { color: var(--accent-2); }

  @media (max-width: 860px) { .proof-grid { grid-template-columns: 1fr; } }
</style>
