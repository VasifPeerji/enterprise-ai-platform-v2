"""
📁 File: scripts/layer3/validate_routing.py
Layer: Layer 0 — Layer 3 redesign (Batch 4 — validation harness)
Purpose: Measure the kNN router's REAL behaviour over the 650 locked validation
         queries so activation (shadow -> canary) is driven by measurement, not
         the design doc. Reports fallback rate + reasons, kNN-vs-prior fire rate,
         free-vs-paid selection (the over-routing proxy), latency p50/p99, and
         estimated cost per query, broken down by benchmark source.
Depends on: data/processed/validation_set.parquet (built by build_validation_set.py,
            train/test-isolated from the kNN corpus — verified 0 leakage), a live
            encoder + Qdrant.
Used by: the owner, before dialling LAYER3_CANARY_FRACTION up.

$0 — this runs the ROUTER only (encode + Qdrant ANN + selection). It never calls
the selected model, so no provider tokens are spent. Provider keys are read from
.env purely so env-gated model activation matches production.

Note on the over-routing metric: true over-/under-routing needs the post-call
Layer-7 quality the online loop will provide. Until then this reports the closest
measurable proxy — the paid-model selection rate (how often a query is routed to
a non-free model, whether by kNN or by the premium fallback default).

Usage:
  python scripts/layer3/validate_routing.py
  python scripts/layer3/validate_routing.py --limit 50 --out artifacts/layer3/validation_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_env_keys() -> None:
    """Inject provider *_API_KEY values from .env into os.environ so the registry's
    env-gated activation matches production. Only API keys are touched — config
    vars are left for pydantic-settings to load (it strips their inline comments;
    a naive parser does not)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(env_path)
    except Exception:
        import re
        vals = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = re.split(r"\s+#", v, 1)[0].strip().strip('"').strip("'")
    for k, v in vals.items():
        if isinstance(k, str) and k.endswith("_API_KEY") and v and k not in os.environ:
            os.environ[k] = v


def _percentile(values, p):
    if not values:
        return 0.0
    import numpy as np
    return float(np.percentile(values, p))


def _slice_metrics(recs):
    """Compute the routing-behaviour metrics for a slice of routed records."""
    n = len(recs)
    if n == 0:
        return {"n": 0}
    fb = [r for r in recs if r["source"] == "fallback"]
    knn = [r for r in recs if r["source"] == "knn_corpus"]
    knn_used_neighbors = sum(1 for r in knn if r["prediction_confidence"] == "high")
    free_sel = sum(1 for r in recs if r["is_free"])
    lat = [r["latency_ms"] for r in recs]
    cost = [r["estimated_cost_usd"] for r in recs]
    return {
        "n": n,
        "source_distribution": dict(Counter(r["source"] for r in recs)),
        "fallback_rate": round(len(fb) / n, 4),
        "fallback_reasons": dict(Counter(r["fallback_reason"] for r in fb)),
        "knn_corpus_rate": round(len(knn) / n, 4),
        # of the kNN-corpus routes, how many used real neighbour outcomes (high
        # confidence) vs fell through to the aggregate prior (low confidence).
        "knn_used_neighbors_rate": round(knn_used_neighbors / len(knn), 4) if knn else None,
        "free_selection_rate": round(free_sel / n, 4),
        "paid_selection_rate": round((n - free_sel) / n, 4),  # over-routing proxy
        "latency_ms": {
            "p50": round(_percentile(lat, 50), 1),
            "p95": round(_percentile(lat, 95), 1),
            "p99": round(_percentile(lat, 99), 1),
            "mean": round(sum(lat) / n, 1),
        },
        "est_cost_usd": {"mean": sum(cost) / n, "total": sum(cost)},
        "top_models": Counter(r["selected_model"] for r in recs).most_common(8),
    }


def _aggregate(records):
    report = {"overall": _slice_metrics(records), "by_source": {}}
    for src in sorted({r["benchmark_source"] for r in records}):
        report["by_source"][src] = _slice_metrics(
            [r for r in records if r["benchmark_source"] == src]
        )
    return report


def _print_report(report):
    def show(title, m):
        if not m.get("n"):
            print(f"\n[{title}] (no queries)")
            return
        knnp = m["knn_used_neighbors_rate"]
        knn_txt = f"{knnp:.1%}" if knnp is not None else "n/a"
        lat = m["latency_ms"]
        print(f"\n[{title}]  n={m['n']}")
        print(f"  source            : {m['source_distribution']}")
        print(f"  fallback_rate     : {m['fallback_rate']:.1%}   reasons: {m['fallback_reasons']}")
        print(f"  knn_corpus_rate   : {m['knn_corpus_rate']:.1%}   (used real neighbours: {knn_txt}, rest prior)")
        print(f"  selection         : free={m['free_selection_rate']:.1%}  paid={m['paid_selection_rate']:.1%} (over-routing proxy)")
        print(f"  latency_ms        : p50={lat['p50']} p95={lat['p95']} p99={lat['p99']} mean={lat['mean']}")
        print(f"  est_cost_usd      : mean={m['est_cost_usd']['mean']:.6f} total={m['est_cost_usd']['total']:.4f}")
        print(f"  top_models        : {m['top_models'][:5]}")

    print("=" * 72)
    print("BATCH 4 — kNN ROUTING VALIDATION (locked queries, $0, router-only)")
    print("=" * 72)
    show("OVERALL", report["overall"])
    for src, m in report["by_source"].items():
        show(f"source={src}", m)


