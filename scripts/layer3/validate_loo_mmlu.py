"""
scripts/layer3/validate_loo_mmlu.py  (WORKING TOOL — not committed yet)

Honest BEFORE/AFTER measurement of the deterministic MMLU-Pro grounding
(generate_mmlu_outcomes.py -> outcomes_mmlu_det.parquet).

Leave-one-out, leakage-safe: for each grounded MMLU-Pro question we route it but
MASK its own self-match in Qdrant (must_not on its qid), forcing the router to
generalise from OTHER neighbours, then score its pick against the REAL per-model
outcomes. Run it once with the new models OUT of the corpus and once with them IN
(merge in between) -- the corpus is the ONLY thing that changes, so the delta is
the grounding effect, nothing else.

Scoring matrix (ground truth, identical both runs, corpus-independent):
  • the 4 newly-grounded models  <- harvested/outcomes_mmlu_det.parquet
  • the 3 already-grounded free models <- live outcomes.parquet (filtered to these qids)
Baselines: always-cheapest (llama-8b), always-strongest-free (gpt-oss-120b),
oracle (best free model per question). Cost = model size (all free).

Usage:
  python scripts/layer3/validate_loo_mmlu.py --label before
  # ... merge ...
  python scripts/layer3/validate_loo_mmlu.py --label after
"""
from __future__ import annotations

import argparse
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

NEW = REPO_ROOT / "data" / "processed" / "harvested" / "outcomes_mmlu_det.parquet"
LIVE = REPO_ROOT / "data" / "processed" / "outcomes.parquet"
QUESTIONS = REPO_ROOT / "data" / "processed" / "questions.parquet"

NEW_FREE = ["gpt-oss-120b-groq", "gpt-oss-20b-groq", "qwen3-32b-groq", "llama-4-scout-17b-groq"]
OLD_FREE = ["llama-3.1-8b-instant-groq", "llama-3.3-70b-versatile-groq", "qwen-2.5-72b-huggingface"]
CHEAP, STRONG, PROXY = "llama-3.1-8b-instant-groq", "gpt-oss-120b-groq", "llama-3.3-70b-versatile-groq"


def _mean(xs):
    s = pd.Series(list(xs), dtype="float64").dropna()
    return float(s.mean()) if len(s) else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run", help="before | after (for the saved json)")
    ap.add_argument("--free-only", action="store_true",
                    help="deactivate paid models (gemini/claude/gpt-4o) so every pick is a "
                         "free model with a real outcome — clean, proxy-free scoring")
    args = ap.parse_args()

    if args.free_only:
        # drop premium keys BEFORE the registry reads activation, so the router
        # genuinely chooses among the free fleet only (all in the scoring matrix)
        for _k in ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]:
            os.environ.pop(_k, None)

    # ---- ground-truth scoring matrix (corpus-independent) ----
    new = pd.read_parquet(NEW)[["question_global_id", "model_id", "outcome"]]
    gqids = set(new.question_global_id.unique())
    live = pd.read_parquet(LIVE)
    old = live[(live.model_id.isin(OLD_FREE)) & (live.question_global_id.isin(gqids))][
        ["question_global_id", "model_id", "outcome"]]
    score = pd.concat([new, old], ignore_index=True)
    piv = score.pivot_table(index="question_global_id", columns="model_id", values="outcome")

    qtext = pd.read_parquet(QUESTIONS).set_index("question_global_id")["question_text"]

    # ---- router (deterministic, on-policy) ----
    from src.layer0_model_infra.routing.registry_loader import get_layer3_registry
    from src.layer0_model_infra.routing.knn_router import get_knn_router, make_feature_cell
    get_layer3_registry().refresh_activation()
    r = get_knn_router(); r.warmup()
    r._config.verdict_cache.enable = False
    r._config.exploration.rate = 0.0
    r._config.warmup.forced_selection_rate = 0.0
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
        text = str(qtext.get(qid, "") or "")
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
        if m in piv.columns and not pd.isna(piv.loc[qid, m]):
            rs, proxied = float(piv.loc[qid, m]), False
        elif not pd.isna(piv.loc[qid, PROXY]):
            rs, proxied = float(piv.loc[qid, PROXY]), True  # keyless/unscored premium -> free proxy
        else:
            rs, proxied = None, False
        rows.append({
            "picked": m, "is_new": m in NEW_FREE, "proxied": proxied, "router": rs,
            "compute": r._model_compute_cost(m),
            "o_cheap": (float(piv.loc[qid, CHEAP]) if CHEAP in piv.columns and not pd.isna(piv.loc[qid, CHEAP]) else None),
            "o_strong": (float(piv.loc[qid, STRONG]) if STRONG in piv.columns and not pd.isna(piv.loc[qid, STRONG]) else None),
            "oracle": float(piv.loc[qid].max()),
        })

    df = pd.DataFrame(rows)
    router, cheap, strong, oracle = _mean(df.router), _mean(df.o_cheap), _mean(df.o_strong), _mean(df.oracle)
    lift_pp = (router - cheap) * 100

    print("=" * 72)
    print(f"LOO MMLU-Pro grounding measurement  [{args.label}]  n={len(df)} questions")
    print("=" * 72)
    print("CORRECTNESS (mean real outcome 0-1):")
    print(f"  router            : {router:.3f}    mean compute {_mean(df.compute):.1f}B")
    print(f"  always-cheapest   : {cheap:.3f}    ({CHEAP}, 8B)")
    print(f"  always-strongest  : {strong:.3f}    ({STRONG}, 120B)")
    print(f"  oracle (best/q)   : {oracle:.3f}")
    print(f"  >> lift vs cheapest: {lift_pp:+.1f} pp")
    print(f"COST: router mean compute {_mean(df.compute):.1f}B vs strongest 120B; "
          f"free-select {df.picked.isin(NEW_FREE + OLD_FREE).mean()*100:.0f}%")
    print(f"NEW models picked  : {df.is_new.mean()*100:.0f}% of routes  (proxied scores: {int(df.proxied.sum())})")
    print(f"PICK DISTRIBUTION  : {dict(collections.Counter(df.picked).most_common())}")

    out = REPO_ROOT / "artifacts" / "layer3" / f"loo_mmlu_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "label": args.label, "n": len(df),
        "router": router, "always_cheapest": cheap, "always_strongest": strong, "oracle": oracle,
        "lift_pp": lift_pp, "router_mean_compute": _mean(df.compute),
        "new_pick_rate": float(df.is_new.mean()),
        "pick_distribution": dict(collections.Counter(df.picked).most_common()),
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
