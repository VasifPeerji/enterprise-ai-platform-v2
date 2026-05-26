"""
Initialize the Qdrant collection that will hold the kNN corpus.

Idempotent: re-running drops and recreates the collection. Safe because the
collection is rebuilt from data/processed/questions.parquet via embed_corpus.py
on every run.

Run:
    python -m scripts.layer3.setup_qdrant_collection
"""

from __future__ import annotations

import sys

from scripts.layer3._common import get_pipeline_logger


COLLECTION_NAME = "layer3_benchmark_corpus"
DEFAULT_VECTOR_DIM = 384  # bge-small / multilingual-MiniLM / multilingual-e5-small


def main(vector_dim: int = DEFAULT_VECTOR_DIM, host: str = "localhost", port: int = 6333) -> int:
    logger = get_pipeline_logger("layer3.qdrant_setup")
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qmodels
    except ImportError:
        logger.error("qdrant_client not installed")
        return 1

    client = QdrantClient(host=host, port=port, timeout=30.0)

    # Drop the existing collection if it exists; idempotent recreation.
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        logger.info("qdrant_dropping_existing_collection name=%s", COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qmodels.VectorParams(
            size=vector_dim,
            distance=qmodels.Distance.COSINE,
        ),
        hnsw_config=qmodels.HnswConfigDiff(
            m=16,
            ef_construct=200,
            full_scan_threshold=10_000,
        ),
        optimizers_config=qmodels.OptimizersConfigDiff(
            default_segment_number=4,
        ),
    )

    # Create payload indexes on the fields the kNN search filters by.
    for field in ("benchmark_source", "modality", "language", "domain", "difficulty_tier"):
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )

    info = client.get_collection(COLLECTION_NAME)
    logger.info(
        "qdrant_collection_ready name=%s vector_dim=%d status=%s",
        COLLECTION_NAME, vector_dim, info.status,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
