"""
scripts/layer3/generate_validation_outcomes.py

Fill data/processed/validation_outcomes.parquet for the 650 HELD-OUT validation
queries (arena_hard / mt_bench / livebench) so the correctness gate can score the
router's picks against baselines.

These queries have NO checklists (unlike WildBench), so grading is REFERENCE-FREE:
a strong free judge rates each answer 0-1 on how well it addresses the request.
The absolute scale need not be calibrated for the gate -- the router and every
baseline are scored by the SAME judge, so only the relative lift matters.

Mirrors generate_outcomes.py: $0 (free APIs), rate-limit-bound, RESUMABLE +
INCREMENTAL (writes after each query, skips done (model, qid) pairs), generation
on Groq across keys, grading on Cerebras (higher TPM) with a self-grade swap so a
model never grades its own answer.

Usage:
  python scripts/layer3/generate_validation_outcomes.py --limit 50
  python scripts/layer3/generate_validation_outcomes.py --models llama-3.1-8b-instant-groq,gpt-oss-120b-groq
"""
from __future__ import annotations

import argparse
import itertools
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


def _collect_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    for k in list(os.environ) + list(_ENVVALS):
        if k.upper().startswith(prefix):
            v = os.environ.get(k) or _ENVVALS.get(k)
            if v and v.strip() not in keys:
                keys.append(v.strip())
    return keys


_GROQ_KEYS = _collect_keys("GROQ_API_KEY")
_CEREBRAS_KEYS = _collect_keys("CEREBRAS_API_KEY")
_groq_cycle = itertools.cycle(_GROQ_KEYS) if _GROQ_KEYS else None
_cerebras_cycle = itertools.cycle(_CEREBRAS_KEYS) if _CEREBRAS_KEYS else None

import litellm  # noqa: E402
import pandas as pd  # noqa: E402

litellm.drop_params = True

from src.layer0_model_infra.routing.registry_loader import get_layer3_registry  # noqa: E402

VALIDATION = REPO_ROOT / "data" / "processed" / "validation_set.parquet"
OUT = REPO_ROOT / "data" / "processed" / "validation_outcomes.parquet"
SOURCE_URL = "generated:rubric-judge-v1"

# The active, executable free models the router actually picks among (so every
# router pick on the validation set is scoreable). Keyless premium picks
# (claude / gpt-4o) execute via the free fallback, which is also in this set.
DEFAULT_MODELS = [
    "llama-3.1-8b-instant-groq",       # the cheap baseline
    "gpt-oss-20b-groq",
    "qwen3-32b-groq",
    "llama-4-scout-17b-groq",
    "llama-3.3-70b-versatile-groq",
    "qwen-2.5-72b-huggingface",
    "gpt-oss-120b-groq",               # the strong baseline
    "gemini-2.5-flash",
]

JUDGE_LLNAME = "cerebras/gpt-oss-120b"
JUDGE_ALT_LLNAME = "groq/llama-3.3-70b-versatile"
SELF_GRADE_MODEL_ID = "gpt-oss-120b-groq"   # generated model whose weights == the judge

_REG = get_layer3_registry()
def _llname(mid: str) -> str:
    return _REG.get(mid).litellm_model_name

_MIN_INTERVAL = max(0.8, 3.0 / max(1, len(_GROQ_KEYS)))
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
        kwargs = {}
        if model.startswith("cerebras/") and _cerebras_cycle is not None:
            kwargs["api_key"] = next(_cerebras_cycle)
        elif model.startswith("groq/") and _groq_cycle is not None:
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
            print(f"    err {model.split('/')[-1]}: {str(exc)[:70]}", flush=True)
            time.sleep(4.0 * (attempt + 1))
    return None


# Reference-free rubric: no checklist or gold answer exists for these queries, so
# the judge scores overall quality on a 0-10 integer scale. Internally consistent
# across models (same judge), which is all the gate needs.
_RUBRIC_PROMPT = """You are grading how well an AI ANSWER addresses a USER REQUEST.

USER REQUEST:
{q}

AI ANSWER:
{a}

Rate the answer's overall quality on a 0 to 10 integer scale, judging correctness,
completeness, and how well it follows what was asked.
  0  = wrong, empty, refuses, or irrelevant
  5  = partially correct or noticeably incomplete
  10 = fully correct, complete, and well-targeted
Output ONLY the integer score (0-10), nothing else."""


def _grade(judge_llname: str, q: str, a: str) -> float | None:
    if not a:
        return 0.0
    out = _complete(judge_llname, _RUBRIC_PROMPT.format(q=q[:6000], a=a[:5000]),
                    temperature=0.0, max_tokens=8)
    if out is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", out)
    if not m:
        _stats["parse_fail"] += 1
        return None
    score = max(0.0, min(10.0, float(m.group(0))))
    return score / 10.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap queries (debug)")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--gen-tokens", type=int, default=1200)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    vs = pd.read_parquet(VALIDATION)[["question_global_id", "question_text"]]
    if args.limit:
        vs = vs.iloc[: args.limit]
    tasks = list(vs.itertuples(index=False, name=None))  # (qid, text)

    rows: list[dict] = []
    done: set[tuple[str, str]] = set()
    if OUT.exists():
        existing = pd.read_parquet(OUT)
        rows = existing.to_dict("records")
        done = {(r["model_id"], r["question_global_id"]) for r in rows}

    print(f"validation grounding {len(models)} models x {len(tasks)} queries "
          f"({len(done)} pairs done); {len(_GROQ_KEYS)} Groq + {len(_CEREBRAS_KEYS)} Cerebras key(s), "
          f"judge={JUDGE_LLNAME}, throttle {_MIN_INTERVAL:.1f}s -> {OUT.name}", flush=True)

    now = datetime.now(timezone.utc)
    for ti, (qid, text) in enumerate(tasks):
        wrote = False
        for mid in models:
            if (mid, qid) in done:
                continue
            ans = _complete(_llname(mid), str(text), temperature=0.7, max_tokens=args.gen_tokens)
            judge = JUDGE_ALT_LLNAME if mid == SELF_GRADE_MODEL_ID else JUDGE_LLNAME
            score = _grade(judge, str(text), ans or "") if ans is not None else None
            if score is not None:
                rows.append({
                    "question_global_id": qid, "model_id": mid, "outcome": float(score),
                    "source_url": SOURCE_URL, "ingested_at": now,
                })
                done.add((mid, qid))
                wrote = True
            print(f"[{ti+1}/{len(tasks)}] {mid:30} {str(qid)[:24]:24} "
                  f"score={None if score is None else round(score, 3)}", flush=True)
        if wrote:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_parquet(OUT, index=False)

    print(f"\nDONE. rows={len(rows)} models={len(models)} "
          f"calls={_stats['calls']} rate_limited={_stats['rate_limited']} "
          f"parse_fail={_stats['parse_fail']} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
