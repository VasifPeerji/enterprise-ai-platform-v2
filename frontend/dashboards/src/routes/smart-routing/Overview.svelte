<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import SectionTitle from '../../components/ui/SectionTitle.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import PipelineFlow from '../../components/PipelineFlow.svelte'
  import { systems, routeFor } from '../../lib/registry.js'
  import { navigate } from '../../lib/router.js'

  const sys = systems.find((s) => s.id === 'smart-routing')
  const layers = sys.items.filter((i) => i.slug !== 'overview')

  const approaches = [
    { kind: 'old', title: 'LLM-per-query classifier', body: 'Ask a big model to rate each query’s difficulty before routing. Accurate, but adds a full LLM call to every request — the exact hot-path cost we’re trying to avoid.', tag: 'expensive' },
    { kind: 'old', title: 'Cold-start contextual bandit', body: 'Learn which model wins from live feedback. But the context space is huge, most cells have ~0 pulls, and Thompson sampling on no data is just random.', tag: 'slow to learn' },
    { kind: 'new', title: 'Benchmark-grounded kNN', body: 'Embed the query, find the nearest benchmark questions whose per-model pass/fail is already known, and predict each model’s quality from those neighbours. No per-query LLM, no cold start.', tag: 'this system' },
  ]
</script>

<PageHeader
  badge="∑"
  eyebrow="Smart Routing System"
  title="The whole routing brain, end to end"
  tagline="Nine layers decide — per query — the cheapest model that can still answer it correctly, grounded in real benchmark outcomes and learning from every result."
  stats={[
    { value: '9', label: 'pipeline layers' },
    { value: '0', label: 'LLM calls to route', tone: 'accent' },
    { value: '~50–150ms', label: 'route latency' },
    { value: '9', label: 'active free models' },
    { value: '$0', label: 'cost per query', tone: 'green' },
  ]}
/>

