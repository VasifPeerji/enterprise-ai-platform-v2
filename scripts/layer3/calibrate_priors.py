"""
📁 File: scripts/layer3/calibrate_priors.py
Layer: Layer 0 — Layer 3 (offline calibration of the aggregate-score priors)
Purpose: Measure how far the published-benchmark PRIORS sit above the MEASURED
         per-model outcomes, and emit a multiplicative "realism" correction that
         debiases prior_quality() toward observed reality.

Why this exists
---------------
The kNN router predicts a model's quality on a query. When a query has no
per-question neighbour outcomes for a model (the low-coverage / off-distribution
case), the prediction falls back to a modality-weighted average of that model's
*published* benchmark scores (aggregate_scores.prior_quality). Those published
numbers are academic-benchmark-scale and run systematically HIGH relative to the
quality the same models actually deliver on real/conversational traffic — by
+0.18 to +0.45 across every model we have ground truth for. For a router that
picks the "cheapest model clearing a quality floor", an inflated prior lets a
weak, cheap model clear a floor it should not → under-routing (the failure mode
that silently degrades answers).

This script joins outcomes.parquet ⋈ questions.parquet (DuckDB; no encoder, no
GPU), computes the measured mean per (model) and per (model, modality), and the
multiplicative factor  measured / prior  that would map the prior down onto
reality. Factors are clamped to [FACTOR_MIN, 1.0] (a prior is never inflated,
and never cut beyond the floor where our evidence runs out). Models with too
little ground truth fall back to a single global factor.

Usage
-----
    python scripts/layer3/calibrate_priors.py            # analysis only (prints)
    python scripts/layer3/calibrate_priors.py --write    # also write _realism

--write injects a "_realism" block into model_aggregate_scores.json which
aggregate_scores.prior_quality() reads and applies. Idempotent; re-runnable.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Windows consoles default to cp1252, which can't encode the arrows/symbols below.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

import duckdb  # noqa: E402

from src.layer0_model_infra.routing.aggregate_scores import AggregateScores  # noqa: E402

SCORES_PATH = REPO / "src/layer0_model_infra/data/model_aggregate_scores.json"
# Derived correction lives in its own sidecar so the hand-curated scores file is
# never rewritten. aggregate_scores.py loads this next to the scores file.
REALISM_PATH = REPO / "src/layer0_model_infra/data/model_prior_realism.json"
REGISTRY_PATH = REPO / "src/layer0_model_infra/data/registry.json"
ENV_PATH = REPO / ".env"
OUTCOMES = (REPO / "data/processed/outcomes.parquet").as_posix()
QUESTIONS = (REPO / "data/processed/questions.parquet").as_posix()

# Trust thresholds: a factor needs at least this many graded outcomes behind it.
MIN_N_MODEL = 30
MIN_N_MODALITY = 50
# A prior is never inflated (cap 1.0) and never cut below FACTOR_MIN — beyond
# that haircut we'd be extrapolating past our evidence.
FACTOR_MIN, FACTOR_MAX = 0.40, 1.00
# Modalities the routing path actually uses the prior for.
MODALITIES = ("text", "code", "math", "vision", "multimodal")


def _present_env_vars() -> set[str]:
    """Best-effort: which provider keys have a non-empty value in .env (so we can
    label which models are currently active). Activation is informational here."""
    present: set[str] = set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if v.strip().strip('"').strip("'"):
                present.add(k.strip())
    return present


def _clamp(x: float) -> float:
    return max(FACTOR_MIN, min(FACTOR_MAX, x))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="inject _realism into the scores JSON")
    args = ap.parse_args()

    agg = AggregateScores(str(SCORES_PATH))
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    reg_models = {m["model_id"]: m for m in registry["models"]}
    env_present = _present_env_vars()

    con = duckdb.connect()
    out_cols = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{OUTCOMES}')").fetchall()]
    q_cols = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{QUESTIONS}')").fetchall()]
    print(f"outcomes.parquet columns : {out_cols}")
    print(f"questions.parquet columns: {q_cols}\n")

    # measured mean + count per (model, modality)
    mm_rows = con.execute(f"""
        SELECT o.model_id AS model_id, q.modality AS modality,
               avg(o.outcome) AS measured, count(*) AS n
        FROM read_parquet('{OUTCOMES}') o
        JOIN read_parquet('{QUESTIONS}') q USING (question_global_id)
        GROUP BY 1, 2
    """).fetchall()
    by_mm: dict[str, dict[str, tuple[float, int]]] = {}
    for mid, modality, measured, n in mm_rows:
        by_mm.setdefault(mid, {})[modality] = (float(measured), int(n))

    # measured mean + count per model (all outcomes)
    ov_rows = con.execute(f"""
        SELECT model_id, avg(outcome) AS measured, count(*) AS n
        FROM read_parquet('{OUTCOMES}') GROUP BY 1
    """).fetchall()
    overall = {mid: (float(m), int(n)) for mid, m, n in ov_rows}

    # ---- per-model table + factor computation -------------------------------
    print(f"{'model':32} {'act':3} {'cov':5} {'prior_t':>8} {'measured':>9} "
          f"{'n':>6} {'raw':>6} {'factor':>7}")
    print("-" * 86)
    realism_models: dict[str, dict] = {}
    raw_ratios: list[float] = []
    for mid, m in reg_models.items():
        prior_t = agg.prior_quality(mid, "text")
        ov = overall.get(mid)
        measured = ov[0] if ov else None
        n = ov[1] if ov else 0
        active = "yes" if m.get("required_env_var") in env_present else "no"
        cov = m.get("coverage_quality", "?")

        raw = factor = None
        if measured is not None and n >= MIN_N_MODEL and prior_t > 0:
            raw = measured / prior_t
            raw_ratios.append(raw)
            factor = _clamp(raw)
            entry: dict = {"overall_factor": round(factor, 4), "n": n}
            # per-modality refinement where we have enough graded outcomes
            by_modality = {}
            for modality, (mmeasured, mn) in (by_mm.get(mid) or {}).items():
                mprior = agg.prior_quality(mid, modality)
                if mn >= MIN_N_MODALITY and mprior > 0:
                    by_modality[modality] = round(_clamp(mmeasured / mprior), 4)
            if by_modality:
                entry["by_modality"] = by_modality
            realism_models[mid] = entry

        print(f"{mid:32} {active:3} {cov:5} {prior_t:8.3f} "
              f"{(f'{measured:.3f}' if measured is not None else '—'):>9} "
              f"{n:6d} {(f'{raw:.3f}' if raw is not None else '—'):>6} "
              f"{(f'{factor:.3f}' if factor is not None else '—'):>7}")

    global_factor = round(_clamp(statistics.median(raw_ratios)), 4) if raw_ratios else 1.0
    print("-" * 86)
    print(f"models with trusted factor : {len(realism_models)}")
    print(f"raw measured/prior ratios  : "
          f"min {min(raw_ratios):.3f}  median {statistics.median(raw_ratios):.3f}  "
          f"max {max(raw_ratios):.3f}" if raw_ratios else "  (none)")
    print(f"GLOBAL median factor       : {global_factor}  "
          f"(informational; unmeasured models keep their prior unchanged — "
          f"uncertainty about them is handled by the LCB selector, not a fabricated haircut)")

    # ---- effect preview: prior before/after for the default text floor 0.65 --
    print("\nEffect on the 0.65 text floor (prior path, query modality=text):")
    print(f"{'model':32} {'prior':>7} {'debiased':>9} {'clears 0.65?':>13}")
    print("-" * 64)
    for mid, m in reg_models.items():
        prior_t = agg.prior_quality(mid, "text")
        f = realism_models.get(mid, {}).get("overall_factor", 1.0)  # unmeasured -> unchanged
        deb = min(1.0, prior_t * f)
        before = "Y" if prior_t >= 0.65 else "n"
        after = "Y" if deb >= 0.65 else "n"
        flag = f"{before}->{after}" + ("  (de-rated)" if before == "Y" and after == "n" else "")
        print(f"{mid:32} {prior_t:7.3f} {deb:9.3f} {flag:>13}")

    if args.write:
        realism = {
            "_meta": {
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "method": "factor = clamp(measured_mean / prior, "
                          f"[{FACTOR_MIN}, {FACTOR_MAX}]); priors are never inflated",
                "source": "data/processed/outcomes.parquet JOIN questions.parquet",
                "min_n_model": MIN_N_MODEL,
                "min_n_modality": MIN_N_MODALITY,
                "note": "Loaded by aggregate_scores.prior_quality() to debias the "
                        "prior-fallback path ONLY; the kNN-grounded path (real "
                        "neighbour outcomes) is untouched. Models without a "
                        "model-specific factor here are left UNCHANGED (factor 1.0); "
                        "global_factor is informational, not auto-applied.",
                "regenerate": "python scripts/layer3/calibrate_priors.py --write",
            },
            "global_factor": global_factor,
            "models": realism_models,
        }
        REALISM_PATH.write_text(
            json.dumps(realism, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        print(f"\n[WROTE] realism sidecar -> {REALISM_PATH}")
    else:
        print("\n(analysis only -- re-run with --write to persist the realism sidecar)")


if __name__ == "__main__":
    main()
