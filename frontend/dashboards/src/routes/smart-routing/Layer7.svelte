<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { evaluate, MIN_QUALITY } from '../../lib/sim/quality.js'

  let answer = $state("The capital of France is Paris. With about 2.1 million residents in the city proper, it has been the nation's capital since 987 AD and remains its political and cultural center.")
  const res = $derived(evaluate(answer))
  const escalate = $derived(res.needs_escalation || res.signals.truncated)

  const examples = [
    { label: 'Solid answer', a: "The capital of France is Paris. With about 2.1 million residents in the city proper, it has been the nation's capital since 987 AD and remains its political and cultural center." },
    { label: 'Refusal', a: "I'm sorry, but as an AI language model, I am unable to provide that information." },
    { label: 'Truncated', a: 'To merge two sorted lists you walk both with two pointers, comparing the front elements and appending the smaller one, repeating until you reach the...' },
    { label: 'Hallucination-y', a: 'According to various sources, studies show that experts say this approach is widely used, and as documented in the research, it is considered the standard method across the industry today.' },
  ]

  const COLORS = ['#6366f1', '#22d3ee', '#a78bfa', '#34d399', '#fbbf24']
  const checks = $derived([
    { k: 'Refusal', bad: res.signals.refusal_detected, val: res.signals.refusal_detected ? 'detected' : 'none' },
    { k: 'Truncation', bad: res.signals.truncated, val: res.signals.truncated ? 'detected' : 'clean' },
    { k: 'Completeness', bad: res.signals.completeness < 0.8, val: res.signals.completeness.toFixed(2) },
    { k: 'Coherence', bad: res.signals.coherence < 0.8, val: res.signals.coherence.toFixed(2) },
    { k: 'Hallucination risk', bad: res.signals.hallucination_risk > 0.3, val: res.signals.hallucination_risk.toFixed(2) },
  ])
</script>

<PageHeader
  badge="L7"
  eyebrow="Smart Routing · Layer 7"
  title="Quality Evaluation"
  tagline="Grades every answer the moment it's generated — refusals, truncation, incoherence — using only deterministic checks and heuristics. No second LLM, so the safety net that drives escalation costs nothing."
  stats={[
    { value: '$0', label: 'per evaluation', tone: 'green' },
    { value: '3', label: 'stages (judge OFF)' },
    { value: String(MIN_QUALITY), label: 'pass threshold' },
    { value: '0', label: 'judge LLM calls' },
  ]}
/>

