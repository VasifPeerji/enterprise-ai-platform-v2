<script>
  import PageHeader from '../../components/ui/PageHeader.svelte'
  import Card from '../../components/ui/Card.svelte'
  import Pill from '../../components/ui/Pill.svelte'
  import PrevNext from '../../components/ui/PrevNext.svelte'
  import { DOC } from '../../lib/sim/ragdoc.js'

  const formats = [
    { ext: 'PDF', approach: 'Native text extraction with true page boundaries; OCR fallback for scanned pages; original page bytes kept for citation rendering.', pageAware: true },
    { ext: 'DOCX', approach: 'Converted to plain text (mammoth.js client-side for uploads), then paragraph-segmented.', pageAware: false },
    { ext: 'TXT', approach: 'Direct ingestion with heuristic paragraph segmentation.', pageAware: false },
    { ext: 'HTML', approach: 'Tag-stripping that preserves structural markers (headings, lists, tables).', pageAware: false },
    { ext: 'CSV', approach: 'Row-wise chunking that carries the header row as context into every chunk.', pageAware: false },
    { ext: 'JSON', approach: 'Structure-aware chunking that respects object / array boundaries.', pageAware: false },
    { ext: 'MD', approach: 'Section-aware chunking that respects the heading hierarchy.', pageAware: true },
  ]
  let sel = $state(0)
  const f = $derived(formats[sel])
</script>

<PageHeader
  badge="1"
  eyebrow="RAG + Citation · Step 1"
  title="Document Parsing & Ingestion"
  tagline="Turns seven messy file formats into clean, page-bounded text. Getting the page boundaries right here is what makes citations possible at the very end — a highlight can only point to a page if parsing kept the pages intact."
  stats={[
    { value: '7', label: 'formats', tone: 'accent' },
    { value: 'page-bounded', label: 'PDF extraction' },
    { value: 'OCR', label: 'fallback for scans' },
    { value: 'surfaced', label: 'parse errors' },
  ]}
/>

<Card eyebrow="Formats" title="One parser per format, one job each">
  <div class="fgrid">
    <div class="ftabs">
      {#each formats as fmt, i}
        <button class="ftab" class:on={sel === i} onclick={() => (sel = i)}>
          <span class="fext">{fmt.ext}</span>
          {#if fmt.pageAware}<span class="fdot" title="page/section aware"></span>{/if}
        </button>
      {/each}
    </div>
    <div class="fdetail">
      <div class="fd-h">
        <span class="fd-ext">{f.ext}</span>
        {#if f.pageAware}<Pill tone="accent">page / section aware</Pill>{:else}<Pill tone="neutral">paragraph segmented</Pill>{/if}
      </div>
      <p class="fd-body">{f.approach}</p>
    </div>
  </div>
</Card>

<Card eyebrow="Parsed output" title="A PDF → page-bounded text">
  <p class="lede">Our sample contract <code>{DOC.source_uri}</code> parsed into pages. Each page keeps its
    boundary and its original index, so a citation later can say <em>“page 1”</em> and mean it.</p>
  <div class="pages">
    {#each DOC.pages as p}
      <div class="page">
        <div class="page-h">
          <span class="page-n">Page {p.page}</span>
          <span class="page-m mono">{p.text.length} chars · boundary kept ✓</span>
        </div>
        <p class="page-t">{p.text}</p>
      </div>
    {/each}
  </div>
  <div class="ingest-note">
    <span class="in-dot"></span>
    For PDFs the original page bytes are persisted at ingest — that's what lets the citation step
    later render the actual page image and draw highlight rectangles on it.
  </div>
</Card>

<Card eyebrow="How it shapes the final output" title="Citations are only as good as the parse">
  <p class="body">
    This is the unglamorous step everything downstream depends on. If parsing loses page boundaries,
    no later layer can recover them — the answer might still be correct, but it could never point you
    to <strong>page 1, characters 24–187</strong>. By keeping pages, sections and the original bytes
    intact from the start, parsing makes the end-to-end citation guarantee structurally possible.
  </p>
</Card>

<PrevNext current="/rag/parsing" />

<style>
  .lede { color: var(--text-2); font-size: 14px; margin-bottom: 16px; }
  code { font-family: var(--font-mono); font-size: 0.9em; color: var(--accent-2); background: var(--accent-soft); padding: 1px 6px; border-radius: 5px; }
  .lede em { font-style: italic; color: var(--accent-2); }

  .fgrid { display: grid; grid-template-columns: 200px 1fr; gap: 20px; }
  .ftabs { display: flex; flex-direction: column; gap: 6px; }
  .ftab { display: flex; align-items: center; justify-content: space-between; background: var(--surface-2); border: 1px solid var(--border-1); border-radius: var(--r-sm); padding: 10px 14px; transition: all 0.12s; }
  .ftab:hover { background: var(--surface-hover); }
  .ftab.on { background: var(--accent-soft); border-color: var(--accent-line); }
  .fext { font-family: var(--font-mono); font-size: 13px; font-weight: 650; color: var(--text-1); }
  .fdot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent-2); }
  .fdetail { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 18px; }
  .fd-h { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .fd-ext { font-family: var(--font-mono); font-size: 22px; font-weight: 740; color: var(--text-1); }
  .fd-body { font-size: 13.5px; color: var(--text-2); line-height: 1.6; }

  .pages { display: flex; flex-direction: column; gap: 10px; }
  .page { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: var(--r-md); padding: 14px 16px; }
  .page-h { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
  .page-n { font-size: 13px; font-weight: 650; color: var(--accent-2); }
  .page-m { font-size: 11px; color: var(--text-3); }
  .page-t { font-size: 13px; color: var(--text-2); line-height: 1.55; }
  .ingest-note { display: flex; gap: 10px; margin-top: 14px; padding: 12px 14px; background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: var(--r-md); font-size: 12.5px; color: var(--text-1); line-height: 1.5; }
  .in-dot { flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; background: var(--accent-2); margin-top: 5px; }

  .body { color: var(--text-2); font-size: 14px; line-height: 1.65; }
  .body strong { color: var(--text-1); }

  @media (max-width: 760px) { .fgrid { grid-template-columns: 1fr; } }
</style>
