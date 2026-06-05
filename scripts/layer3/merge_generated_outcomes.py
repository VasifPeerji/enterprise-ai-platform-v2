"""
scripts/layer3/merge_generated_outcomes.py  (WORKING TOOL — not committed yet)

Fold generated conversational outcomes (harvested/outcomes_generated.parquet,
produced by generate_outcomes.py) into the live outcomes.parquet that the kNN
router reads via the OutcomeStore. Non-destructive: backs up first, dedups by
(question_global_id, model_id) keeping the freshly generated value.

No coverage re-tag needed: since the low-coverage-uses-real-outcomes change
(commit 0740e2e), a low-coverage model uses its neighbour outcomes whenever it
has >= min_outcomes of them, so simply having the rows present is enough.

Run:  python scripts/layer3/merge_generated_outcomes.py
      python scripts/layer3/merge_generated_outcomes.py --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = REPO_ROOT / "data" / "processed" / "outcomes.parquet"
GEN = REPO_ROOT / "data" / "processed" / "harvested" / "outcomes_generated.parquet"
KEY = ["question_global_id", "model_id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not GEN.exists():
        print(f"no generated outcomes at {GEN}", file=sys.stderr)
        return 1
    gen = pd.read_parquet(GEN)
    live = pd.read_parquet(LIVE) if LIVE.exists() else pd.DataFrame(columns=gen.columns)

    # align columns to the live schema (drop any harvest-only provenance cols)
    gen = gen[[c for c in live.columns if c in gen.columns]] if len(live.columns) else gen

    before = len(live)
    new_pairs = gen.merge(live[KEY].drop_duplicates(), on=KEY, how="left", indicator=True)
    n_new = int((new_pairs["_merge"] == "left_only").sum())

    combined = pd.concat([live, gen], ignore_index=True)
    # keep the generated value on conflicts (it's the freshly graded one): keep last
    combined = combined.drop_duplicates(subset=KEY, keep="last").reset_index(drop=True)

    gen_q = gen["question_global_id"].nunique()
    gen_m = sorted(gen["model_id"].unique())
    print(f"live outcomes : {before} rows")
    print(f"generated     : {len(gen)} rows | {gen_q} questions | models={gen_m}")
    print(f"net NEW (model,question) pairs to add: {n_new}")
    print(f"merged total  : {len(combined)} rows")

    if args.dry_run:
        print("\n[dry-run] nothing written")
        return 0

    if LIVE.exists():
        bak = LIVE.with_suffix(".parquet.genmerge.bak")
        shutil.copy2(LIVE, bak)
        print(f"backed up live -> {bak.name}")
    combined.to_parquet(LIVE, index=False)
    print(f"wrote {len(combined)} rows -> {LIVE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
