"""
📁 File: src/interfaces/http/routes/chat.py
Layer: Interfaces (HTTP)
Purpose: Smart chat — full elite pipeline, end to end
Depends on: router.py (route + post_call_with_query), gateway.py

Flow per request:
  1.  router.route()                   → pick model (layers 0-6)
  2.  gateway.complete()               → first LLM call
  3.  router.post_call_with_query()    → quality / escalation / bandit (layers 7-9)
  4.  Return PostCallResult.final_response to user (may differ from step-2 response
      if escalation happened)
"""

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.interfaces.http.demo_mode import (
    charge_demo_wallet,
    choose_backing_model_id,
    choose_demo_profile,
    get_demo_wallet_balance,
    get_or_create_profile,
    list_commercial_models,
    list_demo_profiles,
    reset_demo_wallet,
)
from src.layer1_intelligence.claim_verifier import (
    ClaimVerifier,
    VerificationReport,
    get_claim_verifier,
)
from src.layer3_domain.document_collections import (
    CollectionNotFoundError,
    get_document_collection_service,
)
from src.layer0_model_infra.gateway import LLMRequest, get_gateway
from src.layer0_model_infra.router import get_router
from src.shared.errors import ModelError, ModelNotFoundError, NoRelevantContextError
from src.shared.logger import get_logger

