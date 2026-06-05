"""
scripts/layer3/generate_outcomes.py  (WORKING TOOL — not committed yet)

Online-loop sub-project A: GENERATE per-model outcomes on WildBench conversational
tasks, graded by the validated checklist-judge, to ground conversational routing
for our own free models. (Harvest can't cover them — they're too new/closed.)

For each (free model, WildBench task): generate an answer (free API) → grade it
against WildBench's per-task checklist with a strong free judge → write
(question_global_id, model_id, outcome) to harvested/outcomes_generated.parquet.

Design:
  • $0 (free APIs), rate-limit-bound. Global throttle keeps under Groq's 30 rpm.
  • RESUMABLE + INCREMENTAL: writes the parquet after every task, and skips
    (model, qid) pairs already present — safe to kill/relaunch a long run.
  • Judge = gpt-oss-120b; when grading gpt-oss-120b's OWN answers, swap to
    llama-3.3-70b so a model never grades itself (self-preference bias).
  • Non-destructive: never touches outcomes.parquet; a separate reviewed merge does.

Usage:
  python scripts/layer3/generate_outcomes.py --limit 50
  python scripts/layer3/generate_outcomes.py --limit 50 --models gpt-oss-120b-groq,llama-3.1-8b-instant-groq
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import dotenv_values
_ENVVALS = dotenv_values(REPO_ROOT / ".env")
for _k, _v in _ENVVALS.items():
    if _k.endswith("_API_KEY") and _v:
        os.environ.setdefault(_k, _v.strip())

# Collect ALL Groq keys (GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ...) so a
# token-heavy batch can spread load across separate free accounts and stop
# tripping one key's per-minute (TPM/RPM) limits. With N keys the per-call key is
# round-robined and the throttle loosens; with 1 key it stays slow-but-safe.
import itertools  # noqa: E402
_GROQ_KEYS: list[str] = []
for _k in list(os.environ) + list(_ENVVALS):
    if _k.upper().startswith("GROQ_API_KEY"):  # GROQ_API_KEY, GROQ_API_KEY2/3/4, GROQ_API_KEY_2, ...
        _v = os.environ.get(_k) or _ENVVALS.get(_k)
        if _v and _v.strip() not in _GROQ_KEYS:
            _GROQ_KEYS.append(_v.strip())
_groq_cycle = itertools.cycle(_GROQ_KEYS) if _GROQ_KEYS else None

import litellm  # noqa: E402
import pandas as pd  # noqa: E402

litellm.drop_params = True

from src.layer0_model_infra.routing.registry_loader import get_layer3_registry  # noqa: E402

OUT = REPO_ROOT / "data" / "processed" / "harvested" / "outcomes_generated.parquet"
SOURCE_URL = "generated:checklist-judge-v1"

# Free models to ground, fastest first (all Groq → share the 30 rpm key).
DEFAULT_MODELS = [
    "llama-3.1-8b-instant-groq",
    "llama-3.3-70b-versatile-groq",
    "gpt-oss-120b-groq",
    "gpt-oss-20b-groq",
    "qwen3-32b-groq",
    "llama-4-scout-17b-groq",
]
JUDGE_ID = "llama-3.3-70b-versatile-groq"   # primary judge: dense 70B, far higher Groq rpm/TPM than the 120B MoE preview
JUDGE_ALT = "gpt-oss-120b-groq"             # used only when grading the primary judge's own answers

_REG = get_layer3_registry()
def _llname(mid: str) -> str:
    return _REG.get(mid).litellm_model_name

# --- global throttle: pace each Groq key to ~one call / 5s (TPM-safe for the
#     token-heavy judge prompts); loosen as more keys are added. 1 key -> 5s,
#     3 keys -> ~1.7s, 6 keys -> ~0.8s. ---
_MIN_INTERVAL = max(0.8, 5.0 / max(1, len(_GROQ_KEYS)))
_last = [0.0]
_stats = {"calls": 0, "rate_limited": 0, "parse_fail": 0}


def _throttle() -> None:
    dt = time.monotonic() - _last[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last[0] = time.monotonic()


def _complete(model: str, prompt: str, *, temperature: float, max_tokens: int, retries: int = 5) -> str | None:
    for attempt in range(retries):
        _throttle()
        # Round-robin Groq keys so the load spreads across accounts.
        kwargs = {}
        if model.startswith("groq/") and _groq_cycle is not None:
            kwargs["api_key"] = next(_groq_cycle)
        try:
            _stats["calls"] += 1
            r = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature, max_tokens=max_tokens, **kwargs,
            )
            return (r.choices[0].message.content or "").strip()
        except litellm.RateLimitError:
            _stats["rate_limited"] += 1
            time.sleep(6.0 * (attempt + 1))
        except Exception as exc:
            print(f"    err {model.split('/')[-1]}: {str(exc)[:60]}", flush=True)
            time.sleep(4.0 * (attempt + 1))
    return None


_JUDGE_PROMPT = """You grade an AI ANSWER against a CHECKLIST of yes/no criteria.

