"""
scripts/layer3/generate_mmlu_outcomes.py  (WORKING TOOL — not committed yet)

Option-1 grounding (DETERMINISTIC, judge-free): generate per-model outcomes on
MMLU-Pro for the ACTIVE free models that currently have ZERO benchmark coverage
(gpt-oss-120b/20b, qwen3-32b, llama-4-scout). Those 4 ride pure prior on every
academic query, which is why the prior path defaults to gpt-oss-120b; the 3 older
free models (llama-8b/70b, qwen-72b) already have all 12,032 MMLU-Pro outcomes.

For each (model, MMLU-Pro question): ask the model the multiple-choice question →
parse its chosen letter → grade by EXACT-MATCH against the dataset's gold answer.
No LLM judge anywhere — the answer key is ground truth, so this is free of judge
bias and never touches the hot path.

The 12,032 MMLU-Pro questions are already in questions.parquet + embedded in
Qdrant, so generated rows join straight onto existing kNN neighbours — no
re-embed needed. Merge into the live corpus is a separate reviewed step
(merge_generated_outcomes.py --src mmlu_det).

Design (inherited from generate_outcomes.py):
  • $0 (free Groq APIs), rate-limit-bound. Deterministic grading means HALF the
    calls of the judge path (no grader call).
  • RESUMABLE + INCREMENTAL: writes the parquet after every question; skips
    (model, qid) pairs already present — safe to kill/relaunch.
  • NON-DESTRUCTIVE: writes only to harvested/outcomes_mmlu_det.parquet.

Usage:
  python scripts/layer3/generate_mmlu_outcomes.py --limit 5            # smoke
  python scripts/layer3/generate_mmlu_outcomes.py --limit 1000
  python scripts/layer3/generate_mmlu_outcomes.py --limit 1000 --modality math
  python scripts/layer3/generate_mmlu_outcomes.py --models gpt-oss-120b-groq,qwen3-32b-groq
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

# Collect ALL Groq keys (GROQ_API_KEY, GROQ_API_KEY_2, ...) so a token-heavy batch
# can spread load across separate free accounts and stop tripping one key's
# per-minute / per-day limits. Round-robined per call.
_GROQ_KEYS: list[str] = []
for _k in list(os.environ) + list(_ENVVALS):
    if _k.upper().startswith("GROQ_API_KEY"):
        _v = os.environ.get(_k) or _ENVVALS.get(_k)
        if _v and _v.strip() not in _GROQ_KEYS:
            _GROQ_KEYS.append(_v.strip())
_groq_cycle = itertools.cycle(_GROQ_KEYS) if _GROQ_KEYS else None

import litellm  # noqa: E402
import pandas as pd  # noqa: E402

litellm.drop_params = True

from src.layer0_model_infra.routing.registry_loader import get_layer3_registry  # noqa: E402

OUT = REPO_ROOT / "data" / "processed" / "harvested" / "outcomes_mmlu_det.parquet"
QUESTIONS_PARQUET = REPO_ROOT / "data" / "processed" / "questions.parquet"
SOURCE_URL = "generated:mmlu-pro-exact-match-v1"

# The 4 active free models with ZERO MMLU-Pro coverage (benchmark_coverage_pct 0.0).
# The 3 older free models already have all 12,032 rows, so we don't re-run them.
DEFAULT_MODELS = [
    "gpt-oss-120b-groq",
    "gpt-oss-20b-groq",
    "qwen3-32b-groq",
    "llama-4-scout-17b-groq",
]

_REG = get_layer3_registry()


def _llname(mid: str) -> str:
    return _REG.get(mid).litellm_model_name


# --- throttle: Groq free tier is ~30 rpm/key. With N keys we pace N x faster. ---
_MIN_INTERVAL = max(0.8, 2.2 / max(1, len(_GROQ_KEYS)))
_last = [0.0]
_stats = {"calls": 0, "rate_limited": 0, "no_answer": 0}


def _throttle() -> None:
    dt = time.monotonic() - _last[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last[0] = time.monotonic()


def _complete(model: str, prompt: str, *, temperature: float, max_tokens: int, retries: int = 5) -> str | None:
    for attempt in range(retries):
        _throttle()
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
            print(f"    err {model.split('/')[-1]}: {str(exc)[:70]}", flush=True)
            time.sleep(4.0 * (attempt + 1))
    return None


_LETTERS = "ABCDEFGHIJ"

_MCQ_PROMPT = """Answer this multiple-choice question. Think step by step if needed, then commit to one option.

{question}

Options:
{options}