def _apply_free_fallback(reg, active_ids):
    """What-if override: point the non-high-risk safe defaults at free strong
    models, keeping the high-risk default premium so medical / legal / financial
    off-distribution queries stay on the safer model. Mutates the in-memory
    registry only — nothing on disk changes."""
    from src.layer0_model_infra.routing.layer3_types import SafeDefaults
    free_text, free_code, free_math = (
        "llama-3.3-70b-versatile-groq",
        "qwen-2.5-coder-32b-openrouter-free",
        "qwen-qwq-32b-groq",
    )
    missing = [m for m in (free_text, free_code, free_math) if m not in active_ids]
    if missing:
        print(f"  [free-fallback] skipped — free models inactive: {missing}")
        return "registry_default"
    old = reg.safe_defaults
    reg._safe_defaults = SafeDefaults(
        text=free_text, code=free_code, math=free_math,
        vision=old.vision, multimodal=old.multimodal,
        high_risk=old.high_risk,  # keep premium for medical / legal / financial
    )
    print(f"  [free-fallback] text->{free_text}, code->{free_code}, "
          f"math->{free_math}; high_risk stays {old.high_risk}")
    return "free_nonhighrisk_premium_highrisk"


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch 4 — kNN routing validation harness")
    ap.add_argument("--validation", default="data/processed/validation_set.parquet")
    ap.add_argument("--limit", type=int, default=None, help="cap queries (debug)")
    ap.add_argument("--out", default="artifacts/layer3/validation_report.json")
    ap.add_argument(
        "--free-fallback",
        action="store_true",
        help="What-if: route non-high-risk off-distribution queries to free "
             "strong models (high-risk stays premium); measures the cost of the "
             "premium fallback default. In-memory only.",
    )
    args = ap.parse_args()

    _load_env_keys()

    import duckdb
    from src.layer0_model_infra.routing.knn_router import get_knn_router
    from src.layer0_model_infra.routing.registry_loader import get_layer3_registry

    reg = get_layer3_registry()
    reg.refresh_activation()
    free_ids = {
        e.model_id for e in reg.all_models()
        if e.pricing.input_per_1m_usd == 0.0 and e.pricing.output_per_1m_usd == 0.0
    }
    active_ids = {e.model_id for e in reg.active_models()}
    print(f"registry: {len(active_ids)} active / {len(reg.all_models())} total; {len(free_ids)} free")

    fallback_policy = "registry_default"
    if args.free_fallback:
        fallback_policy = _apply_free_fallback(reg, active_ids)

    vpath = (REPO_ROOT / args.validation).as_posix()
    rows = duckdb.connect(":memory:").execute(
        "select question_global_id, question_text, benchmark_source "
        "from read_parquet(?) order by question_global_id",
        [vpath],
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"loaded {len(rows)} validation queries")

    router = get_knn_router()
    t_warm = time.monotonic()
    router.warmup()
    print(f"warmup: {round(time.monotonic() - t_warm, 1)}s")

    records, errors = [], 0
    t0 = time.monotonic()
    for i, (qid, text, src) in enumerate(rows):
        try:
            d = router.route(text or "")
            sel = d.selected_model
            records.append({
                "qid": qid,
                "benchmark_source": src,
                "source": d.source.value,
                "selected_model": sel,
                "is_free": sel in free_ids,
                "prediction_confidence": d.prediction_confidence,
                "predicted_quality": d.predicted_quality,
                "fallback_reason": d.fallback_reason,
                "effective_floor": d.effective_floor,
                "estimated_cost_usd": d.estimated_cost_usd,
                "latency_ms": d.latency_ms,
            })
        except Exception as exc:
            errors += 1
            print(f"  ERROR routing {qid}: {type(exc).__name__}: {exc}")
        if (i + 1) % 100 == 0:
            print(f"  routed {i + 1}/{len(rows)} ({round(time.monotonic() - t0, 1)}s)")
    wall = time.monotonic() - t0
    print(f"routed {len(records)} queries in {round(wall, 1)}s ({errors} errors)")

    report = _aggregate(records)
    report["_meta"] = {
        "n_queries": len(records),
        "errors": errors,
        "wall_seconds": round(wall, 1),
        "active_models": len(active_ids),
        "free_models": len(free_ids),
        "fallback_policy": fallback_policy,
    }
    _print_report(report)

    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
