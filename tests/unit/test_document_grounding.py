import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer1_intelligence.document_grounding import (  # noqa: E402
    InMemoryDocumentRetriever,
    build_citation,
    locate_highlight_span,
)
from src.layer3_domain.document_models import DocumentChunk, RetrievalQuery  # noqa: E402


def _make_chunk(
    chunk_id: str,
    page_number: int,
    content: str,
    *,
    section_title: str | None = None,
    domain: str = "lending",
    tenant_id: str = "tenant-a",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        tenant_id=tenant_id,
        domain=domain,
        title="Loan Agreement",
        source_uri="/docs/loan-agreement.pdf",
        page_number=page_number,
        page_text=content,
        content=content,
        section_title=section_title,
        start_char=0,
        end_char=len(content),
    )


def test_locate_highlight_span_handles_whitespace_and_punctuation_variation():
    source = "Foreclosure charges: 2% of principal outstanding, plus applicable taxes."
    snippet = "foreclosure charges 2 of principal outstanding"

    span = locate_highlight_span(source, snippet)

    assert span is not None
    assert span.start_char == 0
    assert "Foreclosure charges" in span.text


def test_build_citation_includes_page_and_highlight():
    chunk = _make_chunk(
        "chunk-1",
        4,
        "Prepayment penalty is 2% of the outstanding principal amount.",
        section_title="Foreclosure and Prepayment",
    )

    citation = build_citation(chunk, score=0.91, snippet="2% of the outstanding principal")

    assert citation.page_number == 4
    assert citation.title == "Loan Agreement"
    assert citation.highlights
    assert citation.highlights[0].text == "2% of the outstanding principal"


def test_build_citation_uses_page_offsets_for_proof_highlights():
    page_text = "Clause one.\n\nPrepayment penalty is 2% of the outstanding principal amount."
    chunk = DocumentChunk(
        chunk_id="chunk-2",
        document_id="doc-1",
        tenant_id="tenant-a",
        domain="lending",
        title="Loan Agreement",
        source_uri="/docs/loan-agreement.pdf",
        page_number=4,
        page_text=page_text,
        content="Prepayment penalty is 2% of the outstanding principal amount.",
        section_title="Foreclosure and Prepayment",
        start_char=12,
        end_char=len(page_text),
    )

    citation = build_citation(chunk, score=0.91, snippet="2% of the outstanding principal")

    assert citation.highlights
    assert citation.highlights[0].start_char == page_text.index("2% of the outstanding principal")


def test_in_memory_retriever_prioritizes_exact_clause_matches():
    retriever = InMemoryDocumentRetriever(
        [
            _make_chunk(
                "chunk-1",
                2,
                "Late payment fee is 500 rupees per missed EMI.",
                section_title="Charges",
            ),
            _make_chunk(
                "chunk-2",
                5,
                "Foreclosure charges are 2% of the principal outstanding.",
                section_title="Foreclosure",
            ),
            _make_chunk(
                "chunk-3",
                7,
                "Customer support is available Monday to Saturday.",
                section_title="Support",
            ),
        ]
    )

    results = retriever.search(
        RetrievalQuery(
            query="What are the foreclosure charges?",
            tenant_id="tenant-a",
            domain="lending",
            top_k=2,
        )
    )

    assert len(results) == 2
    assert results[0].chunk.chunk_id == "chunk-2"
    assert "foreclosure" in results[0].matched_terms


def test_in_memory_retriever_honors_tenant_filters():
    retriever = InMemoryDocumentRetriever(
        [
            _make_chunk("tenant-a-chunk", 1, "EMI amount is 25000 rupees.", tenant_id="tenant-a"),
            _make_chunk("tenant-b-chunk", 1, "EMI amount is 41000 rupees.", tenant_id="tenant-b"),
        ]
    )

    results = retriever.search(
        RetrievalQuery(query="What is the EMI amount?", tenant_id="tenant-b", top_k=3)
    )

    assert len(results) == 1
    assert results[0].chunk.chunk_id == "tenant-b-chunk"
