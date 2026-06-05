"""
scripts/layer3/_grader_bakeoff.py  (WORKING TOOL — not committed yet)

Validate a FREE "how good was this answer?" grader for the Layer 3 online-loop
outcome generation (LAYER3_ONLINE_LOOP_PLAN.md, sub-project A).

Grader under test: CHECKLIST-JUDGE — a strong free model grades an answer against
WildBench's per-task yes/no checklist; outcome = fraction of items passed.

Validation method: CAPABILITY ORDERING (not inter-grader agreement). We grade a
known-STRONG model (llama-3.3-70b) and a known-WEAK model (llama-3.1-8b) on the
SAME WildBench tasks. A trustworthy grader must score strong > weak with a clean
margin and few per-task inversions. If it can't separate a 70B from an 8B, it's
too noisy to ground the corpus with.

Judge = gpt-oss-120b (strongest free, different family → no self-preference bias
on the two llama answers being graded).

$0 (free Groq APIs). Non-destructive (writes only an artifacts/ JSON report).
Keys are OS-env-only for the app, so we inject *_API_KEY from .env ourselves.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import os
from dotenv import dotenv_values
for _k, _v in dotenv_values(REPO_ROOT / ".env").items():
    if _k.endswith("_API_KEY") and _v:
        os.environ.setdefault(_k, _v.strip())

import litellm  # noqa: E402
litellm.drop_params = True

STRONG = ("strong", "groq/llama-3.3-70b-versatile")   # llama-3.3-70b-versatile-groq
WEAK = ("weak", "groq/llama-3.1-8b-instant")          # llama-3.1-8b-instant-groq
JUDGE = "groq/openai/gpt-oss-120b"                     # gpt-oss-120b-groq (neutral)

ARTIFACT = REPO_ROOT / "artifacts" / "layer3" / "grader_bakeoff.json"

# --- global throttle: stay under Groq free tier 30 rpm across ALL calls ---
_MIN_INTERVAL = 2.2
_last_call = [0.0]
_stats = {"calls": 0, "rate_limited": 0, "judge_parse_fail": 0}


def _throttle() -> None:
    dt = time.monotonic() - _last_call[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call[0] = time.monotonic()


def _complete(model: str, prompt: str, *, temperature: float, max_tokens: int,
              retries: int = 5) -> str | None:
    for attempt in range(retries):
        _throttle()
        try:
            _stats["calls"] += 1
            r = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (r.choices[0].message.content or "").strip()
        except litellm.RateLimitError:
            _stats["rate_limited"] += 1
            time.sleep(6.0 * (attempt + 1))
        except Exception as exc:
            print(f"    [{model.split('/')[-1]}] {type(exc).__name__}: {str(exc)[:70]} "
                  f"retry {attempt+1}", flush=True)
            time.sleep(4.0 * (attempt + 1))
    return None


_JUDGE_PROMPT = """You grade an AI ANSWER against a CHECKLIST of yes/no criteria.

USER REQUEST:
{question}

AI ANSWER:
{answer}

CHECKLIST ({n} items — judge each independently):
{checklist}

