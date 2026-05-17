import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.layer1_intelligence.rag_service import GroundedRAGService, RAGServiceConfig, _clean_generated_answer  # noqa: E402
from src.layer3_domain.document_models import IngestedDocument, IngestedPage  # noqa: E402
from src.shared.errors import NoRelevantContextError  # noqa: E402


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
                section_title="Charges" if "charge" in text.lower() or "fee" in text.lower() else "Overview",
                language="en",
            )
            for index, text in enumerate(page_texts)
        ],
    )


def test_rag_service_answers_with_multiple_citations():
    service = GroundedRAGService.for_local_testing(domain="lending", top_k=4)
    documents = [
        _make_document(
            "agreement",
            "Loan Agreement",
            [
                "Foreclosure charges are 2% of the outstanding principal plus taxes.",
                "Late payment fee is 500 rupees after the grace period.",
            ],
        ),
        _make_document(
            "sanction-letter",
            "Sanction Letter",
            ["Processing fee is collected upfront at the time of disbursal."],
        ),
    ]

    async def _run():
        await service.index_documents(documents)
        return await service.answer_query(
            "Compare foreclosure charges, late payment fee, and processing fee.",
            tenant_id="tenant-a",
            domain="lending",
        )

    response = asyncio.run(_run())

    assert response.grounded is True
    assert response.retrieval_count >= 2
    assert len(response.citations) >= 2
    assert response.page_proofs
    assert response.evidence_groups
    assert "fee" in response.answer.lower() or "charges" in response.answer.lower()


def test_rag_service_raises_when_no_grounded_context_exists():
    service = GroundedRAGService.for_local_testing(domain="lending")

    with pytest.raises(NoRelevantContextError):
        asyncio.run(
            service.answer_query(
                "What is my EMI amount?",
                tenant_id="tenant-a",
                domain="lending",
            )
        )


def test_clean_generated_answer_removes_inline_citation_lines():
    answer = (
        "Soybeans may decrease SYNTHROID absorption.\n\n"
        "CITATION: Source=Levothyroxine.pdf | Section=Clinical Pharmacology | Page=20"
    )

    assert _clean_generated_answer(answer) == "Soybeans may decrease SYNTHROID absorption."


def test_rag_service_can_degrade_gracefully_when_configured():
    service = GroundedRAGService.for_local_testing(domain="lending")
    service = GroundedRAGService(
        index_service=service.index_service,
        answer_generator=service.answer_generator,
        assembler=service.assembler,
        config=RAGServiceConfig(
            top_k=4,
            rerank_top_k=4,
            min_results=1,
            domain="lending",
            raise_on_no_context=False,
        ),
    )

    response = asyncio.run(
        service.answer_query(
            "Show me a clause that does not exist.",
            tenant_id="tenant-a",
            domain="lending",
        )
    )

    assert response.grounded is False
    assert response.retrieval_count == 0
    assert response.citations == []
    assert response.page_proofs == []


def test_rag_service_respects_tenant_isolation_during_answering():
    service = GroundedRAGService.for_local_testing(domain="lending")
    allowed = IngestedDocument(
        document_id="allowed",
        tenant_id="tenant-a",
        domain="lending",
        title="Allowed Agreement",
        source_uri="/docs/allowed.pdf",
        pages=[
            IngestedPage(
                document_id="allowed",
                tenant_id="tenant-a",
                domain="lending",
                title="Allowed Agreement",
                source_uri="/docs/allowed.pdf",
                source_type="pdf",
                page_number=1,
                text="Foreclosure charges are 2% of the outstanding principal.",
                section_title="Charges",
                language="en",
            )
        ],
    )
    blocked = allowed.model_copy(
        update={
            "document_id": "blocked",
            "tenant_id": "tenant-b",
            "title": "Blocked Agreement",
            "source_uri": "/docs/blocked.pdf",
            "pages": [
                allowed.pages[0].model_copy(
                    update={
                        "document_id": "blocked",
                        "tenant_id": "tenant-b",
                        "title": "Blocked Agreement",
                        "source_uri": "/docs/blocked.pdf",
                    }
                )
            ],
        }
    )

    async def _run():
        await service.index_documents([allowed, blocked])
        return await service.answer_query(
            "What are the foreclosure charges?",
            tenant_id="tenant-a",
            domain="lending",
        )

    response = asyncio.run(_run())

    assert response.citations
    assert response.page_proofs
    assert all(citation.document_id == "allowed" for citation in response.citations)


def test_rag_service_prioritizes_exact_clause_over_loose_thematic_matches():
    service = GroundedRAGService.for_local_testing(domain="lending", top_k=3)
    documents = [
        _make_document(
            "faq",
            "Customer FAQ",
            [
                "Customers ask about foreclosure, payment charges, principal balances, and closure requests.",
            ],
        ),
        _make_document(
            "policy",
            "Support Policy",
            [
                "Charges and service requests are reviewed by the support desk during business days.",
            ],
        ),
        _make_document(
            "agreement",
            "Loan Agreement",
            [
                "Foreclosure charges are 2% of the outstanding principal plus taxes.",
            ],
        ),
    ]

    async def _run():
        await service.index_documents(documents)
        return await service.answer_query(
            "What are the foreclosure charges?",
            tenant_id="tenant-a",
            domain="lending",
        )

    response = asyncio.run(_run())

    assert response.citations
    assert response.citations[0].document_id == "agreement"
    assert "2%" in response.citations[0].snippet


