<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'

  const SYSTEM_PROMPT = `You answer using only the grounded sources provided.
If evidence is incomplete, say so clearly.
Do not invent citations or unsupported facts.
Do not copy raw broken fragments from the source.
Synthesize a complete, readable answer from the cited context.
For direct factual questions, answer with the exact fact first,
then keep the explanation brief.
Do not include citation lines in the answer text;
structured citations are returned separately.`

  const questions = [
    {
      q: 'What is the minimum insurance coverage required?',
      ungrounded: 'Most construction contracts require around €1,000,000 in liability insurance, though it can vary by project size.',
      ungroundedFlag: 'plausible — but unsourced and wrong',
      grounded: 'At least €2,000,000, maintained throughout the project term.',
      groundedCite: 1,
      refused: false,
    },
    {
      q: "What is the contractor's paid vacation policy?",
      ungrounded: 'Contractors are typically entitled to around 20 days of paid leave per year under standard terms.',
      ungroundedFlag: 'fabricated — no such clause exists',
      grounded: "The provided documents don't cover a vacation policy, so I can't answer this from the available evidence.",
      groundedCite: null,
      refused: true,
    },
  ]
  let qi = $state(0)
  const cur = $derived(questions[qi])
</script>

<PageHeader
  badge="7"
  eyebrow="RAG + Citation · Step 7"
  title="Evidence-Constrained Generation"
  tagline="The model finally writes — but on a short leash. A strict system prompt confines it to the assembled evidence, the temperature is near-zero, and the generation model itself was chosen by the Smart Routing System. If the evidence isn't there, it says so."
  stats={[
    { value: '0.1', label: 'temperature', tone: 'accent' },
    { value: 'evidence-only', label: 'system prompt' },
    { value: 'smart-routed', label: 'generation model' },
    { value: 'heuristic', label: 'defensive fallback' },
  ]}
/>

<Card eyebrow="Grounded vs ungrounded" title="Same question, two very different answers" glow>
  <div class="seg">
    {#each questions as q, i}
      <button class:on={qi === i} onclick={() => (qi = i)}>{q.q}</button>
    {/each}
  </div>

  <div class="compare">
    <div class="ans ungrounded">
      <div class="ans-h"><span class="ans-t">Ungrounded LLM</span><Pill tone="red" dot>risky</Pill></div>
      <p class="ans-body">{cur.ungrounded}</p>
      <div class="ans-flag bad">⚠ {cur.ungroundedFlag}</div>
    </div>
    <div class="ans grounded">
      <div class="ans-h"><span class="ans-t">This system · evidence-constrained</span><Pill tone={cur.refused ? 'amber' : 'green'} dot>{cur.refused ? 'refuses' : 'grounded'}</Pill></div>
      <p class="ans-body">
        {cur.grounded}{#if cur.groundedCite}<sup class="cite">[{cur.groundedCite}]</sup>{/if}
      </p>
      <div class="ans-flag {cur.refused ? 'warn' : 'good'}">
        {#if cur.refused}↩ NoRelevantContextError — refuses rather than fabricate{:else}✓ exact fact, backed by a real citation{/if}
      </div>
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The leash" title="The evidence-only system prompt">
    <pre class="prompt">{SYSTEM_PROMPT}</pre>
  </Card>

  <Card eyebrow="Why it's strong" title="Constrained, routed, and double-netted">
    <div class="pt"><b>Temperature 0.1</b><span>minimal stylistic drift — maximises grounding adherence over creativity.</span></div>
    <div class="pt"><b>Token cap</b><span>min(MAX_TOKENS, 1200) — prevents verbose wandering past the evidence.</span></div>
    <div class="pt"><b>Smart-routed model</b><span>the generation model is selected by Layer 3 — the two systems fuse here.</span></div>
    <div class="pt"><b>Two safety nets</b><span>a suspiciously short or citation-only answer falls back to a deterministic heuristic generator; then every claim is verified downstream.</span></div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="The moment grounding becomes prose">
  <p class="body">
    Everything upstream existed to put the right evidence in front of the model with citation slots
    already wired. Generation's only job is to turn that into a readable answer <strong>without
    stepping outside it</strong> — citing what's there, and refusing what isn't. That refusal is a
    feature, not a failure: an honest “the documents don't say” is worth far more than a confident
    fabrication.
  </p>
</Card>

<PrevNext current="/rag/generation" />

<style>
  .seg { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 20px; }
  .seg button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 8px 14px; font-size: 12.5px; transition: all 0.12s; text-align: left; }
  .seg button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .compare { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .ans { border-radius: var(--r-md); padding: 16px; border: 1px solid var(--border-1); }
  .ans.ungrounded { background: var(--red-soft); border-color: color-mix(in srgb, var(--red) 28%, transparent); }
  .ans.grounded { background: var(--accent-soft); border-color: var(--accent-line); }
  .ans-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 11px; }
  .ans-t { font-size: 12.5px; font-weight: 650; color: var(--text-1); }
  .ans-body { font-size: 14px; color: var(--text-1); line-height: 1.6; }
  .cite { font-size: 10px; color: var(--accent-2); font-weight: 700; margin-left: 2px; }
  .ans-flag { margin-top: 12px; font-size: 12px; padding: 8px 11px; border-radius: var(--r-sm); }
  .ans-flag.bad { background: rgba(248,113,113,0.12); color: var(--red); }
  .ans-flag.good { background: rgba(52,211,153,0.12); color: var(--green); }
  .ans-flag.warn { background: rgba(251,191,36,0.12); color: var(--amber); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .prompt { font-family: var(--font-mono); font-size: 11.5px; color: var(--text-2); background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 14px; margin: 0; line-height: 1.65; white-space: pre-wrap; }
  .pt { padding: 9px 0; border-bottom: 1px solid var(--border-1); display: flex; flex-direction: column; gap: 2px; }
  .pt:last-child { border-bottom: none; }
  .pt b { font-size: 13px; color: var(--text-1); }
  .pt span { font-size: 12px; color: var(--text-3); line-height: 1.5; }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .compare, .two { grid-template-columns: 1fr; } }
</style>