Output ONLY a JSON array of exactly {n} booleans (true = the answer satisfies that
item, false = it does not), in order. No explanation, no keys — just the array,
e.g. [true, false, true]."""


def _grade(question: str, answer: str, checklist: list[str]) -> float | None:
    if not answer:
        return 0.0
    n = len(checklist)
    items = "\n".join(f"{i+1}. {c}" for i, c in enumerate(checklist))
    out = _complete(
        JUDGE,
        _JUDGE_PROMPT.format(question=question[:6000], answer=answer[:7000], checklist=items, n=n),
        temperature=0.0, max_tokens=2200,
    )
    if out is None:
        return None
    # Find every [...] group, parse the booleans, keep the one closest to n items.
    cands: list[list[bool]] = []
    for grp in re.findall(r"\[[^\[\]]*\]", out):
        try:
            v = json.loads(grp.lower())
        except Exception:
            continue
        if isinstance(v, list) and v and all(isinstance(x, (bool, int)) for x in v):
            cands.append([bool(x) for x in v])
    if not cands:
        _stats["judge_parse_fail"] += 1
        return None
    best = min(cands, key=lambda c: abs(len(c) - n))
    return sum(best) / len(best)


def _sample_tasks(per_tag: int):
    from datasets import load_dataset
    ds = load_dataset("allenai/WildBench", "v2", split="test")
    by_tag: dict[str, list] = {}
    for row in ds:
        tag = row.get("primary_tag", "?")
        ci = row.get("conversation_input") or []
        text = ci[0].get("content", "") if (ci and isinstance(ci[0], dict)) else ""
        ck = row.get("checklist") or []
        if not text.strip() or not ck:
            continue
        by_tag.setdefault(tag, []).append({
            "id": row.get("id") or row.get("session_id"),
            "tag": tag, "question": text, "checklist": list(ck),
        })
    tasks = []
    for tag in sorted(by_tag):
        for t in sorted(by_tag[tag], key=lambda x: x["id"])[:per_tag]:
            tasks.append(t)
    return tasks


def _summary(results):
    paired = [r for r in results
              if r.get("strong_score") is not None and r.get("weak_score") is not None]
    n = len(paired)
    if not n:
        return None
    s_mean = sum(r["strong_score"] for r in paired) / n
    w_mean = sum(r["weak_score"] for r in paired) / n
    return {
        "paired": n, "of": len(results),
        "strong_mean": round(s_mean, 3), "weak_mean": round(w_mean, 3),
        "separation": round(s_mean - w_mean, 3),
        "strong_wins": sum(1 for r in paired if r["strong_score"] > r["weak_score"]),
        "ties": sum(1 for r in paired if r["strong_score"] == r["weak_score"]),
        "inversions": sum(1 for r in paired if r["strong_score"] < r["weak_score"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tag", type=int, default=2)
    ap.add_argument("--max-gen-tokens", type=int, default=2048)
    args = ap.parse_args()

    tasks = _sample_tasks(args.per_tag)
    print(f"validation slice: {len(tasks)} WildBench tasks "
          f"({len(set(t['tag'] for t in tasks))} tags), judge={JUDGE.split('/')[-1]}, "
          f"gen_max_tokens={args.max_gen_tokens}\n", flush=True)

    results = []
    for i, t in enumerate(tasks):
        print(f"[{i+1}/{len(tasks)}] {t['tag']:22} {t['id']}  (checklist={len(t['checklist'])})", flush=True)
        row = {"id": t["id"], "tag": t["tag"], "n_checklist": len(t["checklist"])}
        for label, model in (STRONG, WEAK):
            ans = _complete(model, t["question"], temperature=0.7, max_tokens=args.max_gen_tokens)
            score = _grade(t["question"], ans or "", t["checklist"]) if ans is not None else None
            row[f"{label}_score"] = score
            row[f"{label}_ans_chars"] = len(ans or "")
            print(f"      {label:6} score={score if score is None else round(score,3)}  "
                  f"(ans {len(ans or '')} chars)", flush=True)
        results.append(row)
        # incremental write so a kill doesn't lose data
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps({
            "judge": JUDGE, "strong": STRONG[1], "weak": WEAK[1],
            "stats": _stats, "summary": _summary(results), "results": results,
        }, indent=2), encoding="utf-8")

    s = _summary(results)
    print("\n================ GRADER VALIDATION (capability ordering) ================")
    if s:
        print(f"  paired tasks graded : {s['paired']}/{s['of']}")
        print(f"  STRONG (llama-3.3-70b) mean checklist pass : {s['strong_mean']}")
        print(f"  WEAK   (llama-3.1-8b)  mean checklist pass : {s['weak_mean']}")
        print(f"  separation (strong - weak)                 : {s['separation']:+}")
        print(f"  per-task: strong_wins={s['strong_wins']}  ties={s['ties']}  INVERSIONS={s['inversions']}")
    else:
        print("  no paired scores")
    print(f"  api calls={_stats['calls']} rate_limited={_stats['rate_limited']} "
          f"judge_parse_fail={_stats['judge_parse_fail']}")
    print(f"\nwrote {ARTIFACT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
