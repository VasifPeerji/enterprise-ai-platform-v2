"""
Dedicated showcase UI for grounded RAG with page-level citations and highlights.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/rag-citations", tags=["RAG Citations Demo"])


RAG_CITATIONS_DEMO_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RAG Citation Demo</title>
  <style>
    :root {
      --bg: #f6f1e8;
      --panel: rgba(255, 251, 244, 0.92);
      --ink: #1d2b2a;
      --muted: #5d6a67;
      --accent: #8a5a2b;
      --accent-soft: #f4e3cf;
      --accent-strong: #2d6a4f;
      --line: #dbcdbb;
      --proof: #fff7cf;
      --danger: #9b2226;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      font-family: "Alegreya", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(213, 231, 220, 0.9) 0, transparent 26%),
        radial-gradient(circle at bottom right, rgba(244, 227, 207, 0.95) 0, transparent 32%),
        var(--bg);
    }
    .wrap {
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
      margin-bottom: 20px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 18px 40px rgba(39, 49, 53, 0.08);
      backdrop-filter: blur(6px);
    }
    h1 {
      margin: 0 0 8px;
      font-size: 2.35rem;
      line-height: 1.05;
    }
    .sub {
      margin: 0;
      color: var(--muted);
      font-size: 1.02rem;
      max-width: 760px;
    }
    .hero-note {
      background: linear-gradient(135deg, rgba(45, 106, 79, 0.14), rgba(138, 90, 43, 0.12));
    }
    .tiny {
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.72rem;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .big {
      font-size: 1.12rem;
      line-height: 1.5;
    }
    .link-row {
      margin-top: 14px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .link-row a, button {
      appearance: none;
      border: 1px solid transparent;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      cursor: pointer;
      text-decoration: none;
      transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .link-row a {
      background: var(--accent-soft);
      color: var(--ink);
    }
    button.primary {
      background: var(--accent);
      color: #fffaf2;
      box-shadow: 0 12px 22px rgba(138, 90, 43, 0.18);
    }
    button.secondary {
      background: #fffaf2;
      border-color: var(--line);
      color: var(--ink);
    }
    button:hover, .link-row a:hover {
      transform: translateY(-1px);
    }
    .layout {
      display: grid;
      grid-template-columns: 0.92fr 1.08fr;
      gap: 20px;
    }
    .section-title {
      margin: 0 0 12px;
      font-size: 0.92rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 12px;
    }
    .row.two {
      grid-template-columns: repeat(2, 1fr);
    }
    label {
      display: block;
      margin-bottom: 6px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 251, 244, 0.95);
      color: var(--ink);
      padding: 12px 13px;
      font: inherit;
    }
    textarea {
      min-height: 128px;
      resize: vertical;
    }
    input[type="file"] {
      padding: 10px;
      background: #fffdf8;
    }
    .status {
      min-height: 24px;
      margin-top: 12px;
      color: var(--accent-strong);
    }
    .status.error {
      color: var(--danger);
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255, 255, 255, 0.55);
    }
    .card .label {
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .card .value {
      font-size: 1rem;
      line-height: 1.35;
      word-break: break-word;
    }
    .collection-list, .citation-list {
      display: grid;
      gap: 10px;
    }
    .collection-card, .citation-card {
      width: 100%;
      text-align: left;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
      color: var(--ink);
      padding: 13px 14px;
    }
    .citation-card.active, .collection-card.active {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px rgba(138, 90, 43, 0.2);
      background: #fffdf6;
    }
    .meta {
      font-size: 0.78rem;
      color: var(--muted);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .title {
      font-size: 1.02rem;
      margin-bottom: 4px;
    }
    .snippet {
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.45;
    }
    .proof-shell {
      display: grid;
      grid-template-columns: 0.88fr 1.12fr;
      gap: 16px;
      margin-top: 16px;
    }
    .proof-viewer {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.7);
      padding: 16px;
      min-height: 340px;
    }
    .proof-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
    }
    .proof-page {
      white-space: nowrap;
      font-size: 0.9rem;
      color: var(--muted);
    }
    .proof-text {
      white-space: pre-wrap;
      line-height: 1.7;
      font-size: 1rem;
    }
    mark.proof-highlight {
      background: var(--proof);
      color: inherit;
      padding: 0.08em 0.06em;
      border-radius: 0.2em;
      box-shadow: inset 0 -1px 0 rgba(138, 90, 43, 0.28);
    }
    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0 0;
    }
    .pill {
      padding: 7px 11px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: #58391a;
      font-size: 0.82rem;
    }
    pre {
      margin: 0;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: #1e2527;
      color: #ecf7f3;
      overflow: auto;
      font-size: 0.88rem;
      line-height: 1.5;
    }
    .proof-empty {
      color: var(--muted);
      font-style: italic;
    }
    .stack {
      display: grid;
      gap: 16px;
    }
    @media (max-width: 1040px) {
      .hero, .layout, .proof-shell, .row, .row.two, .kpis {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="panel">
        <h1>Grounded RAG With Page Proof</h1>
        <p class="sub">Upload documents into a reusable collection, ask a question, and inspect exactly which document pages support the answer. The supporting text is highlighted directly inside the returned page content so the proof is immediately visible.</p>
        <div class="link-row">
          <a href="/chat/demo">Open Router Demo</a>
          <button type="button" class="secondary" onclick="refreshCollections()">Refresh Collections</button>
        </div>
      </div>
      <div class="panel hero-note">
        <div class="tiny">Showcase Value</div>
        <div class="big">This demo isolates the retrieval story: collection ingestion, grounded answering, source citations, exact page numbers, and concrete highlighted text proof for faster verification.</div>
      </div>
    </div>

    <div class="layout">
      <div class="stack">
        <div class="panel">
          <div class="section-title">Collection Setup</div>
          <div class="row">
            <div>
              <label for="tenantId">Tenant</label>
              <input id="tenantId" type="text" value="default">
            </div>
            <div>
              <label for="domain">Domain</label>
              <input id="domain" type="text" value="general">
            </div>
            <div>
              <label for="topK">Top K</label>
              <input id="topK" type="number" min="1" max="20" value="6">
            </div>
          </div>
          <div class="row two">
            <div>
              <label for="collectionId">Collection ID</label>
              <input id="collectionId" type="text" placeholder="loan-servicing">
            </div>
            <div>
              <label for="queryMode">Run Mode</label>
              <select id="queryMode">
                <option value="answer" selected>Answer with proof</option>
                <option value="analyze">Analyze retrieval only</option>
              </select>
            </div>
          </div>
          <div class="row two">
            <div>
              <label for="generationMode">Answer Engine</label>
              <select id="generationMode">
                <option value="heuristic" selected>Extractive proof answer</option>
                <option value="gateway">Free/local generated answer</option>
              </select>
            </div>
            <div>
              <label for="files">Upload Files</label>
              <input id="files" type="file" multiple>
            </div>
          </div>
          <div class="link-row">
            <button type="button" class="primary" onclick="uploadCollection()">Upload To Collection</button>
            <button type="button" class="secondary" onclick="loadCollectionDetails()">Load Collection Details</button>
          </div>
          <div id="status" class="status"></div>
        </div>

        <div class="panel">
          <div class="section-title">Available Collections</div>
          <div id="collectionList" class="collection-list">
            <div class="proof-empty">Collections for this tenant will appear here.</div>
          </div>
        </div>

        <div class="panel">
          <div class="section-title">Collection Metadata</div>
          <pre id="collectionMeta">Load or upload a collection to inspect its metadata.</pre>
        </div>
      </div>

      <div class="stack">
        <div class="panel">
          <div class="section-title">Ask The Collection</div>
          <textarea id="query" placeholder="Ask something that should be grounded in the uploaded documents."></textarea>
          <div class="link-row">
            <button type="button" class="primary" onclick="runQuery()">Run Grounded Query</button>
          </div>
        </div>

        <div class="panel">
          <div class="kpis">
            <div class="card"><div class="label">Collection</div><div class="value" id="kpiCollection">-</div></div>
            <div class="card"><div class="label">Grounded</div><div class="value" id="kpiGrounded">-</div></div>
            <div class="card"><div class="label">Retrieval Count</div><div class="value" id="kpiRetrieval">-</div></div>
            <div class="card"><div class="label">Citations</div><div class="value" id="kpiCitations">-</div></div>
          </div>
          <div class="section-title">Answer</div>
          <pre id="answerBox">The grounded answer will appear here.</pre>
          <div id="pillRow" class="pill-row"></div>
          <div class="proof-shell">
            <div>
              <div class="section-title">Citations</div>
              <div id="citationList" class="citation-list">
                <div class="proof-empty">Run a grounded query to inspect supporting pages.</div>
              </div>
            </div>
            <div>
              <div class="section-title">Highlighted Page Proof</div>
              <div id="proofViewer" class="proof-viewer">
                <div class="proof-empty">A selected citation will render the source page here with the exact supporting text highlighted.</div>
              </div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="section-title">Raw Payload</div>
          <pre id="rawPayload">The underlying API payload will appear here for demo transparency.</pre>
        </div>
      </div>
    </div>
  </div>

  <script>
    let currentCitations = [];
    let currentProofs = [];

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function setStatus(message, isError = false) {
      const element = document.getElementById('status');
      element.textContent = message;
      element.classList.toggle('error', isError);
    }

    function selectedTenant() {
      return document.getElementById('tenantId').value.trim() || 'default';
    }

    function selectedDomain() {
      return document.getElementById('domain').value.trim() || 'general';
    }

    function selectedCollectionId() {
      return document.getElementById('collectionId').value.trim();
    }

    function selectedTopK() {
      const value = Number(document.getElementById('topK').value);
      return Number.isFinite(value) && value > 0 ? value : 6;
    }

    function renderHighlightedText(pageText, highlights) {
      if (!pageText) {
        return '<div class="proof-empty">No page text returned for this page proof.</div>';
      }

      const ordered = [...(highlights || [])]
        .filter((item) => Number.isInteger(item.start_char) && Number.isInteger(item.end_char) && item.end_char > item.start_char)
        .sort((left, right) => left.start_char - right.start_char);

      if (!ordered.length) {
        return '<div class="proof-text">' + escapeHtml(pageText) + '</div>';
      }

      let cursor = 0;
      let html = '';
      for (const highlight of ordered) {
        const start = Math.max(cursor, Math.min(highlight.start_char, pageText.length));
        const end = Math.max(start, Math.min(highlight.end_char, pageText.length));
        if (start > cursor) {
          html += escapeHtml(pageText.slice(cursor, start));
        }
        html += '<mark class="proof-highlight">' + escapeHtml(pageText.slice(start, end)) + '</mark>';
        cursor = end;
      }
      if (cursor < pageText.length) {
        html += escapeHtml(pageText.slice(cursor));
      }
      return '<div class="proof-text">' + html + '</div>';
    }

    function renderProofViewer(index) {
      const viewer = document.getElementById('proofViewer');
      const proof = currentProofs[index];
      if (!proof) {
        viewer.innerHTML = '<div class="proof-empty">Select a citation to inspect the matching page proof.</div>';
        return;
      }

      const pills = (proof.citation_indices || []).map((citationIndex) => {
        const citation = currentCitations[citationIndex];
        if (!citation) {
          return '';
        }
        return '<span class="pill">Citation ' + (citationIndex + 1) + ': ' + escapeHtml(citation.snippet || citation.title || '') + '</span>';
      }).join('');

      viewer.innerHTML = ''
        + '<div class="proof-header">'
        + '  <div>'
        + '    <div class="title">' + escapeHtml(proof.title || 'Untitled Source') + '</div>'
        + '    <div class="snippet">' + escapeHtml(proof.source_uri || '') + '</div>'
        + '  </div>'
        + '  <div class="proof-page">Page ' + escapeHtml(proof.page_number || '-') + '</div>'
        + '</div>'
        + renderHighlightedText(proof.page_text || '', proof.highlights || [])
        + '<div class="pill-row">' + (pills || '<span class="pill">No linked citation snippets</span>') + '</div>';

      document.querySelectorAll('.citation-card').forEach((element, elementIndex) => {
        element.classList.toggle('active', elementIndex === index);
      });
    }

    function renderGroundedPayload(payload) {
      currentCitations = payload.citations || [];
      currentProofs = payload.page_proofs || [];

      document.getElementById('answerBox').textContent = payload.answer || 'Analyze mode only: no final answer was generated.';
      document.getElementById('rawPayload').textContent = JSON.stringify(payload, null, 2);
      document.getElementById('kpiCollection').textContent = payload.collection_id || selectedCollectionId() || '-';
      document.getElementById('kpiGrounded').textContent = String(payload.grounded ?? currentProofs.length > 0);
      document.getElementById('kpiRetrieval').textContent = String(payload.retrieval_count ?? currentCitations.length);
      document.getElementById('kpiCitations').textContent = String(currentCitations.length);

      const pillItems = [];
      if (payload.domain) pillItems.push('domain: ' + payload.domain);
      if (payload.generation_mode) pillItems.push('mode: ' + payload.generation_mode);
      if (payload.model_id) pillItems.push('generator: ' + payload.model_id);
      document.getElementById('pillRow').innerHTML = pillItems.map((item) => '<span class="pill">' + escapeHtml(item) + '</span>').join('');

      const citationList = document.getElementById('citationList');
      if (!currentProofs.length) {
        citationList.innerHTML = '<div class="proof-empty">No page proofs were returned for this query.</div>';
        renderProofViewer(-1);
        return;
      }

      citationList.innerHTML = currentProofs.map((proof, index) => {
        const linkedCitation = (proof.citation_indices || [])
          .map((citationIndex) => currentCitations[citationIndex])
          .find(Boolean);
        const preview = linkedCitation?.snippet || proof.highlights?.[0]?.text || 'Open highlighted proof';
        return ''
          + '<button type="button" class="citation-card ' + (index === 0 ? 'active' : '') + '" onclick="renderProofViewer(' + index + ')">'
          + '  <div class="meta">Proof ' + (index + 1) + '</div>'
          + '  <div class="title">' + escapeHtml(proof.title || 'Untitled Source') + '</div>'
          + '  <div class="snippet">Page ' + escapeHtml(proof.page_number || '-') + ' | ' + escapeHtml(preview) + '</div>'
          + '</button>';
      }).join('');

      renderProofViewer(0);
    }

    async function refreshCollections() {
      const tenantId = selectedTenant();
      try {
        const response = await fetch('/grounded-documents/collections?tenant_id=' + encodeURIComponent(tenantId));
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || 'Could not load collections');
        }

        const list = payload.collections || [];
        const container = document.getElementById('collectionList');
        if (!list.length) {
          container.innerHTML = '<div class="proof-empty">No grounded collections exist for this tenant yet.</div>';
          return;
        }

        const activeCollectionId = selectedCollectionId();
        container.innerHTML = list.map((item) => {
          const active = item.collection_id === activeCollectionId ? 'active' : '';
          return ''
            + '<button type="button" class="collection-card ' + active + '" onclick="selectCollection(\\'' + encodeURIComponent(item.collection_id) + '\\')">'
            + '  <div class="meta">' + escapeHtml(item.document_count || 0) + ' documents</div>'
            + '  <div class="title">' + escapeHtml(item.collection_id) + '</div>'
            + '  <div class="snippet">' + escapeHtml(item.domain || 'general') + ' | ' + escapeHtml(item.generation_mode || 'heuristic') + '</div>'
            + '</button>';
        }).join('');
      } catch (error) {
        setStatus(error.message || String(error), true);
      }
    }

    function selectCollection(encodedCollectionId) {
      const collectionId = decodeURIComponent(encodedCollectionId);
      document.getElementById('collectionId').value = collectionId;
      refreshCollections();
      loadCollectionDetails();
    }

    async function loadCollectionDetails() {
      const collectionId = selectedCollectionId();
      if (!collectionId) {
        setStatus('Enter or select a collection first.', true);
        return;
      }

      try {
        const response = await fetch(
          '/grounded-documents/collections/' + encodeURIComponent(collectionId)
          + '?tenant_id=' + encodeURIComponent(selectedTenant())
        );
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || 'Could not load collection metadata');
        }

        document.getElementById('collectionMeta').textContent = JSON.stringify(payload, null, 2);
        setStatus('Collection metadata loaded.');
      } catch (error) {
        setStatus(error.message || String(error), true);
      }
    }

    async function uploadCollection() {
      const collectionId = selectedCollectionId();
      const filesInput = document.getElementById('files');
      if (!collectionId) {
        setStatus('Collection ID is required before upload.', true);
        return;
      }
      if (!filesInput.files.length) {
        setStatus('Choose at least one file to upload.', true);
        return;
      }

      const formData = new FormData();
      formData.append('collection_id', collectionId);
      formData.append('tenant_id', selectedTenant());
      formData.append('domain', selectedDomain());
      formData.append('generation_mode', document.getElementById('generationMode').value);
      formData.append('top_k', String(selectedTopK()));
      for (const file of filesInput.files) {
        formData.append('files', file);
      }

      setStatus('Uploading and indexing documents...');
      try {
        const response = await fetch('/grounded-documents/collections/upload', {
          method: 'POST',
          body: formData
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || 'Upload failed');
        }

        document.getElementById('collectionMeta').textContent = JSON.stringify(payload, null, 2);
        filesInput.value = '';
        await refreshCollections();
        setStatus('Collection uploaded and indexed successfully.');
      } catch (error) {
        setStatus(error.message || String(error), true);
      }
    }

    async function runQuery() {
      const collectionId = selectedCollectionId();
      const query = document.getElementById('query').value.trim();
      if (!collectionId) {
        setStatus('Select a collection before asking a grounded query.', true);
        return;
      }
      if (!query) {
        setStatus('Enter a question for the collection.', true);
        return;
      }

      const mode = document.getElementById('queryMode').value;
      const endpoint = '/grounded-documents/collections/' + encodeURIComponent(collectionId) + '/' + mode;
      const body = {
        query,
        tenant_id: selectedTenant(),
        domain: selectedDomain(),
        top_k: selectedTopK()
      };

      setStatus(mode === 'answer' ? 'Running grounded answer...' : 'Analyzing retrieval...');
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || 'Grounded query failed');
        }

        if (mode === 'analyze') {
          renderGroundedPayload({
            collection_id: collectionId,
            grounded: payload.page_proofs?.length > 0,
            retrieval_count: payload.retrieval_count,
            citations: payload.citations || [],
            page_proofs: payload.page_proofs || [],
            evidence_groups: payload.evidence_groups || [],
            answer: 'Analyze mode only: inspect citations and page proofs below.'
          });
        } else {
          renderGroundedPayload(payload);
        }
        setStatus('Grounded response ready.');
      } catch (error) {
        setStatus(error.message || String(error), true);
      }
    }

    refreshCollections();
  </script>
</body>
</html>
"""


@router.get(
    "/demo",
    response_class=HTMLResponse,
    summary="Dedicated RAG citation showcase UI",
    description="Standalone demo for grounded retrieval, exact page proofs, and highlighted supporting text.",
)
async def rag_citations_demo_ui() -> HTMLResponse:
    """Serve the dedicated showcase for grounded RAG with citation proof."""
    return HTMLResponse(content=RAG_CITATIONS_DEMO_HTML)
