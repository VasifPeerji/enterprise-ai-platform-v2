"""
📁 File: scripts/layer3/add_wildbench_questions.py
Layer: Layer 0 — Layer 3 redesign (conversational corpus, questions-only)
Purpose: Add WildBench v2's real-user conversational tasks to the kNN corpus as
         QUESTIONS (no per-model outcomes), so conversational queries find
         neighbours and engage Stage C instead of falling back to the safe
         default. WildBench's per-model outputs don't cover our strong free
         models (they're newer than WildBench's mid-2024 cutoff), so this is a
         questions-only engagement win — grounded chat routing for our own
         models comes later via the online loop.
Depends on: datasets (HF), the router's encoder + Qdrant, data/processed/*.parquet
Used by: run once to extend the corpus; safe to re-run (idempotent on ids).

Non-destructive: backs up questions.parquet before appending. Leakage-safe:
drops any task whose normalised text matches a locked validation query (the 650
in validation_set.parquet) and skips ids already in the corpus. $0 — no model
calls, only the local encoder + a Qdrant upsert. Embeds with the SAME encoder /
point-id / payload scheme as embed_corpus.py so the new points share the corpus
vector space; reaches Qdrant on 127.0.0.1 (localhost resolves to IPv6, which the
docker port-proxy doesn't forward).

Usage:
  python scripts/layer3/add_wildbench_questions.py --dry-run
  python scripts/layer3/add_wildbench_questions.py [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

QUESTIONS_PARQUET = REPO_ROOT / "data/processed/questions.parquet"
VALIDATION_PARQUET = REPO_ROOT / "data/processed/validation_set.parquet"
COLLECTION = "layer3_benchmark_corpus"
SOURCE = "wildbench"

# WildBench primary_tag -> our coarse modality bucket. Everything else is text.
_TAG_MODALITY = {"Coding & Debugging": "code", "Math": "math"}


def _norm(t: str) -> str:
    return " ".join((t or "").lower().split())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap tasks (debug)")
    ap.add_argument("--dry-run", action="store_true", help="harvest + report, write nothing")
    args = ap.parse_args()

    import pyarrow as pa
    import pyarrow.parquet as pq
    from datasets import load_dataset

    # --- existing corpus + validation leakage guard ---
    existing = pq.read_table(QUESTIONS_PARQUET)
    existing_ids = set(existing.column("question_global_id").to_pylist())
    val_norm = {
        _norm(t) for t in pq.read_table(VALIDATION_PARQUET).column("question_text").to_pylist()
    }
    print(f"existing corpus = {existing.num_rows} questions; leakage guard = {len(val_norm)} validation texts")

    # --- harvest WildBench v2 (1024 real-user tasks) ---
    ds = load_dataset("allenai/WildBench", "v2", split="test")
    new_rows = []
    dropped_leak = dropped_dup = skipped_empty = 0
    for row in ds:
        if args.limit and len(new_rows) >= args.limit:
            break
        ci = row.get("conversation_input") or []
        text = ci[0].get("content", "") if (ci and isinstance(ci[0], dict)) else ""
        if not (text or "").strip():
            skipped_empty += 1
            continue
        qid = f"{SOURCE}:{row.get('id') or row.get('session_id')}"
        if qid in existing_ids:
            dropped_dup += 1
            continue
        if _norm(text) in val_norm:  # leakage: this task is a locked validation query
            dropped_leak += 1
            continue
        new_rows.append({
            "question_global_id": qid,
            "question_text": text[:2000],
            "benchmark_source": SOURCE,
            "language": "en",
            "modality": _TAG_MODALITY.get(row.get("primary_tag", ""), "text"),
            "domain": "general",
            "difficulty_tier": "moderate",
        })
        existing_ids.add(qid)

    by_mod: dict[str, int] = {}
    for r in new_rows:
        by_mod[r["modality"]] = by_mod.get(r["modality"], 0) + 1
    print(f"WildBench: {len(new_rows)} new questions "
          f"(dropped {dropped_leak} leakage, {dropped_dup} dup-id, {skipped_empty} empty)")
    print(f"  modality split: {by_mod}")
    if new_rows[:1]:
        print(f"  sample: {new_rows[0]['question_global_id']} :: {new_rows[0]['question_text'][:90]!r}")

    if args.dry_run or not new_rows:
        print("dry-run — nothing written" if args.dry_run else "nothing to add")
        return 0

    # --- verify Qdrant is reachable BEFORE mutating the parquet ---
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
    client = QdrantClient(host="127.0.0.1", port=6333, timeout=60.0)
    before = client.get_collection(COLLECTION).points_count
    print(f"qdrant collection '{COLLECTION}' reachable: {before} points")

    # --- append to questions.parquet (backup first) ---
    bak = QUESTIONS_PARQUET.with_suffix(".parquet.bak")
    shutil.copy2(QUESTIONS_PARQUET, bak)
    new_table = pa.table(
        {c: [r[c] for r in new_rows] for c in existing.schema.names},
        schema=existing.schema,
    )
    pq.write_table(pa.concat_tables([existing, new_table]), QUESTIONS_PARQUET, compression="zstd")
    print(f"questions.parquet: {existing.num_rows} -> {existing.num_rows + len(new_rows)}  (backup: {bak.name})")

    # --- embed the new questions + upsert (matches embed_corpus.py exactly) ---
    from sentence_transformers import SentenceTransformer
    from src.layer0_model_infra.config.routing_config import get_routing_config

    model = SentenceTransformer(get_routing_config().layer3.encoder.model_name, device="cuda")
    model.half()
    t0 = time.perf_counter()
    B = 64
    for i in range(0, len(new_rows), B):
        batch = new_rows[i:i + B]
        vecs = model.encode(
            [r["question_text"] for r in batch], batch_size=B,
            convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False,
        )
        points = [
            qmodels.PointStruct(
                id=int(hashlib.sha256(r["question_global_id"].encode()).hexdigest()[:15], 16),
                vector=v.tolist(),
                payload={
                    "question_global_id": r["question_global_id"],
                    "question_text": r["question_text"][:1000],
                    "benchmark_source": r["benchmark_source"],
                    "language": r["language"],
                    "modality": r["modality"],
                    "domain": r["domain"],
                    "difficulty_tier": r["difficulty_tier"],
                },
            )
            for r, v in zip(batch, vecs)
        ]
        client.upsert(collection_name=COLLECTION, points=points, wait=True)
    after = client.get_collection(COLLECTION).points_count
    print(f"qdrant: {before} -> {after} points (embedded {len(new_rows)} in {round(time.perf_counter() - t0, 1)}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
