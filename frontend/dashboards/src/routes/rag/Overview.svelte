<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import SectionTitle from '../../components/ui/SectionTitle.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import RagPipelineFlow from '../../components/RagPipelineFlow.svelte'
  import { systems, routeFor } from '../../lib/registry.js'
  import { navigate } from '../../lib/router.js'

  const sys = systems.find((s) => s.id === 'rag')
  const steps = sys.items.filter((i) => i.slug !== 'overview')

  const failures = [
    { title: 'Citation hallucination', body: 'Models emit plausible-looking citations that point to nothing. Here every "Citation N" must map to a structured page-proof with exact character offsets — or it isn\'t emitted.' },
    { title: 'Evidence dilution', body: 'Irrelevant chunks crowd the context and weaken grounding. Query-aware retrieval, domain reranking and structure-preserving chunks maximise evidence per unit of context.' },
    { title: 'Verification asymmetry', body: 'Even real citations are hard to check. Returning character-offset highlight spans lets the reader see the exact source span supporting each claim.' },
  ]
</script>

<PageHeader
  badge="∑"
  eyebrow="RAG + Citation"
  title="Answers you can check, line by line"
  tagline="A retrieval system built so every sentence is grounded in retrieved evidence and every claim carries a verifiable citation — down to the highlighted span on the source page. When the evidence isn't there, it refuses rather than fabricates."
  stats={[
    { value: '7', label: 'document formats' },
    { value: 'page-level', label: 'citation granularity', tone: 'accent' },
    { value: 'char-offset', label: 'highlight spans' },
    { value: 'refusal', label: 'is first-class' },
  ]}
/>

<Card eyebrow="The whole pipeline" title="Two tracks, one grounded answer" glow>
  <p class="lede">
    Documents are ingested once into a per-tenant vector store; every question then flows through
    retrieval, reranking, grounded assembly, constrained generation, verification and citation.
    Click any step to open its dashboard.
  </p>
  <RagPipelineFlow />
</Card>

<section>
  <SectionTitle eyebrow="Why it exists" title="Three failure modes of naive RAG — each designed out">
    Bolting a vector search onto an LLM produces confident, uncheckable answers. This subsystem
    targets the three specific ways that goes wrong.
  </SectionTitle>
  <div class="threeup">
    {#each failures as f}
      <div class="fail">
        <div class="fx">✕</div>
        <h3>{f.title}</h3>
        <p>{f.body}</p>
      </div>
    {/each}
  </div>
</section>

<Card eyebrow="The contract" title="What a citation guarantees">
  <div class="contract">
    <div class="cpart">
      <span class="ck">Inline marker</span>
      <code>(Citation 1, Source: VINCI.pdf, Page: 1, Section: Art. 5)</code>
      <span class="cnote">collapsed to a clean <b>[1]</b> superscript in the UI</span>
    </div>
    <div class="cpart">
      <span class="ck">Page proof</span>
      <code>{'{ source_uri, page_number, page_text, highlights:[{start_char, end_char}], citation_indices }'}</code>
      <span class="cnote">the exact span that supports the claim</span>
    </div>
    <div class="cpart">
      <span class="ck">Evidence group</span>
      <code>supported by Citations 2, 5, 7</code>
      <span class="cnote">when several sources back one claim</span>
    </div>
  </div>
</Card>

<section>
  <SectionTitle eyebrow="Go deeper" title="Open any step">
    Each step has its own dashboard — what it does, why it's strong, and a live demo.
  </SectionTitle>
  <div class="grid">
    {#each steps as s}
      <button class="scard" class:flag={s.flagship} onclick={() => navigate(routeFor('rag', s.slug))}>
        <span class="sbadge">{s.badge}</span>
        <span class="stext"><span class="stitle">{s.title}</span><span class="stag">{s.tagline}</span></span>
        <span class="sarrow">→</span>
      </button>
    {/each}
  </div>
</section>

<PrevNext current="/rag/overview" />

<style>
  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 20px; }
  .threeup { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  .fail { border-radius: var(--r-lg); padding: 20px; border: 1px solid var(--border-1); background: linear-gradient(180deg, var(--surface-1), transparent); }
  .fx { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; background: var(--red-soft); color: var(--red); font-weight: 700; margin-bottom: 12px; }
  .fail h3 { font-size: 15px; margin-bottom: 8px; }
  .fail p { font-size: 12.5px; color: var(--text-2); line-height: 1.55; }

  .contract { display: flex; flex-direction: column; gap: 14px; }
  .cpart { display: flex; flex-direction: column; gap: 5px; }
  .ck { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-2); font-weight: 700; }
  .cpart code { font-family: var(--font-mono); font-size: 12px; color: var(--text-1); background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-sm); padding: 9px 12px; overflow-x: auto; }
  .cnote { font-size: 12px; color: var(--text-3); }
  .cnote b { color: var(--accent-2); }

  .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 11px; }
  .scard { display: flex; align-items: center; gap: 14px; text-align: left; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 13px 16px; transition: all 0.13s ease; }
  .scard:hover { background: var(--surface-hover); border-color: var(--accent-line); transform: translateX(2px); }
  .scard.flag { border-color: var(--accent-line); }
  .sbadge { flex-shrink: 0; width: 30px; height: 28px; display: grid; place-items: center; border-radius: 7px; font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text-on-accent); background: linear-gradient(135deg, var(--accent-1), var(--accent-2)); }
  .stext { flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .stitle { font-size: 13.5px; font-weight: 650; color: var(--text-1); }
  .stag { font-size: 11.5px; color: var(--text-3); }
  .sarrow { color: var(--text-3); }

  @media (max-width: 860px) { .threeup, .grid { grid-template-columns: 1fr; } }
</style>
