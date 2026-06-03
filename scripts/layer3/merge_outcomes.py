"""
📁 File: scripts/layer3/merge_outcomes.py
Layer: Layer 0 — Layer 3 redesign (corpus expansion / Phase 2 merge + re-tag)
Purpose: Fold the Phase-1 harvested outcomes into the router's live outcome
         corpus, mapping harvested model names to registry model_ids, and
         re-derive coverage_quality from the REAL merged data.

NON-DESTRUCTIVE: writes proposed artifacts under data/processed/ and prints the
proposed registry coverage_quality re-tags. It does NOT overwrite the live
outcomes.parquet or registry.json — that swap is a separate, reviewed step
(merge_outcomes.py --apply, or a manual move) so a bad merge can't break routing.

Outputs:
  data/processed/outcomes_merged.parquet   — original + harvested (registry models)
  data/processed/harvested/candidates_pool.parquet — harvested outcomes for models
        NOT in the current registry (the data-backed menu for pool expansion)
  stdout: per-model coverage + proposed coverage_quality changes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROC = REPO_ROOT / "data" / "processed"
HARVEST_DIR = PROC / "harvested"
REGISTRY = REPO_ROOT / "src" / "layer0_model_infra" / "data" / "registry.json"
OUTCOME_COLUMNS = ["question_global_id", "model_id", "outcome", "source_url", "ingested_at"]

# Coverage thresholds (CoverageQuality in layer3_types): of the full corpus.
FULL_MIN, MEDIUM_MIN = 0.60, 0.20

# Harvested model name -> registry model_id(s). One underlying model can back
# several registry entries (e.g. Llama 3.3 70B is served by both Groq and
# OpenRouter-free), so values are LISTS and outcomes fan out to each.
MODEL_MAP: dict[str, list[str]] = {
    # MMLU-Pro harvested ids (already registry) + same-model siblings
    "llama-3.3-70b-versatile-groq": ["llama-3.3-70b-versatile-groq", "llama-3.3-70b-openrouter-free"],
    "llama-3.1-8b-instant-groq": ["llama-3.1-8b-instant-groq"],
    "qwen-2.5-72b-huggingface": ["qwen-2.5-72b-huggingface"],
    "qwen-2.5-coder-32b-openrouter-free": ["qwen-2.5-coder-32b-openrouter-free"],
    "qwen-qwq-32b-groq": ["qwen-qwq-32b-groq"],
    "gemma-2-27b-openrouter-free": ["gemma-2-27b-openrouter-free"],
    "deepseek-r1-distill-llama-70b-groq": ["deepseek-r1-distill-llama-70b-groq"],
    "gemma2-9b-it-groq": ["gemma2-9b-it-groq"],
    # SWE-bench canonical -> registry (clean matches + sibling)
    "claude-3-5-haiku": ["claude-3-5-haiku"],
    "claude-3-5-sonnet": ["claude-3-5-sonnet"],
    "gpt-4o": ["gpt-4o"],
    "deepseek-v3": ["deepseek-v3-openrouter-free"],
    # LiveBench raw HF names -> registry (clean matches)
    "Qwen2.5-72B-Instruct": ["qwen-2.5-72b-huggingface"],
    "Qwen2.5-Coder-32B-Instruct": ["qwen-2.5-coder-32b-openrouter-free"],
    "gemma-2-9b-it": ["gemma2-9b-it-groq"],
    "gemma-2-27b-it": ["gemma-2-27b-openrouter-free"],
    "Meta-Llama-3.1-8B-Instruct-Turbo": ["llama-3.1-8b-instant-groq"],
    "gpt-4o-2024-08-06": ["gpt-4o"],
    "gpt-4o-mini": ["gpt-4o-mini"],
    # pool-expansion additions: 3 grounded (identity) + kimi (from SWE "kimi")
    "nemotron-70b-huggingface": ["nemotron-70b-huggingface"],
    "qwen-2.5-32b-huggingface": ["qwen-2.5-32b-huggingface"],
    "mistral-small-2409-openrouter": ["mistral-small-2409-openrouter"],
    "kimi": ["kimi-k2-openrouter-free"],
}


def _coverage_quality(frac: float) -> str:
    return "full" if frac >= FULL_MIN else ("medium" if frac >= MEDIUM_MIN else "low")


def main() -> int:
    if not (PROC / "outcomes.parquet").exists():
        print("ERROR: data/processed/outcomes.parquet missing", file=sys.stderr)
        return 1
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    reg_ids = {m["model_id"] for m in reg["models"]}
    current_tags = {m["model_id"]: m.get("coverage_quality", "low") for m in reg["models"]}
    total_q = pd.read_parquet(PROC / "questions.parquet")["question_global_id"].nunique()

    base = pd.read_parquet(PROC / "outcomes.parquet")[OUTCOME_COLUMNS]
    print(f"[base] original outcomes: {len(base):,} rows, "
          f"{base['question_global_id'].nunique()} questions, {base['model_id'].nunique()} models")

    harvested = []
    for f in sorted(HARVEST_DIR.glob("outcomes_*.parquet")):
        if f.name == "candidates_pool.parquet":
            continue
        harvested.append(pd.read_parquet(f))
    harv = pd.concat(harvested, ignore_index=True) if harvested else pd.DataFrame(columns=OUTCOME_COLUMNS)
    print(f"[harvest] {len(harv):,} rows across {harv['model_id'].nunique()} harvested model names")

    # Split harvested into (maps-to-registry) and (candidates for expansion).
    mapped_rows, candidate_rows = [], []
    for _, r in harv.iterrows():
        targets = MODEL_MAP.get(r["model_id"])
        if targets:
            for reg_id in targets:
                d = {c: r[c] for c in OUTCOME_COLUMNS}
                d["model_id"] = reg_id
                mapped_rows.append(d)
        else:
            candidate_rows.append(r)
    mapped = pd.DataFrame(mapped_rows, columns=OUTCOME_COLUMNS) if mapped_rows else pd.DataFrame(columns=OUTCOME_COLUMNS)
    candidates = pd.DataFrame(candidate_rows) if candidate_rows else pd.DataFrame()
    print(f"[map] harvested rows mapped to registry models: {len(mapped):,} "
          f"({mapped['model_id'].nunique() if len(mapped) else 0} registry models)")
    print(f"[map] candidate rows (non-registry models, for pool expansion): {len(candidates):,}")

    # Merge + dedupe (a (question, model) should be unique; keep first defensively).
    merged = pd.concat([base, mapped], ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates(subset=["question_global_id", "model_id"], keep="first")
    print(f"[merge] {before:,} -> {len(merged):,} rows after dedupe; "
          f"{merged['question_global_id'].nunique():,} questions, {merged['model_id'].nunique()} models")

    # Per-model coverage + proposed coverage_quality.
    print(f"\n=== proposed coverage_quality (denominator = {total_q:,} corpus questions) ===")
    cov = merged.groupby("model_id")["question_global_id"].nunique()
    print(f"{'model_id':38} {'questions':>9} {'cover%':>7}  {'current':>7} -> {'proposed'}")
    print("-" * 80)
    proposed = {}
    for mid in sorted(reg_ids):
        n = int(cov.get(mid, 0))
        frac = n / total_q
        newq = _coverage_quality(frac)
        proposed[mid] = newq
        cur = current_tags.get(mid, "low")
        flag = "  <-- CHANGED" if newq != cur else ""
        print(f"{mid:38} {n:9d} {frac*100:6.1f}%  {cur:>7} -> {newq}{flag}")

    # Write artifacts (non-destructive).
    PROC.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(PROC / "outcomes_merged.parquet", index=False)
    print(f"\nwrote {len(merged):,} rows -> {PROC/'outcomes_merged.parquet'}")
    if len(candidates):
        candidates.to_parquet(HARVEST_DIR / "candidates_pool.parquet", index=False)
        csum = candidates.groupby("model_id").agg(q=("question_global_id", "nunique"),
                                                   mean=("outcome", "mean")).sort_values("q", ascending=False)
        print(f"wrote {len(candidates):,} candidate rows -> {HARVEST_DIR/'candidates_pool.parquet'} "
              f"({candidates['model_id'].nunique()} models for Phase-2 expansion)")
        print("  top expansion candidates by coverage:")
        for mid, row in csum.head(10).iterrows():
            print(f"    {mid:42} {int(row['q']):5d} q  mean {row['mean']:.2f}")

    (PROC / "proposed_coverage_quality.json").write_text(json.dumps(proposed, indent=2), encoding="utf-8")
    print(f"\nwrote proposed re-tags -> {PROC/'proposed_coverage_quality.json'}")
    print("\nNOT modified: outcomes.parquet, registry.json (apply is a separate reviewed step).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
