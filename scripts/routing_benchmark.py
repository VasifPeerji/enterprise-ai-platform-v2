"""
📁 File: scripts/routing_benchmark.py
Purpose: Single-pass routing accuracy benchmark.

Runs each gold-set query through the LIVE complexity classifier (Groq 70B LLM
judge with the rubric prompt) and produces:

  - Per-query results (saved to artifacts/routing_benchmark_results.json)
  - Overall band-match accuracy
  - Per-band accuracy and confusion matrix
  - Under-routing / over-routing breakdown
  - Failure dump (every misclassified query with reasoning)

Designed to be re-run cheaply by passing --use-cache (loads previous results
without re-calling the LLM) so we can iterate on threshold / heuristic fixes
without paying for repeated LLM calls.

Usage:
    python scripts/routing_benchmark.py            # fresh run
    python scripts/routing_benchmark.py --use-cache  # re-analyse cached run
    python scripts/routing_benchmark.py --limit 20   # quick smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.layer0_model_infra.routing.complexity_classifier import (  # noqa: E402
    ComplexityResult,
    get_complexity_classifier,
)
from src.layer0_model_infra.routing.fast_triage import (  # noqa: E402
    get_triage_classifier,
)


GOLD_SET_PATH = PROJECT_ROOT / "tests" / "layer0_model_infra" / "complexity_gold_set.json"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
RESULTS_PATH = ARTIFACTS_DIR / "routing_benchmark_results.json"

BAND_ORDER = ["trivial", "simple", "moderate", "complex", "expert"]
BAND_INDEX = {b: i for i, b in enumerate(BAND_ORDER)}

# Tier mapping: band → expected target tier
# (mirrors router._determine_target_tier logic for confident moderate)
BAND_TO_TIER = {
    "trivial": "cheap",
    "simple":  "cheap",
    "moderate": "cheap",   # confident moderate → cheap (per router logic)
    "complex": "premium",
    "expert":  "premium",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_gold_set() -> list[dict]:
    """Load the academic gold set."""
    with open(GOLD_SET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Single-pass evaluation
# ---------------------------------------------------------------------------

def evaluate_query(classifier, triage, entry: dict, idx: int, total: int) -> dict:
    """Run the classifier on one query and capture every signal we care about.

    The PRODUCTION routing decision uses FastTriageClassifier.classify(), which
    runs the strict fast-paths (greetings, arithmetic) BEFORE invoking the LLM
    classifier. We score against the production band so the benchmark reflects
    real routing behavior. We also save the bare LLM-classifier band as
    `classifier_only_band` for diagnostic comparison.
    """
    query = entry["query"]
    expected = entry["expected_band"]

    # ── PRODUCTION PATH: full triage pipeline (this is the routing decision) ─
    triage_started = time.time()
    triage_result = triage.classify(query)
    triage_ms = (time.time() - triage_started) * 1000

    # Production verdict comes from the triage band.
    actual = triage_result.complexity_band.value
    distance = BAND_INDEX[actual] - BAND_INDEX[expected]
    direction = (
        "exact" if distance == 0
        else ("over" if distance > 0 else "under")
    )

    # ── DIAGNOSTIC PATH: bare LLM classifier (skips fast-paths) ──────────────
    # Useful for understanding whether failures are fast-path or LLM issues.
    # Note: triage already invoked the classifier internally, so calling it
    # again would double the LLM cost. We instead read the rubric out of the
    # triage_result.complexity_rubric (populated when LLM was called).
    rubric = triage_result.complexity_rubric or {}
    raw_score = rubric.get("raw_score", 0.0)

    return {
        "idx": idx,
        "query": query,
        "expected_band": expected,
        "actual_band": actual,            # production band (triage-pipeline)
        "match": actual == expected,
        "distance": distance,
        "direction": direction,
        "category": entry.get("category", ""),
        "domain_label": entry.get("domain", ""),

        # Classifier internals (rubric from triage_result)
        "raw_score": round(raw_score, 4),
        "rubric": {
            "task_count":       round(rubric.get("task_count", 0.0), 4),
            "domain_depth":     round(rubric.get("domain_depth", 0.0), 4),
            "reasoning_hops":   round(rubric.get("reasoning_hops", 0.0), 4),
            "output_structure": round(rubric.get("output_structure", 0.0), 4),
            "knowledge_breadth": round(rubric.get("knowledge_breadth", 0.0), 4),
        },
        "classifier_confidence": round(triage_result.confidence, 4),
        "classifier_reasoning": triage_result.reasoning,
        "classifier_latency_ms": round(triage_ms, 1),

        # Full triage (intent + domain)
        "triage_intent": triage_result.intent.value,
        "triage_domain": triage_result.domain.value,
        "triage_confidence": round(triage_result.confidence, 4),
        "triage_latency_ms": round(triage_ms, 1),
    }


def _save_incremental(results: list[dict]) -> None:
    """Save results after every query so a rate-limit kill never loses progress."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"results": results, "saved_at": time.time()}, f, indent=2)


