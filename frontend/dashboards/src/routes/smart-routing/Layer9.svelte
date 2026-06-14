<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { driftScan, THRESHOLDS, TELEMETRY, BINS } from '../../lib/sim/drift.js'

  let drift = $state(0.0)
  const scan = $derived(driftScan(drift))

  const maxSrc = Math.max(...TELEMETRY.routing_source.map((s) => s.count))
  const histMax = $derived(Math.max(...scan.reference, ...scan.recent))

  const levelTone = { stable: 'green', info: 'blue', warn: 'amber', halt: 'red' }
  const levelText = {
    stable: 'distribution stable — calibration keeps learning',
    info: 'minor shift — logged, no action',
    warn: 'notable shift — watching closely',
    halt: 'major shift — calibration FROZEN for this model',
  }
</script>

<PageHeader
  badge="L9"
  eyebrow="Smart Routing · Layer 9"
  title="Telemetry & Drift"
  tagline="The observability layer. Every routing decision is logged with its source, predicted quality and confidence; a drift detector then watches each model's prediction distribution and freezes its online calibration the moment the world shifts under it."
  stats={[
    { value: '10k', label: 'event buffer' },
    { value: '0.30', label: 'KL halt threshold', tone: 'accent' },
    { value: '4', label: 'Layer-3 fields logged' },
    { value: '$0', label: 'pure stats, offline' },
  ]}
/>