USER REQUEST:
{q}

AI ANSWER:
{a}

CHECKLIST ({n} items — judge each independently):
{c}

Output ONLY a JSON array of exactly {n} booleans (true = the answer satisfies that
item), in order. No explanation — just the array, e.g. [true, false, true]."""


def _grade(judge_llname: str, q: str, a: str, checklist: list[str]) -> float | None:
    if not a:
        return 0.0
    n = len(checklist)
    items = "\n".join(f"{i+1}. {c}" for i, c in enumerate(checklist))
    out = _complete(judge_llname, _JUDGE_PROMPT.format(q=q[:6000], a=a[:5000], c=items, n=n),
                    temperature=0.0, max_tokens=1000)
    if out is None:
        return None
    cands: list[list[bool]] = []
    for grp in re.findall(r"\[[^\[\]]*\]", out):
        try:
            v = json.loads(grp.lower())
        except Exception:
            continue
        if isinstance(v, list) and v and all(isinstance(x, (bool, int)) for x in v):
            cands.append([bool(x) for x in v])
    if not cands:
        _stats["parse_fail"] += 1
        return None
    best = min(cands, key=lambda c: abs(len(c) - n))
    return sum(best) / len(best)


def _load_tasks(limit: int | None):
    from datasets import load_dataset
    ds = load_dataset("allenai/WildBench", "v2", split="test")
    rows = []
    for r in ds:
        ci = r.get("conversation_input") or []
        text = ci[0].get("content", "") if (ci and isinstance(ci[0], dict)) else ""
        ck = r.get("checklist") or []
        if text.strip() and ck:
            rows.append({"id": r.get("id") or r.get("session_id"), "q": text, "checklist": list(ck)})
    rows.sort(key=lambda x: x["id"])
    return rows[:limit] if limit else rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--gen-tokens", type=int, default=1500)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    tasks = _load_tasks(args.limit)

    # resume: load existing rows, skip done (model, qid) pairs
    rows: list[dict] = []
    done: set[tuple[str, str]] = set()
    if OUT.exists():
        rows = pd.read_parquet(OUT).to_dict("records")
        done = {(r["model_id"], r["question_global_id"]) for r in rows}
    print(f"grounding {len(models)} models x {len(tasks)} tasks "
          f"({len(done)} pairs already done); {len(_GROQ_KEYS)} Groq key(s), "
          f"throttle {_MIN_INTERVAL:.1f}s -> {OUT.name}", flush=True)

    now = datetime.now(timezone.utc)
    for ti, t in enumerate(tasks):
        qid = f"wildbench:{t['id']}"
        wrote_this_task = False
        for mid in models:
            if (mid, qid) in done:
                continue
            ans = _complete(_llname(mid), t["q"], temperature=0.7, max_tokens=args.gen_tokens)
            judge_id = JUDGE_ALT if mid == JUDGE_ID else JUDGE_ID
            score = _grade(_llname(judge_id), t["q"], ans or "", t["checklist"]) if ans is not None else None
            if score is not None:
                rows.append({
                    "question_global_id": qid, "model_id": mid, "outcome": float(score),
                    "source_url": SOURCE_URL, "ingested_at": now,
                })
                done.add((mid, qid))
                wrote_this_task = True
            print(f"[{ti+1}/{len(tasks)}] {mid:30} {t['id'][:12]} "
                  f"score={None if score is None else round(score, 3)}", flush=True)
        if wrote_this_task:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_parquet(OUT, index=False)

    print(f"\nDONE. rows={len(rows)} models={len(models)} "
          f"calls={_stats['calls']} rate_limited={_stats['rate_limited']} "
          f"parse_fail={_stats['parse_fail']} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
