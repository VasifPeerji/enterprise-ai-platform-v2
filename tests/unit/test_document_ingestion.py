import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer3_domain.document_ingestion import ChunkingConfig, DocumentChunker  # noqa: E402
from src.layer3_domain.document_models import IngestedDocument, IngestedPage  # noqa: E402


def _make_page(
    document_id: str,
    page_number: int,
    text: str,
    *,
    title: str = "Loan Agreement",
    section_title: str | None = None,
    tenant_id: str = "tenant-a",
    domain: str = "lending",
) -> IngestedPage:
    return IngestedPage(
        document_id=document_id,
        tenant_id=tenant_id,
        domain=domain,
        title=title,
        source_uri=f"/docs/{document_id}.pdf",
        source_type="pdf",
        page_number=page_number,
        text=text,
        section_title=section_title,
        language="en",
    )


def test_document_chunker_preserves_page_boundaries():
    doc = IngestedDocument(
        document_id="loan-doc",
        tenant_id="tenant-a",
        domain="lending",
        title="Loan Agreement",
        source_uri="/docs/loan-doc.pdf",
        pages=[
            _make_page("loan-doc", 1, "Clause A.\n\nClause B."),
            _make_page("loan-doc", 2, "Clause C.\n\nClause D."),
        ],
    )

    chunker = DocumentChunker(ChunkingConfig(target_chars=40, overlap_chars=10, min_chunk_chars=5))
    chunks = chunker.chunk_document(doc)

    assert chunks
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.document_id == "loan-doc" for chunk in chunks)


def test_document_chunker_creates_multiple_chunks_for_long_page():
    page_text = (
        "Processing fee is charged once at disbursal.\n\n"
        "Foreclosure charges are 2% of outstanding principal plus taxes.\n\n"
        "Late payment penalty applies after the grace period ends.\n\n"
        "Prepayment requests are processed within seven working days."
    )
    page = _make_page("loan-doc", 3, page_text, section_title="Charges and Payments")

    chunker = DocumentChunker(ChunkingConfig(target_chars=90, overlap_chars=35, min_chunk_chars=20))
    chunks = chunker.chunk_page(page)

    assert len(chunks) >= 2
    assert chunks[0].page_number == 3
    assert chunks[0].section_title == "Charges and Payments"
    assert all(chunk.metadata["source_type"] == "pdf" for chunk in chunks)


def test_document_chunker_supports_multiple_documents():
    docs = [
        IngestedDocument(
            document_id="agreement",
            tenant_id="tenant-a",
            domain="lending",
            title="Loan Agreement",
            source_uri="/docs/agreement.pdf",
            pages=[_make_page("agreement", 1, "Agreement page one.")],
        ),
        IngestedDocument(
            document_id="brochure",
            tenant_id="tenant-a",
            domain="lending",
            title="Product Brochure",
            source_uri="/docs/brochure.pdf",
            pages=[_make_page("brochure", 1, "Brochure page one.", title="Product Brochure")],
        ),
    ]

    chunker = DocumentChunker()
    chunks = chunker.chunk_many(docs)

    assert len(chunks) == 2
    assert {chunk.document_id for chunk in chunks} == {"agreement", "brochure"}


def test_document_chunker_preserves_offsets_for_highlighting():
    text = "Foreclosure charges are 2% of outstanding principal.\n\nLate fee is 500 rupees."
    page = _make_page("loan-doc", 4, text)

    chunker = DocumentChunker(ChunkingConfig(target_chars=65, overlap_chars=0, min_chunk_chars=10))
    chunks = chunker.chunk_page(page)

    assert chunks
    first = chunks[0]
    assert text[first.start_char:first.end_char] == first.content


def test_document_chunker_splits_article_numbered_pages():
    text = (
        "15. Prohibition of discrimination on grounds of religion, race, caste, sex or place of birth. "
        "The State shall not discriminate against any citizen on grounds only of religion, race, caste, sex, place of birth or any of them. "
        "17. Abolition of Untouchability. Untouchability is abolished and its practice in any form is forbidden."
    )
    page = _make_page("constitution", 1, text, title="Constitution of India", domain="law")

    chunks = DocumentChunker().chunk_page(page)

    assert len(chunks) == 2
    assert chunks[0].metadata["article_number"] == "15"
    assert chunks[1].metadata["article_number"] == "17"
    assert chunks[1].section_title == "Article 17: Abolition of Untouchability."


def test_document_chunker_preserves_rag_optimized_medical_pdf_page():
    text = (
        "Metformin Hydrochloride\n"
        "Renal Impairment\n\n"
        "Assess renal function before initiation and periodically thereafter. "
        "Metformin is contraindicated in patients with severe renal impairment."
    )
    page = _make_page(
        "metformin",
        7,
        text,
        title="Metformin.pdf",
        domain="medicine",
    ).model_copy(
        update={
            "source_type": "pdf",
            "section_title": "Renal Impairment",
            "metadata": {
                "drug_name": "Metformin",
                "section_name": "Renal Impairment",
                "rag_section_boundary": "page",
            },
        }
    )

    chunks = DocumentChunker().chunk_page(page)

    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].page_number == 7
    assert chunks[0].metadata["drug_name"] == "Metformin"
    assert chunks[0].metadata["section_name"] == "Renal Impairment"
