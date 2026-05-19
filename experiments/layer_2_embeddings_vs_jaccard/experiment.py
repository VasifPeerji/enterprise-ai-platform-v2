"""
Layer 2 Embedding vs Char-N-gram — Head-to-Head Experiment

Question: Does Model2Vec embedding similarity beat the char-trigram Jaccard
baseline on routing-cache lookup?

Three arms:
  - Heuristic only: char-ngram Jaccard (the original fallback path)
  - Library only: Model2Vec cosine similarity, no other guards
  - Hybrid: Model2Vec + all validation guards (the production design)

Two datasets:
  - golden_set.json (curated cases — hit/miss/guards)
  - wild_corpus.json (real-user-style queries)

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

from src.layer0_model_infra.routing.semantic_memory import SemanticMemory  # noqa: E402


def make_memory(*, use_embeddings: bool, use_guards: bool = True) -> SemanticMemory:
    mem = SemanticMemory(
        similarity_threshold=0.75 if use_embeddings else 0.35,
        decay_half_life_seconds=604_800.0,
        enable_local_embedding=use_embeddings,
        enable_persistence=False,
        enable_negation_guard=use_guards,
        enable_pii_scrubbing=use_guards,
    )
    return mem


def run_case_on_arm(case: dict, *, arm: str) -> dict:
    """Run a single (record, lookup) pair under one configuration."""
    if arm == "heuristic":
        mem = make_memory(use_embeddings=False, use_guards=False)
    elif arm == "library_only":
        mem = make_memory(use_embeddings=True, use_guards=False)
    elif arm == "hybrid":
        mem = make_memory(use_embeddings=True, use_guards=True)
    else:
        raise ValueError(f"Unknown arm: {arm}")

    # Golden set has 'record' dict; wild has 'record_query'
    if "record" in case:
        rec = case["record"]
        mem.record(
            query=rec["query"],
            model_id=rec.get("model_id", "ollama-llama3.1-8b"),
            quality_score=rec.get("quality_score", 0.9),
            escalated=rec.get("escalated", False),
            intent=rec.get("intent", ""),
            domain=rec.get("domain", ""),
            complexity_band=rec.get("complexity_band", ""),
            model_version=rec.get("model_version", ""),
            tenant_id=rec.get("tenant_id", ""),
        )
        lookup_query = case["lookup"]
        lookup_intent = case.get("lookup_intent", "")
        lookup_tenant_id = case.get("lookup_tenant_id", "")
        lookup_model_version = case.get("lookup_model_version")
    else:
        # Wild corpus format
        mem.record(
            query=case["record_query"],
            model_id="ollama-llama3.1-8b",
            quality_score=0.9,
            escalated=False,
            intent="qa", domain="general", complexity_band="moderate",
        )
        lookup_query = case["lookup_query"]
        lookup_intent = ""
        lookup_tenant_id = ""
        lookup_model_version = None

    t0 = time.perf_counter_ns()
    result = mem.lookup(
        lookup_query,
        query_intent=lookup_intent,
        current_model_version=lookup_model_version,
        tenant_id=lookup_tenant_id,
    )
    t1 = time.perf_counter_ns()

    hit_correct = result.hit == case["expected_hit"]
    return {
        "case_id": case["id"],
        "category": case["category"],
        "arm": arm,
        "expected_hit": case["expected_hit"],
        "actual_hit": result.hit,
        "similarity": round(result.similarity, 3),
        "correct": hit_correct,
        "latency_us": round((t1 - t0) / 1000, 1),
    }


def score(dataset_cases: list[dict], arm: str) -> dict:
    rows = [run_case_on_arm(c, arm=arm) for c in dataset_cases]
    n = len(rows)
    correct = sum(r["correct"] for r in rows)
    # Confusion matrix
    tp = sum(1 for r in rows if r["expected_hit"] and r["actual_hit"])
    fp = sum(1 for r in rows if not r["expected_hit"] and r["actual_hit"])
    tn = sum(1 for r in rows if not r["expected_hit"] and not r["actual_hit"])
    fn = sum(1 for r in rows if r["expected_hit"] and not r["actual_hit"])
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    latencies = [r["latency_us"] for r in rows]
    return {
        "arm": arm,
        "n": n,
        "accuracy": correct / n if n else 0.0,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "p50_us": statistics.median(latencies),
        "p99_us": sorted(latencies)[int(0.99 * len(latencies))] if len(latencies) > 100 else max(latencies),
        "rows": rows,
    }


def main() -> int:
    golden = json.loads(
        (REPO_ROOT / "artifacts" / "layer_2" / "golden_set.json").read_text(encoding="utf-8")
    )["cases"]
    wild = json.loads(
        (REPO_ROOT / "artifacts" / "layer_2" / "wild_corpus.json").read_text(encoding="utf-8")
    )["cases"]

    arms = ["heuristic", "library_only", "hybrid"]

    print("=" * 70)
    print(" Layer 2 — Embedding vs Char-N-gram — Head-to-Head")
    print("=" * 70)

    results: dict[str, dict[str, dict]] = {}
    for ds_name, ds_cases in [("golden_set", golden), ("wild_corpus", wild)]:
        print(f"\n--- Dataset: {ds_name} (n={len(ds_cases)}) ---")
        results[ds_name] = {}
        for arm in arms:
            s = score(ds_cases, arm)
            results[ds_name][arm] = s
            print(f"  {arm:15s}  acc={s['accuracy']:.1%}  prec={s['precision']:.1%}  "
                  f"rec={s['recall']:.1%}  F1={s['f1']:.1%}  "
                  f"p50={s['p50_us']:.0f}us  p99={s['p99_us']:.0f}us  "
                  f"(TP={s['tp']} FP={s['fp']} TN={s['tn']} FN={s['fn']})")

    print("\n" + "=" * 70)
    print(" Decision Analysis")
    print("=" * 70)
    g_heur = results["golden_set"]["heuristic"]["f1"]
    g_hybrid = results["golden_set"]["hybrid"]["f1"]
    w_heur = results["wild_corpus"]["heuristic"]["f1"]
    w_hybrid = results["wild_corpus"]["hybrid"]["f1"]
    print(f"\nGolden set:   heuristic F1={g_heur:.1%}  hybrid F1={g_hybrid:.1%}")
    print(f"Wild corpus:  heuristic F1={w_heur:.1%}  hybrid F1={w_hybrid:.1%}")
    print(f"Hybrid lift (wild): {(w_hybrid - w_heur) * 100:+.1f} pp F1")

    decision = "ADOPT" if (w_hybrid - w_heur) >= 0.05 else "REJECT"
    print(f"\nRECOMMENDATION: {decision}")

    out = {
        "_meta": {
            "experiment": "layer_2_embeddings_vs_jaccard",
            "produced_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": decision,
        },
        "summary": {
            "golden": {arm: {k: results["golden_set"][arm][k]
                              for k in ["accuracy", "precision", "recall", "f1", "p50_us", "p99_us"]}
                       for arm in arms},
            "wild": {arm: {k: results["wild_corpus"][arm][k]
                            for k in ["accuracy", "precision", "recall", "f1", "p50_us", "p99_us"]}
                     for arm in arms},
            "hybrid_lift_pp_wild": (w_hybrid - w_heur) * 100,
        },
        "rows_golden": {arm: results["golden_set"][arm]["rows"] for arm in arms},
        "rows_wild": {arm: results["wild_corpus"][arm]["rows"] for arm in arms},
    }
    out_path = Path(__file__).resolve().parent / "results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
