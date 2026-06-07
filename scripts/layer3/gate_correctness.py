"""
scripts/layer3/gate_correctness.py

The CORRECTNESS GATE for Layer 3. Routes the 650 held-out validation queries
through the live kNN router, then scores each routed pick against
validation_outcomes.parquet (built by generate_validation_outcomes.py) and
compares the router to fixed-model baselines.

The objective is "pick the model that correctly answers the query, cheaply", so
both halves are reported:
  correctness : router mean outcome vs ALWAYS-CHEAPEST  -> the >=10pp lift the gate wants
  cost        : router mean compute vs ALWAYS-STRONGEST -> the savings at equal-ish correctness

Grading is internally consistent (one rubric judge), so absolute scores are less
meaningful than the RELATIVE gaps between router and baselines.

Keyless premium picks (claude / gpt-4o have no key) execute via the free fallback,
so they are scored with a strong-free fallback's outcome (a documented proxy);
the report states how many picks needed it.

Usage:
  python scripts/layer3/gate_correctness.py
  python scripts/layer3/gate_correctness.py --limit 100
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import dotenv_values
for _k, _v in dotenv_values(REPO_ROOT / ".env").items():
    if _k.endswith("_API_KEY") and _v:
        os.environ.setdefault(_k, _v.strip())
os.environ.setdefault("LAYER3_CANARY_FRACTION", "1.0")

import pandas as pd  # noqa: E402

CHEAP = "llama-3.1-8b-instant-groq"          # always-cheapest baseline
STRONG = "gpt-oss-120b-groq"                 # always-strongest-free baseline
FALLBACK_PROXY = "llama-3.3-70b-versatile-groq"  # execution proxy for keyless picks
GATE_PP = 0.10                               # >=10pp correctness lift vs cheapest

VAL = REPO_ROOT / "data" / "processed" / "validation_set.parquet"
VAL_OUT = REPO_ROOT / "data" / "processed" / "validation_outcomes.parquet"


def _mean(xs):
    s = pd.Series(list(xs), dtype="float64").dropna()
    return float(s.mean()) if len(s) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default="artifacts/layer3/gate_correctness.json")
    args = ap.parse_args()

    if not VAL_OUT.exists() or VAL_OUT.stat().st_size < 200:
        print(f"validation_outcomes not found at {VAL_OUT}\n"
              f"run: python scripts/layer3/generate_validation_outcomes.py")
        return 1

    vo = pd.read_parquet(VAL_OUT)
    # outcome[(qid, model)] -> score (mean if a pair was graded more than once)
    outcome = vo.groupby(["question_global_id", "model_id"])["outcome"].mean().to_dict()
    scored_models = sorted(vo.model_id.unique())
    by_q = defaultdict(dict)
    for (qid, mid), o in outcome.items():
        by_q[qid][mid] = o

    vs = pd.read_parquet(VAL)[["question_global_id", "question_text", "benchmark_source", "difficulty_tier"]]
    if args.limit:
        vs = vs.iloc[: args.limit]

    from src.layer0_model_infra.routing.registry_loader import get_layer3_registry
    from src.layer0_model_infra.routing.knn_router import get_knn_router
    reg = get_layer3_registry(); reg.refresh_activation()
    free_ids = {e.model_id for e in reg.all_models()
                if e.pricing.input_per_1m_usd == 0.0 and e.pricing.output_per_1m_usd == 0.0}
    r = get_knn_router(); r.warmup()

    recs = []
    keyless_proxy_used = 0
    unscored = 0
    for qid, text, src, diff in vs.itertuples(index=False, name=None):
        d = r.route(str(text) or "")
        m = d.selected_model
        # router correctness: the routed model's outcome; keyless/unscored -> proxy
        rs = by_q.get(qid, {}).get(m)
        if rs is None:
            proxy = by_q.get(qid, {}).get(FALLBACK_PROXY)
            if proxy is not None:
                rs = proxy
                keyless_proxy_used += 1
            else:
                unscored += 1
        recs.append({
            "qid": qid, "src": src, "difficulty": diff, "routed": m,
            "is_free": m in free_ids,
            "compute": r._model_compute_cost(m),
            "router_score": rs,
            "cheap_score": by_q.get(qid, {}).get(CHEAP),
            "strong_score": by_q.get(qid, {}).get(STRONG),
            "oracle_score": (max(by_q[qid].values()) if by_q.get(qid) else None),
        })

    df = pd.DataFrame(recs)
    router = _mean(df.router_score)
    cheap = _mean(df.cheap_score)
    strong = _mean(df.strong_score)
    oracle = _mean(df.oracle_score)
    lift = (router - cheap) if (router is not None and cheap is not None) else None

    print("=" * 72)
    print("LAYER 3 CORRECTNESS GATE  (650 held-out queries, rubric-judged)")
    print("=" * 72)
    print(f"scored models in validation_outcomes: {scored_models}")
    print(f"routed {len(df)} queries; keyless picks scored via {FALLBACK_PROXY}: {keyless_proxy_used}; unscored: {unscored}")
    print(f"\nCORRECTNESS (mean rubric outcome 0-1):")
    print(f"  router            : {router:.3f}")
    print(f"  always-cheapest   : {cheap:.3f}  ({CHEAP})")
    print(f"  always-strongest  : {strong:.3f}  ({STRONG})")
    print(f"  oracle (best/q)   : {oracle:.3f}")
    print(f"  >> lift vs cheapest: {lift*100:+.1f} pp   gate (>= {GATE_PP*100:.0f}pp): "
          f"{'PASS' if (lift is not None and lift >= GATE_PP) else 'FAIL'}")
    print(f"\nCOST (compute-size proxy; all served models are free so $=0):")
    print(f"  router mean compute: {_mean(df.compute):.1f}")
    print(f"  always-strongest   : {df['compute'].map(lambda _: 120).mean():.1f} (120b)")
    print(f"  router free-select : {df.is_free.mean()*100:.0f}%")
    print(f"\nROUTED MODEL DISTRIBUTION: {dict(Counter(df.routed).most_common())}")

    print(f"\nBY SOURCE:")
    for s in sorted(df.src.unique()):
        sub = df[df.src == s]
        rl = _mean(sub.router_score); cl = _mean(sub.cheap_score)
        print(f"  {s:12} n={len(sub):3} router={rl:.3f} cheap={cl:.3f} "
              f"lift={(rl-cl)*100:+.1f}pp compute={_mean(sub.compute):.1f}")
    print(f"\nBY DIFFICULTY:")
    for s in sorted(df.difficulty.unique()):
        sub = df[df.difficulty == s]
        rl = _mean(sub.router_score); cl = _mean(sub.cheap_score); st = _mean(sub.strong_score)
        print(f"  {s:10} n={len(sub):3} router={rl:.3f} cheap={cl:.3f} strong={st:.3f} compute={_mean(sub.compute):.1f}")

    import json
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "n": len(df), "router": router, "always_cheapest": cheap,
        "always_strongest": strong, "oracle": oracle, "lift_pp": (lift * 100 if lift is not None else None),
        "gate_pass": bool(lift is not None and lift >= GATE_PP),
        "router_mean_compute": _mean(df.compute), "router_free_rate": float(df.is_free.mean()),
        "keyless_proxy_used": keyless_proxy_used, "unscored": unscored,
        "scored_models": scored_models,
    }
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
