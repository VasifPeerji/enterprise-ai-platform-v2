# Layer 0 — Fast Path Bypass: Research Notes

> **Layer:** Layer 0 (the only sub-millisecond, deterministic bypass for trivial queries)
> **Goal:** Decide whether a query is trivial enough to skip the full pipeline, without making any LLM call
> **Hard constraint:** any logic must run in < 5 ms on CPU; no API calls in the hot path
> **Last updated:** 2026-05-17

This document records the survey we ran to inform the Layer 0 redesign. The
goal is not just to ship code — it's to be honest about what we considered,
what we adopted, what we rejected, and *why*.

---

## Table of contents
1. [Problem framing](#problem-framing)
2. [Library survey — language detection](#library-survey--language-detection)
3. [Library survey — chitchat / intent classification](#library-survey--chitchat--intent-classification)
4. [Literature — LLM routing papers](#literature--llm-routing-papers)
5. [Production systems — engineering blogs](#production-systems--engineering-blogs)
6. [Decisions](#decisions)
7. [Deferred work](#deferred-work)
8. [Open questions](#open-questions)

---

## Problem framing

A user-facing LLM router has two failure modes:

1. **False negative** (a trivial query goes through the full pipeline) — costs ~200 ms of latency and 3-4 cheap LLM calls. Recoverable.
2. **False positive** (a real question is bypassed to a 3B chat model) — the user gets a bad answer. Hard to recover and damages trust.

So Layer 0 should be biased toward **precision over recall**: missing some bypasses is fine, mis-firing is not. This shapes every library decision below.

---

## Library survey — language detection

The pre-refactor Layer 0 used Unicode-script regex heuristics for language detection (Devanagari → `hi`, Cyrillic → `ru`, etc.) which works for non-Latin scripts but collapses every Latin-script language to "en". We evaluated four candidates.

| Library | Accuracy on short text | Latency | Install size | Maintained | Verdict |
|---|---|---|---|---|---|
| **[fast-langdetect](https://github.com/LlmKira/fast-langdetect)** | 90%+ on phrases, ~30-40% confidence on single words | 10-100 μs after warmup | 125 MB model | Yes (Apr 2026) | **Deferred to Layer 1** |
| **[lingua-py](https://github.com/pemistahl/lingua-py)** | Highest published accuracy on <10-word text (74% single word, 94% pair) | 0.1-1 ms when restricted to 15 langs | Low MB | Yes (Mar 2026) | Deferred (only valuable downstream) |
| **[fasttext (raw)](https://fasttext.cc/docs/en/language-identification.html)** | 90%+ on phrases | 10-100 μs | 125 MB or 917 KB (lid.176.ftz) | Yes | Deferred (same as fast-langdetect) |
| **[langdetect](https://github.com/Mimino666/langdetect)** | Lower accuracy on short text | 1-5 ms | 1 MB | Last release 2021 | Rejected (unmaintained, slower) |
| **[pycld3 / gcld3](https://github.com/google/cld3)** | 95%+ on phrases | <100 μs | 5-10 MB | Yes (gcld3) | Rejected (Windows wheels are painful) |

### Decision: defer to Layer 1

I installed `fast-langdetect` and verified it works. But on hands-on testing against actual greetings:

```
'hello'   -> [{'lang': 'en', 'score': 0.30}]  # low confidence
'hola'    -> [{'lang': 'en', 'score': 0.39}]  # WRONG (should be es)
'bonjour' -> [{'lang': 'fr', 'score': 0.97}]  # ok
```

For single-token queries (the bulk of Fast Path traffic), our token-lookup table is **more accurate** than fastText — because we know with certainty that `"hola"` is registered in the Spanish greeting set. fastText helps for *longer*, less-formulaic queries (Hinglish, mixed-script, paraphrases). That's a Layer 1 (Modality Gate) concern, not Layer 0.

**Action:** integrate `fast-langdetect` in Layer 1 with `low_memory=True` (917 KB model) and a confidence threshold of 0.65.

---

## Library survey — chitchat / intent classification

The current "is this a greeting?" detection is a keyword/regex matcher. The natural ML upgrade is a tiny sentence-level classifier. We surveyed:

| Approach | Latency | Accuracy gain | Install size | Verdict |
|---|---|---|---|---|
| **[Model2Vec](https://github.com/MinishLab/model2vec) static embeddings + scikit-learn LR** | ~50-200 μs | Catches paraphrases ("yo what's good", "ta very much") that keywords miss | 8 MB embedding + 50 KB classifier | **Deferred (needs labeled data + training run)** |
| **[sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)** direct | 10-25 ms per sentence on CPU | Same as Model2Vec but slower | 23 MB | Rejected (blows 5 ms budget) |
| **HF DistilBERT intent classifiers** (e.g. Falconsai/intent_classification) | 10-30 ms | Limited intent taxonomy | 250-500 MB | Rejected (too slow + heavy) |
| **[snips-nlu](https://github.com/snipsco/snips-nlu)** | 1-5 ms | Built-in conversational intents | 100-200 MB RAM | Rejected (unmaintained since 2020) |
| **[Rasa](https://rasa.com/) small-talk policies** | N/A | Heavyweight framework | 1+ GB | Rejected (massive overkill) |

### Decision: Model2Vec — ADOPTED as Tier 2 (after measured A/B)

We did NOT trust the library's reputation. We ran the experiment.

#### Experiment

[experiments/layer_0_model2vec_vs_heuristic/](../../experiments/layer_0_model2vec_vs_heuristic/) — three-arm head-to-head:

1. **Tier 1 only** (current heuristic)
2. **Tier 2 only** (Model2Vec prototype-similarity, no heuristic)
3. **Hybrid** (heuristic → Tier 2 fallback when heuristic returns NONE)

Each evaluated on two datasets:

- The original golden set (77 cases) — library must not regress
- A new paraphrase corpus (68 OOD cases — phrases real ChatGPT users type but our keyword table never anticipated)

Thresholds swept: 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85.

#### Results

**Paraphrase corpus (the real test):**

| Approach | F1 | Precision | Recall | FN | FP |
|---|---|---|---|---|---|
| Tier 1 only (heuristic) | **34.0%** | 100% | 20.5% | 35 | 0 |
| Tier 2 only @ 0.80 | 60.3% | 100% | 43.2% | 25 | 0 |
| **Hybrid @ 0.80** | **76.1%** | **100%** | 61.4% | 17 | **0** |
| Hybrid @ 0.65 | 80.0% | 88.9% | 72.7% | 12 | 4 |

**Golden set:**

| Approach | F1 |
|---|---|
| Tier 1 only | 99.1% |
| **Hybrid @ 0.80** | **100%** |

#### Why threshold 0.80

The threshold sweep makes the trade-off explicit. **At 0.80 we get 100% precision** — zero false positives — with **+42.1 percentage points of F1** over the pure heuristic. At 0.65 we'd gain 11 more percentage points of recall but introduce 4 false positives (real questions routed to a tiny chat model). We don't take that trade because, per the framing at the top of this doc, **a false positive costs the user a bad answer; a false negative only costs a little latency.**

#### What the library catches that the heuristic misses

18 specific queries — all phrases real users actually type, all now bypassed correctly at zero precision cost:

| Greeting | Ack | Farewell |
|---|---|---|
| yo whats good | cheers | peace out |
| wassup | cheers mate | ttyl |
| good day to you | no worries | have a good one |
| long time no see | no problem | take care |
| | much obliged | talk soon |
| | you're a lifesaver | |
| | much love | |
| | you rock | |
| | appreciate the effort | |

#### Decision

**ADOPT Model2Vec + prototype-similarity at threshold 0.80** as Tier 2 fallback. Configured by default (`enable_semantic_tier2=True`). Gracefully degrades to Tier-1-only if `model2vec` isn't installed.

This is also the precedent for [PROTOCOL.md](PROTOCOL.md)'s Library Evaluation Protocol — every future library adoption follows the same A/B shape.

---

## Literature — LLM routing papers

Read primarily for the *bypass / cheap-tier* angle, not the full routing problem.

### FrugalGPT — [arXiv 2305.05176](https://arxiv.org/abs/2305.05176)

Three strategies: prompt adaptation, LLM approximation, LLM **cascade**. Our Fast Path *is* step 0 of a cascade.

**Pattern adopted:** return an explicit `confidence` from each tier so the orchestrator can require high confidence before bypassing. Our `FastPathDecision.confidence` already supports this — per-category thresholds in `FastPathConfig`.

### Hybrid LLM — [arXiv 2404.14618](https://arxiv.org/abs/2404.14618) (ICLR 2024)

Trains a small BERT-based router that predicts a "quality drop" if the query goes to the small model. Tunable cost/quality knob at test time. Reports 40% of queries can go to the small model with **no quality regression**.

**Pattern adopted:** single threshold knob in config (`min_greeting_confidence`, `min_factual_confidence`, etc.) so ops can dial bypass aggressiveness without redeploying code.

### AutoMix — [arXiv 2310.12963](https://arxiv.org/abs/2310.12963) (NeurIPS 2024)

Three-class router: Simple / Complex / **Unsolvable**. The "unsolvable" class lets them avoid expensive routes when no model can help.

**Pattern adopted:** added `MALFORMED` category to `FastPathCategory`. Bypasses pure-punctuation, emoji-only, and repeated-noise queries (`"?"`, `"!!!"`, `"aaaa"`) to a cheap chat model rather than burning the full pipeline on noise.

### RouteLLM — [LMSYS arXiv 2406.18665](https://arxiv.org/abs/2406.18665) / [blog](https://www.lmsys.org/blog/2024-07-01-routellm/)

Four router variants (similarity-weighted ranking, matrix factorization, BERT classifier, causal LLM). All run *after* a hardcoded "is this even a routing question" check. Headline: 85% cost reduction on MT Bench, driven by cheap-bucket hit rate.

**Pattern adopted:** capture and expose `bypass_rate` as a first-class metric (see [LAYER_0_REPORT.md](LAYER_0_REPORT.md)). RouteLLM's cost-savings story is entirely about how often the cheap bucket hits.

### CARGO — [arXiv 2509.14899](https://arxiv.org/html/2509.14899v1)

Embedding regressor with a binary classifier fallback when prediction is uncertain.

**Pattern adopted:** two-stage decision architecture. The regex/keyword tier is the high-confidence first stage (returns a hard decision). A future Model2Vec+LR tier (Phase 2) would be the soft-confidence fallback when regex returns NONE.

### BEST-Route — [Microsoft, arXiv 2506.22716](https://arxiv.org/abs/2506.22716)

Adaptive multi-sampling at the model-selection stage. Less relevant for Layer 0 specifically; flagged for Layer 5 (bandit) review.

### Mixture of Routers — [arXiv 2503.23362](https://arxiv.org/abs/2503.23362)

Per-router-per-domain specialisation. Relevant for Layer 5 design, not Layer 0.

---

## Production systems — engineering blogs

### [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) / [blog](https://blog.vllm.ai/2025/09/11/semantic-router.html)

Production-grade Rust router with a six-signal architecture explicitly including "Keyword Signals: Fast, interpretable regex-based pattern matching" as a fast-path tier alongside a ModernBERT classifier. Reports **47% latency reduction and 48% token reduction** in production.

Their published taxonomy maps closely to our categories. We're not taking a runtime dependency (it's a Go/Rust sidecar) but their config schema validates our category choices.

### Other notes

- **Cursor / Copilot**: public posts indicate they use a fast keyword/regex check for code-only queries before invoking a learned router. Confirms the keyword-first design.
- **Perplexity**: relies on query length and embedding-based routing; no explicit "trivial" tier disclosed.
- **r/LocalLLaMA**: the community's go-to for cheap routing is "regex for the obvious + small SLM for the rest" — which is what we've built.

---

## Decisions

What we **adopted** in this Layer 0 retrofit:

| Source | Adoption |
|---|---|
| AutoMix `UNANSWERABLE` class | Added `FastPathCategory.MALFORMED` — bypasses pure-punctuation / repeated-noise queries to cheap chat. |
| FrugalGPT explicit-confidence cascade | `FastPathDecision.confidence` is per-category and configurable. |
| Hybrid LLM single threshold knob | `FastPathConfig` exposes `min_greeting_confidence`, `min_arithmetic_confidence`, `min_factual_confidence`. |
| RouteLLM bypass-rate metric | Benchmark script captures bypass rate per category, per source, per language. |
| vLLM Semantic Router category taxonomy | Validated our 7-category split (greeting / ack / farewell / arithmetic / definition / factual / malformed). |

What we **rejected** for Layer 0 (with rationale):

- `langdetect`: unmaintained, slower, lower accuracy than fastText on short text.
- `pycld3 / gcld3`: Windows install pain not worth marginal accuracy gain over fastText.
- `snips-nlu`: abandoned since 2020.
- `sentence-transformers all-MiniLM-L6-v2` directly: 10-25 ms on CPU per sentence — blows our budget. (We'd use Model2Vec instead.)
- HF DistilBERT intent classifiers: same latency issue + 250+ MB model.
- Rasa: framework-level dependency, massive overkill.

---

## Deferred work

| Item | Why deferred | Where it belongs |
|---|---|---|
| **fast-langdetect integration** | Single-token greetings benefit more from our token table; fastText shines on longer queries | Layer 1 (Modality Gate) |
| **Model2Vec + LR semantic chitchat detection** | Needs labeled corpus (CLINC150 + Banking77) and a training run; documented in this report | Layer 0 Phase 2 |
| **Lingua-py tiebreaker** | Only worth integrating after fastText is in and we measure its uncertain-zone false-positive rate | After Layer 1 |
| **Confidence as 3-level enum (FrugalGPT pattern)** | Schema-wide change; better done in a single sweep | Cross-layer pass after Layer 5 |
| **Shadow routing for 1% of bypass decisions** | Needs Layer 9 telemetry plumbing for offline comparison | Layer 9 |
| **PII redaction at telemetry** | Cross-layer; better solved once at Layer 9 with Presidio | Layer 9 |

---

## Open questions

1. **What's the false-positive cliff for keyword bypass on production traffic?** Need a week of real logs. The hand-curated golden set scores 100% but real users will type things we haven't anticipated. Plan: when telemetry is wired, sample 1000 bypass decisions weekly and human-label them.

2. **Should the polite-filler set be learned, not curated?** Currently 30+ hand-curated English+European words. A learned classifier ("is this token a polite filler given a greeting prefix?") would be more robust but adds complexity. Deferred until we have logged data.

3. **What's the optimal `max_greeting_words` cap?** Currently 8. Tighter (5) reduces false positives, looser (12) catches more multilingual greetings with politeness. Measure on logs.

4. **Should the `MALFORMED` category go to the FULL pipeline or to cheap chat?** Currently goes to chat (cheaper, faster response to noise). Alternative: respond programmatically with "I didn't understand — could you rephrase?" without any model call. Cheaper but jarring.

---

## Sources

- [lingua-py](https://github.com/pemistahl/lingua-py)
- [fast-langdetect](https://github.com/LlmKira/fast-langdetect)
- [fastText language identification](https://fasttext.cc/docs/en/language-identification.html)
- [pycld3](https://github.com/bsolomon1124/pycld3) / [google/cld3](https://github.com/google/cld3)
- [Model2Vec](https://github.com/MinishLab/model2vec)
- [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
- [CLINC150 dataset](https://huggingface.co/datasets/clinc_oos), [Banking77](https://huggingface.co/datasets/banking77)
- [RouteLLM paper](https://arxiv.org/abs/2406.18665) and [LMSYS blog](https://www.lmsys.org/blog/2024-07-01-routellm/)
- [FrugalGPT (2305.05176)](https://arxiv.org/abs/2305.05176)
- [Hybrid LLM (2404.14618)](https://arxiv.org/abs/2404.14618)
- [AutoMix (2310.12963)](https://arxiv.org/abs/2310.12963)
- [Mixture of Routers (2503.23362)](https://arxiv.org/abs/2503.23362)
- [CARGO (2509.14899)](https://arxiv.org/html/2509.14899v1)
- [BEST-Route (2506.22716)](https://arxiv.org/abs/2506.22716)
- [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) / [blog](https://blog.vllm.ai/2025/09/11/semantic-router.html)
- [snips-nlu](https://github.com/snipsco/snips-nlu)
- [Language identification survey, modelpredict](https://modelpredict.com/language-identification-survey)
