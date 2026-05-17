import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.interfaces.http.routes.grounded_documents import router  # noqa: E402


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _payload() -> dict:
    return {
        "query": "Compare foreclosure charges and processing fee.",
        "tenant_id": "tenant-a",
        "domain": "lending",
        "top_k": 4,
        "generation_mode": "heuristic",
        "no_context_policy": "raise",
        "documents": [
            {
                "document_id": "agreement",
                "tenant_id": "tenant-a",
                "domain": "lending",
                "title": "Loan Agreement",
                "source_uri": "/docs/agreement.pdf",
                "source_type": "pdf",
                "language": "en",
                "pages": [
                    {
                        "document_id": "agreement",
                        "tenant_id": "tenant-a",
                        "domain": "lending",
                        "title": "Loan Agreement",
                        "source_uri": "/docs/agreement.pdf",
                        "source_type": "pdf",
                        "page_number": 4,
                        "text": "Foreclosure charges are 2% of the outstanding principal plus taxes.",
                        "section_title": "Foreclosure",
                        "language": "en",
                        "metadata": {},
                    }
                ],
                "metadata": {},
            },
            {
                "document_id": "sanction-letter",
                "tenant_id": "tenant-a",
                "domain": "lending",
                "title": "Sanction Letter",
                "source_uri": "/docs/sanction-letter.pdf",
                "source_type": "pdf",
                "language": "en",
                "pages": [
                    {
                        "document_id": "sanction-letter",
                        "tenant_id": "tenant-a",
                        "domain": "lending",
                        "title": "Sanction Letter",
                        "source_uri": "/docs/sanction-letter.pdf",
                        "source_type": "pdf",
                        "page_number": 2,
                        "text": "Processing fee is collected upfront at the time of disbursal.",
                        "section_title": "Fees",
                        "language": "en",
                        "metadata": {},
                    }
                ],
                "metadata": {},
            },
        ],
    }


def test_grounded_documents_answer_route_returns_citations():
    client = _build_client()
    response = client.post("/grounded-documents/answer", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["generation_mode"] == "heuristic"
    assert len(body["citations"]) >= 1
    assert len(body["page_proofs"]) >= 1
    assert len(body["evidence_groups"]) >= 1


def test_grounded_documents_analyze_route_returns_context_without_answer():
    client = _build_client()
    payload = _payload()
    response = client.post("/grounded-documents/analyze", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["retrieval_count"] >= 1
    assert body["citations"]
    assert body["page_proofs"]
    assert body["context_blocks"]


def test_grounded_documents_answer_route_returns_404_when_no_context_and_raise_policy():
    client = _build_client()
    payload = _payload()
    payload["query"] = "What is the balloon payment clause?"
    payload["documents"] = [
        {
            "document_id": "agreement",
            "tenant_id": "tenant-a",
            "domain": "lending",
            "title": "Loan Agreement",
            "source_uri": "/docs/agreement.pdf",
            "source_type": "pdf",
            "language": "en",
            "pages": [
                {
                    "document_id": "agreement",
                    "tenant_id": "tenant-a",
                    "domain": "lending",
                    "title": "Loan Agreement",
                    "source_uri": "/docs/agreement.pdf",
                    "source_type": "pdf",
                    "page_number": 1,
                    "text": "Customer support is available from Monday to Saturday.",
                    "section_title": "Support",
                    "language": "en",
                    "metadata": {},
                }
            ],
            "metadata": {},
        }
    ]

    response = client.post("/grounded-documents/answer", json=payload)

    assert response.status_code == 404
