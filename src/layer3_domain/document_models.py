"""
Document grounding models shared across Layer 1 and Layer 3.

These models are intentionally provider- and vector-store-agnostic so the
platform can switch retrieval backends without changing the grounding contract
exposed to the rest of the system.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """Atomic retrievable unit with page-aware provenance."""

    chunk_id: str = Field(..., description="Unique ID for the chunk")
    document_id: str = Field(..., description="Parent document ID")
    tenant_id: str = Field(default="default", description="Tenant isolation key")
    domain: str = Field(default="general", description="Domain or subdomain label")
    title: str = Field(..., description="Human-readable document title")
    source_uri: str = Field(..., description="Canonical source path or URI")
    page_number: int = Field(..., ge=1, description="1-based page number")
    page_text: str = Field(..., min_length=1, description="Normalized full page text for proof rendering")
    content: str = Field(..., min_length=1, description="Chunk text content")
    page_width: float = Field(default=0.0, ge=0.0, description="Source page width in PDF points (0 if unknown)")
    page_height: float = Field(default=0.0, ge=0.0, description="Source page height in PDF points (0 if unknown)")
    section_title: Optional[str] = Field(default=None, description="Optional section heading")
    start_char: int = Field(default=0, ge=0, description="Original page start offset")
    end_char: int = Field(default=0, ge=0, description="Original page end offset")
    metadata: dict[str, str] = Field(default_factory=dict, description="Additional retrieval metadata")


class IngestedPage(BaseModel):
    """Normalized page-level source unit produced by parsers/OCR/ETL."""

    document_id: str = Field(..., description="Parent document ID")
    tenant_id: str = Field(default="default", description="Tenant isolation key")
    domain: str = Field(default="general", description="Domain or subdomain label")
    title: str = Field(..., description="Human-readable document title")
    source_uri: str = Field(..., description="Canonical source path or URI")
    source_type: str = Field(default="pdf", description="pdf|table|database|api|web|text")
    page_number: int = Field(..., ge=1, description="1-based page number")
    text: str = Field(..., min_length=1, description="Normalized extracted text for the page")
    width: float = Field(default=0.0, ge=0.0, description="Source page width in PDF points (0 if unknown)")
    height: float = Field(default=0.0, ge=0.0, description="Source page height in PDF points (0 if unknown)")
    section_title: Optional[str] = Field(default=None, description="Optional section heading")
    language: str = Field(default="en", description="Primary language for the page")
    metadata: dict[str, str] = Field(default_factory=dict, description="Additional source metadata")


class IngestedDocument(BaseModel):
    """Whole document with ordered pages ready for chunking."""

    document_id: str = Field(..., description="Unique document ID")
    tenant_id: str = Field(default="default", description="Tenant isolation key")
    domain: str = Field(default="general", description="Domain or subdomain label")
    title: str = Field(..., description="Human-readable document title")
    source_uri: str = Field(..., description="Canonical source path or URI")
    source_type: str = Field(default="pdf", description="Primary source type")
    language: str = Field(default="en", description="Primary document language")
    pages: list[IngestedPage] = Field(..., min_length=1, description="Ordered extracted pages")
    metadata: dict[str, str] = Field(default_factory=dict, description="Document metadata")


class HighlightSpan(BaseModel):
    """Exact span to highlight inside a page or chunk."""

    start_char: int = Field(..., ge=0, description="Inclusive start offset")
    end_char: int = Field(..., gt=0, description="Exclusive end offset")
    text: str = Field(..., description="Matched text from the source")


class SourceCitation(BaseModel):
    """Grounding citation attached to an answer."""

    document_id: str = Field(..., description="Document identifier")
    chunk_id: str = Field(..., description="Chunk identifier")
    title: str = Field(..., description="Source title")
    source_uri: str = Field(..., description="Source path or URI")
    page_number: int = Field(..., ge=1, description="1-based page number")
    section_title: Optional[str] = Field(default=None, description="Section heading if known")
    snippet: str = Field(..., description="Source snippet supporting the answer")
    snippet_truncated: bool = Field(
        default=False,
        description="Whether the snippet is an exact truncated excerpt of a longer chunk",
    )
    score: float = Field(
        ...,
        description=(
            "Retrieval relevance score. May be negative when a reranker subtracts "
            "domain penalties (e.g. article-mismatch penalty) — negative just means "
            "'less relevant than baseline', not invalid."
        ),
    )
    highlights: list[HighlightSpan] = Field(
        default_factory=list,
        description="Highlight spans inside the full page text for rendering exact source proof",
    )


class PageProof(BaseModel):
    """Exact page-level proof payload for UI rendering and auditability."""

    document_id: str = Field(..., description="Document identifier")
    title: str = Field(..., description="Source title")
    source_uri: str = Field(..., description="Source path or URI")
    page_number: int = Field(..., ge=1, description="1-based page number")
    section_title: Optional[str] = Field(default=None, description="Section heading if known")
    page_text: str = Field(..., description="Full normalized page text used to render the proof")
    highlights: list[HighlightSpan] = Field(
        default_factory=list,
        description="Exact highlight spans inside page_text",
    )
    citation_indices: list[int] = Field(
        default_factory=list,
        description="Indices into the top-level citations array that map to this page",
    )


class EvidenceGroup(BaseModel):
    """A grouped claim-support unit spanning one or more citations."""

    claim_label: str = Field(..., description="Short label for the supported claim")
    summary: str = Field(..., description="Human-readable support summary")
    citation_indices: list[int] = Field(
        default_factory=list,
        description="Indices into the top-level citations array",
        min_length=1,
    )


class GroundedAnswerContext(BaseModel):
    """
    Retrieval-backed context payload for answer generation and UI rendering.

    The answer text itself may be generated later by an LLM or filled manually,
    but the grounding payload shape stays consistent.
    """

    query: str = Field(..., description="Original user query")
    answer: str = Field(default="", description="Answer text if already assembled/generated")
    citations: list[SourceCitation] = Field(
        default_factory=list,
        description="Ordered citations supporting the answer",
    )
    page_proofs: list[PageProof] = Field(
        default_factory=list,
        description="Exact page-level proof payloads with full text and highlight spans",
    )
    evidence_groups: list[EvidenceGroup] = Field(
        default_factory=list,
        description="Grouped support units across one or more citations",
    )
    context_blocks: list[str] = Field(
        default_factory=list,
        description="Prompt/context blocks prepared for downstream answer generation",
    )


class RetrievalQuery(BaseModel):
    """Normalized retrieval request."""

    query: str = Field(..., min_length=1, description="User or system retrieval query")
    tenant_id: str = Field(default="default", description="Tenant isolation key")
    domain: Optional[str] = Field(default=None, description="Optional domain filter")
    top_k: int = Field(default=5, ge=1, le=20, description="Maximum number of results")


class RetrievalResult(BaseModel):
    """Ranked retrieval result with chunk payload and citation-ready metadata."""

    chunk: DocumentChunk = Field(..., description="Retrieved chunk")
    score: float = Field(
        ...,
        description=(
            "Backend relevance score. May be negative after rerank penalties — "
            "negative means 'less relevant than baseline', not invalid."
        ),
    )
    matched_terms: list[str] = Field(default_factory=list, description="Matched lexical hints")
