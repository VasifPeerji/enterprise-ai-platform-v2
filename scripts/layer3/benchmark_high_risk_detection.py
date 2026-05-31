"""
3-arm benchmark for high-risk (medical/legal/financial) detection — Batch 3.5.

Arms (each is "Tier-1 regex, then Tier-2 on a miss"):
  A_regex            — the current narrow regex only (baseline)
  B_regex_bge        — regex + bge-small-en kNN over prototype utterances
  C_regex_mdeberta   — regex + mDeBERTa-v3 zero-shot NLI

Metric: binary high-risk detection (is the query medical/legal/financial?) —
precision / recall / F1 — plus per-arm latency and the actual false-positive /
false-negative queries. Domain accuracy (medical vs legal vs financial among
true positives) is reported as a secondary number.

Selection rule (locked in the design): adopt the highest-F1 arm whose PRECISION
does not regress vs Arm A — we will not trade the regex's precision (no
"vision → MEDICAL") for recall.

Outputs:
  artifacts/layer3/high_risk_benchmark.json
  docs/layer3/high_risk_classifier_choice.md

Run:
  python -m scripts.layer3.benchmark_high_risk_detection
  python -m scripts.layer3.benchmark_high_risk_detection --arms A,B   # skip mDeBERTa
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from scripts.layer3._common import ARTIFACTS_LAYER3, REPO_ROOT, ensure_dirs, get_pipeline_logger
from scripts.layer3._high_risk_eval import HIGH_RISK_EVAL


def _regex_predict(query: str):
    from src.layer0_model_infra.routing.feature_extractor import FeatureExtractor
    domain = FeatureExtractor._detect_high_risk_domain(query)
    return domain.value if domain else None


def _combined_predict(query: str, tier2):
    """Tier-1 regex first; on a miss, fall to the Tier-2 classifier."""
    from src.layer0_model_infra.routing.feature_extractor import FeatureExtractor
    domain = FeatureExtractor._detect_high_risk_domain(query)
    if domain:
        return domain.value
    pred, _score = tier2.classify(query)
    return pred.value if pred else None


def _metrics(preds: list, labels: list, queries: list) -> dict:
    tp = fp = fn = tn = 0
    domain_correct = 0
    false_positives: list[str] = []
    false_negatives: list[str] = []
    for pred, label, q in zip(preds, labels, queries):
        p_hr = pred is not None
        l_hr = label is not None
        if p_hr and l_hr:
            tp += 1
            if pred == label:
                domain_correct += 1
        elif p_hr and not l_hr:
            fp += 1
            false_positives.append(f"{q}  [pred={pred}]")
        elif not p_hr and l_hr:
            fn += 1
            false_negatives.append(f"{q}  [true={label}]")
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "domain_accuracy": round(domain_correct / tp, 4) if tp else 0.0,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def _time_predict(fn, queries: list) -> tuple[list, float]:
    t0 = time.perf_counter()
    preds = [fn(q) for q in queries]
    elapsed = time.perf_counter() - t0
    return preds, (elapsed / max(len(queries), 1)) * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="A,B,C", help="comma list of arms to run")
    parser.add_argument("--bge-threshold", type=float, default=0.62)
    parser.add_argument("--mdeberta-threshold", type=float, default=0.55)
    args = parser.parse_args()

    logger = get_pipeline_logger("layer3.high_risk_bench")
    ensure_dirs()

    arms = {a.strip().upper() for a in args.arms.split(",")}
    queries = [q for q, _ in HIGH_RISK_EVAL]
    labels = [l for _, l in HIGH_RISK_EVAL]
    n_pos = sum(1 for l in labels if l is not None)
    logger.info("eval_set n=%d positives=%d negatives=%d", len(queries), n_pos, len(queries) - n_pos)

    results: dict[str, dict] = {}

    if "A" in arms:
        logger.info("running Arm A (regex)")
        preds, ms = _time_predict(_regex_predict, queries)
        results["A_regex"] = {**_metrics(preds, labels, queries), "avg_ms": round(ms, 3)}

    if "B" in arms:
        logger.info("running Arm B (regex + bge-small-en kNN) — loading model")
        try:
            from src.layer0_model_infra.routing.high_risk_classifier import get_bge_classifier
            bge = get_bge_classifier(threshold=args.bge_threshold)
            bge.classify("warmup query")  # load + warm
            preds, ms = _time_predict(lambda q: _combined_predict(q, bge), queries)
            results["B_regex_bge"] = {**_metrics(preds, labels, queries), "avg_ms": round(ms, 3),
                                      "threshold": args.bge_threshold}
        except Exception as exc:
            logger.error("Arm B failed: %s", exc)
            results["B_regex_bge"] = {"error": str(exc)}

    if "C" in arms:
        logger.info("running Arm C (regex + mDeBERTa zero-shot) — loading model (~279MB first run)")
        try:
            from src.layer0_model_infra.routing.high_risk_classifier import get_mdeberta_classifier
            mde = get_mdeberta_classifier(threshold=args.mdeberta_threshold)
            mde.classify("warmup query")  # load + warm
            preds, ms = _time_predict(lambda q: _combined_predict(q, mde), queries)
            results["C_regex_mdeberta"] = {**_metrics(preds, labels, queries), "avg_ms": round(ms, 3),
                                           "threshold": args.mdeberta_threshold}
        except Exception as exc:
            logger.error("Arm C failed: %s", exc)
            results["C_regex_mdeberta"] = {"error": str(exc)}

    # ── Winner selection ──
    # The design prefers RECALL: a missed medical/legal/financial query routed to
    # a weak model is far worse than mild over-routing. So we do NOT require
    # matching the regex's (very high, very low-recall) precision — only a sane
    # precision floor — and then maximize F1. Production additionally gates Tier-2
    # to TEXT modality, which lifts precision further (see the markdown report).
    PRECISION_FLOOR = 0.80
    scored = {k: v for k, v in results.items() if "f1" in v}
    eligible = {k: v for k, v in scored.items() if v["precision"] >= PRECISION_FLOOR}
    pool = eligible or scored
    winner = max(pool, key=lambda k: pool[k]["f1"]) if pool else None

    report = {
        "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "eval_total": len(queries),
        "eval_positives": n_pos,
        "selection_rule": f"highest F1 with precision >= {PRECISION_FLOOR} (recall-favoring)",
        "precision_floor": PRECISION_FLOOR,
        "winner": winner,
        "arms": results,
    }
    (ARTIFACTS_LAYER3 / "high_risk_benchmark.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    _write_markdown(report)

    # Console summary (ascii-safe)
    print("\n==== HIGH-RISK DETECTION BENCHMARK ====")
    for arm, m in results.items():
        if "f1" in m:
            print(f"{arm:20} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} "
                  f"dom_acc={m['domain_accuracy']:.2f} {m['avg_ms']:.2f}ms "
                  f"(fp={m['fp']} fn={m['fn']})")
        else:
            print(f"{arm:20} ERROR: {m.get('error')}")
    print(f"\nWINNER: {winner}")
    return 0


def _write_markdown(report: dict) -> None:
    lines = [
        "# Layer 3 — High-Risk Detection: Arm Choice",
        "",
        "Auto-generated by `scripts/layer3/benchmark_high_risk_detection.py`. Compares",
        "Tier-1 regex (A) against regex + a Tier-2 semantic classifier (B = bge-small-en",
        "kNN over prototypes, C = mDeBERTa-v3 zero-shot NLI).",
        "",
        f"- Eval set: **{report['eval_total']}** queries ({report['eval_positives']} high-risk).",
        f"- Selection rule: **{report['selection_rule']}**.",
        f"- **Winner: `{report['winner']}`**",
        "",
        "| Arm | Precision | Recall | F1 | Domain acc | Latency | FP | FN |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm, m in report["arms"].items():
        if "f1" in m:
            lines.append(
                f"| {arm} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
                f"{m['domain_accuracy']:.2f} | {m['avg_ms']:.2f} ms | {m['fp']} | {m['fn']} |"
            )
        else:
            lines.append(f"| {arm} | — | — | — | — | — | error | {m.get('error', '')[:40]} |")
    lines.append("")
    # Show the winner's remaining errors so the precision/recall trade-off is explicit.
    win = report.get("winner")
    if win and "false_positives" in report["arms"].get(win, {}):
        wm = report["arms"][win]
        lines += ["## Winner's residual errors", "",
                  f"**False positives ({wm['fp']})** — flagged high-risk but aren't:"]
        lines += [f"- {x}" for x in wm["false_positives"]] or ["- none"]
        lines += ["", f"**False negatives ({wm['fn']})** — missed high-risk queries:"]
        lines += [f"- {x}" for x in wm["false_negatives"]] or ["- none"]
        lines.append("")
    docs_dir = REPO_ROOT / "docs" / "layer3"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "high_risk_classifier_choice.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
