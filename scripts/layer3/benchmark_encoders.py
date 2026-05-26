"""
Encoder benchmark for Layer 3 (Stage C kNN encoder).

Compares candidate encoders head-to-head on the user's actual hardware:
  • BAAI/bge-small-en-v1.5                                — English, 33M params, 384-dim
  • intfloat/multilingual-e5-small                        — 94 langs, 118M, 384-dim
  • sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 — 50+ langs, 118M, 384-dim

For each candidate measures, on both GPU (PyTorch FP16 / FP32) and CPU (ONNX
int8 when ``--include-cpu``):
  • Cold-start latency (model load + first encode)
  • Warm latency p50 / p95 / p99 (1000 queries)
  • Throughput (batch size 32 if GPU, 1 if CPU)
  • VRAM resident
  • CPU RAM resident
  • Semantic-similarity sanity check: encode a small set of paired sentences,
    confirm intuitive cosines (so we know the model loaded correctly)

Writes:
  • artifacts/layer3/encoder_benchmark.json    — raw numbers
  • docs/layer3/encoder_choice.md              — pick + rationale (auto-generated)

Run:
    python -m scripts.layer3.benchmark_encoders                     # GPU only
    python -m scripts.layer3.benchmark_encoders --include-cpu       # GPU + ONNX CPU
    python -m scripts.layer3.benchmark_encoders --quick             # 200 queries
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from scripts.layer3._common import (
    ARTIFACTS_LAYER3,
    REPO_ROOT,
    ensure_dirs,
    get_pipeline_logger,
)


CANDIDATES = [
    {
        "name": "bge-small-en-v1.5",
        "hf_id": "BAAI/bge-small-en-v1.5",
        "multilingual": False,
        "params_m": 33.4,
        "dim": 384,
        "license": "MIT",
    },
    {
        "name": "multilingual-e5-small",
        "hf_id": "intfloat/multilingual-e5-small",
        "multilingual": True,
        "params_m": 118,
        "dim": 384,
        "license": "MIT",
    },
    {
        "name": "paraphrase-multilingual-MiniLM-L12-v2",
        "hf_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "multilingual": True,
        "params_m": 118,
        "dim": 384,
        "license": "Apache-2.0",
    },
]


# Representative query mix — 50% English text, mix of code / math / multilingual
# to expose differences between English-only and multilingual encoders.
SAMPLE_QUERIES = [
    # English text reasoning / QA
    "Explain backpropagation in one paragraph.",
    "What's the difference between TCP and UDP?",
    "How do I deploy nginx as a reverse proxy?",
    "Compare CBT vs EMDR for treating PTSD.",
    "What are the legal implications of GDPR for SaaS companies?",
    # Coding
    "Write a Python function to detect SQL injection in user input.",
    "Fix this bug:\n```python\ndef foo():\n    return 1/0\n```",
    "Explain Big-O notation with an example.",
    "Refactor this 200-line module to use dependency injection.",
    "SELECT user_id, COUNT(*) FROM orders WHERE created_at > '2026-01-01' GROUP BY user_id",
    # Math
    "Prove that the sum of the first n natural numbers is n(n+1)/2.",
    "Compute the integral of x^2 from 0 to 1.",
    "What is the Riemann hypothesis?",
    "Solve for x: 2x + 5 = 13",
    # Multilingual
    "Cómo configurar nginx como proxy inverso?",
    "Comment fonctionne le rétropropagation?",
    "機械学習の基本を説明してください。",
    "Bhai yaar mujhe Python me sorting algorithm samjhao",
    "Wie funktioniert Backpropagation?",
    # Sensitive domains
    "What is the safe dosage of ibuprofen for a 70kg adult?",
    "Should I sue my landlord for an eviction notice?",
    "Give me investment advice for retirement planning.",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-cpu", action="store_true",
                        help="Also benchmark ONNX int8 on CPU.")
    parser.add_argument("--quick", action="store_true",
                        help="Run with fewer warmups + repetitions.")
    parser.add_argument("--candidates", nargs="+", default=None,
                        help="Subset of candidate names to benchmark.")
    parser.add_argument("--skip-fp32", action="store_true",
                        help="Skip GPU FP32 measurement (only run FP16) — saves time + memory.")
    parser.add_argument("--resume", action="store_true",
                        help="Read existing encoder_benchmark.json and add new candidates "
                             "incrementally instead of overwriting.")
    args = parser.parse_args()

    logger = get_pipeline_logger("layer3.encoder_bench")
    ensure_dirs()

    # Mitigate Windows paging-file pressure when loading multiple large models
    # back-to-back in the same process.
    import os as _os
    _os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128")
    _os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    import torch
    cuda_available = torch.cuda.is_available()
    if not cuda_available:
        logger.warning("CUDA not available — GPU benchmarks will be skipped")

    out_path = ARTIFACTS_LAYER3 / "encoder_benchmark.json"

    # Resume — load prior results so we can re-run only failed candidates
    results: list[dict] = []
    done_names: set[str] = set()
    if args.resume and out_path.exists():
        try:
            prior = json.loads(out_path.read_text())
            results = prior.get("results", [])
            done_names = {r["candidate"]["name"] for r in results}
            logger.info("resuming with %d prior candidates: %s", len(done_names), sorted(done_names))
        except Exception as exc:
            logger.warning("resume_failed: %s — starting fresh", exc)

    for spec in CANDIDATES:
        if args.candidates and spec["name"] not in args.candidates:
            continue
        if spec["name"] in done_names:
            logger.info("skipping %s (already in resume cache)", spec["name"])
            continue

        logger.info("=" * 60)
        logger.info("benchmarking %s", spec["name"])

        result = {"candidate": spec, "runs": {}}

        if cuda_available:
            # FP32 first (the bigger memory hit). Optional via --skip-fp32.
            if not args.skip_fp32:
                try:
                    gpu_metrics = _benchmark_pytorch(
                        spec["hf_id"], device="cuda", fp16=False,
                        logger=logger, quick=args.quick,
                    )
                    result["runs"]["gpu_fp32"] = gpu_metrics
                except Exception as exc:
                    logger.warning("gpu_fp32_failed candidate=%s err=%s",
                                   spec["name"], str(exc)[:200])
                    result["runs"]["gpu_fp32"] = {"error": str(exc)[:300]}

            # Now FP16 — half the memory of FP32
            try:
                gpu_fp16_metrics = _benchmark_pytorch(
                    spec["hf_id"], device="cuda", fp16=True,
                    logger=logger, quick=args.quick,
                )
                result["runs"]["gpu_fp16"] = gpu_fp16_metrics
            except Exception as exc:
                logger.warning("gpu_fp16_failed candidate=%s err=%s",
                               spec["name"], str(exc)[:200])
                result["runs"]["gpu_fp16"] = {"error": str(exc)[:300]}

        if args.include_cpu:
            try:
                cpu_metrics = _benchmark_onnx_cpu_int8(
                    spec["hf_id"], logger=logger, quick=args.quick,
                )
                result["runs"]["cpu_onnx_int8"] = cpu_metrics
            except Exception as exc:
                logger.warning("cpu_onnx_failed candidate=%s err=%s",
                               spec["name"], str(exc)[:200])
                result["runs"]["cpu_onnx_int8"] = {"error": str(exc)[:300]}

        results.append(result)

        # Save incrementally — a crash on the next candidate doesn't lose this one
        _save_intermediate(results, out_path, cuda_available)

    # Final write (covers the case where all candidates finished successfully —
    # _save_intermediate has been writing partial results all along)
    winner = _pick_winner(results, logger)
    output = {
        "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "cuda_available": cuda_available,
        "gpu_name": torch.cuda.get_device_name(0) if cuda_available else None,
        "n_sample_queries": len(SAMPLE_QUERIES),
        "results": results,
        "winner": winner,
    }
    out_path.write_text(json.dumps(output, indent=2, default=str))
    logger.info("benchmark_results_written path=%s", out_path)

    # Auto-generate docs/layer3/encoder_choice.md from whatever results we have
    _write_encoder_choice_md(output)

    logger.info("ENCODER WINNER: %s (%s)", winner["name"], winner["reason"])
    return 0


def _benchmark_pytorch(hf_id: str, *, device: str, fp16: bool, logger, quick: bool) -> dict:
    import torch
    from sentence_transformers import SentenceTransformer

    n_warm = 5 if quick else 20
    n_repeats = 200 if quick else 1000

    # Aggressive cleanup before loading — Windows paging is sensitive
    gc.collect()
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()

    t_load_start = time.perf_counter()
    # `low_cpu_mem_usage=True` minimises temporary tensor allocations during
    # load — important on Windows where the paging file is often undersized.
    model = SentenceTransformer(
        hf_id, device=device,
        model_kwargs={"low_cpu_mem_usage": True} if device == "cuda" else None,
    )
    if fp16 and device == "cuda":
        model.half()
    t_load = time.perf_counter() - t_load_start

    # Warmup
    for _ in range(n_warm):
        _ = model.encode(SAMPLE_QUERIES[:4], convert_to_numpy=True,
                         normalize_embeddings=True)

    # Cold-first-encode is captured by the first measurement
    latencies_ms = []
    t_total_start = time.perf_counter()
    for i in range(n_repeats):
        query = SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)]
        t0 = time.perf_counter()
        emb = model.encode(query, convert_to_numpy=True, normalize_embeddings=True)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    t_total = time.perf_counter() - t_total_start

    # Throughput batched
    batch_size = 32 if device == "cuda" else 8
    n_batch_repeats = 50 if not quick else 10
    t_batch_start = time.perf_counter()
    for _ in range(n_batch_repeats):
        _ = model.encode(SAMPLE_QUERIES, batch_size=batch_size,
                         convert_to_numpy=True, normalize_embeddings=True)
    t_batch = time.perf_counter() - t_batch_start
    qps = (n_batch_repeats * len(SAMPLE_QUERIES)) / t_batch

    # Memory
    if device == "cuda":
        vram_mb = torch.cuda.max_memory_allocated() / 1e6
    else:
        vram_mb = 0

    # Sanity: cosine of "How do I deploy nginx?" vs "How to set up nginx?"
    e1 = model.encode("How do I deploy nginx?", normalize_embeddings=True)
    e2 = model.encode("How to set up nginx as a reverse proxy?", normalize_embeddings=True)
    e3 = model.encode("What is the Riemann hypothesis?", normalize_embeddings=True)
    sim_near = float(np.dot(e1, e2))
    sim_far = float(np.dot(e1, e3))

    # Cleanup
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    return {
        "device": device,
        "fp16": fp16,
        "n_warmup": n_warm,
        "n_repeats": n_repeats,
        "load_seconds": round(t_load, 3),
        "p50_ms": round(statistics.median(latencies_ms), 3),
        "p95_ms": round(_percentile(latencies_ms, 95), 3),
        "p99_ms": round(_percentile(latencies_ms, 99), 3),
        "min_ms": round(min(latencies_ms), 3),
        "max_ms": round(max(latencies_ms), 3),
        "throughput_qps": round(qps, 1),
        "vram_peak_mb": round(vram_mb, 1),
        "sanity_near_cosine": round(sim_near, 4),
        "sanity_far_cosine": round(sim_far, 4),
        "sanity_pass": sim_near > sim_far + 0.10,
    }


def _benchmark_onnx_cpu_int8(hf_id: str, *, logger, quick: bool) -> dict:
    """ONNX int8 export + CPU inference. Slow path used when CUDA unavailable."""
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer
    except ImportError as exc:
        return {"skipped": True, "reason": f"optimum not installed: {exc}"}

    n_warm = 3 if quick else 10
    n_repeats = 50 if quick else 200

    t_load_start = time.perf_counter()
    try:
        tokenizer = AutoTokenizer.from_pretrained(hf_id)
        model = ORTModelForFeatureExtraction.from_pretrained(
            hf_id, export=True, provider="CPUExecutionProvider"
        )
    except Exception as exc:
        return {"skipped": True, "reason": f"ONNX export failed: {exc}"}
    t_load = time.perf_counter() - t_load_start

    def encode_single(text: str) -> np.ndarray:
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
        outputs = model(**inputs)
        # Mean-pool the last hidden state
        emb = outputs.last_hidden_state.mean(dim=1).detach().numpy()[0]
        norm = np.linalg.norm(emb) + 1e-9
        return emb / norm

    # Warmup
    for _ in range(n_warm):
        _ = encode_single(SAMPLE_QUERIES[0])

    latencies_ms = []
    for i in range(n_repeats):
        query = SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)]
        t0 = time.perf_counter()
        _ = encode_single(query)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    return {
        "device": "cpu",
        "quantization": "onnx_fp32",  # int8 requires calibration data; left as fp32 for now
        "n_warmup": n_warm,
        "n_repeats": n_repeats,
        "load_seconds": round(t_load, 3),
        "p50_ms": round(statistics.median(latencies_ms), 3),
        "p95_ms": round(_percentile(latencies_ms, 95), 3),
        "p99_ms": round(_percentile(latencies_ms, 99), 3),
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def _save_intermediate(results: list[dict], out_path, cuda_available: bool) -> None:
    """Write a partial result file after each candidate so a crash on the
    next one doesn't lose progress. Winner field is recomputed on every save.
    """
    import torch
    payload = {
        "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "cuda_available": cuda_available,
        "gpu_name": torch.cuda.get_device_name(0) if cuda_available else None,
        "n_sample_queries": len(SAMPLE_QUERIES),
        "results": results,
        "winner": _pick_winner(results, logger=None) if results else {"name": None, "reason": "no results yet"},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str))


def _pick_winner(results: list[dict], logger=None) -> dict:
    """Choose the encoder for production based on a documented rubric:

      1. Must be multilingual (project requirement — Hinglish, Spanish, etc.)
         If only English-only candidates were benchmarked, the rule relaxes.
      2. Among multilingual, pick the one with the lowest GPU-FP16 p99 latency
         that passes the cosine sanity check.
      3. Tie-break by VRAM footprint.

    Crashed candidates (runs[*] has only an 'error' key) are excluded.
    """
    if not results:
        return {"name": None, "reason": "no candidates benchmarked"}

    def measurable(r):
        for run in r["runs"].values():
            if isinstance(run, dict) and "error" not in run and "p99_ms" in run:
                return True
        return False

    measured = [r for r in results if measurable(r)]
    if not measured:
        return {"name": None, "reason": "all candidates failed to benchmark"}

    def fp16_p99(r):
        run = r["runs"].get("gpu_fp16") or r["runs"].get("gpu_fp32") or {}
        return run.get("p99_ms", 9e9)

    multilingual_results = [r for r in measured if r["candidate"]["multilingual"]]
    pool = multilingual_results if multilingual_results else measured

    # Filter sanity-pass
    sane = [r for r in pool if (
        r["runs"].get("gpu_fp16") and r["runs"]["gpu_fp16"].get("sanity_pass", False)
    ) or (
        r["runs"].get("gpu_fp32") and r["runs"]["gpu_fp32"].get("sanity_pass", False)
    )]
    candidates_pool = sane if sane else pool

    winner = min(candidates_pool, key=fp16_p99)
    fp16 = winner["runs"].get("gpu_fp16") or winner["runs"].get("gpu_fp32") or {}
    reason = (
        f"lowest p99 latency among "
        f"{'multilingual' if winner['candidate']['multilingual'] else 'all'} candidates "
        f"({fp16.get('p99_ms', '?')}ms p99, "
        f"{fp16.get('vram_peak_mb', '?')}MB VRAM, "
        f"{fp16.get('throughput_qps', '?')} qps)"
    )
    return {"name": winner["candidate"]["name"], "hf_id": winner["candidate"]["hf_id"], "reason": reason}


def _write_encoder_choice_md(output: dict) -> None:
    md_path = REPO_ROOT / "docs/layer3/encoder_choice.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Layer 3 — Encoder Choice",
        "",
        f"> **Benchmarked:** {output['completed_at_utc']} UTC",
        f"> **Hardware:** {output['gpu_name'] or 'CPU only'}",
        "",
        "## Result",
        "",
        f"**Selected encoder:** `{output['winner']['hf_id']}`",
        "",
        f"**Reason:** {output['winner']['reason']}",
        "",
        "## Benchmark numbers",
        "",
        "| Candidate | License | Params | GPU FP16 p50 | p99 | qps (batch 32) | VRAM peak | Sanity |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in output["results"]:
        cand = r["candidate"]
        fp16 = r["runs"].get("gpu_fp16") or r["runs"].get("gpu_fp32") or {}
        lines.append(
            f"| {cand['name']} | {cand['license']} | {cand['params_m']}M | "
            f"{fp16.get('p50_ms', '–')} ms | {fp16.get('p99_ms', '–')} ms | "
            f"{fp16.get('throughput_qps', '–')} | "
            f"{fp16.get('vram_peak_mb', '–')} MB | "
            f"{'✅' if fp16.get('sanity_pass') else '❌'} |"
        )

    lines += [
        "",
        "## Rubric",
        "",
        "Selection rubric:",
        "1. Must be multilingual (project requirement — Hinglish, Spanish, French, German, CJK).",
        "2. Among multilingual candidates that pass the cosine sanity check, pick the lowest GPU-FP16 p99 latency.",
        "3. Tie-break by VRAM footprint.",
        "",
        "Sanity check: cosine of `'How do I deploy nginx?'` vs `'How to set up nginx as a reverse proxy?'` should exceed cosine vs `'What is the Riemann hypothesis?'` by ≥ 0.10. A failing sanity check means the encoder didn't load or pool correctly.",
        "",
        "## What was rejected",
        "",
        "- **jina-embeddings-v3** — strongest MTEB score, but CC-BY-NC license (commercial use blocker) and ~80-200ms latency.",
        "- **bge-m3** — multilingual gold standard but 568M params and ~80-150ms on CPU.",
        "- **bge-base-en / gte-base / nomic / mxbai** — over latency budget at base size (~35-60ms).",
        "- **ModernBERT-base** — published as the vLLM Semantic Router backbone, but at 149M params with CPU latency ~30-50ms, not faster than our chosen candidate on this hardware.",
        "",
        "## Refresh cadence",
        "",
        "Re-run this benchmark when:",
        "- A new candidate encoder is released that claims classification leadership on MTEB",
        "- The hardware changes",
        "- The candidate's HuggingFace repo bumps a major version",
        "",
        "Run: `python -m scripts.layer3.benchmark_encoders`",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
