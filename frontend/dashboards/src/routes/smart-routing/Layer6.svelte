<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { decide, BANDS, TASKS, STRATEGIES } from '../../lib/sim/ttc.js'

  let uncertainty = $state(0.5)
  let band = $state('complex')
  let taskIdx = $state(2) // Coding
  let tier = $state('free')

  const task = $derived(TASKS[taskIdx])
  const d = $derived(decide({ uncertainty, band, tier, task_type: task.task_type, intent: task.intent }))

  // representative samples for the strategy diagram
  const bestOfN = [0.71, 0.86, 0.79, 0.83]
  const consistency = ['42', '42', '37', '42']
</script>

<PageHeader
  badge="L6"
  eyebrow="Smart Routing · Layer 6"
  title="Test-Time Compute"
  tagline="Spend more compute only where it actually helps. When a query sits in the uncertain middle — not trivial, not hopeless — the engine samples a few times and picks the best, instead of trusting a single shot."
  stats={[
    { value: '0.4–0.6', label: 'activation window', tone: 'accent' },
    { value: '3', label: 'strategies' },
    { value: 'OFF', label: 'by default' },
    { value: '2–3', label: 'samples when on' },
  ]}
/>

<Card eyebrow="Decision explorer" title="Tune the inputs — see if extra compute is worth it" glow>
  <div class="explorer">
    <div class="controls">
      <div class="ctl">
        <div class="ctl-h"><span>Uncertainty</span><b>{uncertainty.toFixed(2)}</b></div>
        <div class="gauge">
          <div class="window"></div>
          <input class="slider" type="range" min="0" max="1" step="0.01" bind:value={uncertainty} />
        </div>
        <div class="gauge-labels"><span>single sample</span><span class="win-l">TTC zone</span><span>escalate</span></div>
      </div>

      <div class="ctl">
        <div class="ctl-h"><span>Complexity band</span></div>
        <div class="seg">
          {#each BANDS as b}
            <button class:on={band === b} onclick={() => (band = b)}>{b}</button>
          {/each}
        </div>
      </div>

      <div class="ctl">
        <div class="ctl-h"><span>Task type</span></div>
        <div class="seg">
          {#each TASKS as t, i}
            <button class:on={taskIdx === i} onclick={() => (taskIdx = i)}>{t.label}</button>
          {/each}
        </div>
      </div>

      <div class="ctl row">
        <div class="ctl-h"><span>User tier</span></div>
        <div class="seg sm">
          <button class:on={tier === 'free'} onclick={() => (tier = 'free')}>free</button>
          <button class:on={tier === 'premium'} onclick={() => (tier = 'premium')}>premium</button>
        </div>
      </div>
    </div>

    <div class="outcome">
      <div class="verdict {d.should_use ? 'on' : 'off'}">
        <span class="vlabel">{d.should_use ? 'TTC ENGAGED' : 'SINGLE SAMPLE'}</span>
        <span class="vsub">{d.should_use ? `${STRATEGIES[d.strategy].name} · ${d.num_samples} samples` : 'no extra compute'}</span>
      </div>
      <p class="reason">{d.reason}</p>

      {#if d.should_use}
        <div class="strat">
          <div class="strat-h">{STRATEGIES[d.strategy].name}</div>
          {#if d.strategy === 'best_of_n'}
            <div class="samples">
              {#each bestOfN.slice(0, d.num_samples) as q, i}
                {@const best = q === Math.max(...bestOfN.slice(0, d.num_samples))}
                <div class="samp {best ? 'best' : ''}">
                  <span class="s-n">S{i + 1}</span><span class="s-q">{q.toFixed(2)}</span>
                  {#if best}<span class="s-tag">kept</span>{/if}
                </div>
              {/each}
            </div>
            <div class="strat-note">→ highest quality wins</div>
          {:else if d.strategy === 'self_consistency'}
            <div class="samples">
              {#each consistency.slice(0, d.num_samples) as a, i}
                {@const maj = a === '42'}
                <div class="samp {maj ? 'best' : ''}">
                  <span class="s-n">S{i + 1}</span><span class="s-q">{a}</span>
                </div>
              {/each}
            </div>
            <div class="strat-note">→ majority answer wins (consensus {consistency.slice(0, d.num_samples).filter((a) => a === '42').length}/{d.num_samples})</div>
          {:else}
            <div class="chain">
              <div class="cstep">generate</div><span class="carr">→</span>
              <div class="cstep fail">verify ✗</div><span class="carr">→</span>
              <div class="cstep">regenerate</div><span class="carr">→</span>
              <div class="cstep ok">verify ✓</div>
            </div>
            <div class="strat-note">→ verified answer (≤ {d.num_samples} attempts)</div>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The three strategies" title="Matched to the task">
    {#each Object.entries(STRATEGIES) as [key, s]}
      <div class="sref" class:active={d.should_use && d.strategy === key}>
        <div class="sref-h"><b>{s.name}</b><Pill tone="neutral">{s.best_for}</Pill></div>
        <p>{s.blurb}</p>
      </div>
    {/each}
  </Card>

  <Card eyebrow="Why it's strong" title="Selective by design">
    <p class="body2">
      Extra samples cost extra latency, so TTC refuses to fire unless it will help. It skips the
      <strong>trivial</strong> (a single shot is fine), bows out of the <strong>truly hard</strong>
      (escalate to a better model instead), and only engages the uncertain middle where a second look
      changes the answer.
    </p>
    <div class="rules">
      <div class="rule"><span class="rx">✗</span> uncertainty &lt; 0.4 — too confident</div>
      <div class="rule"><span class="rx">✗</span> uncertainty &gt; 0.6 — escalate instead</div>
      <div class="rule"><span class="rx">✗</span> trivial / simple / expert bands</div>
      <div class="rule"><span class="rc">✓</span> moderate / complex, uncertainty 0.4–0.6</div>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="A quality boost the router can afford">
  <p class="body">
    Layer 6 sits at the start of the execution loop, after the router has picked a model. For most
    queries it does nothing — the single answer ships. But on the uncertain ones it quietly turns one
    attempt into the best of a few, lifting correctness exactly where the router was least sure,
    without ever paying that cost on the queries that don't need it.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-6" />

<style>
  .explorer { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .controls { display: flex; flex-direction: column; gap: 18px; }
  .ctl-h { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 9px; font-size: 12px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; }
  .ctl-h b { font-family: var(--font-mono); font-size: 15px; color: var(--accent-2); }

  .gauge { position: relative; height: 28px; }
  .window { position: absolute; left: 40%; width: 20%; top: 9px; height: 10px; background: var(--green-soft); border: 1px solid var(--green); border-radius: 4px; }
  .slider { position: relative; width: 100%; margin: 0; -webkit-appearance: none; appearance: none; height: 28px; background: transparent; cursor: pointer; }
  .slider::-webkit-slider-runnable-track { height: 4px; background: var(--surface-3); border-radius: 2px; margin-top: 12px; }
  .slider::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: var(--accent-2); margin-top: 6px; box-shadow: 0 0 0 4px var(--accent-soft); }
  .gauge-labels { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-3); margin-top: 2px; }
  .win-l { color: var(--green); }

  .seg { display: flex; flex-wrap: wrap; gap: 6px; }
  .seg button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 6px 12px; font-size: 12.5px; transition: all 0.12s; }
  .seg button:hover { background: var(--surface-hover); }
  .seg button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .outcome { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 18px; }
  .verdict { display: flex; flex-direction: column; gap: 2px; padding: 14px 16px; border-radius: var(--r-md); margin-bottom: 12px; }
  .verdict.on { background: var(--green-soft); border: 1px solid color-mix(in srgb, var(--green) 40%, transparent); }
  .verdict.off { background: var(--surface-2); border: 1px solid var(--border-2); }
  .vlabel { font-family: var(--font-mono); font-size: 19px; font-weight: 740; }
  .verdict.on .vlabel { color: var(--green); }
  .verdict.off .vlabel { color: var(--text-2); }
  .vsub { font-size: 12px; color: var(--text-3); }
  .reason { font-size: 13px; color: var(--text-2); line-height: 1.5; }

  .strat { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border-1); }
  .strat-h { font-size: 12px; color: var(--accent-2); font-weight: 650; margin-bottom: 12px; }
  .samples { display: flex; gap: 9px; flex-wrap: wrap; }
  .samp { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 10px 14px; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-sm); position: relative; }
  .samp.best { border-color: var(--accent-line); background: var(--accent-soft); }
  .s-n { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); }
  .s-q { font-size: 15px; font-weight: 700; color: var(--text-1); font-family: var(--font-mono); }
  .s-tag { position: absolute; top: -8px; right: -6px; font-size: 9px; background: var(--accent-2); color: var(--text-on-accent); padding: 1px 5px; border-radius: 4px; font-weight: 700; }
  .strat-note { font-size: 12px; color: var(--text-3); margin-top: 10px; }
  .chain { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .cstep { padding: 7px 12px; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-sm); font-size: 12px; color: var(--text-2); }
  .cstep.fail { border-color: color-mix(in srgb, var(--red) 40%, transparent); color: var(--red); }
  .cstep.ok { border-color: color-mix(in srgb, var(--green) 40%, transparent); color: var(--green); }
  .carr { color: var(--text-3); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .sref { padding: 11px 0; border-bottom: 1px solid var(--border-1); }
  .sref:last-child { border-bottom: none; }
  .sref.active { background: var(--accent-soft); margin: 0 -22px; padding: 11px 22px; border-radius: 8px; border-bottom-color: transparent; }
  .sref-h { display: flex; align-items: center; gap: 10px; margin-bottom: 5px; }
  .sref-h b { font-size: 13.5px; color: var(--text-1); }
  .sref p { font-size: 12.5px; color: var(--text-3); line-height: 1.5; }

  .body2 { font-size: 13.5px; color: var(--text-2); line-height: 1.6; margin-bottom: 14px; }
  .body2 strong { color: var(--text-1); }
  .rules { display: flex; flex-direction: column; gap: 8px; }
  .rule { display: flex; align-items: center; gap: 9px; font-size: 12.5px; color: var(--text-2); font-family: var(--font-mono); }
  .rx { color: var(--red); font-weight: 700; }
  .rc { color: var(--green); font-weight: 700; }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .explorer, .two { grid-template-columns: 1fr; } }
</style>
