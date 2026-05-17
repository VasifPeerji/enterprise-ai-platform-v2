"""
📁 File: scripts/routing_benchmark_diff.py
Purpose: Compare two routing benchmark runs and report what changed.

Workflow:
  1. Run baseline:   python scripts/routing_benchmark.py
  2. Save snapshot:  python scripts/routing_benchmark_diff.py --snapshot baseline
  3. Make code fixes
  4. Re-run:         python scripts/routing_benchmark.py
  5. Compare:        python scripts/routing_benchmark_diff.py --compare baseline

Output:
  - Aggregate-metric delta table (accuracy, under/over, tier)
  - Newly-passing queries (regressions fixed)
  - Newly-failing queries (regressions introduced) — flagged loudly
  - Verdict-flip summary per query
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
LATEST_PATH = ARTIFACTS_DIR / "routing_benchmark_results.json"
SNAPSHOTS_DIR = ARTIFACTS_DIR / "routing_benchmark_snapshots"


BAND_ORDER = ["trivial", "simple", "moderate", "complex", "expert"]


def _load(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("results", [])


def snapshot(name: str) -> None:
    """Save the current routing_benchmark_results.json under a name."""
    if not LATEST_PATH.exists():
        print(f"ERROR: no benchmark results to snapshot at {LATEST_PATH}")
        sys.exit(1)
    SNAPSHOTS_DIR.mkdir(exist_ok=True, parents=True)
    target = SNAPSHOTS_DIR / f"{name}.json"
    shutil.copy(LATEST_PATH, target)
    print(f"Saved snapshot: {target}")


def _summarise(results: list[dict]) -> dict:
    n = len(results)
    if not n:
        return {"total": 0}
    correct = sum(1 for r in results if r.get("match"))
    under = sum(1 for r in results if r.get("direction") == "under")
    over = sum(1 for r in results if r.get("direction") == "over")
    return {
        "total": n,
        "correct": correct,
        "accuracy": correct / n * 100,
        "under": under,
        "under_pct": under / n * 100,
        "over": over,
        "over_pct": over / n * 100,
    }


def compare(baseline_name: str) -> None:
    """Diff the latest run against a saved snapshot."""
    baseline_path = SNAPSHOTS_DIR / f"{baseline_name}.json"
    if not baseline_path.exists():
        print(f"ERROR: snapshot '{baseline_name}' not found at {baseline_path}")
        print("Available snapshots:")
        if SNAPSHOTS_DIR.exists():
            for p in SNAPSHOTS_DIR.glob("*.json"):
                print(f"  - {p.stem}")
        sys.exit(1)
    if not LATEST_PATH.exists():
        print(f"ERROR: no current run at {LATEST_PATH}")
        sys.exit(1)

    baseline = _load(baseline_path)
    current = _load(LATEST_PATH)

    base_by_query = {r["query"]: r for r in baseline}
    curr_by_query = {r["query"]: r for r in current}
    all_queries = sorted(set(base_by_query.keys()) | set(curr_by_query.keys()))

    base_summary = _summarise(baseline)
    curr_summary = _summarise(current)

    # ── Aggregate delta table ────────────────────────────────────────────
    print("=" * 70)
    print(f"  ROUTING BENCHMARK DIFF: {baseline_name} → current")
    print("=" * 70)
    print()
    print(f"  {'metric':<22} {'baseline':>14} {'current':>14} {'delta':>14}")
    print(f"  {'-'*22} {'-'*14} {'-'*14} {'-'*14}")
    for label, key, fmt in [
        ("Total queries",        "total",     "{:>14d}"),
        ("Correct (exact)",      "correct",   "{:>14d}"),
        ("Accuracy %",           "accuracy",  "{:>14.1f}"),
        ("Under-routing %",      "under_pct", "{:>14.1f}"),
        ("Over-routing %",       "over_pct",  "{:>14.1f}"),
    ]:
        b = base_summary.get(key, 0)
        c = curr_summary.get(key, 0)
        delta = c - b
        delta_marker = ""
        if key in {"accuracy", "correct"}:
            delta_marker = "  [GOOD]" if delta > 0 else ("  [BAD]" if delta < 0 else "")
        elif key in {"under_pct", "over_pct"}:
            delta_marker = "  [GOOD]" if delta < 0 else ("  [BAD]" if delta > 0 else "")
        print(
            f"  {label:<22} "
            f"{fmt.format(b)} "
            f"{fmt.format(c)} "
            f"{fmt.format(delta).strip():>14}"
            f"{delta_marker}"
        )

    # ── Per-query verdict flips ─────────────────────────────────────────
    fixed: list[dict] = []        # was wrong → now right
    broken: list[dict] = []       # was right → now wrong
    drift_better: list[dict] = [] # both wrong, but distance shrank
    drift_worse: list[dict] = []  # both wrong, but distance grew
    swapped_band: list[dict] = [] # band changed but match unchanged

    for q in all_queries:
        b = base_by_query.get(q)
        c = curr_by_query.get(q)
        if b is None or c is None:
            continue
        b_match = b.get("match", False)
        c_match = c.get("match", False)
        b_band = b.get("actual_band", "?")
        c_band = c.get("actual_band", "?")
        b_dist = abs(b.get("distance", 0))
        c_dist = abs(c.get("distance", 0))

        if not b_match and c_match:
            fixed.append({"query": q, "expected": b.get("expected_band"), "before": b_band, "after": c_band})
        elif b_match and not c_match:
            broken.append({"query": q, "expected": b.get("expected_band"), "before": b_band, "after": c_band})
        elif not b_match and not c_match:
            if c_dist < b_dist:
                drift_better.append({"query": q, "expected": b.get("expected_band"), "before": b_band, "after": c_band})
            elif c_dist > b_dist:
                drift_worse.append({"query": q, "expected": b.get("expected_band"), "before": b_band, "after": c_band})
        elif b_match and c_match and b_band != c_band:
            swapped_band.append({"query": q, "expected": b.get("expected_band"), "before": b_band, "after": c_band})

    def _print_group(title: str, items: list[dict], severity: str) -> None:
        print(f"\n  {title} ({len(items)})")
        if not items:
            return
        for x in items[:25]:
            print(
                f"    [{severity}] expected={x['expected']:<8s} "
                f"{x['before']:<8s} -> {x['after']:<8s} | {x['query'][:80]}"
            )
        if len(items) > 25:
            print(f"    ... and {len(items) - 25} more")

    _print_group("FIXED  (regression resolved)",            fixed,         "GOOD")
    _print_group("BROKEN (regression introduced)",          broken,        "BAD ")
    _print_group("Drift toward correct (still off)",         drift_better,  "...")
    _print_group("Drift away from correct (worse)",          drift_worse,   "BAD ")
    _print_group("Verdict band swapped (still correct)",     swapped_band,  "INFO")

    # ── Hard guard: any newly broken queries? ─────────────────────────────
    if broken:
        print("\n  WARNING: This change BROKE previously-correct queries.")
        print("  Investigate before declaring the fix successful.")
    elif fixed:
        print(f"\n  Net improvement: {len(fixed)} queries fixed, 0 broken.")
    else:
        print("\n  No verdict changes.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", metavar="NAME", help="Save the current run as a snapshot")
    parser.add_argument("--compare",  metavar="NAME", help="Diff current run against a saved snapshot")
    parser.add_argument("--list",     action="store_true", help="List saved snapshots")
    args = parser.parse_args()

    if args.list:
        if not SNAPSHOTS_DIR.exists():
            print("(no snapshots yet)")
            return
        for p in sorted(SNAPSHOTS_DIR.glob("*.json")):
            data = _load(p)
            s = _summarise(data)
            print(f"  {p.stem:<24} n={s['total']:>3d}  acc={s.get('accuracy', 0):.1f}%  "
                  f"under={s.get('under_pct', 0):.1f}%  over={s.get('over_pct', 0):.1f}%")
        return

    if args.snapshot:
        snapshot(args.snapshot)
        return
    if args.compare:
        compare(args.compare)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
