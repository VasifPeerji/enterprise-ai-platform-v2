<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { lookup, isReusable, GUARD_DEFS, CFG, scrubPII } from '../../lib/sim/memory.js'

  const cache = [
    { query: 'How do I sort a list of numbers in Python?', model: 'gpt-oss-20b', quality: 0.92, intent: 'coding', escalated: false },
    { query: 'How do I install the numpy package using pip?', model: 'llama-3.1-8b', quality: 0.88, intent: 'coding', escalated: false },
    { query: 'What is the capital city of France?', model: 'llama-3.1-8b', quality: 0.9, intent: 'factual', escalated: false },
    { query: 'How do I fix a TypeError when indexing into a list?', model: 'qwen-2.5-72b', quality: 0.86, intent: 'debugging', escalated: false },
  ]

  let q = $state('How do I sort a list of numbers in Python 3?')
  const res = $derived(lookup(q, cache))

  const examples = [
    { label: 'Near-duplicate → HIT', q: 'How do I sort a list of numbers in Python 3?' },
    { label: 'install → uninstall', q: 'How do I uninstall the numpy package using pip?' },
    { label: 'France → Japan', q: 'What is the capital city of Japan?' },
    { label: 'TypeError → ValueError', q: 'How do I fix a ValueError when indexing into a list?' },
    { label: 'Unrelated', q: 'Write a short poem about the autumn rain' },
  ]

  const verdictTone = $derived(res.verdict === 'HIT' ? 'green' : res.verdict === 'GUARD' ? 'amber' : 'neutral')
  const piiDemo = scrubPII('email the invoice to alice@acme.com or call 415-555-0199')
</script>

<PageHeader
  badge="L2"
  eyebrow="Smart Routing · Layer 2"
  title="Semantic Memory"
  tagline="An outcome-aware cache between the gate and the router. If a near-identical query was answered well before, reuse that decision — but only after six correctness guards confirm the meaning really matches."
  stats={[
    { value: '0.85', label: 'similarity threshold', tone: 'accent' },
    { value: '6', label: 'correctness guards' },
    { value: '+41pp', label: 'F1 over heuristic', tone: 'green' },
    { value: '~117ms', label: 'saved per hit' },
    { value: '7d', label: 'decay half-life' },
  ]}
/>

