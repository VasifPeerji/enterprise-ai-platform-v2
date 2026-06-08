"""
scripts/layer3/validate_loo.py

Leave-one-out GENERALIZATION gate for the kNN router, at $0 / no provider calls.

The held-out 650-query gate needs per-model answers graded by an LLM judge, which
is impractical on the free API tiers (~1 outcome/min -> tens of hours). This is the
zero-cost stand-in: for each conversational task we already grounded, route it but
MASK its own self-match in Qdrant (a Qdrant must_not filter on its qid), forcing
the router to generalise from OTHER neighbours -- exactly the novel-query case --
then score its pick against the known per-model outcomes we already have.

Reports router correctness vs always-cheapest (the >=10pp lift) and vs
always-strongest (the cost saving). Picks outside the grounded set (keyless premium
etc.) are scored with a strong-free proxy; the report states how many.

Usage:
  python scripts/layer3/validate_loo.py
"""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import dotenv_values
for _k, _v in dotenv_values(REPO_ROOT / ".env").items():
    if _k.endswith("_API_KEY") and _v:
        os.environ.setdefault(_k, _v.strip())
os.environ.setdefault("LAYER3_CANARY_FRACTION", "1.0")

import pandas as pd  # noqa: E402
from qdrant_client.http import models as qm  # noqa: E402

CHEAP, STRONG, PROXY = "llama-3.1-8b-instant-groq", "gpt-oss-120b-groq", "llama-3.3-70b-versatile-groq"
GEN = REPO_ROOT / "data" / "processed" / "harvested" / "outcomes_generated.parquet"
QUESTIONS = REPO_ROOT / "data" / "processed" / "questions.parquet"


def _mean(xs):
    s = pd.Series(list(xs), dtype="float64").dropna()
    return float(s.mean()) if len(s) else float("nan")


def main() -> int:
    from src.layer0_model_infra.routing.registry_loader import get_layer3_registry
    from src.layer0_model_infra.routing.knn_router import get_knn_router, make_feature_cell

    get_layer3_registry().refresh_activation()
    r = get_knn_router(); r.warmup()
    # Deterministic, on-policy selection (no cache replay, no exploration/warmup noise).
    r._config.verdict_cache.enable = False
    r._config.exploration.rate = 0.0
    r._config.warmup.forced_selection_rate = 0.0

    gen = pd.read_parquet(GEN)
    q = pd.read_parquet(QUESTIONS).set_index("question_global_id")["question_text"]
    piv = gen.pivot_table(index="question_global_id", columns="model_id", values="outcome")
    grounded = set(piv.columns)
    coll = r._config.encoder.qdrant_collection

    def search_excl(emb, qid):
        resp = r.qdrant.query_points(
            collection_name=coll, query=emb.tolist(),
            query_filter=qm.Filter(must_not=[qm.FieldCondition(
                key="question_global_id", match=qm.MatchValue(value=qid))]),
            limit=r._config.knn.knn_k, score_threshold=r._config.knn.min_similarity,
            with_payload=True)
        return list(resp.points)

    rows = []
    for qid in piv.index:
        text = str(q.get(qid, "") or "")
        if not text.strip():
            continue
        feats = r.feature_extractor.extract(text)
        emb = r._encode(text)
        cell = make_feature_cell(feats)
        nbrs = search_excl(emb, qid)
        if len(nbrs) >= r._config.knn.min_neighbors_for_trust:
            quals, conf, _, cs = r._predict_qualities(feats, nbrs, cell)
            d = r._choose(text, feats, quals, conf, nbrs, "loo", cell, knn_grounded=True, confidence_scores=cs)
        else:
            quals, conf, _, cs = r._predict_qualities(feats, [], cell)
            d = r._choose(text, feats, quals, conf, [], "loo", cell, knn_grounded=False, confidence_scores=cs)
        m = d.selected_model
        if m in grounded and not pd.isna(piv.loc[qid, m]):
            rs, pr = float(piv.loc[qid, m]), False
        elif not pd.isna(piv.loc[qid, PROXY]):
            rs, pr = float(piv.loc[qid, PROXY]), True
        else:
            rs, pr = None, False
        rows.append({
            "picked": m, "in_grounded": m in grounded, "proxy": pr, "router": rs,
            "compute": r._model_compute_cost(m),
            "o_cheap": (float(piv.loc[qid, CHEAP]) if not pd.isna(piv.loc[qid, CHEAP]) else None),
            "o_strong": (float(piv.loc[qid, STRONG]) if not pd.isna(piv.loc[qid, STRONG]) else None),
            "oracle": float(piv.loc[qid].max()),
        })

    df = pd.DataFrame(rows)
    router, cheap, strong = _mean(df.router), _mean(df.o_cheap), _mean(df.o_strong)
    lift_pp = (router - cheap) * 100
    print(f"LEAVE-ONE-OUT generalization, {len(df)} conversational tasks (self-match masked, $0):")
    print(f"  router (LOO)      : {router:.3f}   mean compute {_mean(df.compute):.1f}")
    print(f"  always-cheapest   : {cheap:.3f}   compute 8")
    print(f"  always-strongest  : {strong:.3f}   compute 120")
    print(f"  oracle (best/task): {_mean(df.oracle):.3f}")
    print(f"  >> LIFT vs cheapest: {lift_pp:+.1f} pp   gate(>=10pp): {'PASS' if lift_pp >= 10 else 'FAIL'}")
    print(f"  picks scoreable in grounded set: {df.in_grounded.mean()*100:.0f}%   proxy-scored: {int(df.proxy.sum())}")
    print(f"  pick distribution : {dict(collections.Counter(df.picked).most_common())}")

    out = REPO_ROOT / "artifacts" / "layer3" / "validate_loo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "n": len(df), "router": router, "always_cheapest": cheap, "always_strongest": strong,
        "oracle": _mean(df.oracle), "lift_pp": lift_pp, "gate_pass": bool(lift_pp >= 10),
        "router_mean_compute": _mean(df.compute), "picks_in_grounded_pct": float(df.in_grounded.mean()),
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
