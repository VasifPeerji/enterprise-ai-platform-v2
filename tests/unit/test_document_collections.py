import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer3_domain.document_collections import DocumentCollectionService  # noqa: E402
from src.layer3_domain.document_parsing import RawDocumentAsset  # noqa: E402


def _asset(
    collection_id: str,
    name: str,
    content: str,
    *,
    tenant_id: str = "tenant-a",
    domain: str = "lending",
) -> RawDocumentAsset:
    return RawDocumentAsset(
        document_id=f"{collection_id}:{name}",
        tenant_id=tenant_id,
        domain=domain,
        title=name,
        source_uri=f"/docs/{name}.txt",
        source_type="text",
        mime_type="text/plain",
        content_bytes=content.encode("utf-8"),
    )


def test_document_collection_service_ingests_and_summarizes_collection():
    service = DocumentCollectionService()

    summary = asyncio.run(
        service.ingest_assets(
            collection_id="loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[
                _asset("loan-servicing", "agreement", "Foreclosure charges are 2%.\fLate payment fee is 500 rupees."),
                _asset("loan-servicing", "letter", "Processing fee is collected at disbursal."),
            ],
        )
    )

    assert summary.collection_id == "loan-servicing"
    assert summary.document_count == 2
    assert summary.page_count == 3


def test_document_collection_service_answers_across_uploaded_assets():
    service = DocumentCollectionService()
    asyncio.run(
        service.ingest_assets(
            collection_id="loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[
                _asset("loan-servicing", "agreement", "Foreclosure charges are 2% of outstanding principal."),
                _asset("loan-servicing", "letter", "Processing fee is collected at disbursal."),
            ],
        )
    )

    response = asyncio.run(
        service.answer_query(
            collection_id="loan-servicing",
            query="Compare foreclosure charges and processing fee.",
            tenant_id="tenant-a",
            domain="lending",
        )
    )

    assert response.grounded is True
    assert len(response.citations) >= 2
    assert len(response.page_proofs) >= 2


def test_document_collection_service_analyze_query_returns_context():
    service = DocumentCollectionService()
    asyncio.run(
        service.ingest_assets(
            collection_id="loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[_asset("loan-servicing", "agreement", "Late payment fee is 500 rupees.")],
        )
    )

    payload = asyncio.run(
        service.analyze_query(
            collection_id="loan-servicing",
            query="What is the late payment fee?",
            tenant_id="tenant-a",
        )
    )

    assert payload["retrieval_count"] >= 1
    assert payload["citations"]
    assert payload["page_proofs"]


def test_document_collection_service_replace_assets_rebuilds_collection():
    service = DocumentCollectionService()
    asyncio.run(
        service.ingest_assets(
            collection_id="loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[_asset("loan-servicing", "agreement", "Foreclosure charges are 2%.")],
        )
    )

    summary = asyncio.run(
        service.replace_assets(
            collection_id="loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[_asset("loan-servicing", "letter", "Processing fee is collected at disbursal.")],
        )
    )

    assert summary.document_count == 1
    response = asyncio.run(
        service.answer_query(
            collection_id="loan-servicing",
            query="What is the processing fee?",
            tenant_id="tenant-a",
            domain="lending",
        )
    )
    assert response.citations
    assert response.page_proofs
    assert all("Processing fee" in citation.snippet or "processing fee" in citation.snippet.lower() for citation in response.citations[:1])


def test_document_collection_service_list_and_delete_lifecycle():
    service = DocumentCollectionService()
    asyncio.run(
        service.ingest_assets(
            collection_id="loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[_asset("loan-servicing", "agreement", "Foreclosure charges are 2%.")],
        )
    )
    asyncio.run(
        service.ingest_assets(
            collection_id="loan-faq",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[_asset("loan-faq", "faq", "EMI means equated monthly installment.")],
        )
    )

    collections = asyncio.run(service.list_collections("tenant-a"))
    assert {item.collection_id for item in collections} >= {"loan-servicing", "loan-faq"}

    asyncio.run(service.delete_collection("loan-servicing", "tenant-a"))
    collections_after_delete = asyncio.run(service.list_collections("tenant-a"))
    assert all(item.collection_id != "loan-servicing" for item in collections_after_delete)
