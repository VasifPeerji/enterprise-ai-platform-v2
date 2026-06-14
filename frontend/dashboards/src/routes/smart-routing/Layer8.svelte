<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { QUALIFYING, buildLadder, runScenario, SCENARIOS, MAX_LEVELS } from '../../lib/sim/escalation.js'

  let scenarioIdx = $state(2)
  let rateLimit = $state(false)

  const cooled = $derived(rateLimit ? new Set(['qwen3-32b']) : new Set())
  const ladder = $derived(buildLadder(QUALIFYING, 'gpt-oss-20b', cooled))
  const run = $derived(runScenario(ladder, SCENARIOS[scenarioIdx]))
  const sorted = [...QUALIFYING].sort((a, b) => a.size - b.size)

  const display = $derived(sorted.map((m) => {
    const li = ladder.findIndex((l) => l.id === m.id)
    if (li >= 0) {
      const step = run.steps[li]
      return { m, kind: li === 0 ? 'start' : 'rung', status: step.status, reason: step.reason, attempt: li + 1 }
    }
    if (!m.active) return { m, kind: 'skip', why: 'keyless — would fall back to free' }
    if (cooled.has(m.id)) return { m, kind: 'skip', why: 'rate-limited — cooling down' }
    return { m, kind: 'beyond', why: 'beyond max escalation' }
  }))
</script>

<PageHeader
  badge="L8"
  eyebrow="Smart Routing · Layer 8"
  title="Escalation Ladder"
  tagline="The recovery path. When Layer 7 says the cheap model's answer failed, the request climbs — one rung at a time — to a stronger model from the same qualifying set, and retries. Never downward, never to a model that can't run, capped at three steps."
  stats={[
    { value: String(MAX_LEVELS), label: 'max escalations', tone: 'accent' },
    { value: '$0', label: 'trigger cost', tone: 'green' },
    { value: 'active', label: 'only climbs to executable' },
    { value: '↑', label: 'never downward' },
  ]}
/>

