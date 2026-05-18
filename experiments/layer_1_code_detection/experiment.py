"""
Layer 1 Code Language Detection — Head-to-Head Experiment
==========================================================

Question: Does adding Pygments + signature patterns as Tier 2 improve code
language detection over the original 5-keyword heuristic?

Three arms:
  - Heuristic (original): fence regex + 5-language keyword cues
  - Signature (Tier 1.5 new): fence + distinctive function-signature patterns
  - Hybrid (current): fence + signatures + multi-keyword + Pygments fallback

Output: results.json
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.modality_gate import CodeLanguageDetector


def heuristic_only_detect(text: str) -> str:
    """Reconstruct the original Python/JS/Java/C++/SQL heuristic."""
    if not text:
        return ""
    fenced = re.search(r"```(\w+)", text)
    if fenced:
        return fenced.group(1).lower()
    lowered = text.lower()
    if "def " in lowered and "import " in lowered:
        return "python"
    if "function " in lowered or "const " in lowered or "=> " in lowered:
        return "javascript"
    if "public class " in lowered:
        return "java"
    if "#include" in lowered:
        return "cpp"
    if "select " in lowered and " from " in lowered:
        return "sql"
    return ""


def hybrid_detect(detector: CodeLanguageDetector, text: str) -> str:
    return detector.detect(text)[0]


def main() -> int:
    corpus = json.loads((Path(__file__).resolve().parent / "corpus.json").read_text(encoding="utf-8"))["queries"]

    detector = CodeLanguageDetector()

    def score(name, fn):
        correct = 0
        total = 0
        latencies = []
        mis = []
        for case in corpus:
            expected = case["expected_code_language"]
            t0 = time.perf_counter_ns()
            predicted = fn(case["query"])
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1000.0)
            total += 1
            if predicted == expected:
                correct += 1
            else:
                mis.append({"query": case["query"][:50], "expected": expected, "predicted": predicted})
        return {
            "n": total,
            "correct": correct,
            "accuracy": correct / total,
            "p50_us": statistics.median(latencies),
            "max_us": max(latencies),
            "misclassifications": mis,
        }

    heur = score("heuristic", heuristic_only_detect)
    hybrid = score("hybrid", lambda t: hybrid_detect(detector, t))

    print("=" * 70)
    print(" Layer 1 Code Language Detection — Head-to-Head")
    print("=" * 70)
    print(f"\nCorpus: {len(corpus)} code snippets across {len({c['expected_code_language'] for c in corpus})} languages")
    print(f"\n{'Arm':<15} {'Acc':<10} {'p50':<10} {'max':<10}")
    print(f"  heuristic   {heur['accuracy']:>6.1%}   {heur['p50_us']:>6.0f}us  {heur['max_us']:>6.0f}us")
    print(f"  hybrid      {hybrid['accuracy']:>6.1%}   {hybrid['p50_us']:>6.0f}us  {hybrid['max_us']:>6.0f}us")
    print(f"\nLift: {(hybrid['accuracy'] - heur['accuracy']) * 100:+.1f} pp")
    decision = "ADOPT" if hybrid['accuracy'] > heur['accuracy'] + 0.05 else "REJECT"
    print(f"\nRECOMMENDATION: {decision}")

    if hybrid["misclassifications"]:
        print("\nHybrid misclassifications:")
        for m in hybrid["misclassifications"][:10]:
            print(f"  {m['query']!r}  expected={m['expected']}, got={m['predicted']}")

    payload = {
        "_meta": {
            "experiment": "layer_1_code_detection",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": decision,
        },
        "heuristic": heur,
        "hybrid": hybrid,
        "lift_pp": (hybrid["accuracy"] - heur["accuracy"]) * 100,
    }
    (Path(__file__).resolve().parent / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written to results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
