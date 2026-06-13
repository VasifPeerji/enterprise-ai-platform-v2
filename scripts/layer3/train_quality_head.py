"""
📁 File: scripts/layer3/train_quality_head.py
Layer: Layer 0 — Layer 3 (offline training of the learned quality head)
Purpose: Train a per-model query->quality regressor on benchmark outcomes so the
         router can predict a model's quality on THIS query even when there are no
         kNN neighbours (the prior path), replacing the query-INDEPENDENT flat
         prior with a query-AWARE prediction.

Why a learned head
------------------
The kNN router only has per-query signal where benchmark neighbours exist. Off
that distribution it falls back to a flat per-model prior (a constant), so it
can't tell an easy query from a hard one and routes everything that clears the
floor to the strongest free model. A small regressor over the query embedding
generalises the per-query signal across the WHOLE space: it learns "queries that
look like THIS are easy/hard for model M". Measured (see _tmp experiment): the
embedding carries real signal (in-domain corr ~0.3), and for the weak/cheap model
it transfers to off-distribution conversational queries (corr +0.26) — exactly
the "can a cheaper model handle this?" decision routing needs.

Design
------
One Ridge regressor per model (embedding -> outcome in [0,1]), trained on that
model's outcomes. A model's head is INCLUDED in the artifact only if K-fold CV
shows it genuinely beats the constant baseline (corr >= MIN_CORR) — a head with
no signal would just inject noise, so those models keep the flat prior. The
artifact is a stack of linear weights (numpy), so production inference is a single
matrix multiply with NO torch/sklearn dependency.

Usage
-----
    python scripts/layer3/train_quality_head.py            # train + report, no write
    python scripts/layer3/train_quality_head.py --write    # also save the artifact

Artifact: src/layer0_model_infra/data/quality_head.npz (+ .json metrics sidecar).
Vectors come straight from the live Qdrant corpus so the trained space is exactly
the space the router encodes live queries into.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import duckdb
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold

OUTCOMES = (REPO / "data/processed/outcomes.parquet").as_posix()
QUESTIONS = (REPO / "data/processed/questions.parquet").as_posix()
REGISTRY_PATH = REPO / "src/layer0_model_infra/data/registry.json"
ARTIFACT = REPO / "src/layer0_model_infra/data/quality_head.npz"
METRICS = REPO / "src/layer0_model_infra/data/quality_head.json"

MIN_OUTCOMES = 300        # need this much data to fit a 384-dim regressor safely
MIN_CORR = 0.08           # CV correlation a head must beat the flat prior by
ALPHAS = [1.0, 10.0, 100.0, 300.0, 1000.0]
EMBED_DIM = 384


def fetch_vectors() -> dict[str, np.ndarray]:
    from qdrant_client import QdrantClient
    from src.layer0_model_infra.config.routing_config import get_routing_config
    from src.shared.config import get_settings
    s = get_settings()
    coll = get_routing_config().layer3.encoder.qdrant_collection
    c = QdrantClient(host=s.QDRANT_HOST, port=s.QDRANT_PORT, timeout=30)
    vecs: dict[str, np.ndarray] = {}
    offset = None
    while True:
        pts, offset = c.scroll(coll, limit=2000, with_vectors=True, with_payload=True, offset=offset)
        for p in pts:
            vecs[p.payload["question_global_id"]] = np.asarray(p.vector, dtype=np.float32)
        if offset is None:
            break
    return vecs


def _corr(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def cv_metrics(X, y) -> dict:
    """5-fold CV: head corr/MAE vs the constant (flat-prior) baseline."""
    kf = KFold(n_splits=5, shuffle=True, random_state=0)
    preds = np.zeros_like(y)
    const_abs = []
    for tr, te in kf.split(X):
        m = RidgeCV(alphas=ALPHAS)
        m.fit(X[tr], y[tr])
        preds[te] = np.clip(m.predict(X[te]), 0.0, 1.0)
        const_abs.append(np.mean(np.abs(y[te] - y[tr].mean())))
    return {
        "n": int(len(y)),
        "head_corr": round(_corr(preds, y), 4),
        "head_mae": round(float(np.mean(np.abs(preds - y))), 4),
        "const_mae": round(float(np.mean(const_abs)), 4),
        "mean_outcome": round(float(y.mean()), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    reg_ids = [m["model_id"] for m in registry["models"]]

    print("fetching corpus vectors from Qdrant...")
    VEC = fetch_vectors()
    print(f"  {len(VEC)} vectors (dim {len(next(iter(VEC.values())))})")

    con = duckdb.connect()
    rows = con.execute(f"""
      SELECT model_id, question_global_id, outcome
      FROM read_parquet('{OUTCOMES}')
    """).fetchall()
    by_model: dict[str, list] = {}
    for mid, qid, out in rows:
        v = VEC.get(qid)
        if v is not None and mid in reg_ids:
            by_model.setdefault(mid, []).append((v, float(out)))

    included, weights, biases, metrics = [], [], [], {}
    print(f"\n{'model':30} {'n':>6} {'cv_corr':>8} {'head_mae':>9} {'const_mae':>10} {'verdict'}")
    print("-" * 78)
    for mid in reg_ids:
        pairs = by_model.get(mid, [])
        if len(pairs) < MIN_OUTCOMES:
            metrics[mid] = {"n": len(pairs), "included": False, "reason": "insufficient_data"}
            print(f"{mid:30} {len(pairs):6} {'—':>8} {'—':>9} {'—':>10} skip (prior)")
            continue
        X = np.stack([p[0] for p in pairs])
        y = np.array([p[1] for p in pairs], dtype=np.float32)
        cv = cv_metrics(X, y)
        include = cv["head_corr"] >= MIN_CORR and cv["head_mae"] <= cv["const_mae"]
        cv["included"] = include
        metrics[mid] = cv
        verdict = "INCLUDE" if include else "skip (no signal -> prior)"
        print(f"{mid:30} {cv['n']:6} {cv['head_corr']:+8.3f} {cv['head_mae']:9.3f} "
              f"{cv['const_mae']:10.3f} {verdict}")
        if include:
            m = RidgeCV(alphas=ALPHAS)
            m.fit(X, y)
            included.append(mid)
            weights.append(m.coef_.astype(np.float32))
            biases.append(np.float32(m.intercept_))

    print(f"\nheads with real signal: {len(included)} -> {included}")
    if args.write and included:
        from src.layer0_model_infra.config.routing_config import get_routing_config
        enc = get_routing_config().layer3.encoder.model_name
        np.savez(
            ARTIFACT,
            model_ids=np.array(included),
            weights=np.stack(weights),         # (k, 384)
            biases=np.array(biases),           # (k,)
            encoder_name=np.array(enc),
            embed_dim=np.array(EMBED_DIM),
        )
        METRICS.write_text(json.dumps({
            "_meta": {
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "encoder": enc,
                "min_outcomes": MIN_OUTCOMES,
                "min_corr": MIN_CORR,
                "note": "Per-model Ridge over the MiniLM query embedding -> outcome. "
                        "Used on the prior path only; models absent here keep the flat prior.",
                "regenerate": "python scripts/layer3/train_quality_head.py --write",
            },
            "models": metrics,
        }, indent=2), encoding="utf-8")
        print(f"[WROTE] {ARTIFACT}\n[WROTE] {METRICS}")
    elif args.write:
        print("nothing to write (no model cleared the signal bar)")
    else:
        print("(analysis only -- re-run with --write to save the artifact)")


if __name__ == "__main__":
    main()
