# Layer 2 — Semantic Memory: Research Notes

> **Layer:** Layer 2 (outcome-aware routing cache + novelty signal)
> **Constraint:** < 10ms per lookup, no decoder-LLM calls
> **Last updated:** 2026-05-19

Companion: [LAYER_2_REPORT.md](LAYER_2_REPORT.md), [PROTOCOL.md](PROTOCOL.md).

---

## Problem framing

Layer 2 sits between the modality gate and the triage classifier. Its job
is to **reuse past routing decisions** for queries similar to ones we've
already routed — saving us the cost of running the full pipeline (triage
LLM call + uncertainty + bandit). Two signals come out: a `hit`/`miss`
verdict and a `novelty_score` that downstream layers use to bias
uncertainty.

### Failure modes the audit + reviewer flagged
1. **Bypass-but-not-really** — `_create_cached_decision` still called triage
   classifier (LLM) and uncertainty estimator on every cache hit. Same bug
   we fixed in Layer 0.
2. **Negation false positives** — `"install Docker"` and `"uninstall Docker"`
   had high lexical similarity → cache-hit → user gets the install answer
   for an uninstall question.
3. **No persistence** — in-memory list, process restart wipes everything.
4. **Embedding via gateway** — 50-200ms network round-trip for each
   similarity, vs ~200μs locally with Model2Vec.
5. **Quality threshold 0.7 was flat** — quality 0.71 entry served same as 0.95.
6. **Cache reuses decision not answer** — modest latency win, no inference savings.
7. **60-day cache age too long** — old decisions for now-deprecated models.
8. **Regex entity extractor** — capitalized-only, misses technical terms.
9. **Singleton TOCTOU race** + `_store` not thread-safe.
10. **Outcome-aware** claim conditional on Layer 9 (telemetry) working.
11. **No hit-rate / latency-saved telemetry**.
12. **No PII masking** on stored entities.
13. **Embedding cache silent eviction** at 1000 entries with no LRU.
14. **No multi-tenant scoping** — global store.
15. **No invalidation API** for ops to drop entries when a model is deprecated.

---

## Library survey

### Vector store / persistence

| Library | Latency @ 10K, 256-dim | Footprint | On-disk | License | Verdict |
|---|---|---|---|---|---|
| **NumPy matrix + SQLite (stdlib)** | ~250μs cosine, ~1ms persist | 10MB matrix | `.db` file | — | **Adopted** |
| sqlite-vec | ~1-3ms KNN | <20MB | `.db` | Apache-2.0 / MIT | Defer until >100K entries |
| LanceDB | ~0.5-2ms IVF | 80-120MB | Lance dir | Apache-2.0 | Defer |
| ChromaDB | ~3-8ms | 200+MB | duckdb+parquet | Apache-2.0 | Reject — too heavy |
| FAISS-cpu | ~0.3-1ms | 60MB | manual pickle | MIT | Reject — no persistence story |
| hnswlib | ~0.2-0.5ms | 40MB | manual save/load | Apache-2.0 | Defer |

**Decision: NumPy + stdlib SQLite.**
- At 10-50K entries, brute-force NumPy dot product is ~250μs — fast enough.
- SQLite stdlib is already there; embeddings stored as `BLOB` (packed
  float32). WAL mode for crash safety + concurrent reads.
- No external deps. Reconsider sqlite-vec / LanceDB at 100K+ entries.

### Embedding

| Library | Latency | Quality | Verdict |
|---|---|---|---|
| **Model2Vec potion-base-8M** | ~200μs per encode | STS-B ~0.74, multilingual | **Adopted** (already in env from Layer 0) |
| sentence-transformers all-MiniLM-L6-v2 | 10-25ms | STS-B ~0.80 | Reject — too slow for the budget |
| fastembed (ONNX MiniLM) | 4-6ms | similar quality | Reject — duplicates Model2Vec at +70MB |
| Gateway / Ollama embed | 50-200ms (network) | varies | **Removed** — the original code's path |
| Char-ngram Jaccard | 50μs | poor on paraphrases | **Kept as graceful fallback** |

### NER / entity extraction

| Tool | Latency | Footprint | Verdict |
|---|---|---|---|
| **Current regex (capitalized + technical patterns)** | ~50μs | 0 | **Adopted** with extensions |
| GLiNER (zero-shot, ONNX) | 4-8ms | 50MB | Defer (lazy-load if telemetry surfaces FPs) |
| spaCy en_core_web_sm | 3-6ms | 100MB+ deps | Reject — heavy import |
| dslim/bert-base-NER | 25-40ms | 420MB | Reject — blows budget |

**Decision: extend the existing regex.** Two passes:
1. Capitalized proper-noun phrases (Python, Kubernetes, New York)
2. Lowercase technical terms: `*Error`, `*Exception`, `-able` / `-ible` words,
   dotted module paths (`foo.bar.baz`)

The wild corpus surfaced that `subscriptable` vs `iterable` in stack-trace
queries needed the second pass. Treated as **hard-match** in the guard
(unlike general entities which use a ratio).

### Negation detection

| Approach | Verdict |
|---|---|
| **Curated marker list** | **Adopted** — 12 lines, no library, catches "install/uninstall", "enable/disable", "with/without", "get rid of" |
| negspaCy | Reject — drags in all of spaCy |
| Embedding sign-flip detection | Reject — Model2Vec doesn't reliably encode polarity |
| BERT NLI for entailment | Reject — too slow (50ms+) |