<div class="two">
  <Card eyebrow="Telemetry" title="Live routing buffer">
    <div class="tstats">
      <div class="ts"><span class="tv">{TELEMETRY.buffer_size}</span><span class="tl">events</span></div>
      <div class="ts"><span class="tv">{(TELEMETRY.escalation_rate * 100).toFixed(0)}%</span><span class="tl">escalated</span></div>
      <div class="ts"><span class="tv">{TELEMETRY.avg_quality.toFixed(2)}</span><span class="tl">avg quality</span></div>
      <div class="ts"><span class="tv">{TELEMETRY.avg_latency_ms}ms</span><span class="tl">avg latency</span></div>
    </div>
    <div class="src-h">Routing-source mix</div>
    <div class="srcs">
      {#each TELEMETRY.routing_source as s}
        <div class="src">
          <span class="src-k">{s.source}</span>
          <div class="src-bar"><span style="width:{(s.count / maxSrc) * 100}%"></span></div>
          <span class="src-v mono">{s.count}</span>
        </div>
      {/each}
    </div>
  </Card>

  <Card eyebrow="Per-request record" title="What every route logs">
    <p class="body2">Each decision is fire-and-forget logged with the four signals the kNN router produces — the raw material drift detection and offline analysis run on.</p>
    <div class="fields">
      <div class="fld"><b>routing_source</b><span>knn_corpus · fast_path · cache_hit · fallback</span></div>
      <div class="fld"><b>predicted_quality</b><span>the model's expected score for this query</span></div>
      <div class="fld"><b>prediction_confidence</b><span>coverage × agreement × proximity</span></div>
      <div class="fld"><b>uncertainty_escalated</b><span>did risk-aware escalation fire?</span></div>
    </div>
  </Card>
</div>

<Card eyebrow="Live drift detector" title="Drag the world out from under a model — watch calibration freeze" glow>
  <p class="lede">
    The detector compares a model's <strong>recent</strong> predicted-quality distribution against an
    earlier <strong>reference</strong> window using KL divergence. Push the recent window down and
    watch the divergence climb past the thresholds.
  </p>

  <div class="drift-grid">
    <div class="hist-wrap">
      <div class="hist">
        {#each scan.reference as ref, i}
          <div class="bin">
            <span class="bar-ref" style="height:{(ref / histMax) * 100}%"></span>
            <span class="bar-rec" style="height:{(scan.recent[i] / histMax) * 100}%"></span>
          </div>
        {/each}
      </div>
      <div class="hist-x"><span>0.0</span><span>predicted quality</span><span>1.0</span></div>
      <div class="hist-legend">
        <span><i class="lg-ref"></i>reference window</span>
        <span><i class="lg-rec"></i>recent window</span>
      </div>
      <div class="slider-row">
        <span class="sl-l">drift</span>
        <input class="slider" type="range" min="0" max="0.5" step="0.01" bind:value={drift} />
        <span class="sl-v mono">−{drift.toFixed(2)}</span>
      </div>
    </div>

    <div class="kl-col">
      <div class="kl-num {scan.level}">{scan.kl.toFixed(3)}</div>
      <div class="kl-l">KL divergence</div>
      <div class="thr">
        <div class="thr-row {scan.kl >= THRESHOLDS.info ? 'hit' : ''}"><span>info</span><b>≥ {THRESHOLDS.info}</b></div>
        <div class="thr-row {scan.kl >= THRESHOLDS.warn ? 'hit' : ''}"><span>warn</span><b>≥ {THRESHOLDS.warn}</b></div>
        <div class="thr-row {scan.kl >= THRESHOLDS.halt ? 'hit' : ''}"><span>halt</span><b>≥ {THRESHOLDS.halt}</b></div>
      </div>
      <div class="level {scan.level}">
        <Pill tone={levelTone[scan.level]} dot>{scan.level.toUpperCase()}</Pill>
        <span class="level-t">{levelText[scan.level]}</span>
      </div>
      {#if scan.level === 'halt'}
        <div class="freeze">❄ calibration.freeze("gpt-oss-120b")</div>
      {/if}
    </div>
  </div>
</Card>

<Card eyebrow="How it shapes the final output" title="Closing the loop without chasing noise">
  <p class="body">
    Layer 9 is what lets the router <strong>learn safely</strong>. Online calibration nudges each
    model's predictions toward observed reality — but only while reality is stationary. When a
    provider swaps a model or traffic shifts, the prediction distribution drifts, and a naive learner
    would chase the noise and corrupt itself. The drift detector catches that shift and
    <strong>freezes calibration</strong> for the affected model, holding the last good state until
    things settle. Pure statistics, computed offline from the telemetry buffer — no model calls, no
    cost.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-9" />

<style>
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .tstats { display: flex; gap: 22px; flex-wrap: wrap; margin-bottom: 18px; }
  .ts { display: flex; flex-direction: column; }
  .tv { font-family: var(--font-mono); font-size: 22px; font-weight: 720; color: var(--text-1); }
  .tl { font-size: 11px; color: var(--text-3); }
  .src-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .srcs { display: flex; flex-direction: column; gap: 8px; }
  .src { display: grid; grid-template-columns: 100px 1fr 34px; align-items: center; gap: 10px; }
  .src-k { font-size: 12px; color: var(--text-2); font-family: var(--font-mono); }
  .src-bar { height: 12px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .src-bar span { display: block; height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--accent-1), var(--accent-2)); }
  .src-v { font-size: 12px; color: var(--text-1); text-align: right; }

  .body2 { font-size: 13px; color: var(--text-2); line-height: 1.55; margin-bottom: 14px; }
  .fields { display: flex; flex-direction: column; gap: 9px; }
  .fld { display: flex; flex-direction: column; gap: 1px; padding-bottom: 8px; border-bottom: 1px solid var(--border-1); }
  .fld:last-child { border-bottom: none; }
  .fld b { font-size: 12.5px; color: var(--accent-2); font-family: var(--font-mono); }
  .fld span { font-size: 11.5px; color: var(--text-3); }

  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 18px; }
  .lede strong { color: var(--text-1); }
  .drift-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 22px; }

  .hist { display: flex; align-items: flex-end; gap: 4px; height: 180px; padding: 10px 6px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); }
  .bin { position: relative; flex: 1; height: 100%; display: flex; align-items: flex-end; justify-content: center; }
  .bar-ref { position: absolute; bottom: 0; width: 100%; background: var(--surface-3); border: 1px solid var(--border-2); border-radius: 3px 3px 0 0; transition: height 0.2s ease; }
  .bar-rec { position: relative; width: 58%; background: linear-gradient(180deg, var(--accent-2), var(--accent-1)); border-radius: 3px 3px 0 0; transition: height 0.2s ease; }
  .hist-x { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-3); margin-top: 6px; }
  .hist-legend { display: flex; gap: 16px; margin-top: 10px; }
  .hist-legend span { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-3); }
  .lg-ref { width: 11px; height: 11px; border-radius: 3px; background: var(--surface-3); border: 1px solid var(--border-2); }
  .lg-rec { width: 11px; height: 11px; border-radius: 3px; background: var(--accent-2); }
  .slider-row { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
  .sl-l { font-size: 12px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; }
  .slider { flex: 1; -webkit-appearance: none; appearance: none; height: 4px; background: var(--surface-3); border-radius: 2px; cursor: pointer; }
  .slider::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: var(--accent-2); box-shadow: 0 0 0 4px var(--accent-soft); }
  .sl-v { font-size: 13px; color: var(--accent-2); }

  .kl-col { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 18px; display: flex; flex-direction: column; }
  .kl-num { font-family: var(--font-mono); font-size: 40px; font-weight: 760; line-height: 1; color: var(--text-1); }
  .kl-num.info { color: var(--blue); }
  .kl-num.warn { color: var(--amber); }
  .kl-num.halt { color: var(--red); }
  .kl-l { font-size: 12px; color: var(--text-3); margin-top: 2px; margin-bottom: 14px; }
  .thr { display: flex; flex-direction: column; gap: 4px; margin-bottom: 14px; }
  .thr-row { display: flex; justify-content: space-between; padding: 5px 9px; border-radius: 6px; font-size: 12px; color: var(--text-3); font-family: var(--font-mono); background: var(--surface-2); opacity: 0.6; }
  .thr-row.hit { opacity: 1; color: var(--text-1); background: var(--surface-3); }
  .level { display: flex; flex-direction: column; gap: 6px; }
  .level-t { font-size: 12px; color: var(--text-2); line-height: 1.4; }
  .freeze { margin-top: 12px; padding: 9px 12px; background: var(--red-soft); border: 1px solid color-mix(in srgb, var(--red) 40%, transparent); border-radius: var(--r-sm); font-family: var(--font-mono); font-size: 12px; color: var(--red); }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .two, .drift-grid { grid-template-columns: 1fr; } }
</style>
