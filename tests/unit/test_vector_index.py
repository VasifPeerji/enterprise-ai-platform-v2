import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer1_intelligence.vector_index import (  # noqa: E402
    DeterministicEmbeddingProvider,
    DocumentIndexService,
    InMemoryVectorStore,
    rerank_results,
)
from src.layer3_domain.document_models import IngestedDocument, IngestedPage, RetrievalQuery  # noqa: E402


def _make_document(document_id: str, title: str, page_texts: list[str]) -> IngestedDocument:
    return IngestedDocument(
        document_id=document_id,
        tenant_id="tenant-a",
        domain="lending",
        title=title,
        source_uri=f"/docs/{document_id}.pdf",
        pages=[
            IngestedPage(
                document_id=document_id,
                tenant_id="tenant-a",
                domain="lending",
                title=title,
                source_uri=f"/docs/{document_id}.pdf",
                source_type="pdf",
                page_number=index + 1,
                text=text,
                section_title="Charges" if "charge" in text.lower() else "Overview",
                language="en",
            )
            for index, text in enumerate(page_texts)
        ],
    )


def test_document_index_service_indexes_and_searches_documents():
    service = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
    )
    documents = [
        _make_document(
            "agreement",
            "Loan Agreement",
            [
                "Foreclosure charges are 2% of the outstanding principal.",
                "Late payment fee is 500 rupees per missed EMI.",
            ],
        ),
        _make_document(
            "brochure",
            "Product Brochure",
            [
                "Flexible repayment options are available for salaried customers.",
            ],
        ),
    ]

    async def _run() -> tuple[list, list]:
        chunks = await service.index_documents(documents)
        results = await service.search(
            RetrievalQuery(
                query="What are the foreclosure charges?",
                tenant_id="tenant-a",
                domain="lending",
                top_k=3,
            )
        )
        return chunks, results

    chunks, results = asyncio.run(_run())

    assert chunks
    assert results
    assert results[0].chunk.document_id == "agreement"
    assert "Foreclosure charges" in results[0].chunk.content


def test_document_index_service_respects_tenant_filters():
    service = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
    )
    allowed = IngestedDocument(
        document_id="allowed",
        tenant_id="tenant-a",
        domain="lending",
        title="Allowed",
        source_uri="/docs/allowed.pdf",
        pages=[
            IngestedPage(
                document_id="allowed",
                tenant_id="tenant-a",
                domain="lending",
                title="Allowed",
                source_uri="/docs/allowed.pdf",
                source_type="pdf",
                page_number=1,
                text="EMI amount is 24000 rupees.",
                language="en",
            )
        ],
    )
    blocked = allowed.model_copy(
        update={
            "document_id": "blocked",
            "tenant_id": "tenant-b",
            "source_uri": "/docs/blocked.pdf",
            "pages": [
                allowed.pages[0].model_copy(
                    update={
                        "document_id": "blocked",
                        "tenant_id": "tenant-b",
                        "source_uri": "/docs/blocked.pdf",
                    }
                )
            ],
        }
    )

    async def _run() -> list:
        await service.index_documents([allowed, blocked])
        return await service.search(
            RetrievalQuery(query="What is the EMI amount?", tenant_id="tenant-a", domain="lending")
        )

    results = asyncio.run(_run())

    assert results
    assert all(result.chunk.tenant_id == "tenant-a" for result in results)


def test_rerank_results_boosts_term_overlap():
    document = _make_document("agreement", "Loan Agreement", ["Foreclosure charges are 2% of outstanding principal."])
    chunk = document.pages[0]
    from src.layer3_domain.document_ingestion import DocumentChunker

    base_chunk = DocumentChunker().chunk_document(document)[0]
    low_overlap_chunk = base_chunk.model_copy(
        update={"chunk_id": "other", "content": "Customer support is available from Monday to Saturday."}
    )
    from src.layer3_domain.document_models import RetrievalResult

    reranked = rerank_results(
        "foreclosure charges outstanding principal",
        [
            RetrievalResult(chunk=low_overlap_chunk, score=0.8, matched_terms=[]),
            RetrievalResult(chunk=base_chunk, score=0.75, matched_terms=[]),
        ],
    )

    assert reranked[0].chunk.chunk_id == base_chunk.chunk_id


