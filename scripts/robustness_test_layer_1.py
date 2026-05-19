"""
Robustness Test — Layer 0 + Layer 1 vs the Wild Corpus
=======================================================

Runs the Fast Path + Modality Gate against the wild_corpus.json — queries
that simulate REAL user behavior (voice-to-text, customer support, code with
stack traces, mixed-language, markdown, URLs, emoji-only, RTL, sarcasm, etc.)
WITHOUT having been used during development.

Failures are reported honestly. The wild corpus is intentionally adversarial:
queries the engineer did not specifically optimize for. If the system handles
them well, that's evidence of robustness; if not, those are real bugs.

Acceptance:
  - acceptable_modalities[] — multiple labels OK when genuinely ambiguous
  - acceptable_languages[] — same
  - acceptable_code_languages[] — same
  - must_validate=True → expects validation_passed=True
  - should_block=True → expects validation_passed=False (injection cases)

Output: artifacts/layer_1/robustness_results.json
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.fast_path import FastPathAnalyzer  # noqa: E402
from src.layer0_model_infra.routing.modality_gate import ModalityGate  # noqa: E402


CORPUS_PATH = REPO_ROOT / "artifacts" / "layer_1" / "wild_corpus.json"
OUT_PATH = REPO_ROOT / "artifacts" / "layer_1" / "robustness_results.json"


def evaluate_one(fp, gate, case):
    """Run one query through Layer 0 + Layer 1, return verdict + diagnostics."""
    query = case["query"]
    verdict = {
        "id": case["id"],
        "category": case["category"],
        "query_preview": query[:80] + ("…" if len(query) > 80 else ""),
        "issues": [],
        "warnings": [],
    }

    # Layer 0
    try:
        t0 = time.perf_counter_ns()
        fp_decision = fp.analyze(query)
        t1 = time.perf_counter_ns()
        verdict["fast_path_latency_us"] = (t1 - t0) / 1000
        verdict["fast_path_bypass"] = fp_decision.should_bypass
        verdict["fast_path_category"] = fp_decision.category.value
    except Exception as exc:
        verdict["issues"].append({
            "layer": "fast_path", "type": "exception",
            "exception": type(exc).__name__, "message": str(exc),
            "trace": traceback.format_exc(limit=3),
        })
        return verdict  # can't continue if Layer 0 crashed

    # Layer 1
    try:
        t0 = time.perf_counter_ns()
        m = gate.analyze(text=query)
        t1 = time.perf_counter_ns()
        verdict["modality_latency_us"] = (t1 - t0) / 1000
        verdict["modality"] = m.primary_modality.value
        verdict["language"] = m.language
        verdict["language_method"] = m.language_detector_used
        verdict["code_language"] = m.code_language
        verdict["structured_format"] = m.structured_format
        verdict["validation_passed"] = m.validation_passed
        verdict["token_count"] = m.token_count
    except Exception as exc:
        verdict["issues"].append({
            "layer": "modality_gate", "type": "exception",
            "exception": type(exc).__name__, "message": str(exc),
            "trace": traceback.format_exc(limit=3),
        })
        return verdict

    # ---- Verdict checks ----

    # 1. Validation expectations
    if case.get("should_block"):
        if m.validation_passed:
            verdict["issues"].append({
                "type": "injection_not_blocked",
                "detail": f"Expected validation_passed=False (injection), got True",
            })
    elif case.get("must_validate", True):
        if not m.validation_passed:
            verdict["issues"].append({
                "type": "legitimate_query_blocked",
                "detail": f"Expected validation_passed=True, got False; reason={m.reasoning}",
            })

    # 2. Modality expectations
    acceptable = case.get("acceptable_modalities")
    if acceptable and verdict.get("modality") and verdict["modality"] not in acceptable:
        verdict["issues"].append({
            "type": "wrong_modality",
            "detail": f"Got {verdict['modality']!r}, acceptable {acceptable}",
        })

    # 3. Language expectations
    acc_lang = case.get("acceptable_languages")
    if acc_lang and verdict.get("language") and verdict["language"] not in acc_lang:
        # Don't fire on empty-text edge cases
        if query.strip():
            verdict["issues"].append({
                "type": "wrong_language",
                "detail": f"Got {verdict['language']!r}, acceptable {acc_lang}",
            })

    # 4. Code-language expectations (only when specified)
    acc_code = case.get("acceptable_code_languages")
    if acc_code and verdict.get("code_language", "") not in acc_code:
        verdict["issues"].append({
            "type": "wrong_code_language",
            "detail": f"Got {verdict['code_language']!r}, acceptable {acc_code}",
        })

    # 5. PII flag (informational — we don't have detection yet)
    if case.get("contains_pii"):
        verdict["warnings"].append("Query contains PII (telemetry-redaction not yet implemented)")

    # 6. Latency
    total_lat = verdict.get("fast_path_latency_us", 0) + verdict.get("modality_latency_us", 0)
    if total_lat > 100_000:  # 100ms
        verdict["warnings"].append(f"Slow: total {total_lat/1000:.1f}ms")

    return verdict


def main() -> int:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    cases = payload["queries"]

    fp = FastPathAnalyzer()
    fp.analyze("warmup")
    gate = ModalityGate()
    gate.analyze("warmup")

    print(f"Running wild corpus: {len(cases)} queries across {len(payload['_meta']['categories'])} categories")
    print("=" * 70)

    results = [evaluate_one(fp, gate, c) for c in cases]

    crashes = [r for r in results if any(i["type"] == "exception" for i in r["issues"])]
    issues = [r for r in results if r["issues"]]
    clean = [r for r in results if not r["issues"]]

    print(f"\nResults:")
    print(f"  Clean (no issues):   {len(clean):>3} / {len(cases)}")
    print(f"  Issues:              {len(issues):>3} / {len(cases)}")
    print(f"  Exceptions:          {len(crashes):>3} / {len(cases)}")

    # Issue breakdown by type
    issue_types: dict[str, int] = {}
    for r in results:
        for i in r["issues"]:
            issue_types[i["type"]] = issue_types.get(i["type"], 0) + 1
    if issue_types:
        print(f"\nIssue type breakdown:")
        for t, n in sorted(issue_types.items(), key=lambda x: -x[1]):
            print(f"  {t:<35}  {n:>3}")

    # Per-category pass rate
    by_cat: dict[str, dict] = {}
    for r in results:
        cat = r["category"]
        slot = by_cat.setdefault(cat, {"total": 0, "clean": 0})
        slot["total"] += 1
        if not r["issues"]:
            slot["clean"] += 1
    print(f"\nPer-category pass rate:")
    for cat, slot in sorted(by_cat.items()):
        rate = slot["clean"] / slot["total"]
        flag = "✓" if rate == 1.0 else "✗"
        print(f"  {flag} {cat:<30}  {rate:>5.0%}  ({slot['clean']}/{slot['total']})")

    # First N issues in detail
    if issues:
        print(f"\nFirst 15 issues (of {len(issues)}):")
        for r in issues[:15]:
            print(f"\n  [{r['id']}] ({r['category']})")
            print(f"    query: {r['query_preview']}")
            for i in r["issues"]:
                print(f"    → {i['type']}: {i['detail'] if 'detail' in i else i.get('message', '')}")

    # Persist
    out_payload = {
        "_meta": {
            "produced_by": "scripts/robustness_test_layer_1.py",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "Wild-corpus testing — queries the engineer didn't specifically optimize for",
        },
        "summary": {
            "total": len(cases),
            "clean": len(clean),
            "with_issues": len(issues),
            "with_exceptions": len(crashes),
            "pass_rate": len(clean) / len(cases),
        },
        "issue_type_counts": issue_types,
        "per_category": {
            c: {**s, "rate": s["clean"] / s["total"]}
            for c, s in by_cat.items()
        },
        "results": results,
    }
    OUT_PATH.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written to {OUT_PATH}")
    return 0 if not crashes else 2


if __name__ == "__main__":
    sys.exit(main())
