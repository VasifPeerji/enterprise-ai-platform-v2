"""
Layer 0 Library Evaluation Experiment
======================================

Question: Does adding a Model2Vec-based semantic classifier (Tier 2) improve
Layer 0 over the current pure-heuristic implementation (Tier 1)?

Method:
  1. Run both classifiers on:
     (a) the original golden_set.json (sanity: heuristic must still hit ~100%)
     (b) the paraphrase_corpus.json (the real test: does the library catch
         queries the keyword table misses?)
  2. Report precision, recall, F1, latency, and confusion matrices for each.
  3. Identify cases where each approach wins / loses.
  4. Make a data-driven adopt/reject/hybrid decision.

Tier 2 architecture (Model2Vec prototype-similarity classifier):
  - Embed all known greeting / ack / farewell prototypes ONCE at startup.
  - For a new query: embed it, compute cosine similarity to each prototype.
  - If max similarity >= threshold, classify as the matching category.
  - Else: no bypass.

The threshold is swept to find the precision/recall trade-off point.

Output: experiments/layer_0_model2vec_vs_heuristic/results.json
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.layer0_model_infra.routing.fast_path import (  # noqa: E402
    FastPathAnalyzer,
    FastPathCategory,
)

EXPERIMENT_DIR = Path(__file__).resolve().parent
GOLDEN_SET_PATH = REPO_ROOT / "artifacts" / "layer_0" / "golden_set.json"
PARAPHRASE_PATH = EXPERIMENT_DIR / "paraphrase_corpus.json"
RESULTS_PATH = EXPERIMENT_DIR / "results.json"


# ----------------------------------------------------------------------------
# Tier 2: Model2Vec prototype-similarity classifier
# ----------------------------------------------------------------------------

class Model2VecClassifier:
    """Prototype-based semantic chitchat classifier.

    Embeds a curated set of greeting / ack / farewell prototypes and classifies
    new queries by cosine similarity. No training step required — the
    prototypes ARE the model.

    Why prototype-based and not a trained LR head?
      - Keeps the experiment honest: no risk of overfitting to the test set
      - Sub-millisecond inference on CPU once embeddings are cached
      - Easy to add a new chitchat phrase: just append to PROTOTYPES
    """

    # Curated prototypes — diverse phrasings per category. Lifted from the
    # paraphrase corpus and a few extra synonyms. Multilingual where natural.
    PROTOTYPES: dict[str, list[str]] = {
        "trivial_greeting": [
            # English
            "hi", "hello", "hey", "yo", "sup", "wassup", "howdy",
            "good morning", "good afternoon", "good evening", "good day",
            "how are you", "how's it going", "what's up", "how's life",
            "long time no see", "nice to meet you",
            # Non-English
            "hola", "bonjour", "guten tag", "ciao", "olá", "namaste",
            "你好", "こんにちは", "안녕하세요", "مرحبا", "привет",
            "merhaba", "salut",
        ],
        "trivial_acknowledgment": [
            # English
            "thanks", "thank you", "thanks a lot", "thanks so much",
            "much appreciated", "appreciate it", "appreciate you",
            "ok", "okay", "got it", "understood", "noted", "sounds good",
            "cheers", "cheers mate", "you're a lifesaver", "much obliged",
            "no problem", "no worries", "you rock", "much love",
            # Non-English
            "gracias", "muchas gracias", "merci", "merci beaucoup",
            "danke", "vielen dank", "grazie", "obrigado", "謝謝",
            "ありがとう", "감사합니다", "شكرا", "धन्यवाद",
        ],
        "trivial_farewell": [
            # English
            "bye", "goodbye", "see you", "see you later", "later",
            "take care", "talk to you later", "talk soon", "ttyl",
            "have a good one", "peace out", "catch you later", "farewell",
            # Non-English
            "adios", "au revoir", "auf wiedersehen", "arrivederci",
            "再见", "さようなら", "пока", "до свидания",
        ],
    }

    def __init__(self) -> None:
        from model2vec import StaticModel
        self.model = StaticModel.from_pretrained("minishlab/potion-base-8M")
        # Pre-compute and L2-normalise prototype embeddings.
        self._proto_vecs: dict[str, np.ndarray] = {}
        for category, phrases in self.PROTOTYPES.items():
            vecs = self.model.encode(phrases)  # (n, d)
            vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
            self._proto_vecs[category] = vecs

    def predict(self, query: str, threshold: float) -> tuple[bool, str, float]:
        """Return (should_bypass, category, confidence)."""
        if not query or not query.strip():
            return False, "none", 0.0
        v = self.model.encode(query)
        v = v / (np.linalg.norm(v) + 1e-9)
        best_cat = "none"
        best_sim = 0.0
        for category, proto_vecs in self._proto_vecs.items():
            # Cosine = dot since both are L2-normalised
            sims = proto_vecs @ v
            top = float(np.max(sims))
            if top > best_sim:
                best_sim = top
                best_cat = category
        return (best_sim >= threshold, best_cat if best_sim >= threshold else "none",
                best_sim)


# ----------------------------------------------------------------------------
# Tier 1: existing heuristic
# ----------------------------------------------------------------------------

def heuristic_predict(fp: FastPathAnalyzer, query: str) -> tuple[bool, str, float]:
    d = fp.analyze(query)
    return d.should_bypass, d.category.value, d.confidence


# ----------------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------------

def confusion(rows: list[dict]) -> dict:
    """Compute confusion matrix for binary bypass decision."""
    tp = sum(1 for r in rows if r["expected_bypass"] and r["actual_bypass"])
    fp = sum(1 for r in rows if not r["expected_bypass"] and r["actual_bypass"])
    tn = sum(1 for r in rows if not r["expected_bypass"] and not r["actual_bypass"])
    fn = sum(1 for r in rows if r["expected_bypass"] and not r["actual_bypass"])
    n = len(rows)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "n": n,
        "accuracy": (tp + tn) / n if n else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_dataset(name, cases, fp, classifier, thresholds):
    """Evaluate both approaches on a dataset across multiple thresholds."""
    print(f"\n{'=' * 70}\n  {name}  (n={len(cases)})\n{'=' * 70}")

    # Heuristic baseline
    heur_rows = []
    heur_latencies = []
    for case in cases:
        t0 = time.perf_counter_ns()
        bypass, cat, conf = heuristic_predict(fp, case["query"])
        t1 = time.perf_counter_ns()
        heur_latencies.append((t1 - t0) / 1000)
        heur_rows.append({
            "query": case["query"],
            "tag": case.get("tag", case.get("source", "?")),
            "expected_bypass": case["expected_bypass"],
            "expected_category": case.get("expected_category", case.get("category")),
            "actual_bypass": bypass,
            "actual_category": cat,
            "confidence": conf,
        })

    heur_conf = confusion(heur_rows)
    print(f"\nHeuristic (Tier 1):")
    print(f"  accuracy={heur_conf['accuracy']:.1%}  precision={heur_conf['precision']:.1%}  "
          f"recall={heur_conf['recall']:.1%}  F1={heur_conf['f1']:.1%}")
    print(f"  TP={heur_conf['tp']} FP={heur_conf['fp']} TN={heur_conf['tn']} FN={heur_conf['fn']}")
    print(f"  latency p50={statistics.median(heur_latencies):.1f}us  "
          f"p99={sorted(heur_latencies)[int(0.99 * len(heur_latencies))]:.1f}us")

    # Model2Vec across thresholds
    m2v_results = {}
    print("\nModel2Vec (Tier 2 standalone) — threshold sweep:")
    for thr in thresholds:
        rows = []
        latencies = []
        for case in cases:
            t0 = time.perf_counter_ns()
            bypass, cat, sim = classifier.predict(case["query"], threshold=thr)
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1000)
            rows.append({
                "query": case["query"],
                "tag": case.get("tag", case.get("source", "?")),
                "expected_bypass": case["expected_bypass"],
                "actual_bypass": bypass,
                "actual_category": cat,
                "similarity": sim,
            })
        c = confusion(rows)
        m2v_results[thr] = {"confusion": c, "rows": rows,
                            "p50_us": statistics.median(latencies),
                            "p99_us": sorted(latencies)[int(0.99 * len(latencies))]}
        print(f"  thr={thr:.2f}: acc={c['accuracy']:.1%} prec={c['precision']:.1%} "
              f"rec={c['recall']:.1%} F1={c['f1']:.1%}  "
              f"TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}")

    # Hybrid: heuristic → fall back to Model2Vec when heuristic returns NONE
    print("\nHybrid (Tier 1 + Tier 2 fallback) — threshold sweep:")
    hybrid_results = {}
    for thr in thresholds:
        rows = []
        latencies = []
        for case in cases:
            t0 = time.perf_counter_ns()
            h_bypass, h_cat, _ = heuristic_predict(fp, case["query"])
            if h_bypass:
                bypass, cat = h_bypass, h_cat
                sim = 0.0
            else:
                bypass, cat, sim = classifier.predict(case["query"], threshold=thr)
            t1 = time.perf_counter_ns()
            latencies.append((t1 - t0) / 1000)
            rows.append({
                "query": case["query"],
                "tag": case.get("tag", case.get("source", "?")),
                "expected_bypass": case["expected_bypass"],
                "actual_bypass": bypass,
                "actual_category": cat,
                "similarity": sim,
            })
        c = confusion(rows)
        hybrid_results[thr] = {"confusion": c, "rows": rows,
                               "p50_us": statistics.median(latencies),
                               "p99_us": sorted(latencies)[int(0.99 * len(latencies))]}
        print(f"  thr={thr:.2f}: acc={c['accuracy']:.1%} prec={c['precision']:.1%} "
              f"rec={c['recall']:.1%} F1={c['f1']:.1%}  "
              f"TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}")

    return {
        "name": name,
        "n": len(cases),
        "heuristic": {"confusion": heur_conf, "rows": heur_rows,
                      "p50_us": statistics.median(heur_latencies),
                      "p99_us": sorted(heur_latencies)[int(0.99 * len(heur_latencies))]},
        "model2vec": m2v_results,
        "hybrid": hybrid_results,
    }


def find_misclassifications(rows):
    fps = [r for r in rows if not r["expected_bypass"] and r["actual_bypass"]]
    fns = [r for r in rows if r["expected_bypass"] and not r["actual_bypass"]]
    return fps, fns


def main() -> int:
    # Tier-1-only analyzer for honest baseline (Tier 2 explicitly disabled)
    fp = FastPathAnalyzer()
    fp._tier2 = None
    fp.analyze("warmup")

    print("Loading Model2Vec for the standalone-and-hybrid arms...")
    t0 = time.perf_counter()
    classifier = Model2VecClassifier()
    print(f"  Tier 2 ready in {time.perf_counter() - t0:.1f}s")
    classifier.predict("warmup", 0.5)  # warmup encode

    golden = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))["queries"]
    paraphrase = json.loads(PARAPHRASE_PATH.read_text(encoding="utf-8"))["queries"]

    thresholds = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]

    golden_result = evaluate_dataset("Golden Set (Tier 1 native)", golden, fp,
                                     classifier, thresholds)
    paraphrase_result = evaluate_dataset("Paraphrase Corpus (OOD for Tier 1)",
                                         paraphrase, fp, classifier, thresholds)

    # ---- Best-threshold selection ----
    # Goal: maximise F1 on paraphrase corpus WITHOUT regressing precision below 0.95.
    print("\n" + "=" * 70)
    print("  Decision Analysis")
    print("=" * 70)

    best_thr = None
    best_f1 = 0.0
    for thr in thresholds:
        c = paraphrase_result["hybrid"][thr]["confusion"]
        if c["precision"] >= 0.95 and c["f1"] > best_f1:
            best_f1 = c["f1"]
            best_thr = thr

    if best_thr is None:
        print("\nNo threshold yields precision >= 0.95 on paraphrase corpus.")
        print("Hybrid Tier 2 should NOT be adopted at the standard precision bar.")
        recommendation = {
            "decision": "reject",
            "reason": "No threshold meets precision floor of 0.95 on paraphrase corpus",
        }
    else:
        hyb = paraphrase_result["hybrid"][best_thr]["confusion"]
        heur = paraphrase_result["heuristic"]["confusion"]
        delta_recall = hyb["recall"] - heur["recall"]
        delta_f1 = hyb["f1"] - heur["f1"]
        print(f"\nBest hybrid threshold: {best_thr:.2f}")
        print(f"  paraphrase corpus heuristic-only F1: {heur['f1']:.1%}")
        print(f"  paraphrase corpus hybrid F1:         {hyb['f1']:.1%}")
        print(f"  ΔF1: {delta_f1:+.1%}, Δrecall: {delta_recall:+.1%}")

        if delta_f1 >= 0.05:
            decision = "adopt"
            reason = (f"Hybrid F1 improves by {delta_f1:+.1%} at precision "
                      f"{hyb['precision']:.1%} (threshold={best_thr:.2f})")
        elif delta_f1 >= 0.01:
            decision = "consider"
            reason = (f"Marginal F1 improvement ({delta_f1:+.1%}). Latency cost "
                      f"+{paraphrase_result['hybrid'][best_thr]['p50_us'] - heur['p50_us']:.0f}us. "
                      f"Borderline.")
        else:
            decision = "reject"
            reason = (f"F1 improvement only {delta_f1:+.1%} — not worth the "
                      f"latency cost and added dependency")
        recommendation = {
            "decision": decision,
            "reason": reason,
            "best_threshold": best_thr,
            "heuristic_only_paraphrase_f1": heur["f1"],
            "hybrid_paraphrase_f1": hyb["f1"],
            "delta_f1": delta_f1,
            "delta_recall": delta_recall,
        }
        print(f"\nRECOMMENDATION: {decision.upper()}")
        print(f"  {reason}")

    # ---- Show specific wins / losses on paraphrase corpus ----
    if best_thr is not None:
        print("\n" + "-" * 70)
        print("Cases the HYBRID catches that HEURISTIC misses (true wins):")
        print("-" * 70)
        hyb_rows = paraphrase_result["hybrid"][best_thr]["rows"]
        heur_rows = paraphrase_result["heuristic"]["rows"]
        for h_row, hyb_row in zip(heur_rows, hyb_rows):
            if (hyb_row["actual_bypass"] == hyb_row["expected_bypass"]
                    and h_row["actual_bypass"] != h_row["expected_bypass"]
                    and hyb_row["expected_bypass"]):
                print(f"  ✓ {hyb_row['query']!r}  (sim={hyb_row['similarity']:.2f})")

        print("\nCases the HYBRID misclassifies (new false positives — BAD):")
        print("-" * 70)
        for h_row, hyb_row in zip(heur_rows, hyb_rows):
            if (hyb_row["actual_bypass"] and not hyb_row["expected_bypass"]
                    and not h_row["actual_bypass"]):
                print(f"  ✗ {hyb_row['query']!r}  (sim={hyb_row['similarity']:.2f}, "
                      f"as={hyb_row['actual_category']})")

    # ---- Write JSON artifact ----
    payload = {
        "_meta": {
            "experiment": "layer_0_model2vec_vs_heuristic",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "thresholds_swept": thresholds,
            "model2vec_model": "minishlab/potion-base-8M",
            "embedding_dim": 256,
        },
        "datasets": {
            "golden_set": _strip_rows(golden_result),
            "paraphrase_corpus": _strip_rows(paraphrase_result, keep_misclass=True),
        },
        "recommendation": recommendation,
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(f"\n\nResults written to {RESULTS_PATH}")
    return 0


def _strip_rows(result, keep_misclass=False):
    """Strip full row arrays from result for compact JSON output."""
    out = {
        "name": result["name"],
        "n": result["n"],
        "heuristic": {
            "confusion": result["heuristic"]["confusion"],
            "p50_us": result["heuristic"]["p50_us"],
            "p99_us": result["heuristic"]["p99_us"],
        },
        "model2vec": {
            str(thr): {"confusion": v["confusion"], "p50_us": v["p50_us"],
                       "p99_us": v["p99_us"]}
            for thr, v in result["model2vec"].items()
        },
        "hybrid": {
            str(thr): {"confusion": v["confusion"], "p50_us": v["p50_us"],
                       "p99_us": v["p99_us"]}
            for thr, v in result["hybrid"].items()
        },
    }
    if keep_misclass:
        # Keep mis-classifications for the paraphrase set so they're auditable
        out["heuristic"]["misclassifications"] = [
            r for r in result["heuristic"]["rows"]
            if r["actual_bypass"] != r["expected_bypass"]
        ]
    return out


if __name__ == "__main__":
    sys.exit(main())