<section>
  <SectionTitle eyebrow="Why it's different" title="Three ways to route — one that's cheap and grounded">
    Most routers pay for their intelligence on the hot path or wait to learn it. This one borrows
    it from a benchmark corpus that already knows how every model performs.
  </SectionTitle>
  <div class="threeup">
    {#each approaches as a}
      <div class="approach {a.kind}">
        <div class="ap-top">
          <Pill tone={a.kind === 'new' ? 'accent' : 'neutral'}>{a.tag}</Pill>
          {#if a.kind === 'old'}<span class="strike">replaced</span>{/if}
        </div>
        <h3>{a.title}</h3>
        <p>{a.body}</p>
      </div>
    {/each}
  </div>
</section>

<Card eyebrow="Live walk-through" title="Follow a query through all nine layers" glow>
  <p class="card-lede">
    Pick a query and watch which layers fire, which short-circuit, and which are skipped — with the
    real decision shown at each step. This mirrors <code>ModelRouter.route()</code> then the
    orchestrator's execution loop.
  </p>
  <PipelineFlow />
</Card>

<div class="two">
  <Card eyebrow="The economics" title="An all-free cost model">
    <p class="body">
      The nine active models are all <strong>free tiers</strong> (Groq, Gemini, HuggingFace), so
      dollar-cost is the same — <strong>$0</strong> — for every one. "Cost-efficient" therefore
      means the <strong>smallest-sufficient compute</strong>: the fewest parameters (a proxy for
      latency and energy) that still clears the quality bar, with a size tiebreak.
    </p>
    <div class="cost-row">
      <div class="cost-item"><span class="ci-k">cheap & capable</span><span class="ci-v">8B → 20B</span></div>
      <div class="cost-arrow">→</div>
      <div class="cost-item"><span class="ci-k">only when needed</span><span class="ci-v">70B → 120B</span></div>
      <div class="cost-arrow">→</div>
      <div class="cost-item"><span class="ci-k">routed, not run</span><span class="ci-v">premium*</span></div>
    </div>
    <p class="muted">
      * Keyless premium models (GPT-4o, Claude Opus) are still <em>routed to</em> when they're
      benchmark-best — execution falls back to a free model until a key is added.
    </p>
  </Card>

  <Card eyebrow="The evolution" title="From a hot-path LLM judge to kNN">
    <div class="evo">
      <div class="evo-col then">
        <div class="evo-h">Legacy (retired)</div>
        <ul>
          <li><s>70B LLM rubric per query</s> <span class="ms">~500ms each</span></li>
          <li><s>regex uncertainty estimator</s> <span class="ms">12 hand-weighted signals</span></li>
          <li><s>Thompson-sampling bandit</s> <span class="ms">random on cold cells</span></li>
        </ul>
      </div>
      <div class="evo-arrow">⟶</div>
      <div class="evo-col now">
        <div class="evo-h">Now</div>
        <ul>
          <li><b>kNN over benchmark outcomes</b> <span class="ms">no per-query LLM</span></li>
          <li><b>free neighbour-confidence</b> <span class="ms">coverage × agreement × proximity</span></li>
          <li><b>EMA calibration</b> <span class="ms">the only online learning</span></li>
        </ul>
      </div>
    </div>
    <p class="muted">The legacy chain is archived under <code>routing/legacy/</code> — the project tested multiple designs and finalized one.</p>
  </Card>
</div>

<section>
  <SectionTitle eyebrow="Go deeper" title="Open any layer">
    Each layer has its own dashboard — what it does, why it's strong, and a live tester.
  </SectionTitle>
  <div class="layer-grid">
    {#each layers as l}
      <button class="lcard" class:flag={l.flagship} onclick={() => navigate(routeFor('smart-routing', l.slug))}>
        <span class="lbadge">{l.badge}</span>
        <span class="ltext">
          <span class="ltitle">{l.title}</span>
          <span class="ltag">{l.tagline}</span>
        </span>
        <span class="larrow">→</span>
      </button>
    {/each}
  </div>
</section>

<PrevNext current="/smart-routing/overview" />

<style>
  .threeup { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  .approach {
    border-radius: var(--r-lg); padding: 20px;
    border: 1px solid var(--border-1);
    background: linear-gradient(180deg, var(--surface-1), transparent);
  }
  .approach.old { opacity: 0.92; }
  .approach.new {
    border-color: var(--accent-line);
    background: linear-gradient(180deg, var(--accent-soft), transparent 70%);
    box-shadow: var(--glow);
  }
  .ap-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .strike { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.08em; }
  .approach h3 { font-size: 15.5px; margin-bottom: 8px; }
  .approach p { font-size: 13px; color: var(--text-2); line-height: 1.5; }

  .card-lede { color: var(--text-2); font-size: 14px; margin-bottom: 20px; }
  .card-lede code, .muted code, .body code { font-family: var(--font-mono); font-size: 0.9em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 6px; border-radius: 5px; }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .body { font-size: 13.5px; color: var(--text-2); line-height: 1.6; }
  .muted { font-size: 12px; color: var(--text-3); margin-top: 14px; line-height: 1.5; }
  .muted em { font-style: italic; color: var(--text-2); }

  .cost-row { display: flex; align-items: center; gap: 12px; margin-top: 18px; flex-wrap: wrap; }
  .cost-item {
    display: flex; flex-direction: column; gap: 3px;
    background: var(--surface-2); border: 1px solid var(--border-1);
    border-radius: var(--r-md); padding: 11px 15px; flex: 1; min-width: 120px;
  }
  .ci-k { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; }
  .ci-v { font-family: var(--font-mono); font-size: 16px; font-weight: 700; color: var(--text-1); }
  .cost-arrow { color: var(--text-3); font-size: 18px; }

  .evo { display: flex; align-items: stretch; gap: 14px; }
  .evo-col { flex: 1; }
  .evo-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700; color: var(--text-3); margin-bottom: 10px; }
  .evo-col ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .evo-col li { font-size: 12.5px; color: var(--text-1); display: flex; flex-direction: column; gap: 2px; }
  .evo-col.then s { color: var(--text-3); }
  .evo-col.now b { color: var(--accent-2); font-weight: 650; }
  .evo .ms { font-size: 11px; color: var(--text-3); }
  .evo-arrow { display: grid; place-items: center; color: var(--accent-1); font-size: 20px; }

  .layer-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 11px; }
  .lcard {
    display: flex; align-items: center; gap: 14px; text-align: left;
    background: var(--surface-2); border: 1px solid var(--border-1);
    border-radius: var(--r-md); padding: 13px 16px;
    transition: all 0.13s ease;
  }
  .lcard:hover { background: var(--surface-hover); border-color: var(--accent-line); transform: translateX(2px); }
  .lcard.flag { border-color: var(--accent-line); }
  .lbadge {
    flex-shrink: 0; min-width: 34px; height: 28px; padding: 0 7px;
    display: grid; place-items: center; border-radius: 7px;
    font-family: var(--font-mono); font-size: 12px; font-weight: 700;
    color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2));
  }
  .ltext { flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .ltitle { font-size: 13.5px; font-weight: 650; color: var(--text-1); }
  .ltag { font-size: 11.5px; color: var(--text-3); }
  .larrow { color: var(--text-3); font-size: 15px; }

  @media (max-width: 860px) {
    .threeup, .two, .layer-grid { grid-template-columns: 1fr; }
  }
</style>
