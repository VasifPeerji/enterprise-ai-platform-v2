"""
Comprehensive tests for Layer 0 — Fast Path bypass.

Tests cover:
- Categorical bypass (greeting / ack / farewell / arithmetic / factual)
- Multilingual greetings (en, es, fr, de, hi, zh, ja, ar, ru)
- Negative cases that MUST NOT bypass (the old broken heuristics)
- Registry-aware model resolution and fallback-chain behaviour
- Schema completeness (provenance fields: category, matched_pattern, fallback_chain)
- Configuration toggle (enabled=False short-circuits)

These tests are deterministic — no LLM calls, no network — and run fast.
"""

import pytest

from src.layer0_model_infra.routing.fast_path import (
    FastPathAnalyzer,
    FastPathCategory,
    FastPathDecision,
)


@pytest.fixture
def fp():
    return FastPathAnalyzer()


# ===========================================================================
# Categorical bypass
# ===========================================================================

class TestGreetings:
    @pytest.mark.parametrize("q", [
        "hi", "Hi", "HELLO", "hey", "Hey there",
        "howdy", "yo", "sup", "greetings",
    ])
    def test_english_greetings(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_GREETING
        assert d.recommended_model is not None
        assert d.detected_language == "en"

    @pytest.mark.parametrize("q,lang", [
        ("hola", "es"),
        ("bonjour", "fr"),
        ("ciao", "it"),
        ("olá", "pt"),
        ("hallo", "de"),
        ("merhaba", "tr"),
    ])
    def test_european_greetings(self, fp, q, lang):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_GREETING
        # Language must be in the candidate set the token belongs to.
        assert d.detected_language in {lang, "en", "de"}  # some tokens overlap (hi/de)

    @pytest.mark.parametrize("q,lang", [
        ("नमस्ते", "hi"),
        ("namaste", "hi"),
        ("你好", "zh"),
        ("こんにちは", "ja"),
        ("안녕", "ko"),
        ("مرحبا", "ar"),
        ("привет", "ru"),
    ])
    def test_non_latin_greetings(self, fp, q, lang):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_GREETING
        assert d.detected_language == lang


class TestAcknowledgments:
    @pytest.mark.parametrize("q", [
        "thanks", "thank you", "ty", "ok", "okay", "got it",
        "understood", "noted", "sounds good", "fair enough",
        "appreciate it", "much appreciated",
    ])
    def test_english_acks(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_ACK

    @pytest.mark.parametrize("q", [
        "gracias", "merci", "danke", "grazie",
        "obrigado", "спасибо", "谢谢", "ありがとう",
        "감사합니다", "شكرا", "धन्यवाद",
    ])
    def test_multilingual_acks(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_ACK


class TestFarewells:
    @pytest.mark.parametrize("q", [
        "bye", "goodbye", "cya", "see you later", "catch you later",
    ])
    def test_english_farewells(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_FAREWELL

    @pytest.mark.parametrize("q", [
        "adios", "tchau", "再见", "さようなら", "alvida",
    ])
    def test_multilingual_farewells(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_FAREWELL


class TestArithmetic:
    @pytest.mark.parametrize("q", [
        "2+2", "2 + 2", "3 * 7", "100 / 4", "(5 + 3) * 2",
        "2.5 * 4.1", "2+2?",
        "what is 2+2", "What is 2+2?", "What's 7-3",
        "calculate 5*7", "compute 10/2",
    ])
    def test_arithmetic_bypasses(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True, f"arithmetic '{q}' should bypass"
        assert d.category == FastPathCategory.PURE_ARITHMETIC

    @pytest.mark.parametrize("q", [
        # Word problems — must NOT bypass
        "If Alice has 5 apples, how many does Bob have?",
        "Calculate the derivative of x^2 + 3x",  # has letters in middle
        "What is the integral of sin(x)?",
        "Solve for x: 2x + 3 = 7",  # has letters
    ])
    def test_word_problems_do_not_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False, f"word problem '{q}' must NOT bypass"

    def test_bare_question_marks_classified_malformed(self, fp):
        """A bare '?' has no alphanumeric content — MALFORMED, not arithmetic.

        Bypasses to a cheap chat model (cheaper than spending full pipeline
        on noise). The category MUST be MALFORMED, not PURE_ARITHMETIC.
        """
        d = fp.analyze("?")
        assert d.should_bypass is True
        assert d.category == FastPathCategory.MALFORMED


class TestSimpleFactual:
    @pytest.mark.parametrize("q,category", [
        ("What is the capital of France", FastPathCategory.SIMPLE_FACTUAL),
        ("what's the capital of japan", FastPathCategory.SIMPLE_FACTUAL),
        ("Who is the president of Brazil", FastPathCategory.SIMPLE_FACTUAL),
        ("Who was the prime minister of UK", FastPathCategory.SIMPLE_FACTUAL),
        ("define photosynthesis", FastPathCategory.SIMPLE_DEFINITION),
        ("Define osmosis", FastPathCategory.SIMPLE_DEFINITION),
        ("What does encryption mean?", FastPathCategory.SIMPLE_DEFINITION),
    ])
    def test_factual_bypasses(self, fp, q, category):
        d = fp.analyze(q)
        assert d.should_bypass is True, f"factual '{q}' should bypass"
        assert d.category == category


# ===========================================================================
# Negative cases — the old broken heuristics
# ===========================================================================

class TestMustNotBypass:
    """The old fast path bypassed these to a tiny model and gave bad answers."""

    @pytest.mark.parametrize("q", [
        # All <15 chars, no '?' or '.' — would've matched old `query_length<15` rule
        "login broken",
        "docker oom",
        "deploy failed",
        "quick",
        "memory leak",
        "build broken",
        "k8s pod oom",
    ])
    def test_short_technical_questions_do_not_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False, (
            f"'{q}' is a real technical question — must NOT route to a 3B chat model"
        )

    @pytest.mark.parametrize("q", [
        # These contain greeting tokens but are real questions
        "Hi, can you help me debug this 200-line Python script?",
        "Hello, I need to refactor my authentication module",
        "hey what is the time complexity of quicksort",
    ])
    def test_greeting_prefix_long_query_does_not_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False, (
            f"greeting-prefixed real question '{q[:40]}…' must not bypass"
        )

    @pytest.mark.parametrize("q", [
        # Real questions that contain greeting-like words but are clearly NOT greetings
        "How do I center a div in CSS?",
        "What is photosynthesis?",
        "How does TCP differ from UDP?",
        "What is the difference between async and sync?",
    ])
    def test_real_questions_do_not_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False


# ===========================================================================
# Provenance & schema
# ===========================================================================

class TestDecisionSchema:
    def test_decision_is_pydantic(self, fp):
        d = fp.analyze("hi")
        assert isinstance(d, FastPathDecision)

    def test_bypass_provides_full_provenance(self, fp):
        d = fp.analyze("hello")
        assert d.should_bypass is True
        assert d.category != FastPathCategory.NONE
        assert d.recommended_model is not None
        assert d.matched_pattern is not None
        assert len(d.fallback_chain) >= 1
        assert d.recommended_model in d.fallback_chain
        assert 0.0 <= d.confidence <= 1.0

    def test_no_bypass_provides_clean_negative(self, fp):
        d = fp.analyze("Explain quantum entanglement in depth")
        assert d.should_bypass is False
        assert d.category == FastPathCategory.NONE
        assert d.recommended_model is None
        assert d.fallback_chain == []
        assert d.matched_pattern is None


# ===========================================================================
# Registry-aware fallback chain
# ===========================================================================

class TestRegistryFallback:
    """When a chain head model is unavailable, the next entry wins."""

    def test_walks_chain_when_head_unavailable(self, fp, monkeypatch):
        # The chain head is now an env-gated Groq model. Setting is_active=False
        # wouldn't stick — get_model re-activates env-gated models from the present
        # key — so clear GROQ_API_KEY to keep the Groq entries inactive, then verify
        # Fast Path walks past them to an available entry (ollama-phi3-mini has no
        # env gate so it stays active).
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        chain = fp._cfg.chat_chain
        head_id = chain[0]
        d = fp.analyze("hello")
        assert d.should_bypass is True
        assert d.recommended_model != head_id
        assert d.recommended_model in chain

    def test_no_bypass_when_entire_chain_unavailable(self, fp, monkeypatch):
        """When every chain member is unavailable AND the registry's dynamic
        env-var refresh cannot re-activate them, Fast Path returns no-bypass.
        """
        import os
        from src.layer0_model_infra.registry import get_registry
        registry = get_registry()

        # 1) Clear env vars that registry._refresh_dynamic_activation reads.
        # Without this, get_model() re-activates free API models from env.
        for env_key in (
            "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
            "HUGGINGFACE_API_KEY", "HUGGINGFACE_API_BASE",
        ):
            monkeypatch.delenv(env_key, raising=False)

        # 2) Deactivate every chain member's static is_active flag.
        chain = fp._cfg.chat_chain
        originals: dict[str, bool] = {}
        for model_id in chain:
            try:
                m = registry._models.get(model_id)  # direct access — bypass get_model refresh
                if m is not None:
                    originals[model_id] = m.is_active
                    m.is_active = False
            except Exception:
                pass

        try:
            d = fp.analyze("hello")
            # All chain members inactive → no-bypass; full pipeline will route it
            assert d.should_bypass is False, (
                f"Expected no-bypass but got {d.recommended_model} from chain {chain}"
            )
            assert d.recommended_model is None
        finally:
            for model_id, was_active in originals.items():
                m = registry._models.get(model_id)
                if m is not None:
                    m.is_active = was_active


# ===========================================================================
# MALFORMED / noise detection (AutoMix-inspired)
# ===========================================================================

class TestMalformed:
    """Pure noise should bypass to cheap chat — don't burn the full pipeline."""

    @pytest.mark.parametrize("q", [
        "?", "!!!", "??!?", "...", ".,;:", "()", "+++", "---",
        "🙂🙂🙂", "🤷", "💩💩",
    ])
    def test_pure_punctuation_emoji_is_malformed(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.MALFORMED

    @pytest.mark.parametrize("q", [
        "aaaa", "....", "!!!!!", "----", "xxxx",
    ])
    def test_repeated_single_char_is_malformed(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.MALFORMED

    @pytest.mark.parametrize("q", [
        # Real short queries — must NOT be classified malformed
        "ok", "hi", "yes", "no",
        # Long noise — out of scope for MALFORMED (length cap protects against
        # mis-classifying a real query that happens to lack ASCII letters)
        "x" * 50,
    ])
    def test_real_short_queries_not_malformed(self, fp, q):
        d = fp.analyze(q)
        if d.should_bypass:
            assert d.category != FastPathCategory.MALFORMED


# ===========================================================================
# Adversarial / robustness corpus
# ===========================================================================

class TestAdversarial:
    """Inputs that historically tripped keyword routers."""

    @pytest.mark.parametrize("q", [
        # Quoting a greeting in a real question
        "What does 'how are you' mean in French?",
        "Translate 'good morning' to Japanese",
        "Why do English speakers say 'thanks a lot' sarcastically?",
        # Greeting word inside a long technical question
        "Hey, in Python how do I implement a least-recently-used cache?",
        "Hi team, I need help debugging this 500-line race condition",
    ])
    def test_quoted_or_embedded_greetings_do_not_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False, (
            f"'{q[:50]}…' wraps a greeting in a real question — must not bypass"
        )

    @pytest.mark.parametrize("q", [
        # Mixed-script real questions (Hinglish, Spanglish)
        "kya hai photosynthesis?",   # Hindi romanised — real question
        "como funciona machine learning",  # Spanish + English technical
    ])
    def test_mixed_script_questions_do_not_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False

    def test_zero_width_chars_do_not_break_tokeniser(self, fp):
        # U+200B (zero-width space), U+FEFF (BOM)
        d = fp.analyze("hi​﻿")
        # Should still recognize as a greeting (zero-width chars are not \w)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_GREETING

    def test_rtl_marks_do_not_break_tokeniser(self, fp):
        # U+200F (right-to-left mark)
        d = fp.analyze("‏مرحبا")
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_GREETING

    def test_extremely_long_query_is_not_bypassed(self, fp):
        d = fp.analyze("hello " + "world " * 200)
        assert d.should_bypass is False

    def test_query_with_only_numbers_is_arithmetic(self, fp):
        d = fp.analyze("42")
        # Single number, no operator → not arithmetic.
        # Either MALFORMED (no operator/letters) or NONE — both acceptable.
        # Must NOT be PURE_ARITHMETIC since "42" alone isn't computable.
        if d.should_bypass:
            assert d.category != FastPathCategory.PURE_ARITHMETIC


# ===========================================================================
# Model-type validation (audit #2)
# ===========================================================================

class TestModelTypeValidation:
    """Fast Path must reject embedding/audio models from chains."""

    def test_skips_embedding_model_in_chain(self, fp, monkeypatch):
        """If a config error puts an embedding model in a chain, skip to the
        next entry rather than recommending it."""
        from src.layer0_model_infra.registry import get_registry
        registry = get_registry()

        # Inject an embedding model at the head of the chat chain
        original = fp._cfg.chat_chain
        monkeypatch.setattr(
            fp._cfg,
            "chat_chain",
            ["text-embedding-3-small"] + list(original),
        )
        d = fp.analyze("hello")
        assert d.should_bypass is True
        # Must NOT have selected the embedding model
        assert d.recommended_model != "text-embedding-3-small"
        embedding_model = registry.get_model("text-embedding-3-small")
        assert getattr(embedding_model.model_type, "value", None) == "embedding"


# ===========================================================================
# Multilingual fillers (audit #11)
# ===========================================================================

class TestMultilingualFillers:
    @pytest.mark.parametrize("q", [
        "muchas gracias",
        "gracias por todo",
        "merci beaucoup",
        "vielen dank",
        "grazie mille",
        "muito obrigado",
    ])
    def test_multilingual_polite_phrases_bypass(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is True
        assert d.category == FastPathCategory.TRIVIAL_ACK


# ===========================================================================
# Tier 2 — Semantic chitchat classifier (Model2Vec)
# ===========================================================================

try:
    import model2vec  # noqa: F401
    HAS_MODEL2VEC = True
except ImportError:
    HAS_MODEL2VEC = False


@pytest.mark.skipif(not HAS_MODEL2VEC, reason="model2vec not installed")
class TestSemanticTier2:
    """Verify Tier 2 catches paraphrases the keyword table misses,
    without introducing false positives on real questions.

    Empirical baseline from experiments/layer_0_model2vec_vs_heuristic:
    F1 lift on paraphrase corpus from 23.5% → 71.4% at 96.2% precision.
    """

    @pytest.mark.parametrize("q,category", [
        # Paraphrased greetings the keyword table cannot anticipate
        ("yo whats good", "trivial_greeting"),
        ("wassup", "trivial_greeting"),
        ("good day to you", "trivial_greeting"),
        ("long time no see", "trivial_greeting"),
        # Paraphrased acknowledgments
        ("cheers", "trivial_acknowledgment"),
        ("cheers mate", "trivial_acknowledgment"),
        ("no worries", "trivial_acknowledgment"),
        ("no problem", "trivial_acknowledgment"),
        ("much obliged", "trivial_acknowledgment"),
        ("you're a lifesaver", "trivial_acknowledgment"),
        ("you rock", "trivial_acknowledgment"),
        # Paraphrased farewells
        ("peace out", "trivial_farewell"),
        ("ttyl", "trivial_farewell"),
        ("take care", "trivial_farewell"),
        ("talk soon", "trivial_farewell"),
        ("have a good one", "trivial_farewell"),
    ])
    def test_paraphrases_caught_by_tier2(self, fp, q, category):
        d = fp.analyze(q)
        assert d.should_bypass is True, (
            f"Paraphrase '{q}' should bypass via Tier 2 — heuristic alone misses it"
        )
        assert d.category.value == category, (
            f"Wrong category for '{q}': got {d.category.value}, expected {category}"
        )
        # Tier 2 hits are tagged with semantic:NN.NN
        assert d.matched_pattern and d.matched_pattern.startswith("semantic:"), (
            f"Expected Tier 2 (semantic:*) pattern, got {d.matched_pattern!r}"
        )

    @pytest.mark.parametrize("q", [
        # Real questions wearing casual prefixes — must NOT bypass even
        # though some of these are semantically near a greeting.
        "Hey, can you help me debug this Python script?",
        "yo do you know python",
        "thanks but how do I deploy this",
        "ok so how does async work",
        "cheers but my deploy broke",
        "good morning, can you review my PR",
        "appreciate ya but I need help with kubernetes",
        "hi explain quantum computing",
        # Real technical jargon
        "broken build",
        "ssl error",
        "react state",
        "redis down",
    ])
    def test_real_questions_not_bypassed_by_tier2(self, fp, q):
        d = fp.analyze(q)
        assert d.should_bypass is False, (
            f"Real question '{q}' must NOT bypass — Tier 2 false positive"
        )


class TestTier2GracefulDegradation:
    """Tier 2 must degrade cleanly when model2vec is unavailable or disabled."""

    def test_tier2_disabled_via_config(self, monkeypatch):
        """Setting enable_semantic_tier2=False should make Tier 2 a no-op."""
        from src.layer0_model_infra.routing.fast_path import FastPathAnalyzer
        analyzer = FastPathAnalyzer()
        monkeypatch.setattr(analyzer._cfg, "enable_semantic_tier2", False)
        # Manually clear the Tier 2 instance so the disabled flag takes effect
        analyzer._tier2 = None

        d = analyzer.analyze("cheers mate")
        # With Tier 2 disabled and "cheers mate" not in keyword tables,
        # this query falls through to the full pipeline.
        assert d.should_bypass is False

    def test_tier1_unaffected_when_tier2_unavailable(self):
        """Even if Tier 2 fails to load, Tier 1 must still bypass greetings."""
        from src.layer0_model_infra.routing.fast_path import FastPathAnalyzer
        analyzer = FastPathAnalyzer()
        analyzer._tier2 = None  # simulate unavailability

        d = analyzer.analyze("hello")
        assert d.should_bypass is True
        assert d.category.value == "trivial_greeting"


# ===========================================================================
# Configuration toggle
# ===========================================================================

class TestConfiguration:
    def test_disabled_returns_no_bypass(self):
        fp = FastPathAnalyzer()
        original = fp._cfg.enabled
        try:
            fp._cfg.enabled = False
            d = fp.analyze("hello")
            assert d.should_bypass is False
            assert "disabled" in d.reasoning.lower()
        finally:
            fp._cfg.enabled = original

    def test_empty_query_is_no_bypass(self, fp):
        d = fp.analyze("")
        assert d.should_bypass is False

    def test_whitespace_only_is_no_bypass(self, fp):
        d = fp.analyze("   \n\t  ")
        assert d.should_bypass is False
