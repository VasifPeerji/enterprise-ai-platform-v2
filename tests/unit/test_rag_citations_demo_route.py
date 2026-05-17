import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.interfaces.http.routes.rag_citations_demo import router  # noqa: E402


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rag_citations_demo_ui_exposes_collection_and_proof_controls():
    client = _build_client()

    response = client.get("/rag-citations/demo")

    assert response.status_code == 200
    html = response.text
    assert 'id="collectionId"' in html
    assert 'id="files"' in html
    assert 'id="citationList"' in html
    assert 'id="proofViewer"' in html
    assert "uploadCollection()" in html
    assert "runQuery()" in html
    assert "/grounded-documents/collections/upload" in html
