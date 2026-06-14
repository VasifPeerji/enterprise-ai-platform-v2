<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { route, CORPUS, CFG } from '../../lib/sim/knn.js'

  let query = $state('Reverse a linked list in Python')
  const r = $derived(route(query))
  const sel = $derived(r.selected)
  const neighborIds = $derived(new Set(r.neighbors.map((n) => n.c.id)))

  const examples = [
    'What is the capital of Japan?',
    'Reverse a linked list in Python',
    'Prove that there are infinitely many prime numbers',
    'Design a distributed rate limiter',
    'What is the safe ibuprofen dose for a child?',
  ]

  const diffColor = (d) => (d < 0.35 ? '#34d399' : d < 0.65 ? '#fbbf24' : '#f87171')
  const SX = (x) => 8 + (x / 100) * 84
  const SY = (y) => 10 + (y / 100) * 82
</script>

<PageHeader
  badge="L3"
  eyebrow="Smart Routing · Layer 3 · the brain"
  title="Benchmark-Grounded kNN Router"
  tagline="The decision engine. It embeds the query, finds the nearest benchmark questions whose per-model pass/fail is already known, predicts every model's quality from those neighbours, and picks the cheapest one above the quality floor — no per-query LLM."
  stats={[
    { value: '14,922', label: 'benchmark points' },
    { value: 'k=20', label: 'neighbours', tone: 'accent' },
    { value: '0.65', label: 'quality floor' },
    { value: '0', label: 'LLM calls to route' },
    { value: '~50–150ms', label: 'latency' },
  ]}
/>

