<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import SectionTitle from '../../components/ui/SectionTitle.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { analyze, STEP_DEFS, CONFIG, LANG_COUNT } from '../../lib/sim/fastpath.js'

  let query = $state('hey there!')
  const res = $derived(analyze(query))
  const d = $derived(res.decision)

  const examples = [
    'hey there!',
    "how's it going?",
    'thanks so much for your help',
    "what's the capital of France?",
    '2 + 2 * 10',
    'cheers mate',
    'hi can you debug my python code?',
    '?!?!?!',
  ]

  const MODELS = {
    'groq-llama-3.1-8b': 'Llama 3.1 8B',
    'groq-llama-3.3-70b': 'Llama 3.3 70B',
    'ollama-phi3-mini': 'Phi-3 Mini',
  }
  const pretty = (m) => MODELS[m] || m

  const CATS = [
    ['TRIVIAL_GREETING', '“hey”, “hola”, “how’s it going”'],
    ['TRIVIAL_ACK', '“thanks”, “ok”, “got it”'],
    ['TRIVIAL_FAREWELL', '“bye”, “see you later”'],
    ['PURE_ARITHMETIC', '“2 + 2 * 10”, “calculate 5*7”'],
    ['SIMPLE_FACTUAL', '“capital of France?”, “who is the CEO of …”'],
    ['SIMPLE_DEFINITION', '“define recursion”, “what does API mean”'],
    ['MALFORMED', '“asdfgh”, “!!!”, “aaaa”'],
    ['NONE', 'everything else → full router'],
  ]
</script>

<PageHeader
  badge="L0"
  eyebrow="Smart Routing · Layer 0"
  title="Fast Path Bypass"
  tagline="The one place that can decide a query is trivial enough to skip the entire router — greetings, arithmetic, simple facts — and answer from the cheapest model in microseconds."
  stats={[
    { value: '36µs', label: 'p50 latency', tone: 'accent' },
    { value: '136µs', label: 'p99 latency' },
    { value: String(LANG_COUNT), label: 'languages' },
    { value: '8', label: 'categories' },
    { value: '+42pp', label: 'F1 vs heuristic', tone: 'green' },
    { value: '0', label: 'LLM calls' },
  ]}
/>

