"""
Layer 2 (Semantic Memory) Benchmark Suite
==========================================

Runs SemanticMemory against the golden set:
  - For each case: record the entry, then look up
  - Compare actual hit/guard verdict vs expected
  - Emit hit-rate, precision, recall, per-category breakdown, latency stats

Output: artifacts/layer_2/benchmark_results.json
Usage:
  python scripts/benchmark_layer_2.py
  python scripts/benchmark_layer_2.py --strict
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.semantic_memory import SemanticMemory  # noqa: E402


ACCURACY_FLOOR = 0.85           # bypass / guard decisions must match expected
LATENCY_P99_BUDGET_MS = 10.0    # Layer 2 budget — embedding + matrix-vec
LATENCY_P50_BUDGET_MS = 5.0


def make_memory() -> SemanticMemory:
    """Fresh instance — persistence off so each benchmark run starts clean."""
    return SemanticMemory(
        similarity_threshold=0.75,
        decay_half_life_seconds=604_800.0,
        enable_local_embedding=True,
        enable_persistence=False,
    )


def run_case(mem: SemanticMemory, case: dict) -> dict:
    """Record the entry, then look up; return the verdict row."""
    rec = case["record"]
    mem.record(
        query=rec["query"],
        model_id=rec["model_id"],
        quality_score=rec["quality_score"],
        escalated=rec["escalated"],
        intent=rec.get("intent", ""),
        domain=rec.get("domain", ""),
        complexity_band=rec.get("complexity_band", ""),
        model_version=rec.get("model_version", ""),
        tenant_id=rec.get("tenant_id", ""),
    )

    t0 = time.perf_counter_ns()
    result = mem.lookup(
        case["lookup"],
        query_intent=case.get("lookup_intent", ""),
        current_model_version=case.get("lookup_model_version"),
        tenant_id=case.get("lookup_tenant_id", ""),
    )
    t1 = time.perf_counter_ns()

    latency_us = (t1 - t0) / 1000

    hit_correct = result.hit == case["expected_hit"]
    # Guard accuracy semantics: a guard is "correct" if either
    #  (a) the expected guard fired, OR
    #  (b) the verdict (hit/miss) is already correct because Model2Vec's
    #      similarity threshold caught it before the guard layer.
    # The point of guards is to catch what the embedding misses; if the
    # embedding already rejects, the guard not firing is fine.
    guard_correct = True
    if case.get("expected_guard_rejected"):
        if result.guard_rejected is not None:
            guard_correct = case["expected_guard_rejected"] in result.guard_rejected
        else:
            # No guard fired — only "correct" if similarity was below threshold
            # (i.e. embedding caught it). Bypass-via-similarity is also OK.
            guard_correct = (
                hit_correct and result.similarity < 0.75
            )
    correct = hit_correct and guard_correct

    return {
        "id": case["id"],
        "category": case["category"],
        "expected_hit": case["expected_hit"],
        "actual_hit": result.hit,
        "expected_guard": case.get("expected_guard_rejected"),
        "actual_guard": result.guard_rejected,
        "similarity": round(result.similarity, 3),
        "novelty": round(result.novelty_score, 3),
        "detector": result.detector_used,
        "correct": correct,
        "hit_correct": hit_correct,
        "guard_correct": guard_correct,
        "latency_us": round(latency_us, 1),
        "rationale": case.get("rationale", ""),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--golden-set", type=Path,
                   default=REPO_ROOT / "artifacts" / "layer_2" / "golden_set.json")
    p.add_argument("--out", type=Path,
                   default=REPO_ROOT / "artifacts" / "layer_2" / "benchmark_results.json")
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()

    if not args.golden_set.exists():
        print(f"ERROR: {args.golden_set} not found", file=sys.stderr)
        return 1

    payload = json.loads(args.golden_set.read_text(encoding="utf-8"))
    cases = payload["cases"]
    print(f"Loaded {len(cases)} golden cases from {args.golden_set}")

    rows = []
    for case in cases:
        # Use a FRESH instance per case so prior entries don't leak between scenarios
        mem = make_memory()
        rows.append(run_case(mem, case))

    n = len(rows)
    correct = sum(r["correct"] for r in rows)
    accuracy = correct / n if n else 0.0
    hit_correct = sum(r["hit_correct"] for r in rows)
    guard_correct = sum(r["guard_correct"] for r in rows)

    latencies = [r["latency_us"] for r in rows]
    lat_sorted = sorted(latencies)
    lat = {
        "p50_us": lat_sorted[len(lat_sorted) // 2],
        "p95_us": lat_sorted[int(0.95 * len(lat_sorted))],
        "p99_us": lat_sorted[int(0.99 * len(lat_sorted)) if len(lat_sorted) > 100 else -1],
        "max_us": lat_sorted[-1],
        "mean_us": statistics.mean(lat_sorted),
    }

    print("\n" + "=" * 70)
    print(" Layer 2 Semantic Memory — Benchmark Results")
    print("=" * 70)
    print(f"\nTotal cases: {n}")
    print(f"  Overall accuracy:    {accuracy:.1%}  ({correct}/{n})")
    print(f"  Hit-decision correct: {hit_correct}/{n} ({hit_correct/n:.1%})")
    print(f"  Guard correct:        {guard_correct}/{n} ({guard_correct/n:.1%})")

    print(f"\nLatency (us):")
    print(f"  p50: {lat['p50_us']:.0f}")
    print(f"  p95: {lat['p95_us']:.0f}")
    print(f"  p99: {lat['p99_us']:.0f}")
    print(f"  max: {lat['max_us']:.0f}")

    # Per-category breakdown
    by_cat: dict[str, dict] = {}
    for r in rows:
        slot = by_cat.setdefault(r["category"], {"total": 0, "correct": 0})
        slot["total"] += 1
        if r["correct"]:
            slot["correct"] += 1
    print(f"\nPer-category accuracy:")
    for cat in sorted(by_cat):
        s = by_cat[cat]
        print(f"  {cat:25s}  {s['correct']/s['total']:.1%}  ({s['correct']}/{s['total']})")

    # Failures
    failures = [r for r in rows if not r["correct"]]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures[:10]:
            print(f"  [{f['category']}] {f['id']}")
            print(f"    expected hit={f['expected_hit']} guard={f['expected_guard']}")
            print(f"    actual   hit={f['actual_hit']} guard={f['actual_guard']} "
                  f"sim={f['similarity']} via {f['detector']}")
            if f["rationale"]:
                print(f"    note: {f['rationale']}")

    out = {
        "_meta": {
            "produced_by": "scripts/benchmark_layer_2.py",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "layer": "layer_2_semantic_memory",
            "accuracy_floor": ACCURACY_FLOOR,
            "latency_p99_budget_ms": LATENCY_P99_BUDGET_MS,
            "latency_p50_budget_ms": LATENCY_P50_BUDGET_MS,
        },
        "summary": {
            "total_cases": n,
            "accuracy": accuracy,
            "hit_decision_accuracy": hit_correct / n,
            "guard_accuracy": guard_correct / n,
        },
        "latency_us": lat,
        "per_category": by_cat,
        "rows": rows,
        "passed_thresholds": {
            "accuracy_floor": accuracy >= ACCURACY_FLOOR,
            "latency_p99": lat["p99_us"] / 1000.0 <= LATENCY_P99_BUDGET_MS,
            "latency_p50": lat["p50_us"] / 1000.0 <= LATENCY_P50_BUDGET_MS,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {args.out}")

    if args.strict:
        if accuracy < ACCURACY_FLOOR:
            print(f"\nREGRESSION: accuracy {accuracy:.1%} < floor {ACCURACY_FLOOR:.1%}")
            return 2
        if lat["p99_us"] / 1000.0 > LATENCY_P99_BUDGET_MS:
            print(f"REGRESSION: p99 latency {lat['p99_us']/1000:.2f}ms > budget {LATENCY_P99_BUDGET_MS}ms")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
