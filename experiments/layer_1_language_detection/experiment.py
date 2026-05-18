"""
Layer 1 Language Detection — Head-to-Head Experiment
=====================================================

Question: Does adding lingua-py + Hinglish markers as Tier 2 improve language
detection over the original script-regex-only heuristic?

Three arms:
  - Script-only (original): Unicode-script regex, defaults to "en"
  - Hybrid (current): script → Hinglish markers → lingua-py (conf-gated)
  - Lingua-only: bypass script tier entirely, just lingua

Two datasets:
  - artifacts/layer_1/golden_set.json (multilingual sanity)
  - corpus.json in this dir (Hinglish + Latin-script non-English + adversarial)

Output: results.json
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.modality_gate import HybridLanguageDetector, ModalityGate


def script_only_detect(text: str) -> str:
    """Reconstruct the original script-only detector for the baseline arm."""
    if not text:
        return "en"
    det = HybridLanguageDetector(confidence_threshold=1.0)
    det._lingua = None
    code, _, _ = det.detect(text)
    return code if code != "hi-Latn" else "en"  # script-only had no Hinglish tier


def lingua_only_detect(detector, text: str) -> str:
    """Pure lingua arm (no script regex, no Hinglish markers)."""
    if not text or not text.strip():
        return "en"
    if detector is None:
        return "en"
    try:
        conf = detector.compute_language_confidence_values(text)
    except Exception:
        return "en"
    if not conf:
        return "en"
    top = conf[0]
    return top.language.iso_code_639_1.name.lower()


def hybrid_detect(gate: ModalityGate, text: str) -> str:
    """Current production hybrid (script → Hinglish → lingua-conf-gated)."""
    return gate.analyze(text=text).language


def main() -> int:
    # Load datasets
    golden = json.loads((REPO_ROOT / "artifacts" / "layer_1" / "golden_set.json").read_text(encoding="utf-8"))["queries"]
    corpus = json.loads((Path(__file__).resolve().parent / "corpus.json").read_text(encoding="utf-8"))["queries"]

    gate = ModalityGate()
    gate.analyze("warmup")

    # Build a pure-lingua detector for the second arm
    try:
        from lingua import Language, LanguageDetectorBuilder
        langs = [Language.ENGLISH, Language.SPANISH, Language.FRENCH, Language.GERMAN,
                 Language.PORTUGUESE, Language.ITALIAN, Language.DUTCH, Language.TURKISH,
                 Language.POLISH, Language.INDONESIAN, Language.VIETNAMESE]
        lingua_det = LanguageDetectorBuilder.from_languages(*langs).build()
        lingua_det.detect_language_of("warmup")
    except ImportError:
        lingua_det = None

    def score(arm_name, cases, detect_fn):
        correct = 0
        total = 0
        latencies = []
        misclass = []
        for case in cases:
            expected = case.get("expected_language") or case.get("expected")
            if not expected:
                continue
            t0 = time.perf_counter_ns()
            predicted = detect_fn(case["query"])
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1000.0)
            total += 1
            if predicted == expected:
                correct += 1
            else:
                misclass.append({
                    "query": case["query"][:60],
                    "expected": expected,
                    "predicted": predicted,
                })
        return {
            "name": arm_name,
            "n": total,
            "correct": correct,
            "accuracy": correct / total if total else 0.0,
            "latency_p50_us": statistics.median(latencies) if latencies else 0,
            "latency_p99_us": sorted(latencies)[int(0.99 * len(latencies))] if len(latencies) > 100 else (max(latencies) if latencies else 0),
            "misclassifications": misclass,
        }

    print("=" * 70)
    print("  Layer 1 Language Detection — Head-to-Head Experiment")
    print("=" * 70)

    datasets = {
        "golden_set": golden,
        "paraphrase_corpus": corpus,
    }
    arms = {
        "script_only": script_only_detect,
        "hybrid": lambda text: hybrid_detect(gate, text),
        "lingua_only": lambda text: lingua_only_detect(lingua_det, text),
    }

    results = {}
    for dname, cases in datasets.items():
        print(f"\n--- Dataset: {dname} ({len(cases)} cases) ---")
        results[dname] = {}
        for aname, fn in arms.items():
            r = score(aname, cases, fn)
            results[dname][aname] = r
            print(f"  {aname:15}  acc={r['accuracy']:.1%}  "
                  f"({r['correct']}/{r['n']})  p50={r['latency_p50_us']:.0f}us")

    print("\n" + "=" * 70)
    print("  Decision Analysis")
    print("=" * 70)
    g_script = results["golden_set"]["script_only"]["accuracy"]
    g_hybrid = results["golden_set"]["hybrid"]["accuracy"]
    p_script = results["paraphrase_corpus"]["script_only"]["accuracy"]
    p_hybrid = results["paraphrase_corpus"]["hybrid"]["accuracy"]
    print(f"\nGolden set:        script_only={g_script:.1%}, hybrid={g_hybrid:.1%}")
    print(f"Paraphrase corpus: script_only={p_script:.1%}, hybrid={p_hybrid:.1%}")
    print(f"Hybrid lift (paraphrase): {(p_hybrid - p_script) * 100:+.1f} pp")

    decision = ("ADOPT" if (p_hybrid - p_script) >= 0.05 and g_hybrid >= g_script
                else "REJECT" if p_hybrid < p_script else "MIXED")
    print(f"\nRECOMMENDATION: {decision}")

    # Persist
    out_path = Path(__file__).resolve().parent / "results.json"
    payload = {
        "_meta": {
            "experiment": "layer_1_language_detection",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": decision,
        },
        "results": results,
        "summary": {
            "golden_set": {"script_only": g_script, "hybrid": g_hybrid},
            "paraphrase_corpus": {"script_only": p_script, "hybrid": p_hybrid},
            "hybrid_lift_pp": (p_hybrid - p_script) * 100,
        },
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
