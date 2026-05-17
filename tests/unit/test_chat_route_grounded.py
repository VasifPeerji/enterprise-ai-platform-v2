import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.interfaces.http.routes import chat as chat_route  # noqa: E402


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_route.router)
    return TestClient(app)


def test_chat_route_returns_grounded_proof_payload(monkeypatch):
    client = _build_client()

    grounded_response = SimpleNamespace(
        answer="Foreclosure charges are 2% of the outstanding principal.",
        model_id="heuristic-grounder",
        retrieval_count=1,
        grounded=True,
        citations=[
            {
                "document_id": "agreement",
                "chunk_id": "agreement:p4:c0",
                "title": "Loan Agreement",
                "source_uri": "/docs/agreement.pdf",
                "page_number": 4,
                "section_title": "Foreclosure",
                "snippet": "Foreclosure charges are 2% of the outstanding principal.",
                "snippet_truncated": False,
                "score": 0.91,
                "highlights": [
                    {
                        "start_char": 0,
                        "end_char": 52,
                        "text": "Foreclosure charges are 2% of the outstanding principal",
                    }
                ],
            }
        ],
        page_proofs=[
            {
                "document_id": "agreement",
                "title": "Loan Agreement",
                "source_uri": "/docs/agreement.pdf",
                "page_number": 4,
                "section_title": "Foreclosure",
                "page_text": "Foreclosure charges are 2% of the outstanding principal plus taxes.",
                "highlights": [
                    {
                        "start_char": 0,
                        "end_char": 52,
                        "text": "Foreclosure charges are 2% of the outstanding principal",
                    }
                ],
                "citation_indices": [0],
            }
        ],
        evidence_groups=[
            {
                "claim_label": "Foreclosure",
                "summary": "Loan Agreement, page 4",
                "citation_indices": [0],
            }
        ],
    )

    async def _answer_query(**kwargs):
        return grounded_response

    monkeypatch.setattr(
        chat_route.grounded_collection_service,
        "answer_query",
        _answer_query,
    )

    response = client.post(
        "/chat",
        json={
            "message": "What are the foreclosure charges?",
            "grounded_collection_id": "loan-servicing",
            "grounded_tenant_id": "tenant-a",
            "grounded_domain": "lending",
            "grounded_top_k": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["grounded_collection_id"] == "loan-servicing"
    assert body["response"] == grounded_response.answer
    assert body["citations"]
    assert body["page_proofs"]
    assert body["page_proofs"][0]["page_number"] == 4
    assert body["page_proofs"][0]["highlights"][0]["text"].startswith("Foreclosure charges")


def test_chat_route_preserves_standard_execution_when_not_grounded(monkeypatch):
    client = _build_client()

    decision = SimpleNamespace(
        routing_reasoning="Standard route",
        confidence_level="high",
        pipeline_metadata={"fast_path_triggered": False, "semantic_memory_hit": False},
        modality_analysis={"primary_modality": "text"},
        triage_result={"intent": "qa", "domain": "general", "complexity_band": "simple"},
        uncertainty_score={"total_uncertainty": 0.12},
        bandit_context={"input_difficulty": 0.2},
        fallback_models=[SimpleNamespace(display_name="fallback-model")],
        estimated_cost_usd=0.001,
        selected_model=SimpleNamespace(
            model_id="mock-model",
            display_name="Mock Model",
            provider="mock-provider",
            model_type="chat",
        ),
        escalation_path_available=True,
        escalation_levels=1,
        benchmark_recommendation=None,
    )

    result = SimpleNamespace(
        content="Standard chat response",
        model_used="mock-model",
        total_cost_usd=0.001,
        total_latency_ms=25.0,
        escalation_count=0,
        quality_passed=True,
        quality_score=0.97,
        quality_reasoning="Looks good",
        execution_metadata={"path": "standard"},
    )

    class DummyOrchestrator:
        async def execute(self, **kwargs):
            return result

    monkeypatch.setattr(chat_route.model_router, "route", lambda **kwargs: decision)
    monkeypatch.setattr(chat_route, "get_orchestrator", lambda: DummyOrchestrator(), raising=False)

    import src.layer2_orchestrator.execution_loop as execution_loop  # noqa: E402

    monkeypatch.setattr(execution_loop, "get_orchestrator", lambda: DummyOrchestrator())

    response = client.post(
        "/chat",
        json={
            "message": "Hello there",
            "user_tier": "standard",
            "budget_remaining": 1.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is False
    assert body["citations"] == []
    assert body["page_proofs"] == []
    assert body["response"] == "Standard chat response"


def test_chat_demo_ui_exposes_grounded_proof_controls():
    client = _build_client()

    response = client.get("/chat/demo")

    assert response.status_code == 200
    html = response.text
    assert 'id="grounded_collection_id"' in html
    assert 'id="citationList"' in html
    assert 'id="proofViewer"' in html
    assert 'renderProofViewer' in html