Finish your reply with a line in EXACTLY this format and nothing after it:
Answer: <letter>"""


def _gold_letter(row: dict) -> str | None:
    """Gold answer as a letter A-J. Prefer the explicit 'answer' letter; fall
    back to deriving it from 'answer_index'."""
    ans = row.get("answer")
    if isinstance(ans, str):
        a = ans.strip().upper()
        if len(a) == 1 and a in _LETTERS:
            return a
    idx = row.get("answer_index")
    if idx is not None:
        try:
            i = int(idx)
        except (TypeError, ValueError):
            return None
        if 0 <= i < len(_LETTERS):
            return _LETTERS[i]
    return None


def _extract_letter(text: str, n_options: int) -> str | None:
    """Parse the model's chosen option letter. Takes the LAST 'Answer: X' so a
    reasoning preamble (gpt-oss / qwen3 thinking) doesn't fool it; falls back to
    the last standalone letter token in range."""
    if not text:
        return None
    valid = _LETTERS[:max(1, min(n_options, len(_LETTERS)))]
    m = re.findall(rf"answer\s*[:\-]?\s*\(?\*{{0,2}}\s*([{valid}])\b", text, flags=re.I)
    if m:
        return m[-1].upper()
    toks = re.findall(rf"(?<![A-Za-z])([{valid}])(?![A-Za-z])", text)
    if toks:
        return toks[-1].upper()
    return None


def _load_questions(limit: int | None, modality: str | None) -> list[dict]:
    """Load MMLU-Pro (gold answers) and keep only questions that are already in
    our corpus (so generated outcomes join to an embedded kNN neighbour).
    Optionally filter by our modality tag (text/math/code). Deterministic sample."""
    from datasets import load_dataset

    # which mmlu_pro ids are in our corpus, and their modality
    qdf = pd.read_parquet(QUESTIONS_PARQUET, columns=["question_global_id", "benchmark_source", "modality"])
    qdf = qdf[qdf.benchmark_source == "mmlu_pro"]
    if modality:
        qdf = qdf[qdf.modality == modality]
    # local int id -> modality
    corpus_ids = {
        gid.split(":", 1)[1]: mod
        for gid, mod in zip(qdf.question_global_id, qdf.modality)
    }

    ds = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
    rows: list[dict] = []
    for r in ds:
        qid_local = r.get("question_id")
        if qid_local is None:
            qid_local = r.get("id")
        if qid_local is None:
            continue
        key = str(qid_local)
        if key not in corpus_ids:
            continue
        options = r.get("options") or []
        gold = _gold_letter(r)
        if not options or gold is None:
            continue
        rows.append({
            "qid": f"mmlu_pro:{key}",
            "question": r.get("question") or "",
            "options": list(options),
            "gold": gold,
            "modality": corpus_ids[key],
        })

    # deterministic, category-spread sample: sort by qid then stride to the limit
    rows.sort(key=lambda x: x["qid"])
    if limit and limit < len(rows):
        step = len(rows) / limit
        rows = [rows[int(i * step)] for i in range(limit)]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000, help="number of MMLU-Pro questions")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--modality", default=None, choices=[None, "text", "math", "code"])
    ap.add_argument("--gen-tokens", type=int, default=2048)
    ap.add_argument("--show-first", action="store_true", help="print the first prompt+reply (smoke)")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    tasks = _load_questions(args.limit, args.modality)
    if not tasks:
        print("no MMLU-Pro questions matched (check modality / corpus)", file=sys.stderr)
        return 1

    # resume
    rows: list[dict] = []
    done: set[tuple[str, str]] = set()
    if OUT.exists():
        rows = pd.read_parquet(OUT).to_dict("records")
        done = {(r["model_id"], r["question_global_id"]) for r in rows}

    print(f"grounding {len(models)} models x {len(tasks)} MMLU-Pro questions "
          f"(modality={args.modality or 'all'}; {len(done)} pairs already done); "
          f"{len(_GROQ_KEYS)} Groq key(s); throttle {_MIN_INTERVAL:.1f}s -> {OUT.name}", flush=True)

    now = datetime.now(timezone.utc)
    correct = {m: 0 for m in models}
    seen = {m: 0 for m in models}
    for ti, t in enumerate(tasks):
        qid = t["qid"]
        opts = "\n".join(f"{_LETTERS[i]}. {o}" for i, o in enumerate(t["options"]))
        prompt = _MCQ_PROMPT.format(question=t["question"], options=opts)
        wrote = False
        for mid in models:
            if (mid, qid) in done:
                continue
            reply = _complete(_llname(mid), prompt, temperature=0.0, max_tokens=args.gen_tokens)
            if reply is None:
                continue  # call failed after retries; retry on next run
            if args.show_first and ti == 0:
                print(f"\n--- PROMPT ({mid}) ---\n{prompt}\n--- REPLY ---\n{reply[:1200]}\n--- GOLD={t['gold']} ---\n", flush=True)
            pick = _extract_letter(reply, len(t["options"]))
            if pick is None:
                # likely a truncated reasoning chain, not a real wrong answer —
                # skip (don't mark done) so a later run with more tokens retries it
                _stats["no_answer"] += 1
                print(f"[{ti+1}/{len(tasks)}] {mid:24} {qid:16} pick=None (no parse; retry next run)", flush=True)
                continue
            score = 1.0 if pick == t["gold"] else 0.0
            rows.append({
                "question_global_id": qid, "model_id": mid, "outcome": float(score),
                "source_url": SOURCE_URL, "ingested_at": now,
            })
            done.add((mid, qid))
            seen[mid] += 1
            correct[mid] += int(score == 1.0)
            wrote = True
            print(f"[{ti+1}/{len(tasks)}] {mid:24} {qid:16} pick={pick} gold={t['gold']} "
                  f"{'OK' if score else '..'}", flush=True)
        if wrote:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_parquet(OUT, index=False)

    print(f"\nDONE rows={len(rows)} calls={_stats['calls']} "
          f"rate_limited={_stats['rate_limited']} no_answer_parsed={_stats['no_answer']}", flush=True)
    print("per-model accuracy this run (sanity check - is the grader sane?):", flush=True)
    for m in models:
        if seen[m]:
            print(f"  {m:24} {correct[m]}/{seen[m]} = {correct[m]/seen[m]:.3f}", flush=True)
    print(f"-> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
