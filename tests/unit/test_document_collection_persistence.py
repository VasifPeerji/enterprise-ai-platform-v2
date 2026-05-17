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


def test_document_collection_can_be_rehydrated_from_persistence():
    service = DocumentCollectionService()
    asyncio.run(
        service.ingest_assets(
            collection_id="persisted-loan-servicing",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
            assets=[
                _asset(
                    "persisted-loan-servicing",
                    "agreement",
                    "Foreclosure charges are 2% of outstanding principal.\fLate payment fee is 500 rupees.",
                )
            ],
        )
    )

    fresh_service = DocumentCollectionService()
    collection = asyncio.run(fresh_service.hydrate_collection("persisted-loan-servicing"))

    assert collection.collection_id == "persisted-loan-servicing"
    assert len(collection.documents) == 1
    assert "Foreclosure charges" in collection.documents[0].pages[0].text

    response = asyncio.run(
        fresh_service.answer_query(
            collection_id="persisted-loan-servicing",
            query="What are the foreclosure charges?",
            tenant_id="tenant-a",
            domain="lending",
            generation_mode="heuristic",
        )
    )
    assert response.grounded is True
    assert response.citations