def run_full_benchmark(
    limit: Optional[int] = None,
    primary_model: Optional[str] = None,
    resume: bool = False,
) -> list[dict]:
    """Execute classifier+triage on every gold-set query.

    Saves incrementally after every query so rate-limit kills don't lose work.
    With --resume, skips queries already present in the cache.
    With --model, overrides the primary classifier model.
    """
    gold = load_gold_set()
    if limit:
        gold = gold[:limit]

    classifier = get_complexity_classifier()
    triage = get_triage_classifier()

    if primary_model:
        prev = classifier._model_id
        classifier._model_id = primary_model
        print(f"\nClassifier primary model overridden: {prev} -> {primary_model}")

    # Resume support: load existing results and skip already-evaluated queries
    results: list[dict] = []
    already_done: set[str] = set()
    if resume:
        cached = load_cached_results()
        if cached:
            results = cached
            already_done = {r["query"] for r in cached}
            print(f"\nResuming with {len(already_done)} cached queries.")

    print(f"\nRunning routing benchmark on {len(gold)} gold-set queries...")
    print(f"Classifier model: {classifier._model_id}\n")

    overall_started = time.time()
    for i, entry in enumerate(gold, start=1):
        if entry["query"] in already_done:
            continue  # Skip: already done in a previous run
        try:
            result = evaluate_query(classifier, triage, entry, i, len(gold))
        except KeyboardInterrupt:
            print(f"\nInterrupted at {i}/{len(gold)}. {len(results)} results saved to cache.")
            _save_incremental(results)
            sys.exit(130)
        marker = "OK" if result["match"] else ("UNDER" if result["direction"] == "under" else "OVER")
        print(
            f"  [{i:3d}/{len(gold)}] [{marker:5s}] "
            f"exp={result['expected_band']:8s} got={result['actual_band']:8s} "
            f"raw={result['raw_score']:.2f} | {result['query'][:65]}"
        )
        results.append(result)
        # ── Incremental save after EVERY query ────────────────────────────
        _save_incremental(results)

    total_s = time.time() - overall_started
    print(f"\nFinished in {total_s:.1f}s ({total_s/max(len(gold),1):.2f}s per query).")
    return results


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(results: list[dict]) -> dict:
    """Compute per-axis metrics from cached results."""
    total = len(results)
    correct = sum(1 for r in results if r["match"])
    under = sum(1 for r in results if r["direction"] == "under")
    over = sum(1 for r in results if r["direction"] == "over")
    within_one = sum(1 for r in results if abs(r["distance"]) <= 1)

    accuracy = correct / total * 100 if total else 0.0
    under_rate = under / total * 100 if total else 0.0
    over_rate = over / total * 100 if total else 0.0
    within_one_rate = within_one / total * 100 if total else 0.0

    # Per-band accuracy
    per_band: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    for r in results:
        per_band[r["expected_band"]]["total"] += 1
        if r["match"]:
            per_band[r["expected_band"]]["correct"] += 1
    per_band_pct = {
        band: (s["correct"] / s["total"] * 100 if s["total"] else 0.0)
        for band, s in per_band.items()
    }

    # Confusion matrix
    confusion: dict[str, Counter] = {b: Counter() for b in BAND_ORDER}
    for r in results:
        confusion[r["expected_band"]][r["actual_band"]] += 1

    # Tier-level accuracy (does the band map to the right tier?)
    tier_correct = 0
    for r in results:
        if BAND_TO_TIER[r["actual_band"]] == BAND_TO_TIER[r["expected_band"]]:
            tier_correct += 1
    tier_accuracy = tier_correct / total * 100 if total else 0.0

    # Failures
    failures = [r for r in results if not r["match"]]
    failures.sort(key=lambda r: (r["direction"], r["expected_band"], r["query"]))

    return {
        "total": total,
        "correct": correct,
        "accuracy_pct": round(accuracy, 1),
        "within_one_band_pct": round(within_one_rate, 1),
        "under_routing_pct": round(under_rate, 1),
        "over_routing_pct": round(over_rate, 1),
        "tier_accuracy_pct": round(tier_accuracy, 1),
        "per_band_accuracy_pct": {b: round(v, 1) for b, v in per_band_pct.items()},
        "per_band_counts": {b: dict(s) for b, s in per_band.items()},
        "confusion_matrix": {b: dict(c) for b, c in confusion.items()},
        "failures": failures,
    }