<Card eyebrow="Live cache lookup" title="Look up a query — see what hits and what a guard kills" glow>
  <p class="lede">
    The cache below is pre-populated. Type a lookup (or pick an example): the layer finds the most
    similar entry, then runs the guards. High similarity alone isn't enough — a flipped meaning is
    rejected even at 0.9+ similarity.
  </p>

  <div class="cache">
    <div class="cache-h">Cached decisions</div>
    {#each cache as e}
      {@const r = isReusable(e)}
      <div class="centry" class:matched={res.matched === e}>
        <span class="cq">{e.query}</span>
        <span class="cmeta">
          <Pill tone="neutral" mono>{e.model}</Pill>
          <Pill tone={e.quality >= 0.85 ? 'green' : 'amber'} mono>q {e.quality}</Pill>
          <Pill tone="neutral" mono>{e.intent}</Pill>
          <span class="ttl">{r.ttl}</span>
        </span>
      </div>
    {/each}
  </div>

  <input class="qinput" bind:value={q} spellcheck="false" placeholder="Look up a query…" />
  <div class="chips">
    {#each examples as ex}
      <button class="chip" class:on={q === ex.q} onclick={() => (q = ex.q)}>{ex.label}</button>
    {/each}
  </div>

  <div class="result-grid">
    <div class="verdict-col">
      <div class="verdict {verdictTone}">
        <span class="vlabel">{res.verdict === 'GUARD' ? 'GUARD REJECTED' : res.verdict}</span>
        <span class="vsub">
          {#if res.verdict === 'HIT'}reuses cached model — full pipeline skipped
          {:else if res.verdict === 'GUARD'}similar, but the meaning changed
          {:else}not in cache — full pipeline runs{/if}
        </span>
      </div>
      <div class="rfields">
        <div class="rf"><span class="k">similarity</span><span class="v mono">{res.similarity.toFixed(3)}</span></div>
        {#if res.matched}<div class="rf"><span class="k">nearest</span><span class="v">{res.matched.query}</span></div>{/if}
        {#if res.verdict === 'HIT'}<div class="rf"><span class="k">reuse model</span><span class="v mono">{res.matched.model}</span></div>{/if}
        <div class="rf"><span class="k">reason</span><span class="v small">{res.reason}</span></div>
      </div>
    </div>

    <div class="ladder">
      <div class="ladder-h">Guard ladder</div>
      <div class="rung {res.trace.threshold.pass ? 'pass' : 'fail'}">
        <span class="dot"></span>
        <span class="rname">similarity ≥ {CFG.similarity_threshold}</span>
        <span class="rtag {res.trace.threshold.pass ? 'pass' : 'fail'}">{res.trace.threshold.sim.toFixed(3)}</span>
      </div>
      {#each GUARD_DEFS as gdef}
        {@const g = res.trace.guards[gdef.key]}
        {@const status = g ? g.status : 'skipped'}
        <div class="rung {status}">
          <span class="dot"></span>
          <span class="rname">{gdef.name}</span>
          {#if status === 'fired'}<span class="rtag fired">rejected · {g.detail}</span>
          {:else if status === 'pass'}<span class="rtag pass">ok</span>
          {:else}<span class="rtag skip">—</span>{/if}
        </div>
      {/each}
      <div class="rung outcome {res.verdict.toLowerCase()}">
        <span class="dot"></span>
        <span class="rname">
          {#if res.verdict === 'HIT'}Serve cached → {res.matched.model}
          {:else if res.verdict === 'GUARD'}Reject → full pipeline
          {:else}Miss → full pipeline{/if}
        </span>
      </div>
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="Why it's strong" title="Six guards close the similarity trap">
    <p class="body2">
      A pure similarity cache is dangerous: “how to <em>install</em> X” and “how to <em>uninstall</em>
      X” look almost identical but want opposite answers. These guards catch exactly those
      high-similarity-but-wrong cases — the source of the <strong>+41pp F1</strong> over a naive cache.
    </p>
    <div class="guards-ref">
      {#each GUARD_DEFS as g, i}
        <div class="gref"><span class="gn">{i + 1}</span><div><b>{g.name}</b><span>{g.desc}</span></div></div>
      {/each}
    </div>
  </Card>

  <Card eyebrow="Two more safeguards" title="Decay, tiered TTL & PII scrubbing">
    <div class="sub">
      <b>Time decay</b> — similarity is multiplied by <code>exp(−ln2·age/7d)</code>, so a stale
      match must be <em>more</em> similar to still hit.
    </div>
    <div class="sub">
      <b>Tiered TTL</b> — quality ≥ 0.85 reusable for 14 days, ≥ 0.70 for 3 days, escalated answers
      <em>never</em> reused. Low-quality outcomes don't get cached.
    </div>
    <div class="sub">
      <b>PII scrubbing</b> — emails, phones, cards become type tokens before matching, so two queries
      that differ only by personal data still match.
    </div>
    <div class="pii">
      <div class="pii-in">email the invoice to alice@acme.com or call 415-555-0199</div>
      <div class="pii-arrow">↓ scrub</div>
      <div class="pii-out mono">{piiDemo}</div>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="The shortcut that never sacrifices correctness">
  <p class="body">
    When Layer 2 hits, the router serves the cached model and <strong>skips the kNN search, the
    feature extraction, everything downstream</strong> — answering in ~3ms instead of ~120ms. But its
    real contribution is what it <em>refuses</em> to do: the guards mean the cache never trades
    correctness for speed. A flipped negation, a different error type, a new country — each sends the
    query to the full router rather than reusing a subtly-wrong answer.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-2" />

<style>
  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 16px; }
  code { font-family: var(--font-mono); font-size: 0.88em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 6px; border-radius: 5px; }

  .cache { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 12px 14px; margin-bottom: 16px; }
  .cache-h { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .centry { display: flex; flex-direction: column; gap: 6px; padding: 9px 0; border-bottom: 1px solid var(--border-1); transition: all 0.15s ease; }
  .centry:last-child { border-bottom: none; }
  .centry.matched { background: var(--accent-soft); margin: 0 -14px; padding: 9px 14px; border-bottom-color: transparent; border-radius: 8px; }
  .cq { font-size: 13px; color: var(--text-1); }
  .cmeta { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
  .ttl { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); }

  .qinput { width: 100%; background: var(--bg-1); border: 1px solid var(--border-2); border-radius: var(--r-md); padding: 13px 15px; color: var(--text-1); font-size: 14px; font-family: var(--font-mono); outline: none; transition: border-color 0.15s ease, box-shadow 0.15s ease; }
  .qinput:focus { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-soft); }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .chip { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-pill); padding: 5px 11px; font-size: 12px; transition: all 0.12s ease; }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .result-grid { display: grid; grid-template-columns: 1fr 1.05fr; gap: 18px; margin-top: 18px; }
  .verdict { display: flex; flex-direction: column; gap: 1px; padding: 15px 18px; border-radius: var(--r-md); margin-bottom: 14px; border: 1px solid var(--border-2); background: var(--surface-2); }
  .verdict.green { background: var(--green-soft); border-color: color-mix(in srgb, var(--green) 40%, transparent); }
  .verdict.amber { background: var(--amber-soft); border-color: color-mix(in srgb, var(--amber) 40%, transparent); }
  .vlabel { font-family: var(--font-mono); font-size: 20px; font-weight: 740; color: var(--text-1); }
  .verdict.green .vlabel { color: var(--green); }
  .verdict.amber .vlabel { color: var(--amber); }
  .vsub { font-size: 12px; color: var(--text-3); }
  .rfields { display: flex; flex-direction: column; gap: 9px; }
  .rf { display: flex; gap: 12px; }
  .rf .k { width: 84px; flex-shrink: 0; font-size: 11.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }
  .rf .v { font-size: 13px; color: var(--text-1); }
  .rf .v.mono { font-family: var(--font-mono); }
  .rf .v.small { font-size: 12px; color: var(--text-2); }

  .ladder { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 13px 15px; }
  .ladder-h { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .rung { display: flex; align-items: center; gap: 10px; padding: 6px 0; }
  .rung .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--border-strong); }
  .rname { flex: 1; font-size: 12.5px; color: var(--text-2); }
  .rtag { font-size: 11px; font-family: var(--font-mono); padding: 2px 8px; border-radius: var(--r-pill); }
  .rung.pass .dot { background: var(--green); }
  .rung.pass .rtag.pass { color: var(--green); background: var(--green-soft); }
  .rung.fired .dot { background: var(--amber); box-shadow: 0 0 9px var(--amber); }
  .rung.fired .rname { color: var(--text-1); font-weight: 650; }
  .rtag.fired { color: var(--amber); background: var(--amber-soft); }
  .rung.fail .dot { background: var(--text-3); }
  .rtag.fail { color: var(--text-3); background: var(--surface-2); }
  .rung.skipped { opacity: 0.35; }
  .rtag.skip { color: var(--text-3); }
  .rung.outcome { margin-top: 6px; padding-top: 11px; border-top: 1px solid var(--border-1); }
  .rung.outcome.hit .dot { background: var(--green); box-shadow: 0 0 9px var(--green); }
  .rung.outcome.hit .rname { color: var(--green); font-weight: 650; }
  .rung.outcome.guard .dot { background: var(--amber); }
  .rung.outcome.guard .rname { color: var(--amber); font-weight: 600; }
  .rung.outcome.miss .dot { background: var(--blue); }
  .rung.outcome.miss .rname { color: var(--blue); font-weight: 600; }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .body2 { font-size: 13.5px; color: var(--text-2); line-height: 1.6; margin-bottom: 14px; }
  .body2 strong { color: var(--text-1); }
  .body2 em { font-style: italic; color: var(--accent-2); }
  .guards-ref { display: flex; flex-direction: column; gap: 9px; }
  .gref { display: flex; gap: 11px; align-items: flex-start; }
  .gn { flex-shrink: 0; width: 20px; height: 20px; border-radius: 5px; display: grid; place-items: center; font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); }
  .gref div { display: flex; flex-direction: column; }
  .gref b { font-size: 12.5px; color: var(--text-1); }
  .gref span { font-size: 11.5px; color: var(--text-3); }

  .sub { font-size: 13px; color: var(--text-2); line-height: 1.55; margin-bottom: 11px; }
  .sub b { color: var(--text-1); }
  .sub em { font-style: italic; color: var(--accent-2); }
  .pii { margin-top: 6px; padding: 12px 14px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); }
  .pii-in { font-size: 12px; color: var(--text-3); }
  .pii-arrow { font-size: 11px; color: var(--accent-2); margin: 5px 0; }
  .pii-out { font-size: 12.5px; color: var(--text-1); }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }
  .body em { font-style: italic; color: var(--accent-2); }

  @media (max-width: 860px) { .result-grid, .two { grid-template-columns: 1fr; } }
</style>
