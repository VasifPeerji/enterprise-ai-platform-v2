"""
Embed all unique questions from data/processed/questions.parquet and load them
into the Qdrant collection ``layer3_benchmark_corpus``.

Prerequisites:
  1. scripts/layer3/build_outcomes_corpus.py has produced questions.parquet
  2. scripts/layer3/setup_qdrant_collection.py has created the collection
  3. Qdrant is reachable on localhost:6333 (docker-compose up qdrant)

Output:
  • Qdrant collection populated with N points, one per unique question
  • artifacts/layer3/embed_report.json with timing + counts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from scripts.layer3._common import (
    ARTIFACTS_LAYER3,
    QUESTIONS_PARQUET,
    ensure_dirs,
    get_pipeline_logger,
)
from src.layer0_model_infra.config.routing_config import get_routing_config


# The corpus MUST be embedded with the SAME model the router queries with, or
# query vectors and corpus vectors live in different spaces and kNN returns
# nonsense. Source the default straight from the routing config (the single
# source of truth — Layer3EncoderConfig.model_name) so the build encoder and the
# router's query encoder can never silently diverge. This previously hardcoded a
# DIFFERENT model (bge-small-en) than the router's encoder
# (paraphrase-multilingual-MiniLM-L12-v2) — a latent footgun that would corrupt
# the live collection on a default re-run. (bge-small is the high-risk Tier-2
# classifier's model, not the kNN encoder.)
DEFAULT_ENCODER = get_routing_config().layer3.encoder.model_name
DEFAULT_BATCH_SIZE = 64
COLLECTION_NAME = "layer3_benchmark_corpus"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", default=DEFAULT_ENCODER,
                        help="HuggingFace model id of the encoder")
    parser.add_argument("--device", default="cuda",
                        help="cuda | cpu")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of questions embedded (for testing)")
    args = parser.parse_args()

    logger = get_pipeline_logger("layer3.embed")
    ensure_dirs()

    if not QUESTIONS_PARQUET.exists():
        logger.error(
            "questions_parquet_missing path=%s — run build_outcomes_corpus.py first",
            QUESTIONS_PARQUET,
        )
        return 1

    # Load questions
    table = pq.read_table(QUESTIONS_PARQUET)
    rows = table.to_pylist()
    if args.limit is not None:
        rows = rows[: args.limit]
    n_rows = len(rows)
    logger.info("embed_starting questions=%d encoder=%s device=%s",
                n_rows, args.encoder, args.device)

    # Load encoder
    from sentence_transformers import SentenceTransformer
    t_load = time.perf_counter()
    model = SentenceTransformer(args.encoder, device=args.device)
    if args.device == "cuda":
        model.half()
    logger.info("encoder_loaded elapsed=%.2fs", time.perf_counter() - t_load)

    # Connect to Qdrant
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
    client = QdrantClient(host="localhost", port=6333, timeout=60.0)
    if COLLECTION_NAME not in [c.name for c in client.get_collections().collections]:
        logger.error("qdrant_collection_missing name=%s — run setup_qdrant_collection.py first",
                     COLLECTION_NAME)
        return 1

    # Batched embed + upsert
    t_embed = time.perf_counter()
    n_upserted = 0
    for i in range(0, n_rows, args.batch_size):
        batch = rows[i : i + args.batch_size]
        texts = [r["question_text"] for r in batch]
        vectors = model.encode(
            texts, batch_size=args.batch_size, convert_to_numpy=True,
            normalize_embeddings=True, show_progress_bar=False,
        )

        points = []
        for row, vec in zip(batch, vectors):
            qid = row["question_global_id"]
            # Qdrant point IDs must be unsigned int or UUID; hash the qid.
            point_id = int(hashlib.sha256(qid.encode()).hexdigest()[:15], 16)
            points.append(qmodels.PointStruct(
                id=point_id,
                vector=vec.tolist(),
                payload={
                    "question_global_id": qid,
                    "question_text": row["question_text"][:1000],
                    "benchmark_source": row["benchmark_source"],
                    "language": row["language"],
                    "modality": row["modality"],
                    "domain": row["domain"],
                    "difficulty_tier": row["difficulty_tier"],
                },
            ))
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=False)
        n_upserted += len(points)
        if (i // args.batch_size) % 10 == 0:
            logger.info("embed_progress %d / %d", n_upserted, n_rows)

    t_embed_elapsed = time.perf_counter() - t_embed
    logger.info("embed_done n=%d elapsed=%.1fs throughput=%.1f qps",
                n_upserted, t_embed_elapsed, n_upserted / max(t_embed_elapsed, 1e-3))

    # Force flush + sanity-check the collection
    client.update_collection(
        collection_name=COLLECTION_NAME,
        optimizers_config=qmodels.OptimizersConfigDiff(),
    )

    info = client.get_collection(COLLECTION_NAME)
    logger.info("qdrant_collection_status points=%d status=%s",
                info.points_count, info.status)

    # End-to-end sanity probe — uses qdrant_client's new query_points API
    # (search() was deprecated in v1.10 and removed in some later builds)
    probe = "How do I deploy a Python web service?"
    qv = model.encode(probe, convert_to_numpy=True, normalize_embeddings=True)
    try:
        # new API (1.10+)
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=qv.tolist(),
            limit=5,
            with_payload=True,
        )
        hits = response.points
    except AttributeError:
        # legacy fallback
        hits = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=qv.tolist(),
            limit=5,
            with_payload=True,
        )
    sanity = [
        {"qid": h.payload["question_global_id"],
         "source": h.payload["benchmark_source"],
         "modality": h.payload["modality"],
         "score": round(float(h.score), 4),
         "text": h.payload["question_text"][:80]}
        for h in hits
    ]
    logger.info("sanity_probe query=%r top_5=%s", probe, sanity)

    # Report
    report = {
        "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "encoder": args.encoder,
        "device": args.device,
        "batch_size": args.batch_size,
        "n_questions_embedded": n_upserted,
        "embed_seconds": round(t_embed_elapsed, 1),
        "throughput_qps": round(n_upserted / max(t_embed_elapsed, 1e-3), 1),
        "qdrant_collection_points": info.points_count,
        "sanity_probe_query": probe,
        "sanity_probe_top_5": sanity,
    }
    (ARTIFACTS_LAYER3 / "embed_report.json").write_text(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
