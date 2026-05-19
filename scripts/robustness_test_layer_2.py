"""
Layer 2 Wild Corpus Robustness Runner

Runs the hand-curated 'real user behavior' corpus (artifacts/layer_2/wild_corpus.json)
through the semantic memory cache and emits per-case verdicts. Anything that
fails becomes a regression test.

Output: artifacts/layer_2/robustness_results.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.semantic_memory import SemanticMemory  # noqa: E402


def make_memory() -> SemanticMemory:
    return SemanticMemory(
        similarity_threshold=0.75,
        decay_half_life_seconds=604_800.0,
        enable_local_embedding=True,
        enable_persistence=False,
    )


def run_case(case: dict) -> dict:
    mem = make_memory()
    mem.record(
        query=case["record_query"],
        model_id="ollama-llama3.1-8b",
        quality_score=0.9,
        escalated=False,
        intent="qa", domain="general", complexity_band="moderate",
    )

    t0 = time.perf_counter_ns()
    result = mem.lookup(case["lookup_query"])
    t1 = time.perf_counter_ns()

    hit_correct = result.hit == case["expected_hit"]
    guard_correct = True
    if case.get("expected_guard_rejected"):
        if result.guard_rejected:
            guard_correct = case["expected_guard_rejected"] in result.guard_rejected
        else:
            guard_correct = hit_correct and result.similarity < 0.75

    return {
        "id": case["id"],
        "category": case["category"],
        "expected_hit": case["expected_hit"],
        "actual_hit": result.hit,
        "similarity": round(result.similarity, 3),
        "guard": result.guard_rejected,
        "detector": result.detector_used,
        "pass": hit_correct and guard_correct,
        "rationale": case.get("rationale", ""),
        "latency_us": round((t1 - t0) / 1000, 1),
    }


def main() -> int:
    corpus_path = REPO_ROOT / "artifacts" / "layer_2" / "wild_corpus.json"
    if not corpus_path.exists():
        print(f"ERROR: {corpus_path} not found", file=sys.stderr)
        return 1
    cases = json.loads(corpus_path.read_text(encoding="utf-8"))["cases"]
    print(f"Loaded {len(cases)} wild corpus cases")

    rows = [run_case(c) for c in cases]

    n = len(rows)
    passes = sum(r["pass"] for r in rows)
    print(f"\n{'='*70}\n  Layer 2 — Wild Corpus Robustness\n{'='*70}")
    print(f"\nTotal: {n}   Passing: {passes}/{n} ({passes/n:.1%})")

    by_cat: dict[str, dict] = {}
    for r in rows:
        s = by_cat.setdefault(r["category"], {"total": 0, "passing": 0})
        s["total"] += 1
        if r["pass"]:
            s["passing"] += 1
    print("\nPer-category:")
    for cat in sorted(by_cat):
        s = by_cat[cat]
        print(f"  {cat:25s}  {s['passing']}/{s['total']}  ({s['passing']/s['total']:.0%})")

    fails = [r for r in rows if not r["pass"]]
    if fails:
        print(f"\nFailures ({len(fails)}):")
        for f in fails:
            print(f"  [{f['category']}] {f['id']}")
            print(f"    expected hit={f['expected_hit']}, actual hit={f['actual_hit']}, sim={f['similarity']}")
            if f["rationale"]:
                print(f"    {f['rationale']}")

    out_path = REPO_ROOT / "artifacts" / "layer_2" / "robustness_results.json"
    out_path.write_text(
        json.dumps({
            "_meta": {
                "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total": n, "passing": passes, "pass_rate": passes / n,
            },
            "rows": rows,
            "per_category": by_cat,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nReport written to {out_path}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