def test_rag_service_direct_fact_answer_uses_best_focused_snippet_only():
    service = GroundedRAGService.for_local_testing(domain="law", top_k=4)
    document = IngestedDocument(
        document_id="constitution",
        tenant_id="tenant-a",
        domain="law",
        title="Constitution of India",
        source_uri="/docs/constitution.pdf",
        pages=[
            IngestedPage(
                document_id="constitution",
                tenant_id="tenant-a",
                domain="law",
                title="Constitution of India",
                source_uri="/docs/constitution.pdf",
                source_type="pdf",
                page_number=13,
                text=(
                    "Right against Exploitation 23. Traffic in human beings and forced labour are prohibited. "
                    "24. No child below the age of fourteen years shall be employed to work in any factory or mine or engaged in any other hazardous employment. "
                    "Right to Freedom of Religion 25. All persons are equally entitled to freedom of conscience."
                ),
                language="en",
            )
        ],
    )

    async def _run():
        await service.index_documents([document])
        return await service.answer_query(
            "What is the minimum age of employment to work in any factory?",
            tenant_id="tenant-a",
            domain="law",
        )

    response = asyncio.run(_run())

    assert response.citations
    assert response.answer.startswith("24. No child below")
    assert "fourteen years" in response.answer
    assert "Right to Freedom of Religion" not in response.answer


def test_rag_service_answers_constitution_article_number_queries():
    service = GroundedRAGService.for_local_testing(domain="law", top_k=6)
    document = IngestedDocument(
        document_id="constitution",
        tenant_id="tenant-a",
        domain="law",
        title="Constitution of India",
        source_uri="/docs/constitution.pdf",
        pages=[
            IngestedPage(
                document_id="constitution",
                tenant_id="tenant-a",
                domain="law",
                title="Constitution of India",
                source_uri="/docs/constitution.pdf",
                source_type="pdf",
                page_number=1,
                text=(
                    "15. Prohibition of discrimination on grounds of religion, race, caste, sex or place of birth. "
                    "The State shall not discriminate against any citizen on grounds only of religion, race, caste, sex, place of birth or any of them. "
                    "17. Abolition of Untouchability. Untouchability is abolished and its practice in any form is forbidden. "
                    "21A. Right to education. The State shall provide free and compulsory education to all children of the age of six to fourteen years."
                ),
                language="en",
            )
        ],
    )

    async def _run():
        await service.index_documents([document])
        article_15 = await service.answer_query(
            "What is under Article 15 ?",
            tenant_id="tenant-a",
            domain="law",
        )
        untouchability = await service.answer_query(
            'Which article deals with the "Abolition of Untouchability"?',
            tenant_id="tenant-a",
            domain="law",
        )
        article_21a = await service.answer_query(
            "What does Article 21A of the Constitution provide?",
            tenant_id="tenant-a",
            domain="law",
        )
        return article_15, untouchability, article_21a

    article_15, untouchability, article_21a = asyncio.run(_run())

    assert article_15.answer.startswith("Article 15")
    assert "Prohibition of discrimination" in article_15.answer
    assert untouchability.answer == "Article 17 deals with Abolition of Untouchability."
    assert article_21a.answer.startswith("Article 21A")
    assert "free and compulsory education" in article_21a.answer


def test_rag_service_article_query_does_not_bleed_into_next_article():
    service = GroundedRAGService.for_local_testing(domain="law", top_k=6)
    document = IngestedDocument(
        document_id="constitution",
        tenant_id="tenant-a",
        domain="law",
        title="Constitution of India",
        source_uri="/docs/constitution.pdf",
        pages=[
            IngestedPage(
                document_id="constitution",
                tenant_id="tenant-a",
                domain="law",
                title="Constitution of India",
                source_uri="/docs/constitution.pdf",
                source_type="pdf",
                page_number=11,
                text=(
                    "*[21A. The State shall provide free and compulsory education to all children "
                    "of the age of six to fourteen years in such manner as the State may, by law, determine.] "
                    "22. (1) No person who is arrested shall be detained in custody without being informed."
                ),
                language="en",
            )
        ],
    )

    async def _run():
        await service.index_documents([document])
        return await service.answer_query(
            "What does Article 21A of the Constitution provide?",
            tenant_id="tenant-a",
            domain="law",
        )

    response = asyncio.run(_run())

    assert "free and compulsory education" in response.answer
    assert "No person who is arrested" not in response.answer
    assert response.citations
    assert "No person who is arrested" not in response.citations[0].snippet
    assert response.page_proofs[0].highlights
    assert "No person who is arrested" not in response.page_proofs[0].highlights[0].text


def test_rag_service_answers_constitution_emergency_queries():
    service = GroundedRAGService.for_local_testing(domain="law", top_k=10)
    document = IngestedDocument(
        document_id="constitution",
        tenant_id="tenant-a",
        domain="law",
        title="Constitution of India",
        source_uri="/docs/constitution.pdf",
        pages=[
            IngestedPage(
                document_id="constitution",
                tenant_id="tenant-a",
                domain="law",
                title="Constitution of India",
                source_uri="/docs/constitution.pdf",
                source_type="pdf",
                page_number=2,
                text=(
                    "352. Proclamation of Emergency. If the President is satisfied that a grave emergency exists. "
                    "356. Provisions in case of failure of constitutional machinery in States. "
                    "360. Provisions as to financial emergency. If the President is satisfied that a situation has arisen whereby the financial stability is threatened."
                ),
                language="en",
            )
        ],
    )

    async def _run():
        await service.index_documents([document])
        types = await service.answer_query(
            "What are the three types of emergencies mentioned in the Constitution?",
            tenant_id="tenant-a",
            domain="law",
        )
        financial = await service.answer_query(
            "Under which article can the President declare a Financial Emergency?",
            tenant_id="tenant-a",
            domain="law",
        )
        return types, financial

    types, financial = asyncio.run(_run())

    assert "National Emergency" in types.answer
    assert "President's Rule" in types.answer
    assert "Financial Emergency" in types.answer
    assert financial.answer == "The President can declare a Financial Emergency under Article 360."
