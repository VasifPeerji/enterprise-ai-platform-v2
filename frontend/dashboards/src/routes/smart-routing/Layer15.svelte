<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { extract, band } from '../../lib/sim/signals.js'

  let query = $state('Write a Python function to reverse a linked list, then explain its time complexity.')
  const s = $derived(extract(query))
  const b = $derived(band(s.overall_difficulty))

  const examples = [
    { label: 'Greeting', q: 'hey, how are you?' },
    { label: 'Code + explain', q: 'Write a Python function to reverse a linked list, then explain its time complexity.' },
    { label: 'Multi-part', q: 'Compare BFS and DFS, explain when to use each, and also give pseudocode for both.' },
    { label: 'Math proof', q: 'Prove that the square root of 2 is irrational.' },
    { label: 'Arithmetic', q: 'What is 15% of 240?' },
    { label: 'Constrained', q: 'Summarize this article in exactly 3 bullet points, must be under 50 words, with no jargon.' },
  ]

  const COLORS = ['#6366f1', '#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#60a5fa', '#f472b6', '#2dd4bf', '#f87171']
  // segments of the stacked bar (only non-zero contributions)
  const segs = $derived(
    s.components
      .map((c, i) => ({ ...c, contribution: c.raw * c.weight, color: COLORS[i % COLORS.length] }))
      .filter((c) => c.contribution > 0.0001)
  )
</script>

<PageHeader
  badge="L1½"
  eyebrow="Smart Routing · Layer 1.5"
  title="Input Signals"
  tagline="Turns a raw query into a structured, explainable difficulty profile — 20+ signals distilled into one weighted score across nine dimensions. Pure regex and string math, zero LLM."
  stats={[
    { value: '20+', label: 'extracted signals' },
    { value: '9', label: 'weighted dimensions', tone: 'accent' },
    { value: '1.0', label: 'weights sum to' },
    { value: '0', label: 'LLM calls' },
  ]}
/>

