# Layer 3 — Encoder Choice

> **Benchmarked:** 2026-05-26T11:28:49 UTC
> **Hardware:** NVIDIA GeForce RTX 4060 Laptop GPU

## Result

**Selected encoder:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

**Reason:** lowest p99 latency among multilingual candidates (42.946ms p99, 674.6MB VRAM, 549.6 qps)

## Benchmark numbers

| Candidate | License | Params | GPU FP16 p50 | p99 | qps (batch 32) | VRAM peak | Sanity |
|---|---|---|---|---|---|---|---|
| bge-small-en-v1.5 | MIT | 33.4M | 29.132 ms | 61.324 ms | 537.9 | 156.9 MB | ✅ |
| multilingual-e5-small | MIT | 118M | 30.507 ms | 44.322 ms | 416.8 | 674.6 MB | ✅ |
| paraphrase-multilingual-MiniLM-L12-v2 | Apache-2.0 | 118M | 27.142 ms | 42.946 ms | 549.6 | 674.6 MB | ✅ |

## Rubric

Selection rubric:
1. Must be multilingual (project requirement — Hinglish, Spanish, French, German, CJK).
2. Among multilingual candidates that pass the cosine sanity check, pick the lowest GPU-FP16 p99 latency.
3. Tie-break by VRAM footprint.

Sanity check: cosine of `'How do I deploy nginx?'` vs `'How to set up nginx as a reverse proxy?'` should exceed cosine vs `'What is the Riemann hypothesis?'` by ≥ 0.10. A failing sanity check means the encoder didn't load or pool correctly.

## What was rejected

- **jina-embeddings-v3** — strongest MTEB score, but CC-BY-NC license (commercial use blocker) and ~80-200ms latency.
- **bge-m3** — multilingual gold standard but 568M params and ~80-150ms on CPU.
- **bge-base-en / gte-base / nomic / mxbai** — over latency budget at base size (~35-60ms).
- **ModernBERT-base** — published as the vLLM Semantic Router backbone, but at 149M params with CPU latency ~30-50ms, not faster than our chosen candidate on this hardware.

## Refresh cadence

Re-run this benchmark when:
- A new candidate encoder is released that claims classification leadership on MTEB
- The hardware changes
- The candidate's HuggingFace repo bumps a major version

Run: `python -m scripts.layer3.benchmark_encoders`