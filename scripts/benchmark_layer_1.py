"""
Layer 1 (Modality Gate) Benchmark Suite
========================================

Runs the ModalityGate on the curated golden eval set and emits metrics for:
  - Modality detection accuracy
  - Language detection accuracy
  - Code-language detection accuracy
  - Vision-relevance correctness
  - Structured-format detection
  - Per-decision latency (p50/p95/p99)

Output: artifacts/layer_1/benchmark_results.json
Usage:
  python scripts/benchmark_layer_1.py
  python scripts/benchmark_layer_1.py --strict        # CI gate
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.modality_gate import (  # noqa: E402
    ModalityGate,
    InputModality,
)


MODALITY_ACCURACY_FLOOR = 0.92
LANGUAGE_ACCURACY_FLOOR = 0.85
LATENCY_P99_BUDGET_MS = 50.0   # Layer 1 budget — Tier 2 libraries push p99 up
LATENCY_P50_BUDGET_MS = 5.0


@dataclass
class CaseResult:
    query: str
    expected_modality: str
    expected_language: str
    expected_code_language: str
    expected_structured_format: str
    expected_validation_passes: bool
    actual_modality: str
    actual_language: str
    actual_code_language: str
    actual_structured_format: str
    actual_validation_passed: bool
    requires_vision: bool
    requires_code_model: bool
    expected_requires_vision: bool
    expected_requires_code_model: bool
    language_detector_used: str
    code_detector_used: str
    latency_us: float
    source: str

    @property
    def modality_correct(self) -> bool:
        return self.actual_modality == self.expected_modality

    @property
    def language_correct(self) -> bool:
        return self.actual_language == self.expected_language

    @property
    def code_lang_correct(self) -> bool:
        # Empty expected = don't care
        if not self.expected_code_language:
            return True
        return self.actual_code_language == self.expected_code_language

    @property
    def structured_correct(self) -> bool:
        return self.actual_structured_format == self.expected_structured_format

    @property
    def vision_correct(self) -> bool:
        return self.requires_vision == self.expected_requires_vision

    @property
    def validation_correct(self) -> bool:
        return self.actual_validation_passed == self.expected_validation_passes


def run_case(gate: ModalityGate, case: dict) -> CaseResult:
    t0 = time.perf_counter_ns()
    result = gate.analyze(
        text=case["query"],
        has_images=case.get("has_images", False),
        has_audio=case.get("has_audio", False),
        image_count=case.get("image_count", 0),
    )
    t1 = time.perf_counter_ns()

    return CaseResult(
        query=case["query"],
        expected_modality=case["expected_modality"],
        expected_language=case["expected_language"],
        expected_code_language=case.get("expected_code_language", ""),
        expected_structured_format=case.get("expected_structured_format", ""),
        expected_validation_passes=case.get("expected_validation_passes", True),
        actual_modality=result.primary_modality.value,
        actual_language=result.language,
        actual_code_language=result.code_language,
        actual_structured_format=result.structured_format,
        actual_validation_passed=result.validation_passed,
        requires_vision=result.requires_vision,
        requires_code_model=result.requires_code_model,
        expected_requires_vision=case.get("expected_requires_vision", False),
        expected_requires_code_model=case.get("expected_requires_code_model", False),
        language_detector_used=result.language_detector_used,
        code_detector_used=result.code_detector_used,
        latency_us=(t1 - t0) / 1000.0,
        source=case.get("source", "curated"),
    )


def latency_stats(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    return {
        "count": len(s),
        "min_us": s[0],
        "max_us": s[-1],
        "mean_us": statistics.mean(s),
        "p50_us": s[len(s) // 2],
        "p95_us": s[int(0.95 * len(s))],
        "p99_us": s[int(0.99 * len(s)) if len(s) > 100 else -1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-set", type=Path,
                        default=REPO_ROOT / "artifacts" / "layer_1" / "golden_set.json")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "artifacts" / "layer_1" / "benchmark_results.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not args.golden_set.exists():
        print(f"ERROR: {args.golden_set} not found", file=sys.stderr)
        return 1

    payload = json.loads(args.golden_set.read_text(encoding="utf-8"))
    queries = payload["queries"]
    print(f"Loaded {len(queries)} golden cases from {args.golden_set}")

    gate = ModalityGate()
    gate.analyze("warmup")  # warm Tier 2 detectors

    results = [run_case(gate, q) for q in queries]

    n = len(results)
    modality_acc = sum(r.modality_correct for r in results) / n
    language_acc = sum(r.language_correct for r in results) / n
    code_lang_acc = sum(r.code_lang_correct for r in results) / n
    structured_acc = sum(r.structured_correct for r in results) / n
    vision_acc = sum(r.vision_correct for r in results) / n
    validation_acc = sum(r.validation_correct for r in results) / n

    lat = latency_stats([r.latency_us for r in results])

    print("\n" + "=" * 70)
    print(" Layer 1 Modality Gate — Benchmark Results")
    print("=" * 70)
    print(f"\nTotal cases: {n}")
    print(f"  Modality accuracy:          {modality_acc:.1%}")
    print(f"  Language accuracy:          {language_acc:.1%}")
    print(f"  Code-language accuracy:     {code_lang_acc:.1%}")
    print(f"  Structured-format accuracy: {structured_acc:.1%}")
    print(f"  Vision-relevance accuracy:  {vision_acc:.1%}")
    print(f"  Validation accuracy:        {validation_acc:.1%}")

    print(f"\nLatency (us):")
    print(f"  p50:  {lat['p50_us']:>8.1f}")
    print(f"  p95:  {lat['p95_us']:>8.1f}")
    print(f"  p99:  {lat['p99_us']:>8.1f}")
    print(f"  max:  {lat['max_us']:>8.1f}")

    # Per-language breakdown
    by_lang: dict[str, dict] = {}
    for r in results:
        slot = by_lang.setdefault(r.expected_language, {"total": 0, "correct": 0})
        slot["total"] += 1
        if r.language_correct:
            slot["correct"] += 1
    print(f"\nPer-language accuracy:")
    for lang, slot in sorted(by_lang.items()):
        acc = slot["correct"] / slot["total"]
        print(f"  {lang:10}  {acc:>6.1%}  ({slot['correct']}/{slot['total']})")

    # Per-detector breakdown (which tier resolved which queries)
    by_method: dict[str, int] = {}
    for r in results:
        by_method[r.language_detector_used] = by_method.get(r.language_detector_used, 0) + 1
    print(f"\nLanguage detector tier usage:")
    for method, count in sorted(by_method.items()):
        print(f"  {method:20}  {count:>3}")

    # Mis-classifications
    mis = [r for r in results
           if not (r.modality_correct and r.language_correct and r.code_lang_correct)]
    if mis:
        print(f"\nMis-classifications ({len(mis)}):")
        for r in mis[:15]:
            problem = []
            if not r.modality_correct:
                problem.append(f"modality {r.actual_modality}→exp {r.expected_modality}")
            if not r.language_correct:
                problem.append(f"lang {r.actual_language}→exp {r.expected_language}")
            if not r.code_lang_correct:
                problem.append(f"code_lang {r.actual_code_language}→exp {r.expected_code_language}")
            print(f"  [{r.source}] {r.query[:50]!r}")
            print(f"    → {', '.join(problem)}")

    out_payload = {
        "_meta": {
            "produced_by": "scripts/benchmark_layer_1.py",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "layer": "layer_1_modality_gate",
            "modality_accuracy_floor": MODALITY_ACCURACY_FLOOR,
            "language_accuracy_floor": LANGUAGE_ACCURACY_FLOOR,
            "latency_p99_budget_ms": LATENCY_P99_BUDGET_MS,
            "latency_p50_budget_ms": LATENCY_P50_BUDGET_MS,
        },
        "summary": {
            "total_cases": n,
            "modality_accuracy": modality_acc,
            "language_accuracy": language_acc,
            "code_language_accuracy": code_lang_acc,
            "structured_format_accuracy": structured_acc,
            "vision_relevance_accuracy": vision_acc,
            "validation_accuracy": validation_acc,
        },
        "latency_us": lat,
        "per_language": by_lang,
        "per_language_detector": by_method,
        "misclassifications": [
            {
                "query": r.query,
                "source": r.source,
                "expected": {
                    "modality": r.expected_modality,
                    "language": r.expected_language,
                    "code_language": r.expected_code_language,
                    "structured_format": r.expected_structured_format,
                },
                "actual": {
                    "modality": r.actual_modality,
                    "language": r.actual_language,
                    "code_language": r.actual_code_language,
                    "structured_format": r.actual_structured_format,
                },
                "detector_used": {
                    "language": r.language_detector_used,
                    "code": r.code_detector_used,
                },
            }
            for r in mis
        ],
        "passed_thresholds": {
            "modality_floor": modality_acc >= MODALITY_ACCURACY_FLOOR,
            "language_floor": language_acc >= LANGUAGE_ACCURACY_FLOOR,
            "latency_p99": lat["p99_us"] / 1000.0 <= LATENCY_P99_BUDGET_MS,
            "latency_p50": lat["p50_us"] / 1000.0 <= LATENCY_P50_BUDGET_MS,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {args.out}")

    if args.strict:
        regressions = []
        if modality_acc < MODALITY_ACCURACY_FLOOR:
            regressions.append(f"modality_acc {modality_acc:.1%} < floor {MODALITY_ACCURACY_FLOOR:.1%}")
        if language_acc < LANGUAGE_ACCURACY_FLOOR:
            regressions.append(f"language_acc {language_acc:.1%} < floor {LANGUAGE_ACCURACY_FLOOR:.1%}")
        if lat["p99_us"] / 1000.0 > LATENCY_P99_BUDGET_MS:
            regressions.append(f"p99 {lat['p99_us']/1000:.2f}ms > budget {LATENCY_P99_BUDGET_MS}ms")
        if regressions:
            print("\nREGRESSIONS:")
            for r in regressions:
                print(f"  - {r}")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