<div class="stages">
  {#each [['A', 'Verdict cache', 'exact + ANN hit'], ['B', 'Features', 'modality · difficulty · risk'], ['C', 'kNN predict', 'neighbour-weighted quality'], ['D', 'Fallback', 'priors if no neighbours']] as [s, t, d], i}
    <div class="stage" class:active={r.source === 'fallback' ? s === 'D' : s === 'C'}>
      <span class="sbadge">{s}</span>
      <div><b>{t}</b><span>{d}</span></div>
      {#if i < 3}<span class="sarrow">→</span>{/if}
    </div>
  {/each}
</div>

<Card eyebrow="Live router" title="Route a query — watch it reason from benchmark evidence" glow>
  <input class="qinput" bind:value={query} spellcheck="false" placeholder="Ask anything…" />
  <div class="chips">
    {#each examples as ex}
      <button class="chip" class:on={query === ex} onclick={() => (query = ex)}>{ex}</button>
    {/each}
  </div>

  <div class="lab">
    <!-- neighbour map -->
    <div class="panel">
      <div class="panel-h">Embedding space — k nearest benchmark questions</div>
      <svg viewBox="0 0 100 100" class="map">
        {#each r.neighbors as n}
          <line x1={SX(r.queryPos[0])} y1={SY(r.queryPos[1])} x2={SX(n.c.pos[0])} y2={SY(n.c.pos[1])}
            stroke="var(--accent-2)" stroke-width="0.5" opacity={0.25 + n.sim * 0.6} />
        {/each}
        {#each CORPUS as c}
          {@const near = neighborIds.has(c.id)}
          <circle cx={SX(c.pos[0])} cy={SY(c.pos[1])} r={near ? 2.4 : 1.6}
            fill={diffColor(c.difficulty)} opacity={near ? 1 : 0.28}
            stroke={near ? '#fff' : 'none'} stroke-width="0.3" />
        {/each}
        <circle cx={SX(r.queryPos[0])} cy={SY(r.queryPos[1])} r="3.2" fill="none" stroke="var(--accent-2)" stroke-width="0.8" class="qpulse" />
        <circle cx={SX(r.queryPos[0])} cy={SY(r.queryPos[1])} r="1.7" fill="var(--accent-2)" />
      </svg>
      <div class="legend">
        <span><i style="background:#34d399"></i>easy</span>
        <span><i style="background:#fbbf24"></i>medium</span>
        <span><i style="background:#f87171"></i>hard</span>
        <span><i class="qd"></i>your query</span>
      </div>
    </div>

    <!-- per-model bars -->
    <div class="panel">
      <div class="panel-h">Predicted quality per model · floor {r.floor.toFixed(2)}</div>
      <div class="bars">
        {#each r.perModel as p}
          {@const qualifies = p.predicted >= r.floor}
          {@const isSel = p.model.id === sel.model.id}
          <div class="brow" class:sel={isSel} class:qual={qualifies && !isSel} class:no={!qualifies}>
            <span class="bname">{p.model.label}<em>{p.model.size === 999 ? '·premium' : p.model.size + 'B'}</em></span>
            <div class="btrack">
              <span class="bfill" style="width:{p.predicted * 100}%"></span>
              <span class="floormark" style="left:{r.floor * 100}%"></span>
            </div>
            <span class="bval">{p.predicted.toFixed(2)}</span>
            <span class="bstar">{isSel ? '★' : qualifies ? '✓' : ''}</span>
          </div>
        {/each}
      </div>
    </div>
  </div>

  <!-- decision banner -->
  <div class="decision">
    <div class="dleft">
      <span class="dlabel">SELECTED</span>
      <span class="dmodel">{sel.model.label}</span>
      {#if !sel.model.active}<span class="dexec">routed-to · executes via free fallback (keyless)</span>{/if}
    </div>
    <div class="dpills">
      <Pill tone={r.source === 'knn_corpus' ? 'green' : 'amber'} mono>{r.source}</Pill>
      <Pill tone="accent" mono>pred {sel.predicted.toFixed(2)}</Pill>
      <Pill tone="neutral" mono>conf {sel.confidence.toFixed(2)}</Pill>
      <Pill tone="neutral" mono>floor {r.floor.toFixed(2)}</Pill>
      {#if r.highRisk}<Pill tone="violet">high-risk · {r.highRisk}</Pill>{/if}
      {#if r.hard}<Pill tone="amber">hard +0.10</Pill>{/if}
      {#if r.escalated}<Pill tone="amber">↑ uncertainty escalated</Pill>{/if}
    </div>
  </div>

  <!-- neighbour list -->
  <div class="nlist">
    <div class="nlist-h">Neighbours used (similarity-weighted)</div>
    {#each r.neighbors as n}
      <div class="nrow">
        <span class="ndot" style="background:{diffColor(n.c.difficulty)}"></span>
        <span class="nq">{n.c.text}</span>
        <Pill tone="neutral" mono>{n.c.domain}</Pill>
        <span class="nsim mono">sim {n.sim.toFixed(2)}</span>
      </div>
    {/each}
  </div>
</Card>

<div class="two">
  <Card eyebrow="How prediction works" title="Quality borrowed from neighbours">
    <p class="body2">
      Each model's predicted quality is the <strong>similarity-weighted average</strong> of how it
      scored on the nearest benchmark questions. A scalar prior is query-independent and can never
      tell easy from hard — this can, because the neighbours change with every query.
    </p>
    <div class="conf">
      <div class="conf-h">Prediction confidence = weighted blend of</div>
      <div class="cmet"><b>coverage</b><span>how many neighbours had outcomes</span><i>0.34</i></div>
      <div class="cmet"><b>agreement</b><span>1 − spread of neighbour outcomes</span><i>0.33</i></div>
      <div class="cmet"><b>proximity</b><span>how close the nearest neighbour is</span><i>0.33</i></div>
    </div>
  </Card>

  <Card eyebrow="The two safety levers" title="Quality floor + risk-aware escalation">
    <div class="lever">
      <b>Quality floor</b> — base {CFG.floor_base}, raised to {CFG.floor_high_risk} for high-risk
      domains (medical / legal / financial) and +{CFG.hard_penalty} on hard queries. Only models
      predicted above the floor may be selected; the cheapest one wins.
    </div>
    <div class="lever">
      <b>Risk-aware escalation</b> — when the cheapest pick's neighbour-confidence is below
      {CFG.escalate_below_confidence} and stronger qualifiers exist, the router climbs to the
      strongest <em>executable</em> qualifier instead. Selective, and still $0.
    </div>
    <p class="muted">Premium models (Claude, GPT-4o) are routed to when they're benchmark-best, but execution falls back to a free model until a key is added — so the displayed pick can differ from what runs.</p>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="This is the decision">
  <p class="body">
    Every earlier layer feeds this one: the fast path filters the trivial, the gate supplies modality
    and risk, the cache absorbs repeats, and the signals quantify difficulty. Layer 3 turns all of it
    into the actual model choice — grounded in <strong>real per-question outcomes</strong>, not a
    guess, at <strong>zero hot-path LLM cost</strong>. It's the mechanism that lets a cheap 8B answer
    the easy questions while the hard ones climb to a model that can actually solve them.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-3" />

<style>
  .stages { display: flex; gap: 8px; flex-wrap: wrap; }
  .stage { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 190px; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 11px 14px; position: relative; }
  .stage.active { border-color: var(--accent-line); background: var(--accent-soft); }
  .sbadge { width: 24px; height: 24px; border-radius: 6px; display: grid; place-items: center; font-family: var(--font-mono); font-weight: 700; font-size: 12px; background: var(--surface-3); color: var(--text-2); }
  .stage.active .sbadge { background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); color: var(--text-on-accent); }
  .stage div { display: flex; flex-direction: column; }
  .stage b { font-size: 13px; color: var(--text-1); }
  .stage span:not(.sbadge):not(.sarrow) { font-size: 11px; color: var(--text-3); }
  .sarrow { position: absolute; right: -10px; color: var(--text-3); z-index: 1; }

  .qinput { width: 100%; background: var(--bg-1); border: 1px solid var(--border-2); border-radius: var(--r-md); padding: 14px 16px; color: var(--text-1); font-size: 15px; font-family: var(--font-mono); outline: none; transition: border-color 0.15s, box-shadow 0.15s; }
  .qinput:focus { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-soft); }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .chip { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-pill); padding: 5px 11px; font-size: 12px; transition: all 0.12s; }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .lab { display: grid; grid-template-columns: 1fr 1.15fr; gap: 16px; margin-top: 18px; }
  .panel { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 14px; }
  .panel-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .map { width: 100%; height: 230px; display: block; background: radial-gradient(circle at 50% 45%, rgba(99,102,241,0.06), transparent 70%); border-radius: var(--r-sm); }
  .qpulse { animation: pulse-dot 2s ease-in-out infinite; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 8px; }
  .legend span { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-3); }
  .legend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .legend .qd { border: 1.5px solid var(--accent-2); background: var(--accent-2); }

  .bars { display: flex; flex-direction: column; gap: 7px; }
  .brow { display: grid; grid-template-columns: 150px 1fr 34px 16px; align-items: center; gap: 9px; }
  .bname { font-size: 12px; color: var(--text-2); display: flex; flex-direction: column; line-height: 1.2; }
  .bname em { font-style: normal; font-size: 10px; color: var(--text-3); font-family: var(--font-mono); }
  .btrack { position: relative; height: 14px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .bfill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; background: var(--surface-3); transition: width 0.3s ease; }
  .brow.qual .bfill { background: linear-gradient(90deg, rgba(52,211,153,0.5), var(--green)); }
  .brow.sel .bfill { background: linear-gradient(90deg, var(--accent-1), var(--accent-2)); }
  .brow.no .bfill { background: var(--surface-3); }
  .floormark { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--amber); opacity: 0.85; }
  .bval { font-family: var(--font-mono); font-size: 12px; color: var(--text-1); text-align: right; }
  .brow.no .bval { color: var(--text-3); }
  .bstar { font-size: 12px; color: var(--accent-2); }
  .brow.qual .bstar { color: var(--green); }

  .decision { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-top: 16px; padding: 16px 20px; border-radius: var(--r-md); background: linear-gradient(180deg, var(--accent-soft), transparent); border: 1px solid var(--accent-line); }
  .dleft { display: flex; flex-direction: column; gap: 2px; }
  .dlabel { font-size: 11px; letter-spacing: 0.1em; color: var(--text-3); font-weight: 700; }
  .dmodel { font-size: 22px; font-weight: 740; background: linear-gradient(95deg, var(--accent-1), var(--accent-2)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
  .dexec { font-size: 11.5px; color: var(--amber); }
  .dpills { display: flex; flex-wrap: wrap; gap: 7px; }

  .nlist { margin-top: 16px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 12px 14px; }
  .nlist-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-3); font-weight: 700; margin-bottom: 8px; }
  .nrow { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--border-1); }
  .nrow:last-child { border-bottom: none; }
  .ndot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .nq { flex: 1; font-size: 12.5px; color: var(--text-1); }
  .nsim { font-size: 11.5px; color: var(--text-3); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .body2 { font-size: 13.5px; color: var(--text-2); line-height: 1.6; margin-bottom: 14px; }
  .body2 strong { color: var(--text-1); }
  .conf-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-3); margin-bottom: 9px; }
  .cmet { display: grid; grid-template-columns: 90px 1fr 32px; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border-1); }
  .cmet:last-child { border-bottom: none; }
  .cmet b { font-size: 12.5px; color: var(--accent-2); font-family: var(--font-mono); }
  .cmet span { font-size: 11.5px; color: var(--text-3); }
  .cmet i { font-style: normal; font-family: var(--font-mono); font-size: 12px; color: var(--text-2); text-align: right; }

  .lever { font-size: 13px; color: var(--text-2); line-height: 1.55; margin-bottom: 12px; }
  .lever b { color: var(--text-1); }
  .lever em { font-style: italic; color: var(--accent-2); }
  .muted { font-size: 12px; color: var(--text-3); line-height: 1.5; margin-top: 4px; }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 920px) { .lab, .two { grid-template-columns: 1fr; } }
</style>