def test_document_index_service_hybrid_search_recovers_exact_clause():
    service = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
    )
    documents = [
        _make_document(
            "charges-guide",
            "Charges Guide",
            [
                "Processing fee may vary by campaign and customer profile.",
                "Customer support and complaint escalation options are listed here.",
            ],
        ),
        _make_document(
            "agreement",
            "Loan Agreement",
            [
                "Section heading Foreclosure Charges.\n\nForeclosure charges are 2% of the outstanding principal plus applicable taxes.",
            ],
        ),
        _make_document(
            "faq",
            "Customer FAQ",
            [
                "Customers often ask about charges, foreclosure timelines, and how principal is calculated during closure.",
            ],
        ),
    ]

    async def _run() -> list:
        await service.index_documents(documents)
        return await service.search(
            RetrievalQuery(
                query="What are the foreclosure charges on the outstanding principal?",
                tenant_id="tenant-a",
                domain="lending",
                top_k=10,
            )
        )

    results = asyncio.run(_run())

    assert results
    top_ids = [result.chunk.document_id for result in results[:3]]
    assert "agreement" in top_ids
    assert results[0].chunk.document_id == "agreement"


def test_hybrid_search_uses_drug_metadata_to_prevent_cross_drug_confusion():
    service = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
    )
    metformin = IngestedDocument(
        document_id="metformin",
        tenant_id="tenant-a",
        domain="medicine",
        title="Metformin.pdf",
        source_uri="/docs/Metformin.pdf",
        pages=[
            IngestedPage(
                document_id="metformin",
                tenant_id="tenant-a",
                domain="medicine",
                title="Metformin.pdf",
                source_uri="/docs/Metformin.pdf",
                source_type="pdf",
                page_number=7,
                text=(
                    "Metformin Hydrochloride\nRenal Impairment\n\n"
                    "Assess renal function before initiation. Metformin is contraindicated in severe renal impairment."
                ),
                section_title="Renal Impairment",
                metadata={
                    "drug_name": "Metformin",
                    "section_name": "Renal Impairment",
                    "rag_section_boundary": "page",
                },
            )
        ],
    )
    amlodipine = metformin.model_copy(
        update={
            "document_id": "amlodipine",
            "title": "Amlodipine_Norvasc.pdf",
            "source_uri": "/docs/Amlodipine_Norvasc.pdf",
            "pages": [
                metformin.pages[0].model_copy(
                    update={
                        "document_id": "amlodipine",
                        "title": "Amlodipine_Norvasc.pdf",
                        "source_uri": "/docs/Amlodipine_Norvasc.pdf",
                        "page_number": 6,
                        "text": (
                            "Amlodipine Besylate\nRenal Impairment\n\n"
                            "Renal impairment does not significantly influence amlodipine pharmacokinetics."
                        ),
                        "metadata": {
                            "drug_name": "Amlodipine",
                            "section_name": "Renal Impairment",
                            "rag_section_boundary": "page",
                        },
                    }
                )
            ],
        }
    )

    async def _run() -> list:
        await service.index_documents([amlodipine, metformin])
        return await service.search(
            RetrievalQuery(
                query="What does Metformin say about renal impairment?",
                tenant_id="tenant-a",
                domain="medicine",
                top_k=4,
            )
        )

    results = asyncio.run(_run())

    assert results
    assert results[0].chunk.document_id == "metformin"
    assert results[0].chunk.metadata["drug_name"] == "Metformin"