<Card eyebrow="Live ladder" title="Pick a scenario — watch the request climb" glow>
  <div class="controls">
    <div class="seg">
      {#each SCENARIOS as s, i}
        <button class:on={scenarioIdx === i} onclick={() => (scenarioIdx = i)}>{s.label}</button>
      {/each}
    </div>
    <label class="tog"><input type="checkbox" bind:checked={rateLimit} /> <span>rate-limit Qwen3 32B</span></label>
  </div>

  <div class="ladder">
    {#key scenarioIdx + (rateLimit ? 'r' : '')}
      {#each display as row, i}
        <div class="rung {row.kind} {row.status || ''}" style="animation-delay:{i * 60}ms">
          <div class="rail">
            <span class="node">
              {#if row.kind === 'start'}▶{:else if row.status === 'pass'}✓{:else if row.status === 'fail'}✗{:else if row.kind === 'skip'}⊘{:else}·{/if}
            </span>
          </div>
          <div class="rbody">
            <div class="line1">
              <span class="mname">{row.m.label}</span>
              <span class="msize mono">{row.m.size === 999 ? 'premium' : row.m.size + 'B'}</span>
              {#if row.kind === 'start'}<Pill tone="accent">Layer 3 pick · attempt 1</Pill>{/if}
              {#if row.status === 'fail'}<Pill tone="red">attempt {row.attempt} · {row.reason}</Pill>{/if}
              {#if row.status === 'pass'}<Pill tone="green">attempt {row.attempt} · answered ✓</Pill>{/if}
              {#if row.kind === 'skip'}<Pill tone="neutral">skipped</Pill>{/if}
            </div>
            {#if row.kind === 'skip'}<div class="why">{row.why}</div>{/if}
            {#if row.kind === 'beyond'}<div class="why">{row.why}</div>{/if}
          </div>
        </div>
      {/each}
    {/key}
  </div>

  <div class="summary {run.halted ? 'halt' : 'ok'}">
    {#if run.halted}
      <span class="s-label">HALTED AT CAP</span>
      <span class="s-text">All {MAX_LEVELS} escalations exhausted — returns the best answer so far ({run.finalModel}) rather than looping forever.</span>
    {:else if run.escalations === 0}
      <span class="s-label">NO ESCALATION</span>
      <span class="s-text">First answer passed Layer 7 — shipped from {run.finalModel} in a single attempt.</span>
    {:else}
      <span class="s-label">RESOLVED</span>
      <span class="s-text">{run.escalations} escalation{run.escalations > 1 ? 's' : ''} → answered by {run.finalModel} after {run.attempts} attempts.</span>
    {/if}
  </div>
</Card>

<div class="two">
  <Card eyebrow="How the ladder is built" title="path_from_qualifiers">
    <p class="body2">
      The rungs aren't a generic list of big models — they're <strong>Layer 3's own qualifying set</strong>,
      cost-sorted. Escalation reuses the work the router already did.
    </p>
    <div class="rules">
      <div class="rule"><span class="rc">▲</span> start at the selected pick, climb to <b>more expensive</b> qualifiers</div>
      <div class="rule"><span class="rc">●</span> only <b>active</b> models — climbing to a keyless one would just fall back</div>
      <div class="rule"><span class="rc">⊘</span> skip models that are <b>rate-limited / cooling down</b></div>
      <div class="rule"><span class="rc">↓</span> <b>never</b> downward — escalation only ever increases capability</div>
      <div class="rule"><span class="rc">■</span> cap at <b>{MAX_LEVELS}</b> levels, then return the best answer so far</div>
    </div>
  </Card>

  <Card eyebrow="Why it's strong" title="A free trigger, a bounded climb">
    <p class="body2">
      The decision to escalate comes entirely from <strong>Layer 7's cost-free signal</strong> — a
      refusal, a truncation, a sub-threshold score. There's no judge model deciding whether to retry,
      so the safety net adds no per-query LLM cost.
    </p>
    <p class="body2">
      And because the climb is bounded and monotonic, a hard query can't spiral: it gets at most a few
      escalations to genuinely stronger models, then ships the best result. Most queries never escalate
      at all — the cheap model was right the first time.
    </p>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="Cheap by default, strong when it has to be">
  <p class="body">
    Layers 3 and 7 let the router be optimistic: route to the cheapest model that should work, ship if
    it does. Layer 8 is the insurance that makes that optimism safe. When the cheap answer fails, the
    user still gets a correct one — from a stronger model — without the router having paid for that
    model on every query. It's how the system stays cheap on average while staying correct in the worst
    case.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-8" />

<style>
  .controls { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
  .seg { display: flex; flex-wrap: wrap; gap: 6px; }
  .seg button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 7px 13px; font-size: 12.5px; transition: all 0.12s; }
  .seg button:hover { background: var(--surface-hover); }
  .seg button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }
  .tog { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
  .tog input { accent-color: var(--accent-1); }

  .ladder { display: flex; flex-direction: column; }
  .rung { display: flex; gap: 16px; animation: fade-up 0.3s ease both; }
  .rail { position: relative; width: 36px; flex-shrink: 0; display: flex; justify-content: center; }
  .rail::before { content: ''; position: absolute; top: 0; bottom: 0; left: 50%; width: 2px; transform: translateX(-50%); background: var(--border-1); }
  .rung:first-child .rail::before { top: 20px; }
  .rung:last-child .rail::before { bottom: calc(100% - 20px); }
  .node { position: relative; z-index: 1; margin-top: 6px; width: 32px; height: 32px; display: grid; place-items: center; border-radius: 9px; font-size: 14px; font-weight: 700; background: var(--surface-3); border: 1px solid var(--border-2); color: var(--text-3); }
  .rung.start .node { background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); color: var(--text-on-accent); border-color: transparent; }
  .rung.pass .node { background: linear-gradient(135deg, var(--green), #10b981); color: #04140d; border-color: transparent; box-shadow: 0 0 0 4px var(--green-soft); }
  .rung.fail .node { background: linear-gradient(135deg, var(--red), #ef4444); color: #fff; border-color: transparent; }
  .rung.skip { opacity: 0.5; }
  .rung.skip .node { border-style: dashed; }
  .rung.beyond { opacity: 0.4; }

  .rbody { padding: 8px 0 18px; }
  .line1 { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .mname { font-size: 14.5px; font-weight: 650; color: var(--text-1); }
  .rung.skip .mname, .rung.beyond .mname { color: var(--text-3); }
  .msize { font-size: 11.5px; color: var(--text-3); }
  .why { font-size: 12px; color: var(--text-3); margin-top: 3px; }

  .summary { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; padding: 15px 18px; border-radius: var(--r-md); border: 1px solid var(--border-2); background: var(--surface-2); }
  .summary.ok { background: var(--accent-soft); border-color: var(--accent-line); }
  .summary.halt { background: var(--amber-soft); border-color: color-mix(in srgb, var(--amber) 40%, transparent); }
  .s-label { font-family: var(--font-mono); font-size: 12px; font-weight: 700; letter-spacing: 0.06em; color: var(--accent-2); }
  .summary.halt .s-label { color: var(--amber); }
  .s-text { font-size: 13px; color: var(--text-2); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .body2 { font-size: 13.5px; color: var(--text-2); line-height: 1.6; margin-bottom: 12px; }
  .body2 strong { color: var(--text-1); }
  .rules { display: flex; flex-direction: column; gap: 9px; }
  .rule { display: flex; align-items: baseline; gap: 11px; font-size: 12.5px; color: var(--text-2); }
  .rule b { color: var(--text-1); }
  .rc { flex-shrink: 0; width: 16px; text-align: center; color: var(--accent-2); }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
</style>