<Card eyebrow="Live tester" title="Type a query — watch the cascade decide" glow>
  <p class="lede">
    The fast path runs an ordered cascade of cheap checks. The first one that matches wins and the
    query bypasses the whole router. This runs the real Tier-1 logic in your browser — same
    registries, regexes and order as <code>fast_path.py</code>.
  </p>

  <input class="qinput" bind:value={query} placeholder="Type anything…" spellcheck="false" />
  <div class="chips">
    {#each examples as ex}
      <button class="chip" class:on={query === ex} onclick={() => (query = ex)}>{ex}</button>
    {/each}
  </div>

  <div class="result-grid">
    <!-- verdict + decision -->
    <div class="verdict-col">
      <div class="verdict {d.bypass ? 'yes' : 'no'}">
        <span class="vlabel">{d.bypass ? 'BYPASS' : 'NO BYPASS'}</span>
        <span class="vsub">{d.bypass ? 'router skipped' : 'full pipeline runs'}</span>
      </div>
      <div class="dfields">
        <div class="df"><span class="k">category</span><Pill tone={d.bypass ? 'accent' : 'neutral'} mono>{d.category}</Pill></div>
        {#if d.bypass}
          <div class="df"><span class="k">model</span><span class="v">{pretty(d.recommended_model)}</span></div>
          <div class="df"><span class="k">pattern</span><span class="v mono">{d.matched_pattern}</span></div>
          {#if d.detected_language}<div class="df"><span class="k">language</span><span class="v mono">{d.detected_language}</span></div>{/if}
          <div class="df"><span class="k">confidence</span><span class="v mono">{d.confidence.toFixed(2)}</span></div>
          <div class="df"><span class="k">fallback</span><span class="v mono small">{d.fallback_chain.map(pretty).join(' → ')}</span></div>
        {/if}
      </div>
      <p class="reason">{d.reason}</p>
      {#if res.tier2}<p class="t2note">★ matched by Tier-2 semantic similarity — illustrative here; the real path uses a Model2Vec embedder.</p>{/if}
    </div>

    <!-- cascade ladder -->
    <div class="ladder">
      <div class="ladder-h">Decision cascade</div>
      {#each STEP_DEFS as step}
        {@const t = res.trace.find((x) => x.key === step.key)}
        {@const status = t ? t.status : 'skipped'}
        <div class="rung {status}">
          <span class="dot"></span>
          <span class="rname">{step.name}</span>
          {#if status === 'fired'}<span class="rtag fired">match → {t.detail}</span>
          {:else if status === 'pass'}<span class="rtag pass">no match</span>
          {:else}<span class="rtag skip">skipped</span>{/if}
        </div>
      {/each}
      <div class="rung outcome {d.bypass ? 'bypassed' : 'full'}">
        <span class="dot"></span>
        <span class="rname">{d.bypass ? `Bypass → ${pretty(d.recommended_model)}` : 'Full router → L1 · L1.5 · L2 · L3'}</span>
      </div>
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The eight categories" title="What it catches">
    <div class="cat-list">
      {#each CATS as [name, ex]}
        <div class="cat">
          <span class="cat-name mono">{name}</span>
          <span class="cat-ex">{ex}</span>
        </div>
      {/each}
    </div>
  </Card>

  <Card eyebrow="Why it's strong" title="Two tiers, precision-first">
    <div class="tier">
      <span class="tnum">1</span>
      <div>
        <strong>Heuristic tier</strong> — multilingual token registries, an O(1) inverse index,
        start-anchored phrase regexes, and try-parse arithmetic. Catches the obvious cases in a
        few microseconds.
      </div>
    </div>
    <div class="tier">
      <span class="tnum">2</span>
      <div>
        <strong>Semantic tier</strong> — a Model2Vec prototype classifier (≥{CONFIG.semantic_threshold}
        cosine) catches paraphrases the keyword tables can't anticipate (“cheers mate”, “no worries”).
        No training, ~150–300µs on CPU.
      </div>
    </div>
    <div class="rule">
      <span class="rdot"></span>
      <span><strong>Precision over recall.</strong> A wrong bypass costs more than a missed one, so
      every rule is tight: “hi can you debug my code” must <em>not</em> bypass.</span>
    </div>
  </Card>
</div>

<div class="two">
  <Card eyebrow="Measured" title="The evidence that earned Tier 2">
    <div class="res-row">
      <div class="rstat"><span class="rv green">+42.1pp</span><span class="rl">F1 over heuristic-only (paraphrase corpus)</span></div>
      <div class="rstat"><span class="rv">100%</span><span class="rl">precision · 0 new false positives</span></div>
      <div class="rstat"><span class="rv">36 / 136 µs</span><span class="rl">p50 / p99 latency</span></div>
    </div>
    <p class="muted">Tier 2 was adopted only because a measured A/B showed it adds recall without sacrificing a single false positive — the bar for any library in the pre-routing layers.</p>
  </Card>

  <Card eyebrow="Real config" title="FastPathConfig">
    <div class="cfg">
      <div class="crow"><span>min_greeting_confidence</span><b>{CONFIG.min_greeting_confidence}</b></div>
      <div class="crow"><span>min_arithmetic_confidence</span><b>{CONFIG.min_arithmetic_confidence}</b></div>
      <div class="crow"><span>min_factual_confidence</span><b>{CONFIG.min_factual_confidence}</b></div>
      <div class="crow"><span>max_greeting_words</span><b>{CONFIG.max_greeting_words}</b></div>
      <div class="crow"><span>semantic_threshold</span><b>{CONFIG.semantic_threshold}</b></div>
      <div class="crow"><span>chat_chain[0]</span><b>llama-3.1-8b</b></div>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="A cheap exit that protects the whole budget">
  <p class="body">
    Roughly a third of real traffic is greetings, acknowledgements, and one-line facts. Sending
    those through the full kNN router would waste latency and compute on questions a 8B model nails
    instantly. Layer 0 is the pressure-release valve: when it fires, the orchestrator builds the
    decision from neutral metadata and returns — <strong>no modality gate, no cache lookup, no kNN
    search, no LLM</strong>. Everything downstream exists to handle the queries Layer 0 deliberately
    let through.
  </p>
</Card>

<PrevNext current="/smart-routing/layer-0" />

<style>
  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 16px; }
  code { font-family: var(--font-mono); font-size: 0.9em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 6px; border-radius: 5px; }

  .qinput {
    width: 100%;
    background: var(--bg-1);
    border: 1px solid var(--border-2);
    border-radius: var(--r-md);
    padding: 14px 16px;
    color: var(--text-1);
    font-size: 15px;
    font-family: var(--font-mono);
    outline: none;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .qinput:focus { border-color: var(--accent-line); box-shadow: 0 0 0 3px var(--accent-soft); }
  .chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .chip {
    background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2);
    border-radius: var(--r-pill); padding: 5px 11px; font-size: 12px; font-family: var(--font-mono);
    transition: all 0.12s ease;
  }
  .chip:hover { background: var(--surface-hover); color: var(--text-1); }
  .chip.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 20px; }

  .verdict { display: flex; flex-direction: column; gap: 1px; padding: 14px 18px; border-radius: var(--r-md); margin-bottom: 14px; }
  .verdict.yes { background: var(--green-soft); border: 1px solid color-mix(in srgb, var(--green) 40%, transparent); }
  .verdict.no { background: var(--surface-2); border: 1px solid var(--border-2); }
  .vlabel { font-family: var(--font-mono); font-size: 22px; font-weight: 750; }
  .verdict.yes .vlabel { color: var(--green); }
  .verdict.no .vlabel { color: var(--text-2); }
  .vsub { font-size: 12px; color: var(--text-3); }

  .dfields { display: flex; flex-direction: column; gap: 9px; }
  .df { display: flex; align-items: center; gap: 12px; }
  .df .k { width: 92px; flex-shrink: 0; font-size: 12px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }
  .df .v { font-size: 13.5px; color: var(--text-1); }
  .df .v.mono { font-family: var(--font-mono); font-size: 12.5px; }
  .df .v.small { font-size: 11.5px; color: var(--text-2); }
  .reason { margin-top: 12px; font-size: 12.5px; color: var(--text-3); font-style: italic; }
  .t2note { margin-top: 8px; font-size: 12px; color: var(--violet); }

  .ladder { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 14px 16px; }
  .ladder-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-3); font-weight: 700; margin-bottom: 12px; }
  .rung { display: flex; align-items: center; gap: 11px; padding: 7px 0; }
  .rung .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; background: var(--border-strong); }
  .rname { flex: 1; font-size: 13px; color: var(--text-2); }
  .rtag { font-size: 11px; font-family: var(--font-mono); padding: 2px 8px; border-radius: var(--r-pill); }
  .rtag.pass { color: var(--text-3); background: var(--surface-2); }
  .rtag.skip { color: var(--text-3); opacity: 0.5; }
  .rung.pass .dot { background: var(--text-3); }
  .rung.fired .dot { background: var(--accent-2); box-shadow: 0 0 10px var(--accent-2); }
  .rung.fired .rname { color: var(--text-1); font-weight: 650; }
  .rtag.fired { color: var(--accent-2); background: var(--accent-soft); }
  .rung.skipped { opacity: 0.38; }
  .rung.outcome { margin-top: 6px; padding-top: 12px; border-top: 1px solid var(--border-1); }
  .rung.outcome.bypassed .dot { background: var(--green); box-shadow: 0 0 10px var(--green); }
  .rung.outcome.bypassed .rname { color: var(--green); font-weight: 650; }
  .rung.outcome.full .dot { background: var(--blue); }
  .rung.outcome.full .rname { color: var(--blue); font-weight: 600; }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .cat-list { display: flex; flex-direction: column; gap: 10px; }
  .cat { display: flex; flex-direction: column; gap: 2px; padding-bottom: 9px; border-bottom: 1px solid var(--border-1); }
  .cat:last-child { border-bottom: none; }
  .cat-name { font-size: 12.5px; color: var(--accent-2); font-weight: 600; }
  .cat-ex { font-size: 12.5px; color: var(--text-3); }

  .tier { display: flex; gap: 13px; margin-bottom: 14px; font-size: 13px; color: var(--text-2); line-height: 1.5; }
  .tier strong { color: var(--text-1); }
  .tnum {
    flex-shrink: 0; width: 26px; height: 26px; border-radius: 7px; display: grid; place-items: center;
    font-family: var(--font-mono); font-weight: 700; font-size: 13px;
    color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2));
  }
  .rule { display: flex; gap: 11px; padding: 12px 14px; background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: var(--r-md); font-size: 12.5px; color: var(--text-1); line-height: 1.5; }
  .rule em { font-style: italic; color: var(--accent-2); }
  .rdot { flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; background: var(--accent-2); }

  .res-row { display: flex; gap: 22px; flex-wrap: wrap; margin-bottom: 12px; }
  .rstat { display: flex; flex-direction: column; gap: 2px; }
  .rv { font-family: var(--font-mono); font-size: 22px; font-weight: 720; color: var(--text-1); }
  .rv.green { color: var(--green); }
  .rl { font-size: 11.5px; color: var(--text-3); max-width: 180px; }

  .cfg { display: flex; flex-direction: column; gap: 0; }
  .crow { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border-1); font-size: 12.5px; }
  .crow:last-child { border-bottom: none; }
  .crow span { color: var(--text-3); font-family: var(--font-mono); }
  .crow b { color: var(--text-1); font-family: var(--font-mono); font-weight: 600; }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }
  .muted { font-size: 12px; color: var(--text-3); margin-top: 10px; line-height: 1.5; }

  @media (max-width: 860px) {
    .result-grid, .two { grid-template-columns: 1fr; }
  }
</style>