<Card eyebrow="Live evaluator" title="Paste an answer — grade it without an LLM" glow>
  <textarea class="qinput" bind:value={answer} rows="3" spellcheck="false"></textarea>
  <div class="chips">
    {#each examples as ex}
      <button class="chip" class:on={answer === ex.a} onclick={() => (answer = ex.a)}>{ex.label}</button>
    {/each}
  </div>

  <div class="grid">
    <div class="checks">
      <div class="checks-h">Signals extracted</div>
      {#each checks as c}
        <div class="chk {c.bad ? 'bad' : 'ok'}">
          <span class="chk-dot"></span>
          <span class="chk-k">{c.k}</span>
          <span class="chk-v mono">{c.val}</span>
        </div>
      {/each}
    </div>

    <div class="score-col">
      {#if res.signals.refusal_detected}
        <div class="bigq refuse">
          <span class="bq-v">0.00</span><span class="bq-l">refusal → quality zeroed</span>
        </div>
      {:else}
        <div class="bar-h">overall_quality = validator·0.35 + heuristic·0.65</div>
        <div class="stack">
          {#each res.components as c, i}
            <div class="seg" style="width:{c.raw * c.weight * 100}%; background:{COLORS[i % COLORS.length]}" title="{c.label}"></div>
          {/each}
        </div>
        <div class="bigq">
          <span class="bq-v">{res.overall.toFixed(2)}</span>
          <span class="bq-l">overall quality</span>
        </div>
      {/if}

      <div class="verdict {escalate ? 'esc' : 'pass'}">
        {escalate ? '→ escalate to a stronger model' : '✓ passes — ship the answer'}
      </div>
      <div class="cost">
        <span class="cdot"></span> evaluated with regex + parsing only · <b>no LLM call</b>
      </div>
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The three stages" title="Why it's free">
    <div class="stage">
      <span class="sn">1</span>
      <div><b>Deterministic validators</b><span>JSON parses? code compiles? schema valid? Real correctness for structured output.</span></div>
    </div>
    <div class="stage">
      <span class="sn">2</span>
      <div><b>Heuristics</b><span>Refusal / truncation / coherence / hallucination regexes — plausibility, no model.</span></div>
    </div>
    <div class="stage off">
      <span class="sn">3</span>
      <div><b><s>LLM judge</s> — deliberately OFF</b><span>A cost-optimising router must not add a per-query LLM call. <code>evaluate()</code> is invoked without it.</span></div>
    </div>
  </Card>

  <Card eyebrow="Why it's strong" title="The founding principle, enforced">
    <p class="body2">
      The entire point of this router is to <strong>avoid per-query LLM calls</strong>. A quality gate
      that called a judge model would re-introduce exactly the cost the kNN design removes. So the
      signal that decides whether to escalate is built from things you can compute for free — and
      it's still enough to catch the failures that matter: a refusal, a cut-off answer, broken JSON.
    </p>
    <div class="hardflags">
      <span class="hf-h">hard escalation triggers</span>
      <Pill tone="red">refusal</Pill><Pill tone="red">truncation</Pill><Pill tone="amber">below threshold</Pill>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="The trigger Layer 8 reads">
  <p class="body">
    Layer 7 doesn't change the answer — it judges it. Its <code>QualityScore</code> (overall quality,
    refusal flag, truncation flag) is the signal Layer 8's escalation ladder consumes: if the cheap
    model's answer fails any of these checks, the request climbs to a stronger model and retries.
    Because that judgement is free, the router can afford to apply it to <strong>every</strong> answer,
    not just a sample.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-7" />

<style>
  .qinput { width: 100%; resize: vertical; background: var(--bg-1); border: 1px solid var(--border-2); border-radius: var(--r-md); padding: 13px 15px; color: var(--text-1); font-size: 14px; font-family: var(--font-mono); outline: none; line-height: 1.5; transition: border-color 0.15s, box-shadow 0.15s; }
  .qinput:focus { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-soft); }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .chip { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-pill); padding: 5px 11px; font-size: 12px; transition: all 0.12s; }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
  .checks { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 14px 16px; }
  .checks-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .chk { display: flex; align-items: center; gap: 11px; padding: 9px 0; border-bottom: 1px solid var(--border-1); }
  .chk:last-child { border-bottom: none; }
  .chk-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .chk.ok .chk-dot { background: var(--green); }
  .chk.bad .chk-dot { background: var(--red); box-shadow: 0 0 8px var(--red); }
  .chk-k { flex: 1; font-size: 13px; color: var(--text-2); }
  .chk.bad .chk-k { color: var(--text-1); }
  .chk-v { font-size: 12px; }
  .chk.ok .chk-v { color: var(--text-3); }
  .chk.bad .chk-v { color: var(--red); }

  .score-col { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 16px; display: flex; flex-direction: column; }
  .bar-h { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); margin-bottom: 8px; }
  .stack { display: flex; height: 14px; border-radius: 5px; overflow: hidden; background: var(--surface-2); gap: 1px; }
  .bigq { display: flex; align-items: baseline; gap: 10px; margin: 14px 0; }
  .bq-v { font-family: var(--font-mono); font-size: 38px; font-weight: 760; background: linear-gradient(95deg, var(--accent-1), var(--accent-2)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
  .bigq.refuse .bq-v { background: none; -webkit-text-fill-color: var(--red); color: var(--red); }
  .bq-l { font-size: 12px; color: var(--text-3); }
  .verdict { padding: 11px 14px; border-radius: var(--r-md); font-size: 13.5px; font-weight: 600; text-align: center; }
  .verdict.pass { background: var(--green-soft); color: var(--green); border: 1px solid color-mix(in srgb, var(--green) 35%, transparent); }
  .verdict.esc { background: var(--amber-soft); color: var(--amber); border: 1px solid color-mix(in srgb, var(--amber) 35%, transparent); }
  .cost { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 11.5px; color: var(--text-3); }
  .cost b { color: var(--green); }
  .cdot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .stage { display: flex; gap: 12px; padding: 11px 0; border-bottom: 1px solid var(--border-1); }
  .stage:last-child { border-bottom: none; }
  .stage.off { opacity: 0.72; }
  .sn { flex-shrink: 0; width: 22px; height: 22px; border-radius: 6px; display: grid; place-items: center; font-family: var(--font-mono); font-weight: 700; font-size: 12px; color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); }
  .stage.off .sn { background: var(--surface-3); color: var(--text-3); }
  .stage div { display: flex; flex-direction: column; gap: 2px; }
  .stage b { font-size: 13px; color: var(--text-1); }
  .stage span { font-size: 12px; color: var(--text-3); line-height: 1.45; }
  code { font-family: var(--font-mono); font-size: 0.9em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 5px; border-radius: 4px; }

  .body2 { font-size: 13.5px; color: var(--text-2); line-height: 1.6; margin-bottom: 14px; }
  .body2 strong { color: var(--text-1); }
  .hardflags { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
  .hf-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-3); margin-right: 4px; }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .grid, .two { grid-template-columns: 1fr; } }
</style>
