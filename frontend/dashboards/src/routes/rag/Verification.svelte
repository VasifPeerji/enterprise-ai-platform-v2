<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { CHUNKS, similarity } from '../../lib/sim/ragdoc.js'

  const THRESHOLD = 0.4

  const answers = [
    {
      label: 'Fully grounded',
      claims: [
        { text: 'The contractor must maintain insurance coverage of at least 2,000,000 EUR.', cite: 'c5' },
        { text: 'Payment shall be made within 30 days of invoice receipt.', cite: 'c6' },
      ],
    },
    {
      label: 'One fabricated claim',
      claims: [
        { text: 'The contractor must maintain insurance coverage of at least 2,000,000 EUR.', cite: 'c5' },
        { text: 'The contractor also receives a 10 percent early-completion bonus.', cite: 'c5' },
      ],
    },
    {
      label: 'Mostly fabricated',
      claims: [
        { text: 'The contract includes a five-year warranty on all works.', cite: 'c5' },
        { text: 'Contractors are entitled to unlimited free revisions.', cite: 'c6' },
      ],
    },
  ]
  let ai = $state(0)

  const result = $derived.by(() => {
    const claims = answers[ai].claims.map((c) => {
      const chunk = CHUNKS.find((x) => x.id === c.cite)
      const support = chunk ? similarity(c.text, chunk.text) : 0
      return { ...c, chunk, support, ok: support >= THRESHOLD }
    })
    const unsupported = claims.filter((c) => !c.ok).length
    let outcome
    if (unsupported === 0) outcome = 'return'
    else if (unsupported <= claims.length / 2) outcome = 'strip'
    else outcome = 'regenerate'
    return { claims, unsupported, outcome }
  })

  const OUTCOMES = {
    return: { tone: 'green', label: 'All claims verified', action: 'Return the answer as-is.' },
    strip: { tone: 'amber', label: 'One claim unsupported', action: 'Strip the unsupported claim and return with an explicit gap note.' },
    regenerate: { tone: 'red', label: 'Most claims unsupported', action: 'Regenerate with a stricter grounding prompt — and refuse if it fails again.' },
  }
</script>

<PageHeader
  badge="8"
  eyebrow="RAG + Citation · Step 8"
  title="Claim Verification"
  tagline="The final correctness gate. Before any answer ships, every sentence is checked against the source span it cites. Claims that aren't actually supported get stripped or trigger a regeneration — and if nothing can be grounded, the system refuses."
  stats={[
    { value: 'per-claim', label: 'verification', tone: 'accent' },
    { value: String(THRESHOLD), label: 'support threshold' },
    { value: '4', label: 'outcomes' },
    { value: 'refuses', label: 'rather than fabricate' },
  ]}
/>

