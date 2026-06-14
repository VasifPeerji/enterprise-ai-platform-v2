<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { CHUNKS } from '../../lib/sim/ragdoc.js'

  // Assign citation slots to the retrieved chunks.
  const slots = CHUNKS.map((c, i) => ({ n: i + 1, ...c }))
</script>

<PageHeader
  badge="6"
  eyebrow="RAG + Citation · Step 6"
  title="Grounded Context Assembly"
  tagline="The bridge between retrieval and generation. Retrieved chunks become numbered citation slots in a structured prompt, each one wired to a page-proof object — so when the model writes “Citation 1”, there's already an exact source span waiting behind it."
  stats={[
    { value: 'citation slots', label: 'per chunk', tone: 'accent' },
    { value: 'page proofs', label: 'pre-built' },
    { value: 'evidence groups', label: 'multi-source' },
    { value: 'cross-refs', label: 'resolved' },
  ]}
/>

<Card eyebrow="The assembly" title="Chunks → citation slots + page proofs" glow>
  <p class="lede">Each retrieved chunk is assigned a citation number and turned into two linked things: a
    block the LLM reads, and a structured page-proof the frontend reads. The numbers are the join key.</p>

  <div class="assembly">
    <div class="side">
      <div class="side-h">What the model sees · grounded prompt</div>
      <div class="prompt">
        {#each slots as s}
          <div class="slot">
            <span class="slot-tag">Citation {s.n}</span>
            <span class="slot-meta mono">{s.article} · {s.title} · p{s.page}</span>
            <p class="slot-text">{s.text}</p>
          </div>
        {/each}
      </div>
    </div>

    <div class="side">
      <div class="side-h">What the frontend gets · page proofs</div>
      <div class="proofs">
        {#each slots as s}
          <pre class="proof">{`{
  "citation_index": ${s.n},
  "source_uri": "VINCI_Contract.pdf",
  "page_number": ${s.page},
  "section": "${s.article}",
  "highlights": [{ start_char, end_char }]
}`}</pre>
        {/each}
      </div>
    </div>
  </div>
</Card>

<div class="two">
  <Card eyebrow="Evidence groups" title="When several sources back one claim">
    <p class="body2">
      If a claim is supported by more than one chunk, assembly packages them into an
      <strong>evidence group</strong> so the frontend can render “supported by Citations 2, 5, 7”
      rather than three loose markers.
    </p>
    <div class="egroup">
      <span class="eg-claim">“Contractors carry obligations and liability on termination.”</span>
      <div class="eg-pills"><Pill tone="accent">Citation 1</Pill><Pill tone="accent">Citation 3</Pill></div>
    </div>
  </Card>

  <Card eyebrow="Cross-reference resolution" title="Following the document's own pointers">
    <p class="body2">
      When a retrieved chunk references another part of the document — “as set out in Article 5” —
      assembly pulls that referenced chunk into context too (if it was retrieved), so the model isn't
      reasoning about a clause it can't see.
    </p>
    <div class="xref">
      <span class="xr-from mono">Article 6 → “see Article 5”</span>
      <span class="xr-arrow">resolves</span>
      <span class="xr-to mono">Article 5 pulled into context</span>
    </div>
  </Card>
</div>

<Card eyebrow="How it shapes the final output" title="Why citations can't be faked">
  <p class="body">
    This is the step that makes citation hallucination structurally impossible. The model never invents
    a citation number out of thin air — it can only reference slots that <strong>already exist</strong>,
    each pre-bound to a real page proof. So every “Citation N” in the answer is guaranteed to resolve to
    a specific page and span. Generation writes the prose; assembly already guaranteed the receipts.
  </p>
</Card>

<PrevNext current="/rag/assembly" />

<style>
  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 18px; }
  .assembly { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .side-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-3); font-weight: 700; margin-bottom: 10px; }
  .prompt, .proofs { display: flex; flex-direction: column; gap: 9px; }
  .slot { background: var(--bg-1); border: 1px solid var(--border-1); border-left: 3px solid var(--accent-2); border-radius: var(--r-md); padding: 11px 13px; }
  .slot-tag { display: inline-block; font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); padding: 2px 8px; border-radius: 5px; }
  .slot-meta { font-size: 10.5px; color: var(--text-3); margin-left: 8px; }
  .slot-text { font-size: 12px; color: var(--text-2); line-height: 1.5; margin-top: 7px; }
  .proof { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 11px 13px; margin: 0; line-height: 1.5; overflow-x: auto; }

  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .body2 { font-size: 13px; color: var(--text-2); line-height: 1.6; }
  .body2 strong { color: var(--text-1); }
  .egroup { margin-top: 14px; padding: 13px; background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); }
  .eg-claim { font-size: 12.5px; color: var(--text-1); font-style: italic; }
  .eg-pills { display: flex; gap: 7px; margin-top: 9px; }
  .xref { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  .xr-from, .xr-to { font-size: 11.5px; padding: 7px 11px; border-radius: var(--r-sm); background: var(--surface-2); border: 1px solid var(--border-1); color: var(--text-2); }
  .xr-to { border-color: var(--accent-line); color: var(--accent-2); }
  .xr-arrow { font-size: 11px; color: var(--text-3); }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 860px) { .assembly, .two { grid-template-columns: 1fr; } }
</style>
