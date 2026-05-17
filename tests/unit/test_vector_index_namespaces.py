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
)
from src.layer3_domain.document_models import IngestedDocument, IngestedPage, RetrievalQuery  # noqa: E402


def _document(document_id: str, tenant_id: str, text: str) -> IngestedDocument:
    return IngestedDocument(
        document_id=document_id,
        tenant_id=tenant_id,
        domain="lending",
        title=document_id,
        source_uri=f"/docs/{document_id}.pdf",
        pages=[
            IngestedPage(
                document_id=document_id,
                tenant_id=tenant_id,
                domain="lending",
                title=document_id,
                source_uri=f"/docs/{document_id}.pdf",
                source_type="pdf",
                page_number=1,
                text=text,
                section_title="Charges",
                language="en",
            )
        ],
    )


def test_vector_index_namespaces_isolate_collections():
    store = InMemoryVectorStore()
    service_a = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=store,
        namespace="collection-a",
    )
    service_b = DocumentIndexService(
        embedder=DeterministicEmbeddingProvider(),
        vector_store=store,
        namespace="collection-b",
    )

    asyncio.run(service_a.index_documents([_document("agreement-a", "tenant-a", "Foreclosure charges are 2%.")]))
    asyncio.run(service_b.index_documents([_document("agreement-b", "tenant-a", "Processing fee is 1%.")]))

    results_a = asyncio.run(
        service_a.search(
            RetrievalQuery(
                query="What are the foreclosure charges?",
                tenant_id="tenant-a",
                domain="lending",
                top_k=3,
            )
        )
    )
    results_b = asyncio.run(
        service_b.search(
            RetrievalQuery(
                query="What are the foreclosure charges?",
                tenant_id="tenant-a",
                domain="lending",
                top_k=3,
            )
        )
    )

    assert results_a
    assert results_a[0].chunk.document_id == "agreement-a"
    assert all(result.chunk.document_id != "agreement-a" for result in results_b)