# ---------------------------------------------------------------------------
# Initialise singletons once at import time
# ---------------------------------------------------------------------------
router  = APIRouter(prefix="/chat", tags=["Chat"])
logger  = get_logger(__name__)
model_router = get_router()
gateway      = get_gateway()
grounded_collection_service = get_document_collection_service()
claim_verifier: ClaimVerifier = get_claim_verifier()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Inbound chat payload."""

    message:        str            = Field(..., description="User's message", min_length=1)
    temperature:    float          = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens:     Optional[int]  = Field(default=None, description="Max output tokens")
    force_model_id: Optional[str]  = Field(None, description="Force a specific model (bypasses routing)")
    has_images:     bool           = Field(default=False)
    has_audio:      bool           = Field(default=False)
    image_count:    int            = Field(default=0, ge=0)
    has_video:      bool           = Field(default=False)
    file_types:     Optional[list[str]] = Field(
        default=None,
        description="Optional attachment MIME types",
    )
    attachment_sizes_mb: Optional[list[float]] = Field(
        default=None,
        description="Optional attachment sizes in MB",
    )
    user_tier:      str            = Field(default="standard", description="free/standard/premium/enterprise")
    budget_remaining: float        = Field(default=1.0, ge=0.0, le=1.0)
    session_id:     Optional[str]  = Field(None, description="Session ID for escalation cooldown tracking")
    demo_mode:      bool           = Field(
        default=False,
        description="Execute on free/local backing models and simulate a commercial tier for demos",
    )
    simulation_profile_id: Optional[str] = Field(
        default=None,
        description="Commercial model profile to simulate while running on a free/local backing model",
    )
    simulation_session_id: Optional[str] = Field(
        default=None,
        description="Session ID for the mock wallet used in demo mode",
    )
    grounded_collection_id: Optional[str] = Field(
        default=None,
        description="Optional grounded document collection to answer from with proof payloads",
    )
    grounded_tenant_id: str = Field(
        default="default",
        description="Tenant key for grounded document retrieval",
    )
    grounded_domain: Optional[str] = Field(
        default=None,
        description="Optional domain override for grounded retrieval",
    )
    grounded_top_k: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Maximum grounded evidence units to retrieve",
    )
    verify_claims: bool = Field(
        default=False,
        description=(
            "When true, the answer is decomposed into atomic claims and each is "
            "verified against the retrieved citations using embedding + lexical "
            "signals. Adds a `verification` block to the response. Free-tier safe."
        ),
    )
    verification_use_embeddings: bool = Field(
        default=True,
        description=(
            "When true (default) the verifier uses the local embedding model in "
            "addition to lexical signals. Set false to force a pure-lexical run "
            "(useful when Ollama is offline)."
        ),
    )


class ChatResponse(BaseModel):
    """Outbound chat payload — includes full routing transparency."""

    response:         str   = Field(..., description="AI response the user sees")
    model_used:       str   = Field(..., description="Display name of the model the router SELECTED for this query (not the free fallback that may execute behind the scenes)")
    routing_decision: dict  = Field(..., description="Pre-LLM routing metadata")
    cost:             dict  = Field(..., description="Cost breakdown")
    performance:      dict  = Field(..., description="Latency / token counts")
    escalation:       dict  = Field(..., description="Escalation info (happened? how many levels?)")
    trace:            dict  = Field(..., description="Layer-by-layer execution trace for demos and debugging")
    simulation:       Optional[dict] = Field(
        default=None,
        description="Transparent simulation metadata for demo mode",
    )
    grounded:         bool = Field(default=False, description="Whether the response used grounded retrieval")
    grounded_collection_id: Optional[str] = Field(
        default=None,
        description="Grounded collection used for the answer when applicable",
    )
    citations:        list = Field(default_factory=list, description="Grounding citations")
    page_proofs:      list = Field(default_factory=list, description="Page-level proof payloads")
    evidence_groups:  list = Field(default_factory=list, description="Grouped evidence support")
    verification:     Optional[dict] = Field(
        default=None,
        description=(
            "Per-claim verification report when verify_claims=true. "
            "Includes verifiability_score (0-100), per-claim verdicts and "
            "links to supporting citation indices."
        ),
    )


async def _maybe_verify_claims(
    *,
    enabled: bool,
    answer: str,
    citations: list,
    use_embeddings: bool = True,
) -> Optional[dict]:
    """Run claim verification when enabled. Never raises — returns None on failure."""
    if not enabled or not answer:
        return None
    try:
        report: VerificationReport = await claim_verifier.verify(
            answer=answer,
            citations=citations or [],
            use_embeddings=use_embeddings,
        )
        return report.model_dump()
    except Exception as exc:
        logger.warning("claim_verification_skipped_due_to_error", error=str(exc))
        return None


def _build_grounded_chat_response(
    *,
    collection_id: str,
    tenant_id: str,
    domain: Optional[str],
    grounded_response: Any,
    latency_ms: float,
    verification: Optional[dict] = None,
) -> ChatResponse:
    return ChatResponse(
        response=grounded_response.answer,
        model_used=grounded_response.model_id or "grounded-rag",
        routing_decision={
            "reasoning": "Answered from grounded collection with exact page-level proof.",
            "confidence_level": "grounded",
            "fast_path": False,
            "memory_hit": False,
            "modality": "text",
            "intent": "grounded_qa",
            "domain": domain,
            "complexity": "document-grounded",
            "uncertainty_score": 0.0,
            "fallback_models": [],
        },
        cost={
            "total_cost_usd": 0.0,
            "estimated_cost_usd": 0.0,
            "provider": "grounded-rag",
            "is_free": True,
        },
        performance={
            "total_latency_ms": latency_ms,
        },
        escalation={
            "escalation_available": False,
            "escalation_levels_possible": 0,
            "escalated": False,
            "escalation_count": 0,
            "quality_passed": True,
            "quality_score": 1.0,
        },
        trace={
            "selected_model": {
                "model_id": grounded_response.model_id or "grounded-rag",
                "display_name": grounded_response.model_id or "grounded-rag",
                "provider": "grounded-rag",
                "model_type": "retrieval_augmented_generation",
            },
            "layers": {
                "grounded_retrieval": {
                    "collection_id": collection_id,
                    "tenant_id": tenant_id,
                    "domain": domain,
                    "retrieval_count": grounded_response.retrieval_count,
                    "grounded": grounded_response.grounded,
                },
            },
            "execution": {
                "path": "grounded_collection",
                "retrieval_count": grounded_response.retrieval_count,
            },
            "quality": {
                "passed": True,
                "score": 1.0,
                "reasoning": "Grounded response backed by retrieved citations and page proofs.",
            },
        },
        simulation=None,
        grounded=True,
        grounded_collection_id=collection_id,
        citations=grounded_response.citations,
        page_proofs=grounded_response.page_proofs,
        evidence_groups=grounded_response.evidence_groups,
        verification=verification,
    )


DEMO_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Adaptive Router Demo</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: #fffaf2;
      --ink: #1e2a2f;
      --muted: #58666b;
      --accent: #0f766e;
      --accent-soft: #d5efe9;
      --warn: #9a3412;
      --line: #d9d0c4;
    }
    body {
      margin: 0;
      font-family: Georgia, "Source Serif 4", serif;
      background:
        radial-gradient(circle at top right, #dff2eb 0, transparent 30%),
        radial-gradient(circle at bottom left, #f9dec9 0, transparent 26%),
        var(--bg);
      color: var(--ink);
    }
    .wrap {
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 2.2rem;
    }
    .sub {
      color: var(--muted);
      margin-bottom: 24px;
      max-width: 760px;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 20px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 12px 30px rgba(41, 51, 57, 0.07);
    }
    textarea, select, input {
      width: 100%;
      box-sizing: border-box;
      border-radius: 12px;
      border: 1px solid #c8beb0;
      padding: 12px 14px;
      font: inherit;
      background: #fffdf8;
      color: var(--ink);
    }
    textarea { min-height: 140px; resize: vertical; }
    .row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 12px;
    }
    button {
      margin-top: 14px;
      background: linear-gradient(135deg, var(--accent), #14532d);
      color: white;
      border: 0;
      border-radius: 999px;
      padding: 12px 20px;
      font: inherit;
      cursor: pointer;
    }
    button:disabled { opacity: 0.6; cursor: progress; }
    .pill {
      display: inline-block;
      background: var(--accent-soft);
      color: var(--accent);
      border-radius: 999px;
      padding: 4px 10px;
      margin: 0 8px 8px 0;
      font-size: 0.9rem;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #fcf8f1;
      border: 1px solid #e6ddd1;
      border-radius: 12px;
      padding: 12px;
      overflow: auto;
      max-height: 460px;
      color: #24343a;
    }
    .section-title {
      margin: 0 0 10px;
      font-size: 1.05rem;
    }
    .kpi {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-bottom: 14px;
    }
    .kpi .card {
      background: #fffdf8;
      border: 1px solid #e3d9cd;
      border-radius: 14px;
      padding: 12px;
    }
    .label {
      color: var(--muted);
      font-size: 0.85rem;
    }
    .value {
      font-size: 1.2rem;
      margin-top: 4px;
    }
    .examples button {
      margin-right: 8px;
      margin-top: 8px;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .status {
      margin-top: 10px;
      color: var(--warn);
      min-height: 1.2em;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 18px;
    }
    .hero-copy {
      max-width: 760px;
    }
    .hero-note {
      min-width: 240px;
      background: linear-gradient(135deg, #0f766e, #14532d);
      color: white;
      border-radius: 18px;
      padding: 14px 16px;
      box-shadow: 0 14px 28px rgba(15, 118, 110, 0.18);
    }
    .hero-note .tiny {
      opacity: 0.8;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .hero-note .big {
      margin-top: 6px;
      font-size: 1.1rem;
      line-height: 1.35;
    }
    .storyboard {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-top: 14px;
      margin-bottom: 14px;
    }
    .story-card {
      background: linear-gradient(180deg, #fffdf8, #f8f2e9);
      border: 1px solid #e3d9cd;
      border-radius: 16px;
      padding: 12px;
    }
    .story-card .step {
      color: var(--accent);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .story-card .headline {
      font-size: 1rem;
      margin-bottom: 4px;
    }
    .story-card .detail {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.4;
    }
    .feature-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 12px;
    }
    .feature-card {
      background: #fffdf8;
      border: 1px solid #e3d9cd;
      border-radius: 14px;
      padding: 12px;
    }
    .feature-card .title {
      color: var(--muted);
      font-size: 0.82rem;
      margin-bottom: 6px;
    }
    .feature-card .body {
      font-size: 0.98rem;
      line-height: 1.45;
    }
    .route-chain {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .chain-item {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      background: #fcf8f1;
      border: 1px solid #e6ddd1;
      border-radius: 12px;
      padding: 10px 12px;
    }
    .chain-badge {
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent);
    }
    .chain-model {
      font-size: 0.98rem;
    }
    .wallet-shell {
      background: #fcf8f1;
      border: 1px solid #e6ddd1;
      border-radius: 14px;
      padding: 12px;
    }
    .wallet-meter {
      height: 10px;
      background: #e8ddd1;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 10px;
    }
    .wallet-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(135deg, #0f766e, #22c55e);
      transition: width 250ms ease;
    }
    .disclaimer {
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.84rem;
      line-height: 1.45;
      background: #fffdf8;
      border: 1px dashed #d7c7b4;
      border-radius: 14px;
      padding: 10px 12px;
    }
    .proof-shell {
      margin-top: 16px;
      display: grid;
      grid-template-columns: 0.95fr 1.05fr;
      gap: 12px;
    }
    .proof-list, .proof-viewer {
      background: #fffdf8;
      border: 1px solid #e3d9cd;
      border-radius: 16px;
      padding: 14px;
    }
    .proof-empty {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
      background: #fcf8f1;
      border: 1px dashed #dccfbe;
      border-radius: 12px;
      padding: 12px;
    }
    .citation-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .citation-card {
      width: 100%;
      text-align: left;
      margin-top: 0;
      background: #fcf8f1;
      color: var(--ink);
      border: 1px solid #e3d9cd;
      border-radius: 14px;
      padding: 12px;
    }
    .citation-card.active {
      border-color: var(--accent);
      background: #eef8f5;
      box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.15);
    }
    .citation-meta {
      color: var(--accent);
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .citation-title {
      font-size: 1rem;
      margin-bottom: 4px;
    }
    .citation-snippet {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }
    .proof-header {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      margin-bottom: 10px;
    }
    .proof-page {
      color: var(--muted);
      font-size: 0.9rem;
    }
    .proof-page-block {
      border-bottom: 1px solid #eadfce;
      padding-bottom: 16px;
      margin-bottom: 16px;
    }
    .proof-page-block:last-child {
      border-bottom: 0;
      margin-bottom: 0;
    }
    .proof-text {
      white-space: pre-wrap;
      background: #fcf8f1;
      border: 1px solid #e6ddd1;
      border-radius: 12px;
      padding: 14px;
      max-height: 420px;
      overflow: auto;
      line-height: 1.7;
      font-size: 0.98rem;
    }
    mark.proof-highlight {
      background: #f9d87e;
      color: #2d2416;
      border-radius: 4px;
      padding: 0 2px;
      box-shadow: inset 0 -1px 0 rgba(125, 84, 0, 0.18);
    }
    .proof-badges {
      margin-top: 10px;
    }
    /* ── Verifiable Reasoning ─────────────────────────────── */
    .verification-shell {
      margin-top: 16px;
      background: #fffdf8;
      border: 1px solid #e3d9cd;
      border-radius: 16px;
      padding: 14px;
    }
    .verification-empty {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
      background: #fcf8f1;
      border: 1px dashed #dccfbe;
      border-radius: 12px;
      padding: 12px;
    }
    .verification-header {
      display: flex;
      gap: 14px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .score-ring {
      --score: 0;
      width: 72px;
      height: 72px;
      border-radius: 50%;
      background:
        conic-gradient(#14b8a6 calc(var(--score) * 1%), #e6ddd1 0);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .score-ring-inner {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: #fffdf8;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--ink);
    }
    .score-ring-label {
      font-size: 0.65rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .verification-summary {
      flex: 1;
      min-width: 200px;
    }
    .verification-summary-line {
      font-size: 1rem;
      margin-bottom: 4px;
    }
    .verification-meta {
      color: var(--muted);
      font-size: 0.82rem;
    }
    .claim-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 340px;
      overflow-y: auto;
      padding-right: 4px;
    }
    .claim-card {
      background: #fcf8f1;
      border: 1px solid #e6ddd1;
      border-left-width: 4px;
      border-radius: 10px;
      padding: 10px 12px;
    }
    .claim-card.supported    { border-left-color: #14b8a6; }
    .claim-card.partial      { border-left-color: #f59e0b; }
    .claim-card.contradicted { border-left-color: #dc2626; background: #fef2f2; }
    .claim-card.unsupported  { border-left-color: #6b7280; }
    .claim-card.inferred     { border-left-color: #3b82f6; }
    .claim-row {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      justify-content: space-between;
    }
    .claim-text {
      font-size: 0.95rem;
      line-height: 1.45;
      color: var(--ink);
      flex: 1;
    }
    .claim-verdict {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 3px 8px;
      border-radius: 999px;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .claim-verdict.supported    { background: #d5f3ec; color: #0f766e; }
    .claim-verdict.partial      { background: #fef3c7; color: #92400e; }
    .claim-verdict.contradicted { background: #fee2e2; color: #b91c1c; }
    .claim-verdict.unsupported  { background: #e5e7eb; color: #374151; }
    .claim-verdict.inferred     { background: #dbeafe; color: #1d4ed8; }
    .claim-meta {
      color: var(--muted);
      font-size: 0.78rem;
      margin-top: 6px;
      line-height: 1.4;
    }
    .claim-meta strong {
      color: var(--ink);
      font-weight: 600;
    }
    .verify-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.92rem;
      color: var(--ink);
      cursor: pointer;
    }
    .verify-toggle input { width: auto; }

    @media (max-width: 920px) {
      .grid, .row, .kpi, .storyboard, .feature-grid, .proof-shell {
        grid-template-columns: 1fr;
      }
      .hero {
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="hero-copy">
        <h1>Adaptive AI Routing Demo</h1>
        <div class="sub">Compare model performance and costs: manually select any commercial LLM, or let Smart Routing pick the optimal model for each query. Track wallet spending to see real cost savings from intelligent routing.</div>
      </div>
      <div class="hero-note">
        <div class="tiny">Cost Optimization Proof</div>
        <div class="big">22 commercial models, 3 cost tiers. Smart Routing saves ~85% by matching query complexity to the right model.</div>
      </div>
    </div>
    <div class="grid">
      <div class="panel">
        <div class="section-title">Interactive Query</div>
        <textarea id="message" placeholder="Try a simple question, a coding task, or a high-risk reasoning prompt."></textarea>
        <div class="examples">
          <button type="button" onclick="setExample('What is overfitting in machine learning?')">Simple</button>
          <button type="button" onclick="setExample('Write a Python function for breadth-first search and explain its time complexity.')">Coding</button>
          <button type="button" onclick="setExample('Compare the legal and ethical implications of using AI diagnosis tools in hospitals.')">High-Risk</button>
          <button type="button" onclick="setExample('Design a distributed consensus protocol with formal safety proofs.')">Expert</button>
        </div>
        <div class="row">
          <div style="grid-column: 1 / -1">
            <label for="model_selector">Model Selection</label>
            <select id="model_selector">
              <option value="smart_routing">🧠 Smart Routing (AI-Selected)</option>
            </select>
          </div>
        </div>
        <div class="row">
          <div>
            <label for="user_tier">User Tier</label>
            <select id="user_tier">
              <option value="free">free</option>
              <option value="standard" selected>standard</option>
              <option value="premium">premium</option>
            </select>
          </div>
          <div>
            <label for="budget_remaining">Budget Remaining</label>
            <input id="budget_remaining" type="number" step="0.05" min="0" max="1" value="1.0">
          </div>
          <div>
            <label for="mode">Mode</label>
            <select id="mode">
              <option value="chat" selected>full execute</option>
              <option value="analyze">analyze only</option>
            </select>
          </div>
        </div>
        <div class="row">
          <div>
            <label for="grounded_collection_id">Grounded Collection</label>
            <input id="grounded_collection_id" type="text" placeholder="Optional collection id for proof-backed chat">
          </div>
          <div>
            <label for="grounded_tenant_id">Grounded Tenant</label>
            <input id="grounded_tenant_id" type="text" value="default">
          </div>
          <div>
            <label for="grounded_domain">Grounded Domain</label>
            <input id="grounded_domain" type="text" placeholder="Optional domain override">
          </div>
        </div>
        <div class="row" style="grid-template-columns: 1fr 1fr; align-items: center; margin-top: 10px;">
          <label class="verify-toggle">
            <input type="checkbox" id="verify_claims" checked>
            <span><strong>Verify claims</strong> — decompose the answer & check each fact (no extra LLM call)</span>
          </label>
          <label class="verify-toggle">
            <input type="checkbox" id="verify_use_embeddings" checked>
            <span>Use embeddings (uncheck for lexical-only fallback)</span>
          </label>
        </div>
        <button id="runButton" onclick="runDemo()">Run Query</button>
        <button type="button" onclick="resetWallet()" style="background:linear-gradient(135deg,#9a3412,#7c2d12);margin-left:10px">Reset Wallet</button>
        <div class="status" id="status"></div>
      </div>
      <div class="panel">
        <div class="section-title">Routing Intelligence</div>
        <div class="storyboard">
          <div class="story-card">
            <div class="step">Model</div>
            <div class="headline">Selected Model</div>
            <div class="detail" id="storyCommercial">Select a model or use Smart Routing to begin.</div>
          </div>
          <div class="story-card">
            <div class="step">Routing</div>
            <div class="headline">Selection Reasoning</div>
            <div class="detail" id="storyExecution">Routing decision details will appear here.</div>
          </div>
          <div class="story-card">
            <div class="step">Cost</div>
            <div class="headline">Cost Impact</div>
            <div class="detail" id="storyEconomics">Cost breakdown will appear here.</div>
          </div>
        </div>
        <div class="section-title">Live Summary</div>
        <div class="kpi">
          <div class="card"><div class="label">Selected Model</div><div class="value" id="modelUsed">-</div></div>
          <div class="card"><div class="label">Model Tier</div><div class="value" id="simulatedModel">-</div></div>
          <div class="card"><div class="label">Confidence</div><div class="value" id="confidence">-</div></div>
          <div class="card"><div class="label">Quality Score</div><div class="value" id="quality">-</div></div>
          <div class="card"><div class="label">Wallet Balance</div><div class="value" id="walletBalance">-</div></div>
          <div class="card"><div class="label">Query Cost</div><div class="value" id="escalationCount">-</div></div>
        </div>
        <div id="pills"></div>
        <pre id="answer">Response will appear here.</pre>
        <div class="section-title" style="margin-top:14px;">Claim Verification</div>
        <div class="verification-shell" id="verificationShell">
          <div class="verification-empty">
            Toggle <strong>Verify claims</strong> above to decompose the answer
            into atomic facts and verify each against the cited evidence.
            Best paired with a grounded collection.
          </div>
        </div>
        <div class="proof-shell">
          <div class="proof-list">
            <div class="section-title">Source Proof</div>
            <div id="citationList" class="citation-list">
              <div class="proof-empty">Grounded citations will appear here when a collection-backed answer is returned.</div>
            </div>
          </div>
          <div class="proof-viewer">
            <div class="section-title">Highlighted Page</div>
            <div id="proofViewer">
              <div class="proof-empty">Select a grounded citation to inspect the exact supporting page and highlighted text.</div>
            </div>
          </div>
        </div>
        <div class="feature-grid">
          <div class="feature-card">
            <div class="title">Model Pipeline</div>
            <div class="route-chain">
              <div class="chain-item"><div><div class="chain-badge">Selected Model</div><div class="chain-model" id="chainCommercial">-</div></div></div>
              <div class="chain-item"><div><div class="chain-badge">Execution Backend</div><div class="chain-model" id="chainBackend">-</div></div></div>
              <div class="chain-item"><div><div class="chain-badge">Fallback Chain</div><div class="chain-model" id="chainFallback">-</div></div></div>
            </div>
          </div>
          <div class="feature-card">
            <div class="title">Wallet Impact</div>
            <div class="wallet-shell">
              <div class="body" id="walletSummary">Cost details appear here.</div>
              <div class="wallet-meter"><div class="wallet-fill" id="walletFill"></div></div>
            </div>
          </div>
        </div>
        <div class="disclaimer" id="simulationDisclaimer">Select a model from the dropdown to manually compare costs, or use Smart Routing to let the AI select the optimal model for each query.</div>
      </div>
    </div>
    <div class="panel" style="margin-top:20px;">
      <div class="section-title">Decision Trail</div>
      <pre id="trace">Run a query to see the full JSON decision trail.</pre>
    </div>
  </div>
  <script>
    let currentProofs = [];
    let currentCitations = [];
    let activeProofIndex = 0;

    const VERDICT_LABELS = {
      supported:    'Supported',
      partial:      'Partial',
      contradicted: 'Contradicted',
      unsupported:  'Unsupported',
      inferred:     'Inferred',
    };

    function setExample(value) {
      document.getElementById('message').value = value;
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function renderHighlightedText(pageText, highlights) {
      if (!pageText) {
        return '<div class="proof-empty">No page text returned for this proof.</div>';
      }

      const ordered = [...(highlights || [])]
        .filter((item) => Number.isInteger(item.start_char) && Number.isInteger(item.end_char) && item.end_char > item.start_char)
        .sort((left, right) => left.start_char - right.start_char);

      if (!ordered.length) {
        return `<div class="proof-text">${escapeHtml(pageText)}</div>`;
      }

      let cursor = 0;
      let html = '';
      for (const highlight of ordered) {
        const safeStart = Math.max(cursor, Math.min(highlight.start_char, pageText.length));
        const safeEnd = Math.max(safeStart, Math.min(highlight.end_char, pageText.length));
        if (safeStart > cursor) {
          html += escapeHtml(pageText.slice(cursor, safeStart));
        }
        html += `<mark class="proof-highlight">${escapeHtml(pageText.slice(safeStart, safeEnd))}</mark>`;
        cursor = safeEnd;
      }
      if (cursor < pageText.length) {
        html += escapeHtml(pageText.slice(cursor));
      }
      return `<div class="proof-text">${html}</div>`;
    }

    function renderProofViewer(index) {
      const viewer = document.getElementById('proofViewer');
      activeProofIndex = index;

      if (!currentProofs.length) {
        viewer.innerHTML = '<div class="proof-empty">Select a grounded citation to inspect the exact supporting page and highlighted text.</div>';
        return;
      }

      viewer.innerHTML = currentProofs.map((proof, proofIndex) => {
        const badges = (proof.citation_indices || []).map((citationIndex) => {
          const citation = currentCitations[citationIndex];
          if (!citation) return '';
          return `<span class="pill">Citation ${citationIndex + 1}: ${escapeHtml(citation.snippet || '')}</span>`;
        }).join('');

        return `
          <div class="proof-page-block" id="proof-page-${proofIndex}">
            <div class="proof-header">
              <div>
                <div class="citation-title">${escapeHtml(proof.title || 'Untitled Source')}</div>
                <div class="citation-snippet">${escapeHtml(proof.source_uri || '')}</div>
              </div>
              <div class="proof-page">Page ${escapeHtml(proof.page_number || '-')}</div>
            </div>
            ${renderHighlightedText(proof.page_text || '', proof.highlights || [])}
            <div class="proof-badges">${badges || '<span class="pill">No linked citations</span>'}</div>
          </div>
        `;
      }).join('');

      const selected = document.getElementById(`proof-page-${index}`);
      if (selected) selected.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

      document.querySelectorAll('.citation-card').forEach((element, elementIndex) => {
        element.classList.toggle('active', elementIndex === index);
      });
    }

    function renderGroundedProof(payload) {
      const citations = payload.citations || payload.pipeline?.citations || [];
      const pageProofs = payload.page_proofs || payload.pipeline?.page_proofs || [];
      currentCitations = citations;
      currentProofs = pageProofs;
      activeProofIndex = 0;

      const citationList = document.getElementById('citationList');
      if (!pageProofs.length) {
        citationList.innerHTML = '<div class="proof-empty">No grounded proof payload was returned for this response.</div>';
        renderProofViewer(-1);
        return;
      }

      citationList.innerHTML = pageProofs.map((proof, index) => {
        const linked = (proof.citation_indices || [])
          .map((citationIndex) => citations[citationIndex]?.snippet)
          .filter(Boolean);
        const preview = linked[0] || proof.highlights?.[0]?.text || 'Open this page proof';
        return `
          <button type="button" class="citation-card ${index === 0 ? 'active' : ''}" onclick="renderProofViewer(${index})">
            <div class="citation-meta">Proof ${index + 1}</div>
            <div class="citation-title">${escapeHtml(proof.title || 'Untitled Source')}</div>
            <div class="citation-snippet">Page ${escapeHtml(proof.page_number || '-')} | ${escapeHtml(preview)}</div>
          </button>
        `;
      }).join('');

      renderProofViewer(0);
    }

    async function loadCommercialModels() {
      try {
        const response = await fetch('/chat/demo/commercial-models');
        const payload = await response.json();
        const select = document.getElementById('model_selector');
        const options = ['<option value="smart_routing">🧠 Smart Routing (AI-Selected)</option>'];
        let currentTier = '';
        for (const model of (payload.models || [])) {
          if (model.tier !== currentTier) {
            currentTier = model.tier;
            const tierLabel = currentTier.charAt(0).toUpperCase() + currentTier.slice(1);
            const emoji = currentTier === 'premium' ? '🔴' : currentTier === 'moderate' ? '🟡' : '🟢';
            options.push(`<option disabled>── ${emoji} ${tierLabel} Tier ──</option>`);
          }
          const costLabel = model.cost_per_1k_tokens < 0.001
            ? `$${(model.cost_per_1k_tokens * 1000).toFixed(2)}/M`
            : `$${model.cost_per_1k_tokens.toFixed(4)}/1K`;
          options.push(`<option value="${model.model_id}">${model.display_name} (${costLabel})</option>`);
        }
        select.innerHTML = options.join('');
      } catch (error) {
        console.error('Failed to load commercial models:', error);
      }
    }

    async function resetWallet() {
      try {
        await fetch('/chat/demo/wallet/reset?session_id=demo', { method: 'POST' });
        const balanceResp = await fetch('/chat/demo/wallet/balance?session_id=demo');
        const data = await balanceResp.json();
        document.getElementById('walletBalance').textContent = `$${Number(data.balance_usd || 10).toFixed(4)}`;
        setStatus('Wallet reset to starting balance.');
      } catch (e) {
        setStatus('Wallet reset failed.', true);
      }
    }

    function setStatus(text, isError=false) {
      const el = document.getElementById('status');
      el.textContent = text;
      el.style.color = isError ? '#9a3412' : '#0f766e';
    }

    function renderVerification(payload) {
      const shell = document.getElementById('verificationShell');
      const verification = payload?.verification;

      if (!verification) {
        shell.innerHTML = `
          <div class="verification-empty">
            Toggle <strong>Verify claims</strong> above to decompose the answer
            into atomic facts and verify each against the cited evidence.
          </div>`;
        return;
      }

      if (verification.method === 'skipped_no_citations') {
        shell.innerHTML = `
          <div class="verification-empty">
            <strong>This answer was not grounded in any sources</strong> —
            so we have nothing to verify it against. Attach a grounded
            collection (left panel) to see per-claim verification.
            <div style="margin-top:6px;color:var(--muted);">
              ${verification.total_claims || 0} claim(s) detected · score 0/100
            </div>
          </div>`;
        return;
      }

      const score = Number(verification.verifiability_score || 0);
      const scoreColor =
        score >= 75 ? '#14b8a6' :
        score >= 50 ? '#f59e0b' :
                      '#dc2626';

      const counts = {
        supported:    verification.supported_count    || 0,
        partial:      verification.partial_count      || 0,
        contradicted: verification.contradicted_count || 0,
        unsupported:  verification.unsupported_count  || 0,
        inferred:     verification.inferred_count     || 0,
      };

      const breakdownPills = [
        ['supported',    counts.supported,    '#d5f3ec', '#0f766e'],
        ['partial',      counts.partial,      '#fef3c7', '#92400e'],
        ['contradicted', counts.contradicted, '#fee2e2', '#b91c1c'],
        ['unsupported',  counts.unsupported,  '#e5e7eb', '#374151'],
        ['inferred',     counts.inferred,     '#dbeafe', '#1d4ed8'],
      ]
        .filter(([, count]) => count > 0)
        .map(
          ([name, count, bg, fg]) => `
            <span class="pill" style="background:${bg};color:${fg};">
              ${count} ${VERDICT_LABELS[name].toLowerCase()}
            </span>`,
        )
        .join('');

      const claimCards = (verification.claims || []).map((claim) => {
        const verdict = claim.verdict || 'unsupported';
        const cite = (claim.best_citation_index ?? null) !== null
          ? `Citation ${claim.best_citation_index + 1}`
          : 'no citation';
        const numericNote = claim.numeric_match === false
          ? ' · <strong style="color:#b91c1c;">numeric mismatch</strong>'
          : '';
        return `
          <div class="claim-card ${verdict}">
            <div class="claim-row">
              <div class="claim-text">${escapeHtml(claim.text)}</div>
              <span class="claim-verdict ${verdict}">${VERDICT_LABELS[verdict] || verdict}</span>
            </div>
            <div class="claim-meta">
              <strong>${cite}</strong>
              · sim ${(Number(claim.similarity_score || 0)).toFixed(2)}
              · overlap ${(Number(claim.token_overlap || 0)).toFixed(2)}
              · conf ${(Number(claim.confidence || 0)).toFixed(2)}${numericNote}
              <br><em>${escapeHtml(claim.reasoning || '')}</em>
            </div>
          </div>`;
      }).join('');

      shell.innerHTML = `
        <div class="verification-header">
          <div class="score-ring" style="--score:${Math.max(0, Math.min(100, score))};
               background: conic-gradient(${scoreColor} ${score}%, #e6ddd1 0);">
            <div class="score-ring-inner">
              ${score.toFixed(0)}
              <div class="score-ring-label">score</div>
            </div>
          </div>
          <div class="verification-summary">
            <div class="verification-summary-line">
              <strong>${escapeHtml(verification.summary || '')}</strong>
            </div>
            <div>${breakdownPills || '<span class="pill">no claims</span>'}</div>
            <div class="verification-meta">
              method: ${escapeHtml(verification.method || 'unknown')}
              · ${(Number(verification.latency_ms || 0)).toFixed(1)}ms
              · ${verification.total_claims || 0} claim(s)
            </div>
          </div>
        </div>
        <div class="claim-list">
          ${claimCards || '<div class="verification-empty">No verifiable claims detected in the answer.</div>'}
        </div>`;
    }

    function renderSummary(payload, mode) {
      const responseText = mode === 'analyze'
        ? 'Analyze mode only: no model output generated.'
        : (payload.response || 'No response content.');
      document.getElementById('answer').textContent = responseText;
      renderGroundedProof(payload);
      renderVerification(payload);

      const confidence = payload.routing_decision?.confidence_level
        || payload.pipeline?.confidence_level
        || '-';
      const commercialProfile = payload.simulation?.commercial_profile || null;
      const quality = payload.escalation?.quality_score
        ?? payload.trace?.quality?.score
        ?? '-';
      const walletBalance = payload.simulation?.wallet?.balance_after_usd
        ?? payload.simulation?.wallet_balance_usd
        ?? '-';
      const walletBefore = payload.simulation?.wallet?.balance_before_usd;
      const walletCharged = payload.simulation?.wallet?.charged_usd ?? 0;
      // Always surface the routing system's selected / commercial model, never
      // the free model that actually executed behind the scenes.
      const backingModel = payload.simulation?.commercial_profile?.display_name
        || payload.model_used
        || payload.trace?.selected_model?.display_name
        || '-';
      const backingCandidates = payload.simulation?.commercial_profile?.backing_model_display_names
        || payload.simulation?.backing_selection?.candidate_model_ids
        || [];

      // Show commercial model name as primary
      const displayModelName = commercialProfile
        ? commercialProfile.display_name
        : (payload.model_used || payload.selected_model?.name || '-');
      const displayTier = commercialProfile
        ? commercialProfile.tier
        : (payload.routing_decision?.tier || '-');

      document.getElementById('modelUsed').textContent = displayModelName;
      document.getElementById('simulatedModel').textContent = displayTier;
      document.getElementById('confidence').textContent = confidence;
      document.getElementById('quality').textContent = quality;
      document.getElementById('walletBalance').textContent =
        walletBalance === '-' ? '-' : `$${Number(walletBalance).toFixed(4)}`;
      document.getElementById('escalationCount').textContent =
        `$${Number(walletCharged).toFixed(4)}`;

      // Model pipeline chain
      document.getElementById('chainCommercial').textContent = commercialProfile
        ? `${commercialProfile.display_name} (${commercialProfile.tier})`
        : displayModelName;
      document.getElementById('chainBackend').textContent = backingModel;
      document.getElementById('chainFallback').textContent = backingCandidates.length
        ? backingCandidates.join(' → ')
        : 'router-managed';

      // Wallet meter
      const walletFill = document.getElementById('walletFill');
      if (walletBalance !== '-' && walletBefore && walletBefore > 0) {
        const percent = Math.max(0, Math.min(100, (Number(walletBalance) / Number(walletBefore)) * 100));
        walletFill.style.width = `${percent}%`;
      } else {
        walletFill.style.width = '0%';
      }

      // Storyboard cards
      const isSmartRouting = document.getElementById('model_selector').value === 'smart_routing';
      if (commercialProfile) {
        document.getElementById('storyCommercial').textContent =
          `${commercialProfile.display_name} (${commercialProfile.provider}) — ${commercialProfile.tier} tier model.`;
        if (isSmartRouting) {
          document.getElementById('storyExecution').textContent =
            `Smart Routing selected ${commercialProfile.display_name} based on query complexity and cost optimization.`;
        } else {
          document.getElementById('storyExecution').textContent =
            `Manually selected. A smart router would optimize cost by choosing the best model for each query.`;
        }
        document.getElementById('storyEconomics').textContent =
          `Charged $${Number(walletCharged).toFixed(4)} for this query. Remaining balance: $${Number(walletBalance || 0).toFixed(4)}.`;
        document.getElementById('walletSummary').textContent =
          `Billed at ${commercialProfile.display_name} rates: $${Number(walletCharged).toFixed(4)}. Balance: $${Number(walletBalance || 0).toFixed(4)}.`;
        document.getElementById('simulationDisclaimer').textContent =
          `Model: ${commercialProfile.display_name} | Tier: ${commercialProfile.tier} | Provider: ${commercialProfile.provider}`;
      } else {
        document.getElementById('storyCommercial').textContent = `${displayModelName} selected by the routing pipeline.`;
        document.getElementById('storyExecution').textContent = `Routed based on query analysis and cost optimization.`;
        document.getElementById('storyEconomics').textContent = `Query cost: $${Number(walletCharged).toFixed(4)}.`;
        document.getElementById('walletSummary').textContent = `Select a model to track wallet spending.`;
        document.getElementById('simulationDisclaimer').textContent =
          'Select a model from the dropdown to manually compare costs, or use Smart Routing to let the AI select the optimal model for each query.';
      }

      // Pills — show routing intelligence + backing model
      const pills = [];
      const routing = payload.routing_decision || {};
      const modality = routing.modality || payload.pipeline?.layer1_modality?.primary_modality;
      const intent = routing.intent || payload.pipeline?.layer3_triage?.intent;
      const domain = routing.domain || payload.pipeline?.layer3_triage?.domain || payload.pipeline?.grounded_domain;
      const complexity = routing.complexity || payload.pipeline?.layer3_triage?.complexity_band;
      if (modality) pills.push(`modality: ${modality}`);
      if (intent) pills.push(`intent: ${intent}`);
      if (domain) pills.push(`domain: ${domain}`);
      if (complexity) pills.push(`complexity: ${complexity}`);
      if (routing.memory_hit) pills.push('semantic memory hit');
      if (routing.fast_path) pills.push('fast path');
      if (payload.trace?.execution?.ttc_used) pills.push(`ttc: ${payload.trace.execution.ttc_strategy}`);
      // (Intentionally NOT surfacing the free backing model — the demo shows the
      //  routing system's selected / commercial model only.)
      if (payload.grounded || payload.pipeline?.grounded_collection_id) {
        pills.push(`grounded collection: ${payload.grounded_collection_id || payload.pipeline?.grounded_collection_id}`);
      }
      // Benchmark Router recommendation
      const benchRec = payload.trace?.layers?.layer5_5_benchmark_router || payload.pipeline?.layer5_5_benchmark_router;
      if (benchRec && benchRec.model_id) {
        pills.push(`benchmark router: ${benchRec.model_id} (${benchRec.tier || 'n/a'}, quality=${Number(benchRec.quality || 0).toFixed(2)})`);
      }
      document.getElementById('pills').innerHTML = pills.map((x) => `<span class="pill">${x}</span>`).join('');
    }

    async function runDemo() {
      const message = document.getElementById('message').value.trim();
      const groundedCollectionId = document.getElementById('grounded_collection_id').value.trim();
      const groundedTenantId = document.getElementById('grounded_tenant_id').value.trim() || 'default';
      const groundedDomain = document.getElementById('grounded_domain').value.trim();
      if (!message) {
        setStatus('Enter a query first.', true);
        return;
      }

      const mode = document.getElementById('mode').value;
      const selectedModel = document.getElementById('model_selector').value;
      const isSmartRouting = selectedModel === 'smart_routing';
      const profileId = isSmartRouting ? null : selectedModel;
      const runButton = document.getElementById('runButton');
      runButton.disabled = true;
      setStatus('Running pipeline...');

      try {
        let payload;
        if (mode === 'analyze') {
          const queryObject = {
            message,
            has_images: 'false',
            has_audio: 'false',
            user_tier: document.getElementById('user_tier').value,
            budget_remaining: String(Number(document.getElementById('budget_remaining').value)),
            demo_mode: 'true',
            simulation_session_id: 'demo',
          };
          if (profileId) queryObject.simulation_profile_id = profileId;
          if (groundedCollectionId) {
            queryObject.grounded_collection_id = groundedCollectionId;
            queryObject.grounded_tenant_id = groundedTenantId;
            if (groundedDomain) queryObject.grounded_domain = groundedDomain;
          }
          const query = new URLSearchParams(queryObject);
          const response = await fetch(`/chat/analyze?${query.toString()}`, { method: 'POST' });
          payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || 'Analyze request failed');
        } else {
          const requestBody = {
            message,
            user_tier: document.getElementById('user_tier').value,
            budget_remaining: Number(document.getElementById('budget_remaining').value),
            demo_mode: true,
            simulation_profile_id: profileId,
            simulation_session_id: 'demo',
            verify_claims: document.getElementById('verify_claims').checked,
            verification_use_embeddings: document.getElementById('verify_use_embeddings').checked,
          };
          if (groundedCollectionId) {
            requestBody.grounded_collection_id = groundedCollectionId;
            requestBody.grounded_tenant_id = groundedTenantId;
            if (groundedDomain) requestBody.grounded_domain = groundedDomain;
          }
          const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(requestBody),
            });
          payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || 'Chat request failed');
        }

        renderSummary(payload, mode);
        document.getElementById('trace').textContent = JSON.stringify(payload, null, 2);
        setStatus('Completed successfully.');
      } catch (error) {
        setStatus(error.message || String(error), true);
      } finally {
        runButton.disabled = false;
      }
    }

    loadCommercialModels();
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# POST /chat   —  the core endpoint
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ChatResponse,
    summary="Smart Chat",
    description="Chat with automatic model routing, quality gating, and auto-escalation.",
)
async def smart_chat(request: ChatRequest) -> ChatResponse:
    """
    Full elite pipeline end-to-end.

    1. Route   – picks the cheapest model that should work.
    2. Call    – sends the request to that model.
    3. Verify  – quality eval + escalation if needed (transparent to user).
    4. Learn   – pushes reward back into the bandit.
    """
    logger.info("smart_chat_request_received",
                message_length=len(request.message), force_model=request.force_model_id)

    try:
        if request.grounded_collection_id:
            started_at = time.time()
            grounded_response = await grounded_collection_service.answer_query(
                collection_id=request.grounded_collection_id,
                query=request.message,
                tenant_id=request.grounded_tenant_id,
                domain=request.grounded_domain,
                top_k=request.grounded_top_k,
            )
            grounded_verification = await _maybe_verify_claims(
                enabled=request.verify_claims,
                answer=grounded_response.answer,
                citations=grounded_response.citations,
                use_embeddings=request.verification_use_embeddings,
            )
            return _build_grounded_chat_response(
                collection_id=request.grounded_collection_id,
                tenant_id=request.grounded_tenant_id,
                domain=request.grounded_domain,
                grounded_response=grounded_response,
                latency_ms=(time.time() - started_at) * 1000,
                verification=grounded_verification,
            )

        # Use Elite Execution Orchestrator
        from src.layer2_orchestrator.execution_loop import get_orchestrator
        orchestrator = get_orchestrator()
        simulation_payload = None
        session_id = request.session_id or "default"

        if request.demo_mode:
            analyzed_decision = model_router.route(
                query=request.message,
                has_images=request.has_images,
                has_audio=request.has_audio,
                image_count=request.image_count,
                has_video=request.has_video,
                file_types=request.file_types,
                attachment_sizes_mb=request.attachment_sizes_mb,
                user_tier=request.user_tier,
                budget_remaining=request.budget_remaining,
            )
            profile = (
                get_or_create_profile(request.simulation_profile_id)
                if request.simulation_profile_id
                else choose_demo_profile(None, analyzed_decision)
            )
            backing_model_id = choose_backing_model_id(profile)
            result = await orchestrator.execute(
                query=request.message,
                force_model_id=backing_model_id,
                routing_decision=analyzed_decision,  # reuse the analyze pass; don't route twice
                has_images=request.has_images,
                has_audio=request.has_audio,
                image_count=request.image_count,
                has_video=request.has_video,
                file_types=request.file_types,
                attachment_sizes_mb=request.attachment_sizes_mb,
                session_id=session_id,
                user_tier=request.user_tier,
                budget_remaining=request.budget_remaining,
            )
            decision = analyzed_decision
            wallet_session_id = request.simulation_session_id or session_id
            wallet_charge = charge_demo_wallet(
                session_id=wallet_session_id,
                profile=profile,
                prompt=request.message,
                response=result.content,
            )
            simulation_payload = {
                "enabled": True,
                "commercial_profile": profile.to_dict(),
                "wallet": wallet_charge,
                "actual_execution": {
                    "model_id": result.routing_decision.selected_model.model_id,
                    "display_name": result.model_used,
                    "provider": result.routing_decision.selected_model.provider,
                    "actual_cost_usd": result.total_cost_usd,
                },
                "backing_selection": {
                    "chosen_model_id": backing_model_id,
                    "candidate_model_ids": list(profile.backing_model_ids),
                },
            }
        else:
            analyzed_decision = model_router.route(
                query=request.message,
                has_images=request.has_images,
                has_audio=request.has_audio,
                image_count=request.image_count,
                has_video=request.has_video,
                file_types=request.file_types,
                attachment_sizes_mb=request.attachment_sizes_mb,
                force_model_id=request.force_model_id,
                user_tier=request.user_tier,
                budget_remaining=request.budget_remaining,
            )
            result = await orchestrator.execute(
                query=request.message,
                force_model_id=request.force_model_id,
                routing_decision=analyzed_decision,
                has_images=request.has_images,
                has_audio=request.has_audio,
                image_count=request.image_count,
                has_video=request.has_video,
                file_types=request.file_types,
                attachment_sizes_mb=request.attachment_sizes_mb,
                session_id=session_id,
                user_tier=request.user_tier,
                budget_remaining=request.budget_remaining,
            )
            decision = analyzed_decision

        # Non-grounded chat normally has no citations to verify against, but
        # we still surface a verification block when explicitly requested so
        # the user can SEE that an ungrounded answer is unverified — that's
        # itself a useful trust signal in the demo.
        nongrounded_verification = await _maybe_verify_claims(
            enabled=request.verify_claims,
            answer=result.content,
            citations=[],
            use_embeddings=request.verification_use_embeddings,
        )

        return ChatResponse(
            response=result.content,
            # Always report the model the ROUTER selected, never the free fallback
            # the gateway may run behind the scenes (rate-limit / keyless premium).
            model_used=decision.selected_model.display_name,
            routing_decision={
                "reasoning":          decision.routing_reasoning,
                "confidence_level":   decision.confidence_level,
                "fast_path":          decision.pipeline_metadata.get("fast_path_triggered", False) if decision.pipeline_metadata else False,
                "memory_hit":         decision.pipeline_metadata.get("semantic_memory_hit", False) if decision.pipeline_metadata else False,
                # "novelty_score":      decision.pipeline_metadata.get("novelty_score", 0.0) if decision.pipeline_metadata else 0.0,
                "modality":           decision.modality_analysis.get("primary_modality"),
                "intent":             decision.triage_result.get("intent"),
                "domain":             decision.triage_result.get("domain"),
                "complexity":         decision.triage_result.get("complexity_band"),
                # "ambiguity":          decision.triage_result.get("ambiguity", {}),
                "uncertainty_score":  decision.uncertainty_score.get("total_uncertainty"),
                # "input_difficulty":   decision.bandit_context.get("input_difficulty", 0.0) if decision.bandit_context else 0.0,
                "fallback_models": [
                    m.display_name for m in decision.fallback_models
                ],
            },
            cost={
                "total_cost_usd":      result.total_cost_usd,
                "estimated_cost_usd":  decision.estimated_cost_usd,
                "provider":            decision.selected_model.provider,
                "is_free":             result.total_cost_usd == 0.0,
            },
            performance={
                "total_latency_ms":      result.total_latency_ms,
            },
            escalation={
                "escalation_available":       decision.escalation_path_available,
                "escalation_levels_possible": decision.escalation_levels,
                "escalated":                  result.escalation_count > 0,
                "escalation_count":           result.escalation_count,
                "quality_passed":             result.quality_passed,
                "quality_score":              result.quality_score,
            },
            trace={
                "selected_model": {
                    "model_id": decision.selected_model.model_id,
                    "display_name": decision.selected_model.display_name,
                    "provider": decision.selected_model.provider,
                    "model_type": decision.selected_model.model_type,
                },
                "layers": {
                    "layer1_modality": decision.modality_analysis,
                    "layer3_triage": decision.triage_result,
                    "layer4_uncertainty": decision.uncertainty_score,
                    "layer5_bandit_context": decision.bandit_context,
                    "layer5_5_benchmark_router": decision.benchmark_recommendation,
                    "pipeline_metadata": decision.pipeline_metadata,
                },
                "execution": result.execution_metadata,
                "quality": {
                    "passed": result.quality_passed,
                    "score": result.quality_score,
                    "reasoning": result.quality_reasoning,
                },
            },
            simulation=simulation_payload,
            grounded=False,
            grounded_collection_id=None,
            citations=[],
            page_proofs=[],
            evidence_groups=[],
            verification=nongrounded_verification,
        )

    except CollectionNotFoundError as e:
        logger.error("grounded_collection_not_found", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )

    except NoRelevantContextError as e:
        logger.warning("grounded_chat_no_context", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )

    except ModelNotFoundError as e:
        logger.error("model_not_found", error=str(e))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Model not found: {e.message}")

    except ModelError as e:
        logger.error("model_error", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Model error: {e.message}")

    except ValueError as e:
        logger.error("demo_mode_validation_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        logger.error("smart_chat_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Chat failed: {str(e)}")


@router.get(
    "/demo",
    response_class=HTMLResponse,
    summary="Interactive Demo UI",
    description="Browser-based presentation UI for live demos with full routing trace.",
)
async def demo_ui() -> HTMLResponse:
    """Serve a lightweight demo page for presentations and live review."""
    return HTMLResponse(content=DEMO_HTML)


# ---------------------------------------------------------------------------
# POST /chat/analyze   —  dry-run: see routing decision without LLM call
# ---------------------------------------------------------------------------


@router.post(
    "/analyze",
    summary="Analyze Query (dry-run)",
    description="Run the full pre-LLM routing pipeline and return the decision. No LLM call is made.",
)
async def analyze_query(
    message:    str,
    has_images: bool = False,
    has_audio:  bool = False,
    user_tier: str = "standard",
    budget_remaining: float = 1.0,
    demo_mode: bool = False,
    simulation_profile_id: Optional[str] = None,
    simulation_session_id: str = "demo",
    grounded_collection_id: Optional[str] = None,
    grounded_tenant_id: str = "default",
    grounded_domain: Optional[str] = None,
    grounded_top_k: int = 6,
) -> dict:
    """
    Useful for debugging / testing routing without burning tokens.
    Returns the same data that would be in ChatResponse.routing_decision,
    plus the full layer-by-layer breakdown.
    """
    try:
        if grounded_collection_id:
            payload = await grounded_collection_service.analyze_query(
                collection_id=grounded_collection_id,
                query=message,
                tenant_id=grounded_tenant_id,
                domain=grounded_domain,
                top_k=grounded_top_k,
            )
            return {
                "selected_model": {
                    "id": "grounded-rag",
                    "name": "grounded-rag",
                    "provider": "grounded-rag",
                    "model_type": "retrieval_augmented_generation",
                    "cost_per_1k": 0.0,
                },
                "pipeline": {
                    "grounded_collection_id": grounded_collection_id,
                    "grounded_tenant_id": grounded_tenant_id,
                    "grounded_domain": grounded_domain,
                    "retrieval_count": payload["retrieval_count"],
                    "page_proofs": payload["page_proofs"],
                    "citations": payload["citations"],
                    "evidence_groups": payload["evidence_groups"],
                    "context_blocks": payload["context_blocks"],
                    "confidence_level": "grounded",
                },
                "routing_reasoning": "Grounded collection analysis path selected.",
                "estimated_cost_usd": 0.0,
                "escalation": {
                    "available": False,
                    "levels": 0,
                },
                "fallback_models": [],
                "simulation": None,
            }

        decision = model_router.route(
            query=message,
            has_images=has_images,
            has_audio=has_audio,
            user_tier=user_tier,
            budget_remaining=budget_remaining,
        )

        simulation = None
        if demo_mode:
            profile = (
                get_or_create_profile(simulation_profile_id)
                if simulation_profile_id
                else choose_demo_profile(None, decision)
            )
            simulation = {
                "enabled": True,
                "commercial_profile": profile.to_dict(),
                "wallet_balance_usd": get_demo_wallet_balance(simulation_session_id),
            }

        return {
            "selected_model": {
                "id":       decision.selected_model.model_id,
                "name":     decision.selected_model.display_name,
                "provider": decision.selected_model.provider,
                "model_type": decision.selected_model.model_type,
                "cost_per_1k": (
                    decision.selected_model.pricing.input_cost_per_1k_tokens
                    + decision.selected_model.pricing.output_cost_per_1k_tokens
                ),
            },
            "pipeline": {
                "fast_path_triggered": decision.pipeline_metadata.get("fast_path_triggered", False),
                "semantic_memory_hit": decision.pipeline_metadata.get("semantic_memory_hit", False),
                "layer1_modality": decision.modality_analysis,
                "layer3_triage": decision.triage_result,
                "layer4_uncertainty": decision.uncertainty_score,
                "layer5_bandit_context": decision.bandit_context,
                "layer5_5_benchmark_router": decision.benchmark_recommendation,
                "pipeline_metadata": decision.pipeline_metadata,
                "confidence_level":     decision.confidence_level,
            },
            "routing_reasoning":  decision.routing_reasoning,
            "estimated_cost_usd": decision.estimated_cost_usd,
            "escalation": {
                "available": decision.escalation_path_available,
                "levels":    decision.escalation_levels,
            },
            "fallback_models": [
                {"id": m.model_id, "name": m.display_name}
                for m in decision.fallback_models
            ],
            "simulation": simulation,
        }

    except CollectionNotFoundError as e:
        logger.error("grounded_query_analysis_collection_not_found", error=str(e))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)

    except NoRelevantContextError as e:
        logger.warning("grounded_query_analysis_no_context", error=str(e))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)

    except ValueError as e:
        logger.error("query_analysis_validation_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        logger.error("query_analysis_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Analysis failed: {str(e)}")


@router.get(
    "/demo/profiles",
    summary="List Demo Profiles",
    description="List commercial model profiles that can be simulated while executing on free/local models.",
)
async def demo_profiles() -> dict:
    """Return the available demo simulation profiles."""
    return {
        "profiles": list_demo_profiles(),
        "default_wallet_usd": get_demo_wallet_balance("demo"),
        "note": "Simulation mode is presentation-only and keeps execution on local/free backing models.",
    }


@router.post(
    "/demo/wallet/reset",
    summary="Reset Demo Wallet",
    description="Reset the wallet for a demo session.",
)
async def reset_wallet(session_id: str = "demo") -> dict:
    """Reset a demo wallet to its configured starting balance."""
    return reset_demo_wallet(session_id)


@router.get(
    "/demo/wallet/balance",
    summary="Get Wallet Balance",
    description="Get the current wallet balance for a demo session.",
)
async def wallet_balance(session_id: str = "demo") -> dict:
    """Return the current wallet balance."""
    return {
        "session_id": session_id,
        "balance_usd": get_demo_wallet_balance(session_id),
    }


@router.get(
    "/demo/commercial-models",
    summary="List Commercial Models",
    description="Return all commercial LLM models available for selection in the demo, sourced from benchmark data.",
)
async def commercial_models() -> dict:
    """Return all commercial models from benchmark data for the demo dropdown."""
    return {
        "models": list_commercial_models(),
        "default_wallet_usd": get_demo_wallet_balance("demo"),
    }


# ---------------------------------------------------------------------------
# POST /chat/verify   —  ad-hoc claim verification (no LLM call required)
# ---------------------------------------------------------------------------


class VerifyRequest(BaseModel):
    """Verify an arbitrary answer against a list of citations."""

    answer: str = Field(..., min_length=1, description="Answer text to verify")
    citations: list[dict] = Field(
        default_factory=list,
        description=(
            "Citations to verify against. Each item must have at least a "
            "'snippet' field; 'title', 'page_number', 'section_title', 'score' "
            "are optional but improve the report metadata."
        ),
    )
    use_embeddings: bool = Field(
        default=True,
        description="When false, run a lexical-only check (no embedding call).",
    )


@router.post(
    "/verify",
    summary="Verify Claims (no LLM call)",
    description=(
        "Decompose an answer into atomic claims and verify each against the "
        "provided citations using embedding + lexical signals. Returns a "
        "verifiability score (0-100) and per-claim verdicts. This endpoint "
        "performs no LLM generation — only one batch embedding call. "
        "Use it as a dry-run inspector or for post-hoc auditing."
    ),
)
async def verify_claims_endpoint(request: VerifyRequest) -> dict:
    """Standalone Verifiable Reasoning entry point."""
    try:
        report = await claim_verifier.verify(
            answer=request.answer,
            citations=request.citations,
            use_embeddings=request.use_embeddings,
        )
        return report.model_dump()
    except Exception as exc:
        logger.error("verify_claims_endpoint_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Verification failed: {exc}",
        )