<Card eyebrow="Live difficulty profiler" title="Type a query — watch the difficulty assemble" glow>
  <p class="lede">
    <code>overall_difficulty</code> is a weighted average of nine signals. Type below and watch each
    one contribute. This is the exact formula from <code>input_signals.py</code>.
  </p>

  <textarea class="qinput" bind:value={query} rows="2" spellcheck="false"></textarea>
  <div class="chips">
    {#each examples as ex}
      <button class="chip" class:on={query === ex.q} onclick={() => (query = ex.q)}>{ex.label}</button>
    {/each}
  </div>

  <div class="profiler">
    <div class="gauge">
      <div class="gnum">{s.overall_difficulty.toFixed(3)}</div>
      <div class="glabel">overall_difficulty</div>
      <Pill tone={b.tone}>{b.label}</Pill>
    </div>

    <div class="breakdown">
      <div class="stack">
        {#each segs as seg}
          <div class="seg" style="width:{(seg.contribution / Math.max(s.overall_difficulty, 0.0001)) * 100}%; background:{seg.color}" title="{seg.label}: {seg.contribution.toFixed(3)}"></div>
        {/each}
        {#if segs.length === 0}<div class="seg empty"></div>{/if}
      </div>
      <div class="comp-list">
        {#each s.components as c, i}
          {@const contribution = c.raw * c.weight}
          <div class="comp" class:zero={contribution < 0.0001}>
            <span class="cdot" style="background:{COLORS[i % COLORS.length]}"></span>
            <span class="cname">{c.label}</span>
            <span class="cbar"><span class="cfill" style="width:{c.raw * 100}%; background:{COLORS[i % COLORS.length]}"></span></span>
            <span class="craw mono">{c.raw.toFixed(2)}</span>
            <span class="cw mono">×{c.weight}</span>
            <span class="ccontrib mono">{contribution.toFixed(3)}</span>
          </div>
        {/each}
      </div>
    </div>
  </div>

  <div class="discrete">
    <div class="dchip"><span>task_type</span><b>{s.task_type}</b></div>
    <div class="dchip"><span>words</span><b>{s.word_count}</b></div>
    <div class="dchip"><span>questions</span><b>{s.question_count}</b></div>
    <div class="dchip"><span>instructions</span><b>{s.instruction_count}</b></div>
    <div class="dchip"><span>reasoning</span><b>{s.reasoning_depth.toFixed(2)}</b></div>
    <div class="dchip"><span>multi_intent</span><b>{s.multi_intent_score.toFixed(2)}</b></div>
    <div class="dchip"><span>code_gen</span><b>{s.code_generation_flag ? 'yes' : 'no'}</b></div>
    <div class="dchip"><span>numerical</span><b>{s.numerical_reasoning_flag ? 'yes' : 'no'}</b></div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The formula" title="Nine signals, one score">
    <pre class="formula">overall_difficulty =
    length        × 0.15
  + structure     × 0.15
  + technical     × 0.10
  + constraints   × 0.10
  + multi_intent  × 0.10
  + reasoning     × 0.15
  + numerical     × 0.10
  + code_gen      × 0.05
  + instructions  × 0.10</pre>
    <p class="muted">Reasoning and length carry the most weight; code-generation the least. Every weight is hand-set and sums to exactly 1.0, so the score is always a clean 0–1.</p>
  </Card>

  <Card eyebrow="Why it's strong" title="Explainable, not a black box">
    <p class="body">
      Unlike an LLM difficulty rater, every point of this score is <strong>traceable</strong> to a
      concrete signal you can see — “this query scored 0.62 because it’s long, asks for a proof, and
      has three instructions.” That transparency is what makes the routing decision auditable.
    </p>
    <div class="grp">
      <div class="grp-h">what it extracts</div>
      <div class="tags">
        <Pill tone="neutral" mono>length</Pill><Pill tone="neutral" mono>structure</Pill>
        <Pill tone="neutral" mono>question_count</Pill><Pill tone="neutral" mono>code_blocks</Pill>
        <Pill tone="neutral" mono>required_format</Pill><Pill tone="neutral" mono>technical_terms</Pill>
        <Pill tone="neutral" mono>constraints</Pill><Pill tone="neutral" mono>multi_intent</Pill>
        <Pill tone="neutral" mono>reasoning_depth</Pill><Pill tone="neutral" mono>task_type</Pill>
        <Pill tone="neutral" mono>instruction_count</Pill><Pill tone="neutral" mono>context_length</Pill>
      </div>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="The difficulty dial the rest of the pipeline reads">
  <p class="body">
    This profile is computed once and reused everywhere: it sets the <strong>difficulty signal</strong>
    the kNN router uses to raise the quality floor on hard queries, it tells <strong>Layer 6</strong>
    whether a query is worth extra test-time compute, and it feeds the <strong>quality thresholds</strong>
    that decide when an answer needs to escalate. One cheap, explainable pass produces a signal the
    whole router trusts.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-1-5" />

<style>
  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 14px; }
  code { font-family: var(--font-mono); font-size: 0.9em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 6px; border-radius: 5px; }

  .qinput { width: 100%; resize: vertical; background: var(--bg-1); border: 1px solid var(--border-2); border-radius: var(--r-md); padding: 13px 15px; color: var(--text-1); font-size: 14px; font-family: var(--font-mono); outline: none; line-height: 1.5; transition: border-color 0.15s ease, box-shadow 0.15s ease; }
  .qinput:focus { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-soft); }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .chip { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-pill); padding: 5px 11px; font-size: 12px; transition: all 0.12s ease; }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .profiler { display: grid; grid-template-columns: 160px 1fr; gap: 20px; margin-top: 20px; align-items: start; }
  .gauge { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 18px 12px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); }
  .gnum { font-family: var(--font-mono); font-size: 34px; font-weight: 760; background: linear-gradient(95deg, var(--accent-1), var(--accent-2)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
  .glabel { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); }

  .stack { display: flex; height: 16px; border-radius: 6px; overflow: hidden; background: var(--surface-2); margin-bottom: 16px; gap: 1px; }
  .seg { transition: width 0.3s ease; }
  .seg.empty { width: 100%; background: var(--surface-2); }

  .comp-list { display: flex; flex-direction: column; gap: 7px; }
  .comp { display: grid; grid-template-columns: 12px 120px 1fr 38px 34px 48px; align-items: center; gap: 9px; font-size: 12px; transition: opacity 0.2s ease; }
  .comp.zero { opacity: 0.38; }
  .cdot { width: 9px; height: 9px; border-radius: 2px; }
  .cname { color: var(--text-2); }
  .cbar { height: 6px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
  .cfill { display: block; height: 100%; border-radius: 3px; transition: width 0.3s ease; }
  .craw, .cw, .ccontrib { font-family: var(--font-mono); text-align: right; }
  .craw { color: var(--text-1); }
  .cw { color: var(--text-3); }
  .ccontrib { color: var(--accent-2); font-weight: 600; }

  .discrete { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 18px; }
  .dchip { display: flex; flex-direction: column; gap: 1px; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-sm); padding: 7px 12px; }
  .dchip span { font-size: 10.5px; color: var(--text-3); font-family: var(--font-mono); }
  .dchip b { font-size: 13px; color: var(--text-1); font-family: var(--font-mono); font-weight: 600; }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .formula { font-family: var(--font-mono); font-size: 12px; color: var(--text-2); background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 14px 16px; margin: 0 0 12px; line-height: 1.6; overflow-x: auto; }
  .muted { font-size: 12px; color: var(--text-3); line-height: 1.5; }
  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }
  .grp { margin-top: 14px; }
  .grp-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-3); margin-bottom: 9px; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; }

  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } .profiler { grid-template-columns: 1fr; } }
</style>
