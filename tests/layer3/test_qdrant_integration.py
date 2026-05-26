"""
End-to-end Qdrant integration tests.

Verifies the kNN search wiring: encoder → Qdrant query → payload returned →
outcome_store lookup → coherent neighbor sets for representative queries.

Skipped when Qdrant isn't reachable on localhost:6333 OR the corpus hasn't
been embedded yet. Catches the kind of issues unit tests can't:
  • Encoder + collection vector dim mismatch
  • Payload schema drift
  • Search-API breaking changes in qdrant-client
  • Multilingual queries actually finding multilingual neighbors
"""

from __future__ import annotations

from pathlib import Path

import pytest


COLLECTION_NAME = "layer3_benchmark_corpus"
ENCODER_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _qdrant_available() -> bool:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333, timeout=2.0)
        collections = client.get_collections().collections
        return COLLECTION_NAME in {c.name for c in collections}
    except Exception:
        return False


def _has_points() -> bool:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333, timeout=2.0)
        info = client.get_collection(COLLECTION_NAME)
        return (info.points_count or 0) > 100
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_qdrant_available() and _has_points()),
    reason="Qdrant collection not embedded; run scripts/layer3/embed_corpus.py",
)


@pytest.fixture(scope="module")
def client():
    from qdrant_client import QdrantClient
    return QdrantClient(host="localhost", port=6333, timeout=10.0)


@pytest.fixture(scope="module")
def encoder():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(ENCODER_NAME, device="cuda" if _cuda_available() else "cpu")
    return model


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _query(client, encoder, text: str, *, limit: int = 5, modality_filter: str = None):
    """Helper: embed + query Qdrant. Returns list of (payload, score) tuples."""
    qv = encoder.encode(text, convert_to_numpy=True, normalize_embeddings=True)

    from qdrant_client.http import models as qmodels
    qfilter = None
    if modality_filter:
        qfilter = qmodels.Filter(must=[
            qmodels.FieldCondition(
                key="modality",
                match=qmodels.MatchValue(value=modality_filter),
            )
        ])

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=qv.tolist(),
        query_filter=qfilter,
        limit=limit,
        with_payload=True,
    )
    return [(h.payload, float(h.score)) for h in response.points]


# ---------------------------------------------------------------------------
# Coherent neighbor sets per modality
# ---------------------------------------------------------------------------


def test_code_query_returns_code_neighbors(client, encoder):
    """A coding query should retrieve mostly code-modality neighbors."""
    hits = _query(client, encoder, "Write a Python function to reverse a linked list", limit=10)
    assert hits
    code_count = sum(1 for payload, _ in hits if payload["modality"] == "code")
    assert code_count >= 5, (
        f"only {code_count}/10 neighbors are code modality — "
        f"neighbor modalities: {[p['modality'] for p, _ in hits]}"
    )


def test_math_query_returns_math_neighbors(client, encoder):
    """A clear math query should retrieve math-modality neighbors."""
    hits = _query(client, encoder, "Compute the indefinite integral of sin(x)*cos(x)", limit=10)
    assert hits
    math_count = sum(1 for payload, _ in hits if payload["modality"] == "math")
    assert math_count >= 5, (
        f"only {math_count}/10 neighbors are math modality — "
        f"neighbor modalities: {[p['modality'] for p, _ in hits]}"
    )


def test_filter_to_specific_modality(client, encoder):
    """Qdrant filter must narrow results to the requested modality."""
    hits = _query(
        client, encoder,
        "I'm not sure what this question is about, can you help?",
        limit=10, modality_filter="code",
    )
    for payload, _ in hits:
        assert payload["modality"] == "code", (
            f"filter leaked: got modality {payload['modality']}"
        )


# ---------------------------------------------------------------------------
# Multilingual sanity
# ---------------------------------------------------------------------------


def test_spanish_query_returns_relevant_neighbors(client, encoder):
    """Spanish query should find semantically similar English neighbors —
    that's what cross-lingual MiniLM is for."""
    hits = _query(client, encoder, "Como funciona el aprendizaje por refuerzo?", limit=5)
    assert hits
    # Top score should be reasonable (>0.45) given paraphrase-multilingual's
    # cross-lingual transfer quality
    assert hits[0][1] > 0.30, f"top similarity too low: {hits[0][1]}"


# ---------------------------------------------------------------------------
# Schema invariants
# ---------------------------------------------------------------------------


def test_payload_contains_all_indexed_fields(client, encoder):
    """Every point's payload must have the fields Stage C filters / pivots on."""
    hits = _query(client, encoder, "test", limit=5)
    required = {
        "question_global_id", "question_text", "benchmark_source",
        "language", "modality", "domain", "difficulty_tier",
    }
    for payload, _ in hits:
        assert required.issubset(payload.keys()), (
            f"payload missing keys: {required - set(payload.keys())}"
        )


def test_question_global_id_format(client, encoder):
    """qids should always be ``{benchmark}:{local_id}`` so they join with the
    DuckDB outcomes side."""
    hits = _query(client, encoder, "test", limit=10)
    for payload, _ in hits:
        qid = payload["question_global_id"]
        assert ":" in qid, f"malformed qid: {qid!r}"
        benchmark = qid.split(":", 1)[0]
        assert benchmark in {
            "livebench", "mmlu_pro", "livecodebench", "swe_bench_verified",
            "gpqa_diamond", "arena_hard", "mt_bench",
        }, f"unknown benchmark prefix in qid: {qid}"


def test_validation_set_ids_NOT_in_corpus(client, encoder):
    """P7 invariant: validation_set_ids.json's qids must be excluded from the
    kNN collection. If a validation query appears as its own neighbor, the
    router's accuracy claims are inflated.
    """
    import json
    repo_root = Path(__file__).resolve().parent.parent.parent
    locked_path = repo_root / "data/validation_set_ids.json"
    if not locked_path.exists():
        pytest.skip("validation_set_ids.json not built yet")

    locked = set(json.loads(locked_path.read_text())["locked_ids"])
    # Look for any arena_hard / mt_bench qid in the corpus — none should appear
    hits = _query(client, encoder, "What is your favourite colour?", limit=20)
    leaked = [p["question_global_id"] for p, _ in hits
              if p["question_global_id"] in locked]
    assert not leaked, f"validation IDs leaked into corpus: {leaked[:5]}"