<Card eyebrow="Live verifier" title="Check an answer claim by claim" glow>
  <div class="seg">
    {#each answers as a, i}
      <button class:on={ai === i} onclick={() => (ai = i)}>{a.label}</button>
    {/each}
  </div>

  <div class="claims">
    {#each result.claims as c}
      <div class="claim {c.ok ? 'ok' : 'bad'}">
        <div class="claim-h">
          <span class="claim-icon">{c.ok ? '✓' : '✗'}</span>
          <span class="claim-text">{c.text}</span>
        </div>
        <div class="claim-evidence">
          <span class="ev-l">cited evidence · {c.chunk.article}</span>
          <span class="ev-t">{c.chunk.text}</span>
        </div>
        <div class="support">
          <div class="sup-bar"><span style="width:{c.support * 100}%" class={c.ok ? 'ok' : 'bad'}></span><span class="thr" style="left:{THRESHOLD * 100}%"></span></div>
          <span class="sup-v mono">support {c.support.toFixed(2)}</span>
          <Pill tone={c.ok ? 'green' : 'red'}>{c.ok ? 'supported' : 'unsupported'}</Pill>
        </div>
      </div>
    {/each}
  </div>

  <div class="outcome {OUTCOMES[result.outcome].tone}">
    <span class="oc-label">{OUTCOMES[result.outcome].label}</span>
    <span class="oc-action">{OUTCOMES[result.outcome].action}</span>
  </div>
</Card>

<div class="two">
  <Card eyebrow="The four outcomes" title="What happens to a checked answer">
    <div class="orow green"><b>All verified</b><span>return the RAGResponse unchanged</span></div>
    <div class="orow amber"><b>One or two unsupported</b><span>strip them, return with a gap note</span></div>
    <div class="orow red"><b>Most unsupported</b><span>regenerate with a stricter grounding prompt</span></div>
    <div class="orow neutral"><b>Regeneration fails</b><span>refuse with NoRelevantContextError</span></div>
  </Card>

  <Card eyebrow="Why it's strong" title="It closes the loop">
    <p class="body2">
      Every earlier step works to make a good citation <em>possible</em>. This is the step that makes
      it <strong>true</strong>. The model emitting “Citation 1” isn't proof that Citation 1 actually
      supports the sentence — the verifier is what checks that the claim and its cited span really
      agree, sentence by sentence.
    </p>
    <p class="body2 mt">
      That's the difference between a system that <em>looks</em> grounded and one that <strong>is</strong>:
      a confident sentence with a citation that doesn't back it up never reaches the user.
    </p>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="The last word before the user sees it">
  <p class="body">
    Verification is where the subsystem's promise is actually kept. By the time an answer reaches the
    user, each of its claims has been matched back to a real source span — the unsupported ones removed,
    not just flagged. It's the gate that lets the product say, truthfully, that every cited claim is one
    you can check.
  </p>
</Card>

<PrevNext current="/rag/verification" />

<style>
  .seg { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 20px; }
  .seg button { background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); border-radius: var(--r-sm); padding: 8px 14px; font-size: 12.5px; transition: all 0.12s; }
  .seg button.on { background: var(--accent-soft); border-color: var(--accent-line); color: var(--text-1); }

  .claims { display: flex; flex-direction: column; gap: 10px; }
  .claim { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 13px 15px; }
  .claim.ok { border-left: 3px solid var(--green); }
  .claim.bad { border-left: 3px solid var(--red); }
  .claim-h { display: flex; align-items: flex-start; gap: 10px; }
  .claim-icon { flex-shrink: 0; width: 20px; height: 20px; display: grid; place-items: center; border-radius: 5px; font-size: 12px; font-weight: 700; }
  .claim.ok .claim-icon { background: var(--green-soft); color: var(--green); }
  .claim.bad .claim-icon { background: var(--red-soft); color: var(--red); }
  .claim-text { font-size: 13.5px; color: var(--text-1); line-height: 1.45; }
  .claim-evidence { margin: 9px 0 9px 30px; padding: 8px 11px; background: var(--surface-2); border-radius: var(--r-sm); }
  .ev-l { display: block; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-3); margin-bottom: 3px; }
  .ev-t { font-size: 11.5px; color: var(--text-3); line-height: 1.45; }
  .support { display: flex; align-items: center; gap: 11px; margin-left: 30px; }
  .sup-bar { position: relative; flex: 1; height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .sup-bar span:not(.thr) { display: block; height: 100%; border-radius: 4px; }
  .sup-bar span.ok { background: var(--green); }
  .sup-bar span.bad { background: var(--red); }
  .sup-bar .thr { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--text-2); opacity: 0.6; }
  .sup-v { font-size: 11.5px; color: var(--text-2); }

  .outcome { display: flex; flex-direction: column; gap: 3px; margin-top: 16px; padding: 14px 17px; border-radius: var(--r-md); border: 1px solid var(--border-2); }
  .outcome.green { background: var(--green-soft); border-color: color-mix(in srgb, var(--green) 40%, transparent); }
  .outcome.amber { background: var(--amber-soft); border-color: color-mix(in srgb, var(--amber) 40%, transparent); }
  .outcome.red { background: var(--red-soft); border-color: color-mix(in srgb, var(--red) 40%, transparent); }
  .oc-label { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text-1); }
  .oc-action { font-size: 13px; color: var(--text-2); }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .orow { display: flex; flex-direction: column; gap: 1px; padding: 9px 0 9px 13px; border-left: 3px solid var(--border-2); margin-bottom: 9px; }
  .orow.green { border-color: var(--green); }
  .orow.amber { border-color: var(--amber); }
  .orow.red { border-color: var(--red); }
  .orow b { font-size: 13px; color: var(--text-1); }
  .orow span { font-size: 12px; color: var(--text-3); }

  .body2 { font-size: 13px; color: var(--text-2); line-height: 1.6; }
  .body2.mt { margin-top: 12px; }
  .body2 strong { color: var(--text-1); }
  .body2 em { font-style: italic; color: var(--accent-2); }
  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }

  @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
</style>
