"""
Layer 0 (Fast Path) Benchmark Suite
====================================

Runs the FastPathAnalyzer over the curated golden eval set and emits
metrics for latency, accuracy, per-category precision/recall, and
multilingual coverage. Output is written to:

    artifacts/layer_0/benchmark_results.json

This script is reproducible — re-run any time after code changes and
commit the updated JSON alongside the code change.

Usage:
    python scripts/benchmark_layer_0.py
    python scripts/benchmark_layer_0.py --golden-set custom.json --out custom.json

Exit codes:
    0  benchmark ran cleanly (regardless of accuracy)
    1  IO / parse / unexpected runtime error
    2  accuracy regression beneath documented baseline

The accuracy thresholds enforced here are the "must-not-regress" floor.
They're intentionally tight on the golden set because the golden set is
hand-curated — production traffic will be noisier.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.fast_path import (  # noqa: E402
    FastPathAnalyzer,
    FastPathCategory,
)

# Minimum acceptable performance — regression check
ACCURACY_FLOOR = 0.92          # overall classification accuracy on golden set
LATENCY_P99_BUDGET_MS = 5.0    # Fast Path must decide in < 5ms p99
LATENCY_P50_BUDGET_MS = 0.5    # and < 0.5ms median


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------

@dataclass
class CaseResult:
    query: str
    expected_bypass: bool
    expected_category: Optional[str]
    expected_language: Optional[str]
    actual_bypass: bool
    actual_category: str
    actual_language: Optional[str]
    actual_model: Optional[str]
    matched_pattern: Optional[str]
    latency_us: float
    bypass_correct: bool
    category_correct: bool
    language_correct: bool
    source: str = "curated"


@dataclass
class BenchmarkReport:
    total: int = 0
    bypass_correct: int = 0
    category_correct: int = 0
    language_correct: int = 0
    by_category: dict = field(default_factory=dict)
    by_source: dict = field(default_factory=dict)
    latencies_us: list = field(default_factory=list)
    misclassifications: list = field(default_factory=list)

    @property
    def bypass_accuracy(self) -> float:
        return self.bypass_correct / self.total if self.total else 0.0

    @property
    def category_accuracy(self) -> float:
        return self.category_correct / self.total if self.total else 0.0

    @property
    def language_accuracy_when_known(self) -> float:
        known = sum(1 for c in self.by_source.get("_lang_evaluable", []) if c)
        evaluated = len(self.by_source.get("_lang_evaluable", []))
        return known / evaluated if evaluated else 0.0


# ----------------------------------------------------------------------------
# Benchmark runner
# ----------------------------------------------------------------------------

def run_case(fp: FastPathAnalyzer, case: dict) -> CaseResult:
    """Run a single golden case and time the decision."""
    t0 = time.perf_counter_ns()
    decision = fp.analyze(case["query"])
    t1 = time.perf_counter_ns()
    latency_us = (t1 - t0) / 1000.0

    expected_bypass = case["expected_bypass"]
    expected_category = case.get("expected_category")
    expected_language = case.get("expected_language")

    bypass_correct = decision.should_bypass == expected_bypass

    actual_category = decision.category.value
    if expected_bypass:
        category_correct = actual_category == expected_category
    else:
        # When we expect no-bypass, "none" is the right answer.
        category_correct = actual_category == "none"

    if expected_language is not None and decision.detected_language is not None:
        language_correct = decision.detected_language == expected_language
    else:
        language_correct = True  # not evaluable

    return CaseResult(
        query=case["query"],
        expected_bypass=expected_bypass,
        expected_category=expected_category,
        expected_language=expected_language,
        actual_bypass=decision.should_bypass,
        actual_category=actual_category,
        actual_language=decision.detected_language,
        actual_model=decision.recommended_model,
        matched_pattern=decision.matched_pattern,
        latency_us=latency_us,
        bypass_correct=bypass_correct,
        category_correct=category_correct,
        language_correct=language_correct,
        source=case.get("source", "curated"),
    )


def aggregate(results: list[CaseResult]) -> BenchmarkReport:
    rep = BenchmarkReport(total=len(results))
    for r in results:
        rep.latencies_us.append(r.latency_us)
        if r.bypass_correct:
            rep.bypass_correct += 1
        if r.category_correct:
            rep.category_correct += 1
        if r.language_correct:
            rep.language_correct += 1

        # Per-category
        cat_key = r.expected_category if r.expected_bypass else "none"
        slot = rep.by_category.setdefault(
            cat_key, {"total": 0, "bypass_correct": 0, "category_correct": 0}
        )
        slot["total"] += 1
        slot["bypass_correct"] += int(r.bypass_correct)
        slot["category_correct"] += int(r.category_correct)

        # Per-source
        src_slot = rep.by_source.setdefault(
            r.source, {"total": 0, "bypass_correct": 0}
        )
        src_slot["total"] += 1
        src_slot["bypass_correct"] += int(r.bypass_correct)

        # Misclassifications
        if not r.bypass_correct or not r.category_correct:
            rep.misclassifications.append({
                "query": r.query,
                "source": r.source,
                "expected_bypass": r.expected_bypass,
                "expected_category": r.expected_category,
                "actual_bypass": r.actual_bypass,
                "actual_category": r.actual_category,
                "matched_pattern": r.matched_pattern,
            })

    return rep


def latency_stats(latencies_us: list[float]) -> dict:
    if not latencies_us:
        return {}
    sorted_us = sorted(latencies_us)

    def percentile(p: float) -> float:
        idx = int(p / 100.0 * len(sorted_us))
        idx = min(idx, len(sorted_us) - 1)
        return sorted_us[idx]

    return {
        "count": len(sorted_us),
        "min_us": sorted_us[0],
        "max_us": sorted_us[-1],
        "mean_us": statistics.mean(sorted_us),
        "median_us": statistics.median(sorted_us),
        "p50_us": percentile(50),
        "p95_us": percentile(95),
        "p99_us": percentile(99),
        "stdev_us": statistics.pstdev(sorted_us),
    }


def language_coverage(results: list[CaseResult]) -> dict:
    """Per-language bypass + correct-language rate."""
    by_lang: dict[str, dict[str, int]] = {}
    for r in results:
        lang = r.expected_language or "?"
        slot = by_lang.setdefault(
            lang, {"total": 0, "bypassed": 0, "language_correct": 0, "category_correct": 0}
        )
        slot["total"] += 1
        if r.actual_bypass:
            slot["bypassed"] += 1
        if r.language_correct:
            slot["language_correct"] += 1
        if r.category_correct:
            slot["category_correct"] += 1
    return by_lang


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=REPO_ROOT / "artifacts" / "layer_0" / "golden_set.json",
        help="Path to golden evaluation set (JSON)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "artifacts" / "layer_0" / "benchmark_results.json",
        help="Where to write the benchmark report (JSON)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 if accuracy < floor or latency > budget",
    )
    args = parser.parse_args()

    if not args.golden_set.exists():
        print(f"ERROR: golden set not found at {args.golden_set}", file=sys.stderr)
        return 1

    payload = json.loads(args.golden_set.read_text(encoding="utf-8"))
    queries = payload["queries"]

    print(f"Loaded {len(queries)} golden cases from {args.golden_set}")

    fp = FastPathAnalyzer()
    # Warm-up — exclude first call from latency stats (registry initialisation)
    fp.analyze("warmup")

    results = [run_case(fp, q) for q in queries]
    report = aggregate(results)
    lat = latency_stats(report.latencies_us)
    by_lang = language_coverage(results)

    # ---- print summary ----
    print("\n" + "=" * 70)
    print(" Layer 0 Fast Path — Benchmark Results")
    print("=" * 70)
    print(f"\nTotal cases:               {report.total}")
    print(f"Bypass-decision accuracy:  {report.bypass_accuracy:.1%}  ({report.bypass_correct}/{report.total})")
    print(f"Category accuracy:         {report.category_accuracy:.1%}  ({report.category_correct}/{report.total})")

    print(f"\nLatency (us):")
    print(f"  p50:   {lat['p50_us']:>8.2f}")
    print(f"  p95:   {lat['p95_us']:>8.2f}")
    print(f"  p99:   {lat['p99_us']:>8.2f}")
    print(f"  max:   {lat['max_us']:>8.2f}")
    print(f"  mean:  {lat['mean_us']:>8.2f}")

    print(f"\nPer-category bypass accuracy:")
    for cat, slot in sorted(report.by_category.items()):
        acc = slot["bypass_correct"] / slot["total"] if slot["total"] else 0.0
        print(f"  {cat:<30} {acc:>6.1%}  ({slot['bypass_correct']}/{slot['total']})")

    print(f"\nPer-source bypass accuracy:")
    for src, slot in sorted(report.by_source.items()):
        if src.startswith("_"):
            continue
        acc = slot["bypass_correct"] / slot["total"] if slot["total"] else 0.0
        print(f"  {src:<25} {acc:>6.1%}  ({slot['bypass_correct']}/{slot['total']})")

    print(f"\nLanguage coverage:")
    for lang, slot in sorted(by_lang.items()):
        if lang == "?" or slot["total"] == 0:
            continue
        byp = slot["bypassed"] / slot["total"]
        cat_acc = slot["category_correct"] / slot["total"]
        print(f"  {lang}:  bypass={byp:.1%}  category_correct={cat_acc:.1%}  (n={slot['total']})")

    if report.misclassifications:
        print(f"\nMisclassifications ({len(report.misclassifications)}):")
        for m in report.misclassifications[:20]:
            print(f"  [{m['source']}] {m['query']!r}")
            print(f"    expected: bypass={m['expected_bypass']}, cat={m['expected_category']}")
            print(f"    actual:   bypass={m['actual_bypass']}, cat={m['actual_category']}")

    # ---- write JSON artifact ----
    out_payload = {
        "_meta": {
            "produced_by": "scripts/benchmark_layer_0.py",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "golden_set": str(args.golden_set.relative_to(REPO_ROOT)).replace("\\", "/"),
            "layer": "layer_0_fast_path",
            "accuracy_floor": ACCURACY_FLOOR,
            "latency_p99_budget_ms": LATENCY_P99_BUDGET_MS,
            "latency_p50_budget_ms": LATENCY_P50_BUDGET_MS,
        },
        "summary": {
            "total_cases": report.total,
            "bypass_accuracy": report.bypass_accuracy,
            "category_accuracy": report.category_accuracy,
            "bypass_correct": report.bypass_correct,
            "category_correct": report.category_correct,
        },
        "latency_us": lat,
        "per_category": report.by_category,
        "per_source": {k: v for k, v in report.by_source.items() if not k.startswith("_")},
        "language_coverage": by_lang,
        "misclassifications": report.misclassifications,
        "passed_thresholds": {
            "accuracy_floor": report.bypass_accuracy >= ACCURACY_FLOOR,
            "latency_p99_budget": lat["p99_us"] / 1000.0 <= LATENCY_P99_BUDGET_MS,
            "latency_p50_budget": lat["p50_us"] / 1000.0 <= LATENCY_P50_BUDGET_MS,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {args.out}")

    # ---- regression gate ----
    if args.strict:
        regress = []
        if report.bypass_accuracy < ACCURACY_FLOOR:
            regress.append(
                f"bypass_accuracy {report.bypass_accuracy:.1%} < floor {ACCURACY_FLOOR:.1%}"
            )
        if lat["p99_us"] / 1000.0 > LATENCY_P99_BUDGET_MS:
            regress.append(
                f"latency p99 {lat['p99_us']/1000:.2f}ms > budget {LATENCY_P99_BUDGET_MS}ms"
            )
        if regress:
            print("\nREGRESSION:")
            for r in regress:
                print(f"  - {r}")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
