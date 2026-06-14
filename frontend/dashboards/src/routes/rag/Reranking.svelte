<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'

  const CORPUS = [
    { id: 'leg', type: 'legal', label: 'Article 5 — Contractor Obligations', base: 0.62 },
    { id: 'clin', type: 'clinical', label: 'Ibuprofen dose — 10 mg/kg every 6h', base: 0.6 },
    { id: 'code', type: 'code', label: 'def calculate_penalty(days): …', base: 0.58 },
    { id: 'tbl', type: 'table', label: '| Milestone | Date | Amount |', base: 0.55 },
    { id: 'gen', type: 'general', label: 'Project timeline spans 18 months', base: 0.5 },
  ]
  const QTYPES = [
    { label: 'Code question', prefer: 'code' },
    { label: 'Table / data', prefer: 'table' },
    { label: 'Legal clause', prefer: 'legal' },
    { label: 'Clinical', prefer: 'clinical' },
  ]
  let qi = $state(0)
  const prefer = $derived(QTYPES[qi].prefer)

  const before = [...CORPUS].sort((a, b) => b.base - a.base)
  const after = $derived(
    [...CORPUS]
      .map((c) => ({ ...c, boost: c.type === prefer ? 0.3 : 0, score: c.base + (c.type === prefer ? 0.3 : 0) }))
      .sort((a, b) => b.score - a.score)
  )
  const beforeRank = $derived(Object.fromEntries(before.map((c, i) => [c.id, i])))
</script>

<PageHeader
  badge="5"
  eyebrow="RAG + Citation · Step 5"
  title="Domain-Aware Reranking"
  tagline="Vector similarity gets you close; reranking gets you right. After retrieval, chunks are reordered by what the question actually wants — code for code questions, tables for data questions, the right domain's evidence first."
  stats={[
    { value: 'content-type', label: 'aware', tone: 'accent' },
    { value: 'domain', label: 'precedence' },
    { value: 'recency', label: 'when it matters' },
  ]}
/>

<Card eyebrow="Before / after" title="Pick a question type — watch the order change" glow>
  <div class="seg">
    {#each QTYPES as q, i}
      <button class:on={qi === i} onclick={() => (qi = i)}>{q.label}</button>
    {/each}
  </div>

  <div class="cols">
    <div class="col">
      <div class="col-h">After ANN retrieval <span>by raw similarity</span></div>
      {#each before as c, i}
        <div class="row">
          <span class="rk mono">{i + 1}</span>
          <Pill tone="neutral" mono>{c.type}</Pill>
          <span class="lbl">{c.label}</span>
          <span class="sc mono">{c.base.toFixed(2)}</span>
        </div>
      {/each}
    </div>

    <div class="arrow-col">→<br />rerank</div>

    <div class="col">
      <div class="col-h">After reranking <span>by query intent</span></div>
      {#each after as c, i}
        {@const moved = beforeRank[c.id] - i}
        <div class="row {c.type === prefer ? 'lifted' : ''}">
          <span class="rk mono">{i + 1}</span>
          <Pill tone={c.type === prefer ? 'accent' : 'neutral'} mono>{c.type}</Pill>
          <span class="lbl">{c.label}</span>
          {#if moved > 0}<span class="mv up">▲{moved}</span>
          {:else if moved < 0}<span class="mv dn">▼{-moved}</span>
          {:else}<span class="mv eq">=</span>{/if}
          <span class="sc mono">{c.score.toFixed(2)}</span>
        </div>
      {/each}
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The rerank factors" title="What the reorder weighs">
    <div class="fac"><b>Content-type match</b><span>code queries favour code chunks, table queries favour tables, prose favours prose.</span></div>
    <div class="fac"><b>Domain precedence</b><span>legal precedence and clinical-evidence priority push the authoritative source up.</span></div>
    <div class="fac"><b>Recency</b><span>for time-sensitive questions, fresher chunks outrank stale ones.</span></div>
  </Card>

  <Card eyebrow="Why it's strong" title="Similarity isn't relevance">
    <p class="body2">
      Two chunks can be equally <em>similar</em> to a query and yet not equally <em>useful</em>: for
      “show me the penalty calculation”, the code chunk is the answer and the prose chunk is noise,
      even if both mention penalties. ANN can't tell them apart — reranking can, because it knows what
      <strong>kind</strong> of evidence the question is asking for.
    </p>
    <p class="body2 mt">
      Lifting the right chunk into the top slots matters because generation reads the top of the list
      most heavily — so reranking directly raises grounding quality without retrieving anything new.
    </p>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="The last filter before the model sees the evidence">
  <p class="body">
    Reranking is cheap insurance on an expensive step. Generation will lean hardest on whatever sits at
    the top of the retrieved set, so getting the <em>most relevant</em> chunk into position 1 — not just
    a <em>similar</em> one — is often the difference between a precisely cited answer and a vaguely
    grounded one.
  </p>
</Card>

<PrevNext current="/rag/reranking" />

<style>
  .seg { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 20px; }
  .seg button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 8px 14px; font-size: 13px; transition: all 0.12s; }
  .seg button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .cols { display: grid; grid-template-columns: 1fr 64px 1fr; gap: 8px; align-items: center; }
  .col-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .col-h span { text-transform: none; letter-spacing: 0; font-weight: 400; color: var(--text-3); opacity: 0.7; }
  .row { display: flex; align-items: center; gap: 8px; padding: 9px 10px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-sm); margin-bottom: 6px; }
  .row.lifted { border-color: var(--accent-line); background: var(--accent-soft); }
  .rk { flex-shrink: 0; width: 18px; color: var(--text-3); font-size: 12px; }
  .lbl { flex: 1; min-width: 0; font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .row.lifted .lbl { color: var(--text-1); }
  .sc { font-size: 11.5px; color: var(--text-3); }
  .mv { font-size: 10px; font-weight: 700; }
  .mv.up { color: var(--green); }
  .mv.dn { color: var(--text-3); }
  .mv.eq { color: var(--text-3); opacity: 0.5; }
  .arrow-col { text-align: center; font-size: 11px; color: var(--text-3); line-height: 1.6; }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .fac { padding: 9px 0; border-bottom: 1px solid var(--border-1); display: flex; flex-direction: column; gap: 2px; }
  .fac:last-child { border-bottom: none; }
  .fac b { font-size: 13px; color: var(--text-1); }
  .fac span { font-size: 12px; color: var(--text-3); line-height: 1.5; }

  .body2 { font-size: 13px; color: var(--text-2); line-height: 1.6; }
  .body2.mt { margin-top: 12px; }
  .body2 strong { color: var(--text-1); }
  .body2 em { font-style: italic; color: var(--accent-2); }
  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body em { font-style: italic; color: var(--accent-2); }

  @media (max-width: 760px) { .cols { grid-template-columns: 1fr; } .arrow-col { transform: rotate(90deg); } .two { grid-template-columns: 1fr; } }
</style>
