# Layer 1 — Modality Gate: Research Notes

> **Layer:** Layer 1 (input-modality signal extractor)
> **Constraint:** < 50ms CPU per query, no decoder-LLM calls
> **Last updated:** 2026-05-18

Companion: [LAYER_1_REPORT.md](LAYER_1_REPORT.md), [PROTOCOL.md](PROTOCOL.md), [Layer 0 precedent](LAYER_0_RESEARCH.md).

---

## Table of contents
1. [Problem framing](#problem-framing)
2. [Library survey](#library-survey)
3. [Literature](#literature)
4. [Hands-on smoke tests](#hands-on-smoke-tests)
5. [Decisions](#decisions)
6. [Deferred work](#deferred-work)
7. [Open questions](#open-questions)

---

## Problem framing

The Modality Gate is **a signal extractor, not a decision maker**. Its job is to enrich each query with orthogonal features:
- What natural language is this?
- Is there code? In what language?
- Is the structure JSON / YAML / TOML / XML / CSV / Markdown?
- Does the user's text actually reference an attached image?
- Is this an injection attempt?

Downstream layers (triage, uncertainty, bandit) compose those signals into a routing decision. The audit found the original implementation conflated extraction with decision-making (`requires_code_model = code_density > 0.3`) — that's a Layer policy concern, not Layer 1's.

### Failure modes the audit + reviewer flagged
1. **Language**: Latin-script non-English (Spanish, French, German, Hinglish) all collapse to "en"
2. **Code language**: only Python/JS/Java/C++/SQL detected; Rust/Go/TS/Bash/Dockerfile invisible
3. **Code density**: arbitrary `/100` denominator gives wildly different scores at different text lengths
4. **Vision relevance**: `has_images=True` → `requires_vision=True` regardless of whether text refers to image
5. **Structured data**: only flat JSON/CSV; YAML/TOML/XML/MD tables miss
6. **Token count**: `len(text)/4` is 4× wrong for CJK and 1.5× wrong for code
7. **Keyword matching**: `"occurred"` matches `"ocr"` (substring), `"play this guitar"` matches `"play this"` (phrase)
8. **ReDoS**: `^\s*\{[\s\S]*\}\s*$` against `"{"×N` exhibits O(n²) backtracking (~10s on n=10k)
9. **Validation silently bypassed**: `validation_passed=False` returned but router doesn't check it
10. **Singleton race**: TOCTOU in `get_modality_gate()` — same pattern fixed in Layer 0
11. **Injection patterns**: 10 regexes, trivially paraphrased around
12. **Threshold inconsistency**: 0.5 in MULTIMODAL check vs 0.6 in IMAGE check
13. **Modality enum gaps**: no LaTeX, ASCII art, music notation
14. **Empty/emoji-only inputs**: token_count=0, no special handling
15. **Code patterns FPs**: `<b>important</b>` matches HTML tag pattern; `{x : x > 0}` matches JSON-like pattern

---

## Library survey

### Language detection

| Library | Latency | Accuracy on short text | Verdict |
|---|---|---|---|
| **lingua-py 2.1.1** (Apache-2.0, ~96MB native binding) | 100-300μs high-acc mode | Best on >5-word text; **misclassifies short English** ("login broken" → nl@0.47) | **Adopt as Tier 2 with confidence ≥ 0.55 threshold** |
| `fast-langdetect` 1.0.1 (fasttext lid.176, 125MB) | 50-100μs | "hola" → en@0.39 (wrong); `low_memory=True` available | **Reject for Layer 1** — short-greeting accuracy is poor (we already deferred from Layer 0) |
| `langdetect` (port of Java lib) | 1-5ms | Non-deterministic; consistently worse than lingua | Reject — unmaintained spirit |
| `pycld3` / `gcld3` | <100μs | Decent on long text | Reject — Windows wheels broken, gcld3 abandoned |
| `papluca/xlm-roberta-base-language-detection` HF model | 50-100ms CPU | High accuracy | Reject — blows latency budget 2× |

**Hinglish gap**: NO library reliably detects Latin-script Hindi as Hindi — lingua, fastText, langdetect all return English for `"kya tum mujhe batayega"`. This is fundamental: there's no script signal, and English-Hindi vocabulary overlap is high. **Solution: maintain a marker lexicon** (`kya, hai, aap, mujhe, tum, kaise, nahi, accha, bhai, yaar, kar, hua, mera, namaste, dhanyavad, …`). If ≥2 markers appear in a Latin-script query, classify as `hi-Latn` (BCP-47). This is what production chat systems do — no library shortcut exists.

### Code language detection

| Library | Latency | Languages | Verdict |
|---|---|---|---|
| **Pygments** 2.18+ (BSD-2, ~5MB) | 3-10ms typical | 300+ via `guess_lexer` | **Adopt as Tier 2** — pre-installed in env, used by GitHub Gist/Jupyter |
| `Guesslang` (Google) | 50-200ms | 54 langs | Reject — last release Aug 2021, TF1 deps don't install on Py3.11+ |
| `enry` / `go-enry` | <10ms | 600+ | Reject — Go binding, no Windows wheels |
| `tree-sitter` | 10-20ms per parse | 40+ language grammars | Defer — use as Tier 3 verification later if needed |

**Tier 1.5 addition** (no library): distinctive signature regex patterns. `\bdef NAME(): ` is essentially uniquely Python — false-positives on prose require contrived sentences. Same for `\bfn NAME(`, `\bfunc NAME(`, `\binterface NAME {`, `\bpublic static`. These as a pre-check before keyword-count detection means single-occurrence high-confidence matches succeed without falling through to Pygments.

### Structured data detection

**No single library** addresses this well. Adopted approach: **try-parse cascade** using stdlib parsers:
- JSON: `json.loads`
- TOML: `tomllib.loads` (stdlib in Python 3.11+)
- XML: `xml.etree.ElementTree.fromstring`
- YAML: regex-only (PyYAML is too permissive — accepts plain prose as valid YAML)
- Markdown tables: regex
- CSV: regex with multi-row check

`python-magic`/`filetype` evaluated and rejected — they work on bytes/MIME, not embedded text snippets.

### Vision relevance

**No light-weight model exists.** CLIP / SigLIP at 150ms each blows our 50ms budget by 3×. Adopted approach: **phrase regex** ("in this image", "what's shown", "describe this", "extract text from", etc.) + short-query default. Vision is required when `has_images AND (text_references_image OR word_count < 15)`.

Patterns curated from observed production chat patterns (Anthropic, OpenAI public network behavior).

### Prompt injection

Current 10 regex patterns. Audit confirmed easily paraphrased around. Researched:
- **protectai/deberta-v3-prompt-injection-v2** ONNX — 200MB model, 15-35ms CPU, F1=95.49. **Deferred** — heavy commitment; would gate behind regex-hit or high-risk paths.
- **Rebuff** — archived May 2025
- **LLM-Guard** — kitchen-sink framework, too heavy
- **NeMo Guardrails** — dialogue-flow oriented

### PII detection

- **Presidio** + scrubadub deferred to Layer 9 (telemetry redaction concern). Layer 1 adds a `contains_injection_risk` boolean for downstream awareness.

---

## Literature

### vLLM Semantic Router — [GitHub](https://github.com/vllm-project/semantic-router), [blog Sept 2025](https://blog.vllm.ai/2025/09/11/semantic-router.html)
Six-signal architecture: Domain, Keyword, Embedding, Factual, Feedback, Preference. Reports 47% latency reduction and 48% token reduction in production. Confirms the **signal-driven decomposition** we're adopting.

### LingoIITGN COMI-LINGUA dataset — [HuggingFace](https://huggingface.co/datasets/LingoIITGN/COMI-LINGUA)
For Hinglish, **token-level language ID** is the right framing — document-level LID will never work because the script signal is absent. Our marker-lexicon approach is the simplest token-level approximation.

### FrugalGPT — [arXiv 2305.05176](https://arxiv.org/abs/2305.05176)
The cascade pattern: cheap deterministic checks before expensive ML. Our Tier 1 → Tier 2 architecture is the same shape.

### AutoMix — [arXiv 2310.12963](https://arxiv.org/abs/2310.12963)
Three-class router with explicit "unanswerable" class. Their pattern of having a per-signal confidence rather than a global one informs our `language_confidence` exposure to downstream layers.

---

## Hands-on smoke tests

I ran **lingua-py against the exact problem queries** before committing to it. Key findings (logged in `experiments/layer_1_language_detection/`):

### Test 1: lingua low-accuracy mode

```
"hola"                          → en (WRONG; should be es) — single word too short
"How do I center a div in CSS"  → it (WRONG; should be en)
"login broken"                  → nl (WRONG)
"What is photosynthesis"        → de (WRONG)
```

Low-accuracy mode is unusable for short English queries.

### Test 2: lingua high-accuracy with confidence values

```
"Hola, gracias por todo"        → es@0.56  ✓
"Bonjour mon ami"               → fr@0.62  ✓
"Guten Tag, wie geht es Ihnen"  → de@0.49  ✓ (borderline)
"login broken"                  → nl@0.47  ✗ (low confidence)
"How do I center a div in CSS"  → en@0.27  ✓ (correct, low confidence)
"kya tum mujhe batayega"        → en@0.35  ✗ (Hinglish, low confidence)
```

The crucial observation: **lingua's WRONG predictions on English have lower confidence than its correct non-English predictions**. With a 0.55 threshold:
- `es@0.56` accepted as Spanish ✓
- `fr@0.62` accepted as French ✓
- `nl@0.47` rejected → defaults to "en" ✓
- `en@0.27` rejected (it's already en, default fits)

This single observation is what made lingua adoptable. Without confidence gating, lingua actively damages routing for English users.

### Test 3: Hinglish

`"kya tum mujhe batayega"` returns `en@0.35` from lingua (low confidence, defaults to "en"). The marker lexicon catches this — 4 markers (`kya, tum, mujhe, batayega`) → `hi-Latn`. Critical: this works because the markers fire BEFORE we call lingua.

---

## Decisions

| Concern | Tier 1 | Tier 2 | Decision |
|---|---|---|---|
| Language detection | Script regex + Hinglish markers | lingua-py @ confidence ≥ 0.55 | **Adopted** (+56.2 pp F1 on OOD corpus) |
| Code language detection | Fence + signatures + keyword counts | Pygments `guess_lexer` | **Adopted** (+50.0 pp F1 on multi-language corpus) |
| Vision relevance | Phrase regex + short-query default | — | **Adopted** (0 FPs on 5 vision-required + 2 image-attached-but-not-referenced cases) |
| Structured-data detection | Try-parse cascade (json/tomllib/xml) + regex (yaml/csv/md) | — | **Adopted** (100% on 6 formats in golden set) |
| Prompt injection | 10 regex patterns | DeBERTa ONNX (gated) | **Deferred** — Phase 2 decision |
| PII detection | — | scrubadub/Presidio | **Deferred to Layer 9** — telemetry concern |

All adopted libraries:
- **Gracefully degrade** if not installed — `try: import …` with fallback to Tier 1
- **Process-wide cached** via module-level `_get_or_build_*` factories with `threading.Lock`
- **Configurable** via `ModalityGateConfig` in `routing_config.py`

---

## Deferred work

| Item | Why deferred | Estimated effort |
|---|---|---|
| DeBERTa-v3 prompt-injection-v2 | 200MB model + 15-35ms latency when active. Gated on regex hit. Worth its own decision. | ~1 day |
| PII redaction (Presidio/scrubadub) | Belongs to Layer 9 telemetry, not Layer 1 modality | (Layer 9 work) |
| LaTeX / ASCII art / music notation categories | Audit issue #15 — minor, no clear downstream consumer yet | ~2 hours when needed |
| Token-level Hinglish LID (COMI-LINGUA) | Our marker lexicon is the cheap approximation; a learned model would help on edge cases | ~1 week (training) |
| Tree-sitter verification pass for code | Tier 3 verifier for high-stakes paths | ~1 day |

---

## Open questions

1. **Hinglish marker FP rate on Indian English** — words like `kar`, `bhai`, `yaar` appear as loanwords in Indian English. Measure on production logs before tightening the marker threshold.
2. **Pygments accuracy on <3-line snippets** — known to be flaky. The signature + keyword tiers catch most cases first, but real failures may emerge in production.
3. **Cold-start cost** — lingua model load time on first request. Currently amortised via singleton cache; document recommended warm-up call at app startup.
4. **DeBERTa adoption threshold** — what's the production injection-attempt rate? If <1%, the cost-benefit is borderline. Need a sampling estimate from telemetry first.
5. **Should `_VISION_REFERENCE_RE` be per-language?** A Hindi user might say "इस तस्वीर में" instead of "in this image". Catalog needed once we have telemetry samples.

---

## Sources

- [lingua-py](https://github.com/pemistahl/lingua-py) v2.1.1
- [fast-langdetect](https://github.com/LlmKira/fast-langdetect) v1.0.1
- [Pygments docs](https://pygments.org/docs/)
- [LingoIITGN COMI-LINGUA dataset](https://huggingface.co/datasets/LingoIITGN/COMI-LINGUA)
- [protectai/deberta-v3-base-prompt-injection-v2](https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2)
- [vLLM Semantic Router blog](https://blog.vllm.ai/2025/09/11/semantic-router.html)
- [FrugalGPT (2305.05176)](https://arxiv.org/abs/2305.05176)
- [AutoMix (2310.12963)](https://arxiv.org/abs/2310.12963)
- [Microsoft Presidio](https://github.com/microsoft/presidio)
- [scrubadub](https://github.com/LeapBeyond/scrubadub)
- [LLM-Guard](https://github.com/protectai/llm-guard)