The negation marker list runs in the validation guard layer. Triggers on
1+ asymmetry between query and cached entry.

### PII detection

| Tool | Latency | Verdict |
|---|---|---|
| **Curated regex (emails, phones, SSN, cards, URLs, IBAN)** | <100μs | **Adopted** for in-cache scrubbing |
| Presidio | ~10ms / 1K tok | Defer to Layer 9 (telemetry redaction) |
| scrubadub | ~2ms | Reject — subsumed by our regex set |

Important: scrubbing happens BEFORE entity extraction so two queries with
different emails / URLs but otherwise identical structure produce
identical entity sets and embedding hits.

---

## Literature

### GPTCache (Zilliz)
Two ideas worth stealing:
1. **Eviction = LRU + similarity-bucket coverage** — don't evict the only
   entry covering a topic. *Deferred.*
2. **Hit-rate methodology**: log `(hit, similarity, post-hoc was correct)`
   to back-compute precision@threshold for offline tuning. *Adopted in the
   metrics counters; the post-hoc piece needs Layer 9 telemetry.*

### MeanCache (arXiv 2403.02694)
Federated query-cluster centroids. ~2× hit rate at the cost of staleness.
**Deferred** — only worth it past 100K entries.

### FrugalGPT cascade pattern
Confidence-tiered routing. Our equivalent: **tiered TTL** by quality band
(14d high quality / 3d medium / 1d escalated). Adopted.

### Anthropic / OpenAI prompt caching
Caches **prefix tokens** server-side, not semantic equivalents. Different
problem — not transferable.

---

## Hands-on validation

The A/B experiment ([experiments/layer_2_embeddings_vs_jaccard/](../../experiments/layer_2_embeddings_vs_jaccard/))
compares three arms on both the golden set (16 cases) and wild corpus
(18 cases):

| Arm | Golden F1 | Wild F1 | p50 latency | p99 latency |
|---|---|---|---|---|
| Heuristic only (char-ngram + old guards) | 28.6% | 58.8% | 143 μs | 223 μs |
| Library only (Model2Vec, no guards) | 75.0% | 87.5% | 317 μs | 695 μs |
| **Hybrid (production)** | **100.0%** | **100.0%** | **414 μs** | 1533 μs |

**Lift: +41.2pp F1 on wild corpus.** Decision: ADOPT.

The library-only arm gets us most of the way (60+pp gain over heuristic
alone) but only the validation guards close the last gap — specifically:
- Negation polarity (catches install/uninstall after embeddings score high)
- Technical-entity hard-match (catches stack-trace error-type differences)
- Tenant isolation (catches cross-tenant leakage that embeddings can't see)

---

## Decisions

| Concern | Decision |
|---|---|
| Embedding | Model2Vec potion-base-8M direct (no gateway) |
| Vector store | NumPy in-memory matrix |
| Persistence | SQLite stdlib, BLOB-stored embeddings, WAL mode, optional via config |
| Entity extraction | Regex (2-pass: capitalized + technical), GLiNER deferred |
| Negation | Curated marker list, 6th validation guard |
| PII scrubbing | Regex on signature + entity-extraction input |
| Concurrency | threading.RLock on _store, double-checked singleton |
| Quality tiering | 14-day high / 3-day medium / 1-day escalated TTLs (GPTCache pattern) |
| Telemetry | In-memory counters: lookup_count, hit_count, latency_saved_us, guard_rejections |
| Multi-tenant | Optional tenant_id parameter; entries scope-filtered on lookup |
| Model invalidation | `invalidate_model(model_id)` and `invalidate_pattern(...)` public methods |

---

## Deferred work

| Item | Why deferred |
|---|---|
| sqlite-vec / LanceDB | NumPy is sufficient until >100K entries |
| GLiNER NER | Current regex hits 100% on golden + wild; revisit if telemetry shows entity-guard false positives |
| Distributed Redis cache | Single-process is fine for now |
| Cache invalidation on model deprecation | API is there (`invalidate_model`) but not wired into the registry yet — needs Layer 0 → Layer 2 hook |
| Adaptive threshold based on drift | Add when we have production telemetry feeding back |
| Post-hoc precision@threshold logging | Needs Layer 9 telemetry round-trip |

---

## Open questions

1. **Cross-language cache hits.** Currently "Como funciona ML" and "How does ML work" don't hit each other even though semantically equivalent. Is this the right call? (Probably yes for routing — different languages may want different models.)
2. **TTL tuning.** 14d / 3d / 1d is GPTCache's pattern; need production telemetry to know if these are right for our traffic.
3. **Hit-rate target.** What's a reasonable hit rate at scale? GPTCache claims 30-50% on chatbot traffic; we should measure before tuning.
4. **GLiNER on domain-specific terms.** If we eventually adopt it, does it correctly identify model names ("Llama-3.3-70B") as entities?

---

## Sources

- [Model2Vec](https://github.com/MinishLab/model2vec) v0.8
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — deferred
- [LanceDB](https://lancedb.com/) — deferred
- [GPTCache](https://github.com/zilliztech/GPTCache) — patterns stolen
- [MeanCache (2403.02694)](https://arxiv.org/abs/2403.02694) — deferred
- [GLiNER](https://github.com/urchade/GLiNER) — deferred
- [Microsoft Presidio](https://github.com/microsoft/presidio) — Layer 9 candidate
- [FrugalGPT (2305.05176)](https://arxiv.org/abs/2305.05176) — tiered-TTL pattern
