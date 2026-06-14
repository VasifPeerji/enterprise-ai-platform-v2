<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { retrieve, STRATEGIES } from '../../lib/sim/retrieval.js'

  let query = $state('What does Article 5 say about insurance?')
  const r = $derived(retrieve(query))
  const firedKeys = $derived(new Set(r.fired.map((f) => f.key)))

  const examples = [
    'What does Article 5 say about insurance?',
    'Compare the payment terms and termination clauses',
    'What is the ibuprofen dose for a child under 50 kg?',
    'What does the contract say about "60 days written notice"?',
  ]
</script>

<PageHeader
  badge="4"
  eyebrow="RAG + Citation · Step 4"
  title="Query-Aware Retrieval"
  tagline="Not every question wants the same search. The retriever reads the query's intent — a specific article, a dose, an exact quote, a comparison — and adapts how and how widely it searches, so the right evidence comes back first."
  stats={[
    { value: 'hybrid', label: 'ANN + sparse keyword', tone: 'accent' },
    { value: '5', label: 'intent strategies' },
    { value: 'adaptive', label: 'top-K' },
  ]}
/>

<Card eyebrow="Live retriever" title="Type a query — see which strategy fires" glow>
  <input class="qinput" bind:value={query} spellcheck="false" placeholder="Ask the document something…" />
  <div class="chips">
    {#each examples as ex}
      <button class="chip" class:on={query === ex} onclick={() => (query = ex)}>{ex}</button>
    {/each}
  </div>

  <div class="fired">
    <span class="f-l">strategies fired:</span>
    {#if r.fired.length}
      {#each r.fired as f}<Pill tone="accent">{f.name}</Pill>{/each}
      <span class="kk mono">top-K = {r.K}</span>
    {:else}
      <Pill tone="neutral">plain hybrid search</Pill>
      <span class="kk mono">top-K = {r.K}</span>
    {/if}
  </div>

  <div class="results">
    {#each r.chunks as row, i}
      <div class="res">
        <span class="rank mono">{i + 1}</span>
        <div class="res-body">
          <div class="res-h">
            <Pill tone="neutral" mono>{row.c.article}</Pill>
            <span class="res-title">{row.c.title}</span>
            <span class="res-page mono">p{row.c.page}</span>
            {#each row.reasons as rsn}<Pill tone="green">+ {rsn}</Pill>{/each}
          </div>
          <p class="res-text">{row.c.text}</p>
          <div class="score">
            <div class="score-bar"><span class="base" style="width:{row.base * 100}%"></span><span class="boost" style="width:{row.boost * 100}%"></span></div>
            <span class="score-v mono">{row.score.toFixed(2)}{#if row.boost > 0}<span class="bv"> (+{row.boost.toFixed(2)})</span>{/if}</span>
          </div>
        </div>
      </div>
    {/each}
  </div>
</Card>

<div class="two">
  <Card eyebrow="The five strategies" title="Intent → search behaviour">
    {#each STRATEGIES as s}
      <div class="strat" class:active={firedKeys.has(s.key)}>
        <div class="strat-h"><b>{s.name}</b>{#if firedKeys.has(s.key)}<Pill tone="green" dot>active</Pill>{/if}</div>
        <p>{s.effect}</p>
      </div>
    {/each}
  </Card>

  <Card eyebrow="Why it's strong" title="Density over recall">
    <p class="body2">
      Naive retrieval grabs the top-K by raw similarity and hopes. But a question about “Article 5”
      wants <em>Article 5</em>, not the three chunks that happen to share vocabulary. By reading intent,
      the retriever raises the <strong>density of relevant evidence</strong> in the context window —
      which is the single biggest lever on whether the generated answer is grounded.
    </p>
    <p class="body2 mt">
      It's also <strong>hybrid</strong>: dense ANN catches paraphrases, sparse keyword catches exact
      terms and identifiers (article numbers, error codes, quoted strings) that embeddings blur.
    </p>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="Better evidence in, better answer out">
  <p class="body">
    Retrieval sets the ceiling for everything after it: the model can only ground its answer in what
    comes back here. Surfacing the <em>right</em> chunks first — and only as many as the question needs
    — is what keeps the context focused, the citations on-target, and the answer faithful.
  </p>
</Card>

<PrevNext current="/rag/retrieval" />

<style>
  .qinput { width: 100%; background: var(--bg-1); border: 1px solid var(--border-2); border-radius: var(--r-md); padding: 14px 16px; color: var(--text-1); font-size: 15px; font-family: var(--font-mono); outline: none; transition: border-color 0.15s, box-shadow 0.15s; }
  .qinput:focus { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-soft); }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .chip { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-pill); padding: 5px 11px; font-size: 12px; transition: all 0.12s; }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .fired { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 18px 0; }
  .f-l { font-size: 12.5px; color: var(--text-3); }
  .kk { font-size: 12px; color: var(--text-2); margin-left: 4px; }

  .results { display: flex; flex-direction: column; gap: 9px; }
  .res { display: flex; gap: 12px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 12px 14px; }
  .rank { flex-shrink: 0; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 6px; background: var(--surface-3); color: var(--text-2); font-size: 12px; font-weight: 700; }
  .res-body { flex: 1; min-width: 0; }
  .res-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
  .res-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
  .res-page { font-size: 11px; color: var(--text-3); }
  .res-text { font-size: 12px; color: var(--text-3); line-height: 1.5; margin-bottom: 9px; }
  .score { display: flex; align-items: center; gap: 10px; }
  .score-bar { flex: 1; height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; display: flex; }
  .base { background: linear-gradient(90deg, var(--accent-1), var(--accent-2)); }
  .boost { background: var(--green); }
  .score-v { font-size: 12px; color: var(--text-1); }
  .bv { color: var(--green); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .strat { padding: 9px 0; border-bottom: 1px solid var(--border-1); }
  .strat:last-child { border-bottom: none; }
  .strat.active { background: var(--accent-soft); margin: 0 -22px; padding: 9px 22px; border-radius: 8px; border-bottom-color: transparent; }
  .strat-h { display: flex; align-items: center; gap: 9px; margin-bottom: 3px; }
  .strat-h b { font-size: 13px; color: var(--text-1); }
  .strat p { font-size: 12px; color: var(--text-3); line-height: 1.5; }

  .body2 { font-size: 13px; color: var(--text-2); line-height: 1.6; }
  .body2.mt { margin-top: 12px; }
  .body2 strong { color: var(--text-1); }
  .body2 em { font-style: italic; color: var(--accent-2); }
  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body em { font-style: italic; color: var(--accent-2); }

  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
</style>