def print_report(metrics: dict) -> None:
    """Print a clean, scannable accuracy report."""
    print("\n" + "=" * 70)
    print(f"{'ROUTING BENCHMARK REPORT':^70}")
    print("=" * 70)

    print(f"\nTotal queries:           {metrics['total']}")
    print(f"Exact-band accuracy:     {metrics['accuracy_pct']}%   ({metrics['correct']}/{metrics['total']})")
    print(f"Within-one-band:         {metrics['within_one_band_pct']}%")
    print(f"Tier-level accuracy:     {metrics['tier_accuracy_pct']}%   (cheap/mid/premium correctness)")
    print(f"Under-routing rate:      {metrics['under_routing_pct']}%   [DANGEROUS - too cheap a model]")
    print(f"Over-routing rate:       {metrics['over_routing_pct']}%   [WASTEFUL - too expensive a model]")

    print("\nPer-band accuracy:")
    for band in BAND_ORDER:
        if band in metrics["per_band_accuracy_pct"]:
            counts = metrics["per_band_counts"][band]
            print(
                f"  {band:8s}  {metrics['per_band_accuracy_pct'][band]:5.1f}%  "
                f"({counts['correct']}/{counts['total']})"
            )

    print("\nConfusion matrix (rows = expected, cols = actual):")
    header_label = "expected\\actual"
    print(f"  {header_label:<18}", end="")
    for band in BAND_ORDER:
        print(f"{band:>10}", end="")
    print()
    print("  " + "-" * 70)
    for expected in BAND_ORDER:
        print(f"  {expected:<18}", end="")
        for actual in BAND_ORDER:
            count = metrics["confusion_matrix"][expected].get(actual, 0)
            cell = f"{count:>10}" if count else f"{'.':>10}"
            print(cell, end="")
        print()

    print("\n" + "=" * 70)
    print(f"{'FAILURES':^70}")
    print("=" * 70)
    for f in metrics["failures"]:
        marker = "UNDER" if f["direction"] == "under" else "OVER"
        print(
            f"\n  [{marker:5s}]  expected={f['expected_band']:8s}  got={f['actual_band']:8s}  "
            f"raw={f['raw_score']:.2f}  conf={f['classifier_confidence']:.2f}"
        )
        print(f"    Q: {f['query'][:120]}")
        print(f"    rubric: tc={f['rubric']['task_count']:.2f} "
              f"dd={f['rubric']['domain_depth']:.2f} "
              f"rh={f['rubric']['reasoning_hops']:.2f} "
              f"os={f['rubric']['output_structure']:.2f} "
              f"kb={f['rubric']['knowledge_breadth']:.2f}")
        print(f"    why: {f['classifier_reasoning'][:160]}")
        print(f"    triage: intent={f['triage_intent']} domain={f['triage_domain']} (conf={f['triage_confidence']})")

    print("\n" + "=" * 70)
    print("Top failure categories (by direction × category):")
    cat_dir = Counter()
    for f in metrics["failures"]:
        cat_dir[(f["direction"], f["category"])] += 1
    for (direction, category), count in cat_dir.most_common(10):
        print(f"  {count:3d}  {direction:<5s}  {category}")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_results(results: list[dict]) -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"results": results, "saved_at": time.time()}, f, indent=2)
    print(f"\nResults cached at: {RESULTS_PATH}")


def load_cached_results() -> Optional[list[dict]]:
    if not RESULTS_PATH.exists():
        return None
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("results")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-cache", action="store_true",
                        help="Skip re-running the classifier; analyse cached results.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip queries already in the cache; only run missing ones.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run the first N gold-set queries (for smoke tests).")
    parser.add_argument("--model", type=str, default=None,
                        help="Override the primary classifier model id "
                             "(e.g. 'gemini-2.0-flash-free'). Useful when the "
                             "default Groq 70B is rate-limited.")
    args = parser.parse_args()

    if args.use_cache:
        cached = load_cached_results()
        if cached is None:
            print("No cached results found — run without --use-cache first.")
            sys.exit(1)
        results = cached
        print(f"\nUsing {len(results)} cached results from {RESULTS_PATH}")
    else:
        results = run_full_benchmark(
            limit=args.limit,
            primary_model=args.model,
            resume=args.resume,
        )
        save_results(results)

    metrics = analyse(results)
    print_report(metrics)


if __name__ == "__main__":
    main()