def test_dose_query_prefers_clinical_dosage_over_nonclinical_mrhd():
    service = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
    )
    dosage_page = IngestedPage(
        document_id="metformin",
        tenant_id="tenant-a",
        domain="medicine",
        title="Metformin.pdf",
        source_uri="/docs/Metformin.pdf",
        source_type="pdf",
        page_number=5,
        text=(
            "Metformin Hydrochloride\nDosage and Administration\n\n"
            "The recommended starting dose is 500 mg twice daily. "
            "The maximum recommended daily dose is 2,000 mg."
        ),
        section_title="Dosage and Administration",
        metadata={
            "drug_name": "Metformin",
            "section_name": "Dosage and Administration",
            "rag_section_boundary": "page",
        },
    )
    toxicology_page = dosage_page.model_copy(
        update={
            "page_number": 12,
            "text": (
                "Metformin Hydrochloride\nNonclinical Toxicology\n\n"
                "The exposure was compared with the maximum recommended human daily dose of 2,000 mg "
                "based on body surface area in rats."
            ),
            "section_title": "Nonclinical Toxicology",
            "metadata": {
                "drug_name": "Metformin",
                "section_name": "Nonclinical Toxicology",
                "rag_section_boundary": "page",
            },
        }
    )
    document = IngestedDocument(
        document_id="metformin",
        tenant_id="tenant-a",
        domain="medicine",
        title="Metformin.pdf",
        source_uri="/docs/Metformin.pdf",
        pages=[toxicology_page, dosage_page],
    )

    async def _run() -> list:
        await service.index_documents([document])
        return await service.search(
            RetrievalQuery(
                query="What is the maximum dose of Metformin?",
                tenant_id="tenant-a",
                domain="medicine",
                top_k=4,
            )
        )

    results = asyncio.run(_run())

    assert results
    assert results[0].chunk.page_number == 5
    assert results[0].chunk.metadata["section_name"] == "Dosage and Administration"


def test_named_drug_query_filters_cross_drug_food_effect_matches():
    service = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
    )
    levothyroxine = IngestedDocument(
        document_id="levothyroxine",
        tenant_id="tenant-a",
        domain="medicine",
        title="Levothyroxine.pdf",
        source_uri="/docs/Levothyroxine.pdf",
        pages=[
            IngestedPage(
                document_id="levothyroxine",
                tenant_id="tenant-a",
                domain="medicine",
                title="Levothyroxine.pdf",
                source_uri="/docs/Levothyroxine.pdf",
                source_type="pdf",
                page_number=20,
                text=(
                    "Drug: Levothyroxine Sodium (Synthroid)\nClinical Pharmacology\n\n"
                    "T4 absorption is increased by fasting and decreased by certain foods such as soybeans."
                ),
                section_title="Clinical Pharmacology",
                metadata={
                    "drug_name": "Levothyroxine",
                    "section_name": "Clinical Pharmacology",
                    "rag_section_boundary": "page",
                },
            )
        ],
    )
    metformin = levothyroxine.model_copy(
        update={
            "document_id": "metformin",
            "title": "Metformin.pdf",
            "source_uri": "/docs/Metformin.pdf",
            "pages": [
                levothyroxine.pages[0].model_copy(
                    update={
                        "document_id": "metformin",
                        "title": "Metformin.pdf",
                        "source_uri": "/docs/Metformin.pdf",
                        "page_number": 10,
                        "text": (
                            "Drug: Metformin\nClinical Pharmacology\n\n"
                            "Effect of food: Low-fat and high-fat meals increased AUC."
                        ),
                        "metadata": {
                            "drug_name": "Metformin",
                            "section_name": "Clinical Pharmacology",
                            "rag_section_boundary": "page",
                        },
                    }
                )
            ],
        }
    )

    async def _run() -> list:
        await service.index_documents([metformin, levothyroxine])
        return await service.search(
            RetrievalQuery(
                query="What food affects SYNTHROID absorption?",
                tenant_id="tenant-a",
                domain="medicine",
                top_k=5,
            )
        )

    results = asyncio.run(_run())

    assert results
    assert {result.chunk.metadata["drug_name"] for result in results} == {"Levothyroxine"}
