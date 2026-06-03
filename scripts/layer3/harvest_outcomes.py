"""
📁 File: scripts/layer3/harvest_outcomes.py
Layer: Layer 0 — Layer 3 redesign (Batch: corpus expansion / Phase 1 harvest)
Purpose: Harvest PER-QUESTION, PER-MODEL outcomes from PUBLIC sources and append
         them to the Layer 3 outcome corpus — lifting coverage far past the
         original 394 LiveBench-only questions, at $0 and with no paid LLM calls.

Design contract (from the corpus-expansion research, Phase 1):
  • NO paid LLM calls. Everything here is harvested from public, already-graded
    (or locally-gradable) sources.
  • NON-DESTRUCTIVE. Each source writes its own parquet under data/processed/
    harvested/; nothing touches the existing outcomes.parquet until a separate,
    reviewed merge step. So a bad harvest can never corrupt the live corpus.
  • Keyed to the EXISTING corpus ids so the join is exact:
        swe_bench_verified:<instance_id>   (e.g. swe_bench_verified:astropy__astropy-12907)
        livebench:<64-hex question_id>
        mmlu_pro:<index>
  • Harvest BROADLY (record every model found, raw name) and keep a separate
    raw_model -> registry model_id map. Pool membership (which models the router
    actually uses) is a later, curated decision (Phase 2) — harvest just gathers
    the evidence.

Sources (this file grows one harvester at a time, each independently verified):
  • SWE-bench  — SWE-bench/experiments repo, per-submission results.json
                 ('resolved' arrays of instance_ids).  [IMPLEMENTED]
  • LiveBench  — livebench/model_answer (raw answers) + local ground-truth grading. [TODO]
  • Open-LLM   — HuggingFace Open-LLM-Leaderboard per-model 'details' datasets
                 (per-example MMLU-Pro / GPQA / MATH correctness).               [TODO]

Output schema (matches outcomes.parquet so the merge is a straight concat):
    question_global_id : str
    model_id           : str   (registry model_id where mapped, else raw harvested name)
    outcome            : float  0.0-1.0
    source_url         : str
    ingested_at        : timestamp (UTC)
Plus harvest-only provenance columns (dropped at merge time):
    raw_model          : str   the source's own model/submission name
    n_submissions      : int   how many source records backed this (model,question)
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

QUESTIONS_PARQUET = REPO_ROOT / "data" / "processed" / "questions.parquet"
HARVEST_DIR = REPO_ROOT / "data" / "processed" / "harvested"

OUTCOME_COLUMNS = ["question_global_id", "model_id", "outcome", "source_url", "ingested_at"]

_HTTP = requests.Session()
_HTTP.headers.update({"User-Agent": "enterprise-ai-platform-harvest/1.0"})


def _now():
    return datetime.now(timezone.utc)


def _get_json(url: str, timeout: float = 30.0, retries: int = 3, headers: dict | None = None):
    """GET with small retry/backoff. Returns parsed JSON or raises."""
    last = None
    for attempt in range(retries):
        try:
            r = _HTTP.get(url, timeout=timeout, headers=headers)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # network blip — back off and retry
            last = str(exc)[:120]
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


def _hf_token() -> str | None:
    """HuggingFace token from env or .env (needed for the gated Open-LLM details)."""
    import os
    for k in ("HUGGINGFACE_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"):
        v = os.getenv(k)
        if v:
            return v.strip()
    envf = REPO_ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip()
            if key in ("HUGGINGFACE_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ============================================================================
# Raw model-name normalisation
# ============================================================================
# SWE-bench submissions are named "<date>_<scaffold>_<model>" (e.g.
# "20250522_tools_claude-4-sonnet", "20231010_rag_gpt35"). The resolution rate
# depends on BOTH the base model and the agent scaffold, so this is a
# capability proxy, not a pure model score (we aggregate per model as
# "resolved by its best submission" and keep n_submissions for auditing).
#
# Ordered list — most specific FIRST. The first substring that appears in the
# lowercased submission name wins. Canonical ids align with registry.json where
# the model is (or plausibly will be) in the pool; others use descriptive names
# so Phase-2 pool selection can see what public data exists.

# Needles are SEPARATOR-COLLAPSED (no -, _, ., space) so "claude-3-5-sonnet",
# "claude3.5sonnet" and "claude_3_5_sonnet" all match the same needle. Ordered
# MOST-SPECIFIC FIRST (longest within a family) so "gpt4o" wins over "gpt4" and
# "claude35sonnet" wins over "claude2"/"claude3".
_MODEL_PATTERNS: list[tuple[str, str]] = [
    # Anthropic
    ("claudeopus4", "claude-opus-4"), ("claude4opus", "claude-opus-4"),
    ("claudesonnet4", "claude-sonnet-4"), ("claude4sonnet", "claude-sonnet-4"),
    ("claude37sonnet", "claude-3-7-sonnet"),
    ("claude35sonnet", "claude-3-5-sonnet"), ("claude35haiku", "claude-3-5-haiku"),
    ("claude3opus", "claude-3-opus"), ("claude3sonnet", "claude-3-sonnet"),
    ("claude3haiku", "claude-3-haiku"), ("claude2", "claude-2"),
    # OpenAI (gpt4omini before gpt4o before gpt4; o-series after)
    ("gpt4omini", "gpt-4o-mini"), ("gpt4o", "gpt-4o"),
    ("gpt4turbo", "gpt-4-turbo"), ("gpt41106", "gpt-4-turbo"), ("gpt40125", "gpt-4-turbo"),
    ("gpt45", "gpt-4.5"), ("gpt41", "gpt-4.1"), ("gpt5", "gpt-5"),
    ("gpt4", "gpt-4"), ("gpt35", "gpt-3.5-turbo"), ("gpt3", "gpt-3.5-turbo"),
    ("o4mini", "openai-o4-mini"), ("o3mini", "openai-o3-mini"), ("o1mini", "openai-o1-mini"),
    ("o3", "openai-o3"), ("o1", "openai-o1"),
    # DeepSeek
    ("deepseekv3", "deepseek-v3"), ("deepseekchat", "deepseek-v3"),
    ("deepseekr1", "deepseek-r1"), ("deepseekcoder", "deepseek-coder"), ("deepseek", "deepseek"),
    # Qwen (coder + 3 + 2.5 before bare qwen)
    ("qwen25coder", "qwen-2.5-coder"), ("qwen3coder", "qwen3-coder"),
    ("qwen3", "qwen3"), ("qwen25", "qwen-2.5"), ("qwen2", "qwen-2"), ("qwen", "qwen"),
    # Llama / Gemini / others
    ("llama3370b", "llama-3.3-70b"), ("llama33", "llama-3.3-70b"), ("llama4", "llama-4"),
    ("swellama", "swe-llama"),
    ("gemini25", "gemini-2.5"), ("gemini15", "gemini-1.5"), ("gemini", "gemini"),
    ("mixtral", "mixtral"), ("mistral", "mistral"), ("gemma", "gemma"),
    ("doubao", "doubao"), ("glm", "glm"), ("kimi", "kimi"), ("grok", "grok"),
    ("nemotron", "nemotron"), ("devstral", "devstral"),
]


def _collapse(s: str) -> str:
    """Lowercase + strip separators so model matching is hyphen/dot/underscore-insensitive."""
    return re.sub(r"[-_.\s]+", "", s.lower())


def normalize_model(submission_name: str) -> str | None:
    """Map a source submission name to a canonical model id, or None if unknown."""
    c = _collapse(submission_name)
    for needle, canonical in _MODEL_PATTERNS:
        if needle in c:
            return canonical
    return None


# ============================================================================
# SWE-bench harvester
# ============================================================================

SWEBENCH_API = "https://api.github.com/repos/SWE-bench/experiments/contents/evaluation/verified"
SWEBENCH_RAW = "https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified/{name}/results/results.json"
SWEBENCH_SOURCE = "https://github.com/SWE-bench/experiments"


def harvest_swebench(our_instance_ids: set[str], limit: int | None = None) -> pd.DataFrame:
    """Harvest per-(model, instance) resolved/unresolved over the SWE-bench
    Verified split, restricted to instances present in our corpus.

    For each canonical model we take the UNION of instances resolved across all
    of that model's submissions (best-scaffold capability), then emit one row
    per (model, our-instance): outcome 1.0 if in that union else 0.0.
    """
    print(f"[swebench] listing submissions: {SWEBENCH_API}")
    listing = _get_json(SWEBENCH_API)
    subs = [x["name"] for x in listing if x.get("type") == "dir"]
    if limit:
        subs = subs[:limit]
    print(f"[swebench] {len(subs)} submissions")

    # model -> set of resolved instance ids (union over its submissions)
    model_resolved: dict[str, set[str]] = {}
    model_subs: dict[str, int] = {}
    raw_name: dict[str, str] = {}
    unmapped: list[str] = []
    fetched = skipped = 0

    for i, name in enumerate(subs):
        model = normalize_model(name)
        if model is None:
            unmapped.append(name)
            continue
        try:
            j = _get_json(SWEBENCH_RAW.format(name=name), timeout=25.0)
        except Exception as exc:
            print(f"  skip {name}: {exc}")
            skipped += 1
            continue
        resolved = j.get("resolved") or j.get("resolved_ids") or []
        # keep only instances that are in OUR corpus
        hit = {r for r in resolved if r in our_instance_ids}
        model_resolved.setdefault(model, set()).update(hit)
        model_subs[model] = model_subs.get(model, 0) + 1
        raw_name.setdefault(model, name)
        fetched += 1
        if (i + 1) % 25 == 0:
            print(f"  ...{i + 1}/{len(subs)} fetched")

    print(f"[swebench] fetched={fetched} skipped={skipped} unmapped_submissions={len(unmapped)}")
    print(f"[swebench] mapped models ({len(model_resolved)}):")
    for m in sorted(model_resolved, key=lambda k: -len(model_resolved[k])):
        print(f"    {m:22} resolved {len(model_resolved[m]):3d}/{len(our_instance_ids)}  "
              f"(from {model_subs[m]} submission(s))")
    if unmapped:
        print(f"[swebench] unmapped (no coverage emitted): {unmapped[:8]}{' ...' if len(unmapped) > 8 else ''}")

    # Emit full coverage: every (mapped model, our instance) gets a 0/1 outcome.
    now = _now()
    rows = []
    for model, resolved in model_resolved.items():
        for inst in our_instance_ids:
            rows.append({
                "question_global_id": f"swe_bench_verified:{inst}",
                "model_id": model,
                "outcome": 1.0 if inst in resolved else 0.0,
                "source_url": SWEBENCH_SOURCE,
                "ingested_at": now,
                "raw_model": raw_name[model],
                "n_submissions": model_subs[model],
            })
    return pd.DataFrame(rows)


# ============================================================================
# Open-LLM-Leaderboard MMLU-Pro harvester (per-example acc, single-shot)
# ============================================================================
# The leaderboard's per-model 'details' datasets are GATED (the HF token must
# have accepted access on the Hub). Each model's leaderboard_mmlu_pro config has
# one row per MMLU-Pro question with doc.question_id (== our mmlu_pro:<id> key)
# and acc (0/1). Clean key join, single-shot correctness (no agent-scaffold
# confound, unlike SWE-bench), 1:1 with our 12,032 MMLU-Pro questions.

# registry model_id -> Open-LLM-Leaderboard 'details' dataset repo.
MMLU_PRO_MODELS: dict[str, str] = {
    "llama-3.3-70b-versatile-groq": "open-llm-leaderboard/meta-llama__Llama-3.3-70B-Instruct-details",
    "llama-3.1-8b-instant-groq":    "open-llm-leaderboard/meta-llama__Llama-3.1-8B-Instruct-details",
    "qwen-2.5-72b-huggingface":     "open-llm-leaderboard/Qwen__Qwen2.5-72B-Instruct-details",
    "qwen-2.5-coder-32b-openrouter-free": "open-llm-leaderboard/Qwen__Qwen2.5-Coder-32B-Instruct-details",
    "qwen-qwq-32b-groq":            "open-llm-leaderboard/Qwen__QwQ-32B-Preview-details",
    "gemma2-9b-it-groq":            "open-llm-leaderboard/google__gemma-2-9b-it-details",
    "gemma-2-27b-openrouter-free":  "open-llm-leaderboard/google__gemma-2-27b-it-details",
    "deepseek-r1-distill-llama-70b-groq": "open-llm-leaderboard/deepseek-ai__DeepSeek-R1-Distill-Llama-70B-details",
    # --- pool-expansion additions (strong, groundable, servable) ---
    "nemotron-70b-huggingface": "open-llm-leaderboard/nvidia__Llama-3.1-Nemotron-70B-Instruct-HF-details",
    "qwen-2.5-32b-huggingface": "open-llm-leaderboard/Qwen__Qwen2.5-32B-Instruct-details",
    "mistral-small-2409-openrouter": "open-llm-leaderboard/mistralai__Mistral-Small-Instruct-2409-details",
}
OPENLLM_SOURCE = "https://huggingface.co/open-llm-leaderboard"


def _mmlu_pro_parquet_url(repo: str, token: str) -> str | None:
    """Parquet URL for the model's leaderboard_mmlu_pro config (prefers 'latest')."""
    try:
        j = _get_json(f"https://datasets-server.huggingface.co/parquet?dataset={repo}",
                      timeout=45.0, headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:
        print(f"  [{repo}] parquet listing failed: {str(exc)[:90]}")
        return None
    files = [f for f in j.get("parquet_files", []) if "mmlu_pro" in f.get("config", "").lower()]
    if not files:
        return None
    latest = [f for f in files if f.get("split") == "latest"] or files
    return latest[0]["url"]


def harvest_openllm_mmlu_pro(our_qids: set[str], models: dict[str, str], token: str) -> pd.DataFrame:
    """Harvest single-shot MMLU-Pro correctness (acc 0/1) per (model, question),
    joining on doc.question_id == our mmlu_pro:<id> key."""
    import io
    import pyarrow.parquet as pq

    auth = {"Authorization": f"Bearer {token}"}
    now = _now()
    rows = []
    for reg_id, repo in models.items():
        url = _mmlu_pro_parquet_url(repo, token)
        if not url:
            print(f"  [{reg_id}] no mmlu_pro config — SKIP ({repo})")
            continue
        try:
            raw = _HTTP.get(url, headers=auth, timeout=240).content
            tbl = pq.read_table(io.BytesIO(raw), columns=["doc", "acc"])
        except Exception as exc:
            print(f"  [{reg_id}] download/read failed: {str(exc)[:90]} — SKIP")
            continue
        docs = tbl.column("doc").to_pylist()
        accs = tbl.column("acc").to_pylist()
        n = 0
        raw_model = repo.split("/")[-1].replace("-details", "")
        for d, a in zip(docs, accs):
            gid = f"mmlu_pro:{d.get('question_id')}"
            if gid in our_qids:
                rows.append({
                    "question_global_id": gid, "model_id": reg_id, "outcome": float(a),
                    "source_url": OPENLLM_SOURCE, "ingested_at": now,
                    "raw_model": raw_model, "n_submissions": 1,
                })
                n += 1
        mean_acc = (sum(accs) / len(accs)) if accs else 0.0
        print(f"  [{reg_id}] {n}/{len(our_qids)} mmlu_pro outcomes  (mean acc {mean_acc:.3f})  <- {raw_model}")
    return pd.DataFrame(rows)


# ============================================================================
# LiveBench model_judgment harvester (pre-scored)
# ============================================================================
# livebench/model_judgment is ungated and already SCORED (score 0/1, mostly
# ground-truth/programmatic). ~195 models over a rotating ~494-question release;
# 394 of those overlap our corpus. We keep the RAW LiveBench model name as the
# model_id (no normalisation) to preserve all variants distinctly; harmonising
# to registry ids happens at the Phase-2 merge.

LIVEBENCH_JUDGMENT = "livebench/model_judgment"
LIVEBENCH_SOURCE = "https://huggingface.co/datasets/livebench/model_judgment"


def harvest_livebench(our_qids: set[str], token: str | None) -> pd.DataFrame:
    """Harvest pre-scored per-(model, question) LiveBench outcomes (score 0/1),
    restricted to questions in our corpus. Aggregates duplicates (turns/tasks)
    by mean."""
    import io
    import pyarrow.parquet as pq

    auth = {"Authorization": f"Bearer {token}"} if token else None
    try:
        pf = _get_json(f"https://datasets-server.huggingface.co/parquet?dataset={LIVEBENCH_JUDGMENT}",
                       timeout=45.0, headers=auth)["parquet_files"]
    except Exception as exc:
        print(f"  livebench parquet listing failed: {str(exc)[:90]}")
        return pd.DataFrame()
    now = _now()
    agg: dict[tuple[str, str], list[float]] = {}
    for f in pf:
        raw = _HTTP.get(f["url"], headers=auth, timeout=120).content
        tbl = pq.read_table(io.BytesIO(raw), columns=["question_id", "model", "score"])
        d = tbl.to_pydict()
        for qid, model, score in zip(d["question_id"], d["model"], d["score"]):
            gid = f"livebench:{qid}"
            if gid not in our_qids:
                continue
            try:
                agg.setdefault((gid, model), []).append(float(score))
            except (TypeError, ValueError):
                continue
    rows = [{
        "question_global_id": gid, "model_id": model,
        "outcome": sum(scs) / len(scs),
        "source_url": LIVEBENCH_SOURCE, "ingested_at": now,
        "raw_model": model, "n_submissions": len(scs),
    } for (gid, model), scs in agg.items()]
    df = pd.DataFrame(rows)
    if not df.empty:
        print(f"  livebench: {df['question_global_id'].nunique()} questions x "
              f"{df['model_id'].nunique()} models = {len(df)} outcomes")
    return df


# ============================================================================
# Driver
# ============================================================================

def load_our_ids(prefix: str) -> set[str]:
    """Load the bare ids for one benchmark_source from questions.parquet,
    stripping the 'prefix:' part of question_global_id."""
    q = pd.read_parquet(QUESTIONS_PARQUET, columns=["question_global_id"])
    ids = q.loc[q["question_global_id"].str.startswith(prefix + ":"), "question_global_id"]
    return {x.split(":", 1)[1] for x in ids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["swebench", "openllm", "livebench"], default="swebench",
                    help="swebench=SWE-bench resolved; openllm=MMLU-Pro acc; livebench=model_judgment score")
    ap.add_argument("--limit", type=int, default=None, help="cap submissions (debug)")
    ap.add_argument("--models", default=None, help="openllm: comma-separated registry ids to limit harvest to")
    ap.add_argument("--out", default=None, help="override output filename (written under harvested/)")
    ap.add_argument("--dry-run", action="store_true", help="compute + report, do NOT write parquet")
    args = ap.parse_args()

    if not QUESTIONS_PARQUET.exists():
        print(f"ERROR: {QUESTIONS_PARQUET} not found", file=sys.stderr)
        return 1

    if args.source == "swebench":
        ours = load_our_ids("swe_bench_verified")
        print(f"[corpus] {len(ours)} swe_bench_verified questions in our corpus")
        df = harvest_swebench(ours, limit=args.limit)
        out = HARVEST_DIR / "outcomes_swebench.parquet"
    elif args.source == "openllm":
        tok = _hf_token()
        if not tok:
            print("ERROR: no HuggingFace token (HUGGINGFACE_API_KEY) — needed for the "
                  "gated Open-LLM details datasets", file=sys.stderr)
            return 1
        ours = {f"mmlu_pro:{i}" for i in load_our_ids("mmlu_pro")}
        print(f"[corpus] {len(ours)} mmlu_pro questions in our corpus")
        models = MMLU_PRO_MODELS
        if args.models:
            wanted = {m.strip() for m in args.models.split(",")}
            models = {k: v for k, v in MMLU_PRO_MODELS.items() if k in wanted}
        df = harvest_openllm_mmlu_pro(ours, models, tok)
        out = HARVEST_DIR / (args.out or "outcomes_mmlu_pro.parquet")
    elif args.source == "livebench":
        ours = {f"livebench:{i}" for i in load_our_ids("livebench")}
        print(f"[corpus] {len(ours)} livebench questions in our corpus")
        df = harvest_livebench(ours, _hf_token())
        out = HARVEST_DIR / "outcomes_livebench.parquet"

    # ---- summary ----
    if df.empty:
        print("\nNo outcomes harvested.")
        return 0
    n_models = df["model_id"].nunique()
    n_q = df["question_global_id"].nunique()
    n_pos = int((df["outcome"] > 0).sum())
    print(f"\n=== HARVEST SUMMARY ({args.source}) ===")
    print(f"  rows={len(df):,}  models={n_models}  questions_covered={n_q}  resolved(1.0)={n_pos}")
    print(f"  per-model resolve rate (of {n_q} questions):")
    rate = df.groupby("model_id")["outcome"].mean().sort_values(ascending=False)
    for m, r in rate.items():
        print(f"    {m:22} {r*100:5.1f}%")

    if args.dry_run:
        print("\n[dry-run] not writing parquet")
        return 0
    HARVEST_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\nwrote {len(df):,} rows -> {out}  (NON-destructive; merge is a separate reviewed step)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
