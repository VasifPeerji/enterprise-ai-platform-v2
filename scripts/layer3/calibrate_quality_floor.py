"""
scripts/layer3/calibrate_quality_floor.py  (WORKING TOOL — not committed yet)

Data-driven calibration of the Layer 3 quality floor (the value referenced by
Layer3QualityFloorConfig as "auto-tuned after 30 days of telemetry" but never
built). Instead of telemetry we use the leakage-safe LOO benchmark over the
grounded MMLU-Pro set: sweep the high-risk floor and the hard-difficulty penalty,
and report the correctness / cost / free-selection tradeoff at each setting so the
floor is lowered on evidence, not guesswork.

Method: encode every grounded question ONCE (the expensive part), cache its
neighbours + per-model predicted qualities, then for each floor setting re-run
ONLY the selection (_choose) — fast. Free-only (premium keys stripped + Fix B
excludes inactive), so every pick is a free model scored against its REAL outcome.

CAVEAT printed in the output: this is the ACADEMIC slice. The floor is global, so
lowering it also affects conversational/production traffic that isn't represented
here — treat the recommendation as a starting point, not a final value.

Usage:
  python scripts/layer3/calibrate_quality_floor.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from dotenv import dotenv_values
for _k, _v in dotenv_values(REPO / ".env").items():
    if _k.endswith("_API_KEY") and _v:
        os.environ.setdefault(_k, _v.strip())
os.environ.setdefault("LAYER3_CANARY_FRACTION", "1.0")
# By default strip premium keys (free-only: measure the FREE fleet's floor
# tradeoff). With --full, keep them so the sweep shows how the floor trades free
# vs PAID escalation — the production-relevant question (free% is the key column).
if "--full" not in sys.argv:
    for _k in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
        os.environ.pop(_k, None)

import pandas as pd  # noqa: E402
from qdrant_client.http import models as qm  # noqa: E402

NEW_FREE = ["gpt-oss-120b-groq", "gpt-oss-20b-groq", "qwen3-32b-groq", "llama-4-scout-17b-groq"]
OLD_FREE = ["llama-3.1-8b-instant-groq", "llama-3.3-70b-versatile-groq", "qwen-2.5-72b-huggingface"]
FREE = NEW_FREE + OLD_FREE
PROXY = "llama-3.3-70b-versatile-groq"

# (high_risk_floor, hard_penalty); default floor stays 0.65 throughout
GRID = [
    (0.75, 0.10),   # current / baseline
    (0.75, 0.05),
    (0.75, 0.00),
    (0.70, 0.05),
    (0.70, 0.00),
    (0.65, 0.05),
    (0.65, 0.00),
]


def _mean(xs):
    s = pd.Series(list(xs), dtype="float64").dropna()
    return float(s.mean()) if len(s) else float("nan")


def main() -> int:
    new = pd.read_parquet(REPO / "data/processed/harvested/outcomes_mmlu_det.parquet")[
        ["question_global_id", "model_id", "outcome"]]
    gqids = set(new.question_global_id.unique())
    live = pd.read_parquet(REPO / "data/processed/outcomes.parquet")
    old = live[(live.model_id.isin(OLD_FREE)) & (live.question_global_id.isin(gqids))][
        ["question_global_id", "model_id", "outcome"]]
    piv = pd.concat([new, old], ignore_index=True).pivot_table(
        index="question_global_id", columns="model_id", values="outcome")
    qtext = pd.read_parquet(REPO / "data/processed/questions.parquet").set_index("question_global_id")["question_text"]

    from src.layer0_model_infra.routing.registry_loader import get_layer3_registry
    from src.layer0_model_infra.routing.knn_router import get_knn_router, make_feature_cell
    get_layer3_registry().refresh_activation()
    r = get_knn_router(); r.warmup()
    r._config.verdict_cache.enable = False
    r._config.exploration.rate = 0.0
    r._config.warmup.forced_selection_rate = 0.0
    coll = r._config.encoder.qdrant_collection

    def search_excl(emb, qid):
        resp = r.qdrant.query_points(
            collection_name=coll, query=emb.tolist(),
            query_filter=qm.Filter(must_not=[qm.FieldCondition(
                key="question_global_id", match=qm.MatchValue(value=qid))]),
            limit=r._config.knn.knn_k, score_threshold=r._config.knn.min_similarity,
            with_payload=True)
        return list(resp.points)

    # ---- PASS 1: encode + predict once per question (the expensive part) ----
    cache = []
    for qid in piv.index:
        text = str(qtext.get(qid, "") or "")
        if not text.strip():
            continue
        feats = r.feature_extractor.extract(text)
        emb = r._encode(text)
        cell = make_feature_cell(feats)
        nbrs = search_excl(emb, qid)
        grounded = len(nbrs) >= r._config.knn.min_neighbors_for_trust
        quals, conf, _, cs = r._predict_qualities(feats, nbrs if grounded else [], cell)
        cache.append({"qid": qid, "text": text, "feats": feats, "quals": quals,
                      "conf": conf, "nbrs": nbrs, "cell": cell, "grounded": grounded, "cs": cs})
    print(f"cached {len(cache)} questions; sweeping {len(GRID)} floor settings (free-only)\n")

    # ---- PASS 2: sweep floors, re-run only selection ----
    print(f"{'high_risk':>9} {'hard':>5} | {'correct':>7} {'compute':>7} {'free%':>5} {'new%':>5} | top picks")
    print("-" * 92)
    base = None
    for hr, hard in GRID:
        r._floor_high_risk = hr
        r._floor_default = 0.65
        r._config.quality_floor.hard_difficulty_penalty = hard
        scores, computes, picks = [], [], []
        for c in cache:
            d = r._choose(c["text"], c["feats"], c["quals"], c["conf"], c["nbrs"],
                          "sweep", c["cell"], knn_grounded=c["grounded"], confidence_scores=c["cs"])
            m = d.selected_model
            picks.append(m)
            computes.append(r._model_compute_cost(m))
            if m in piv.columns and not pd.isna(piv.loc[c["qid"], m]):
                scores.append(float(piv.loc[c["qid"], m]))
            elif not pd.isna(piv.loc[c["qid"], PROXY]):
                scores.append(float(piv.loc[c["qid"], PROXY]))
        correct = _mean(scores)
        compute = _mean(computes)
        freepct = sum(p in FREE for p in picks) / len(picks) * 100
        newpct = sum(p in NEW_FREE for p in picks) / len(picks) * 100
        top = ", ".join(f"{m.split('-groq')[0][:14]}:{n}" for m, n in Counter(picks).most_common(3))
        tag = "  <- current" if (hr, hard) == (0.75, 0.10) else ""
        if (hr, hard) == (0.75, 0.10):
            base = (correct, compute)
        dc = ""
        if base and (hr, hard) != (0.75, 0.10):
            dc = f"  (corr {correct-base[0]:+.3f}, size {compute-base[1]:+.1f})"
        print(f"{hr:>9.2f} {hard:>5.2f} | {correct:>7.3f} {compute:>7.1f} {freepct:>5.0f} {newpct:>5.0f} | {top}{tag}{dc}")

    print("\nCAVEAT: academic (MMLU-Pro) slice only. The floor is GLOBAL -- lowering it "
          "also affects conversational/production traffic not represented here. "
          "Recommendation is a starting point; confirm on broader traffic before locking in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
