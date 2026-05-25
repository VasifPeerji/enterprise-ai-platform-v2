"""
Tests for the Stage B feature extractor.

Key things this guards against:
  • The "vision → MEDICAL → premium tier" class of bug from the old Layer 3 —
    we explicitly test that common false-positive phrases DON'T get tagged
    as high-risk domains
  • Code, math, and vision modality detection on representative inputs
  • Language detection across scripts (CJK, Arabic, Devanagari) + Hinglish
  • Token estimation is roughly right for different scripts
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.routing.feature_extractor import (
    FeatureExtractor,
    get_feature_extractor,
    reset_feature_extractor,
)
from src.layer0_model_infra.routing.layer3_types import (
    DifficultySignal,
    HighRiskDomain,
    Modality,
)


@pytest.fixture
def extractor() -> FeatureExtractor:
    return FeatureExtractor()


# ---------------------------------------------------------------------------
# Modality
# ---------------------------------------------------------------------------


def test_text_query_is_text(extractor):
    f = extractor.extract("Explain backpropagation in one paragraph.")
    assert f.modality == Modality.TEXT
    assert f.has_code_block is False
    assert f.has_image_attachment is False


def test_code_block_query_is_code(extractor):
    f = extractor.extract("Fix this bug:\n```python\ndef foo():\n    return 1+1\n```")
    assert f.modality == Modality.CODE
    assert f.has_code_block is True


def test_python_def_signature_detected_as_code(extractor):
    f = extractor.extract("def fibonacci(n: int) -> int: return n if n < 2 else fibonacci(n-1) + fibonacci(n-2)")
    assert f.modality == Modality.CODE


def test_sql_query_detected_as_code(extractor):
    f = extractor.extract("SELECT user_id, COUNT(*) FROM orders WHERE created_at > '2026-01-01' GROUP BY user_id")
    assert f.modality == Modality.CODE


def test_math_query_is_math(extractor):
    f = extractor.extract("Prove that the sum of the first n natural numbers is n*(n+1)/2")
    assert f.modality == Modality.MATH


def test_latex_inline_detected_as_math(extractor):
    f = extractor.extract("Compute $\\int_0^1 x^2 dx$ analytically.")
    assert f.modality == Modality.MATH


def test_image_attachment_with_reference_is_vision(extractor):
    f = extractor.extract(
        "Describe what is in this image.",
        has_image_attachment=True,
    )
    assert f.modality == Modality.VISION


def test_image_attachment_without_reference_with_short_query_is_vision(extractor):
    # Short query + image → assume the image is the subject
    f = extractor.extract("?", has_image_attachment=True)
    assert f.modality == Modality.VISION


def test_image_attachment_without_reference_with_long_query_falls_to_text(extractor):
    """An image attached for 'context' shouldn't force vision routing if the
    text is clearly about something else — same heuristic as Layer 1's
    require_vision_reference."""
    f = extractor.extract(
        "I attached a screenshot for context. The actual question is, how do I "
        "refactor this 200-line Python module to use dependency injection? "
        "I'm thinking of using protocols rather than abstract base classes "
        "because the type signatures end up cleaner.",
        has_image_attachment=True,
    )
    assert f.modality != Modality.VISION


def test_code_block_plus_image_is_multimodal(extractor):
    f = extractor.extract(
        "Fix this:\n```python\ndef foo(): pass\n```\nAlso see attached.",
        has_image_attachment=True,
    )
    assert f.modality == Modality.MULTIMODAL


# ---------------------------------------------------------------------------
# Anti-over-routing on the high-risk domain detector
# ---------------------------------------------------------------------------
# The previous Layer 3 had a MEDICAL keyword list that included "vision",
# "leg", "bone", "pain", "care". These tests pin down that the new narrow
# patterns don't repeat that mistake.


@pytest.mark.parametrize("query", [
    "What's the latest research in computer vision?",
    "Show me a vision pipeline in PyTorch",
    "Vision transformers vs ConvNets",
    "Build a vision-language model architecture",
])
def test_vision_keyword_does_not_trigger_medical(extractor, query):
    f = extractor.extract(query)
    assert f.high_risk_domain is None, (
        f"REGRESSION: '{query}' tagged as {f.high_risk_domain} — "
        f"this is the 3.R1 / 3.B2 'vision → MEDICAL' bug coming back"
    )


@pytest.mark.parametrize("query", [
    "Pain in the neck to debug this issue",
    "I have a leg of lamb recipe — how do I roast it?",
    "Climbing the corporate ladder is a long career road",
    "Bone china is delicate, how should I wash it?",
    "Take care of business as soon as possible",
])
def test_idiomatic_medical_words_dont_trigger_medical(extractor, query):
    f = extractor.extract(query)
    assert f.high_risk_domain is None, (
        f"REGRESSION: '{query}' tagged as {f.high_risk_domain} — narrow "
        f"medical patterns are too loose"
    )


@pytest.mark.parametrize("query", [
    "Class action lawsuit advice for tenants",
    "What's the difference between a class and a struct in Java?",
    "I want to take a Coursera class on machine learning",
])
def test_class_keyword_doesnt_always_trigger_legal(extractor, query):
    f = extractor.extract(query)
    if "lawsuit" in query.lower() or "tenant" in query.lower():
        assert f.high_risk_domain == HighRiskDomain.LEGAL
    else:
        assert f.high_risk_domain is None


# ---------------------------------------------------------------------------
# True positives for high-risk domains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", [
    "What is the safe dosage of ibuprofen for a 70kg adult?",
    "Should I take metformin with my morning coffee?",
    "Is it safe to take antidepressants while pregnant?",
    "What are the symptoms of a vitamin D deficiency?",
])
def test_medical_queries_flagged(extractor, query):
    f = extractor.extract(query)
    assert f.high_risk_domain == HighRiskDomain.MEDICAL, (
        f"medical query not flagged: '{query}'"
    )


@pytest.mark.parametrize("query", [
    "What are my legal rights after a car accident?",
    "Should I sue my landlord for an eviction notice?",
    "I need to consult a lawyer about a contract dispute",
])
def test_legal_queries_flagged(extractor, query):
    f = extractor.extract(query)
    assert f.high_risk_domain == HighRiskDomain.LEGAL


@pytest.mark.parametrize("query", [
    "Should I invest my 401k in index funds?",
    "Give me investment advice for retirement planning",
    "How do I file a tax return as an LLC owner?",
    "What's the best wealth management strategy for high net worth?",
])
def test_financial_queries_flagged(extractor, query):
    f = extractor.extract(query)
    assert f.high_risk_domain == HighRiskDomain.FINANCIAL


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def test_english_default(extractor):
    f = extractor.extract("How do I deploy a docker container?")
    assert f.language == "en"


def test_japanese_detected(extractor):
    f = extractor.extract("こんにちは、機械学習について教えてください。")
    assert f.language == "ja"


def test_chinese_detected(extractor):
    f = extractor.extract("请解释一下神经网络的工作原理。")
    assert f.language == "zh"


def test_arabic_detected(extractor):
    f = extractor.extract("ما هو الذكاء الاصطناعي؟ اشرح لي بالتفصيل.")
    assert f.language == "ar"


def test_devanagari_detected_as_hindi(extractor):
    f = extractor.extract("मशीन लर्निंग क्या है? मुझे विस्तार से समझाइए।")
    assert f.language == "hi"


def test_hinglish_in_latin_script(extractor):
    """Hinglish (Hindi in Latin script) was a known gap of the old detector."""
    f = extractor.extract("Bhai yaar mujhe kya batao kaise karna hai")
    assert f.language == "hi-Latn"


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def test_token_estimation_english_roughly_4_chars_per_token(extractor):
    text = "x" * 400
    f = extractor.extract(text)
    # 400 chars / 4 ≈ 100 tokens
    assert 90 <= f.estimated_input_tokens <= 110


def test_token_estimation_cjk_roughly_1_char_per_token(extractor):
    # 100 CJK chars (need ≥3 for language detection to trigger 'zh')
    text = "神" * 100
    f = extractor.extract(text)
    assert f.language == "zh"
    # 100 chars × 1 ≈ 100 tokens
    assert 90 <= f.estimated_input_tokens <= 110


def test_output_tokens_default_per_modality(extractor):
    code_f = extractor.extract("```python\ndef foo(): pass\n```")
    text_f = extractor.extract("What is the meaning of life?")
    assert code_f.estimated_output_tokens > text_f.estimated_output_tokens


# ---------------------------------------------------------------------------
# Difficulty signal (consumed by length-adjusted similarity — P3)
# ---------------------------------------------------------------------------


def test_trivial_difficulty_on_very_short_query(extractor):
    f = extractor.extract("Hi")
    assert f.difficulty_signal == DifficultySignal.TRIVIAL


def test_hard_difficulty_on_proof_request(extractor):
    f = extractor.extract("Prove the Riemann hypothesis using analytic continuation")
    assert f.difficulty_signal == DifficultySignal.HARD


def test_hard_difficulty_on_distributed_system_design(extractor):
    f = extractor.extract(
        "Design a fault-tolerant distributed system for processing 1M events per second "
        "with exactly-once semantics, multi-region replication, and sub-100ms p99 latency."
    )
    assert f.difficulty_signal == DifficultySignal.HARD


def test_normal_difficulty_on_typical_question(extractor):
    f = extractor.extract("How do I use Python list comprehensions?")
    assert f.difficulty_signal == DifficultySignal.NORMAL


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_query_returns_default_features(extractor):
    f = extractor.extract("")
    assert f.language == "en"
    assert f.modality == Modality.TEXT
    assert f.high_risk_domain is None
    assert f.char_count == 0


def test_whitespace_only_query_is_empty(extractor):
    f = extractor.extract("   \n\n\t  ")
    assert f.char_count == 0


def test_none_query_handled(extractor):
    f = extractor.extract(None)  # type: ignore
    assert f.language == "en"
    assert f.char_count == 0


def test_hidden_unicode_stripped(extractor):
    """U+200B (ZWSP) and U+202E (RLO) should be removed before feature extraction."""
    query = "Hello​world‮!"
    f = extractor.extract(query)
    # Stripped to "Helloworld!"
    assert f.char_count == len("Helloworld!")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton_returns_same_instance(reset_feature_extractor):
    a = get_feature_extractor()
    b = get_feature_extractor()
    assert a is b


def test_reset_creates_fresh_singleton(reset_feature_extractor):
    a = get_feature_extractor()
    reset_feature_extractor_module()
    b = get_feature_extractor()
    assert a is not b


def reset_feature_extractor_module():
    """Local helper because the fixture uses the same name."""
    from src.layer0_model_infra.routing import feature_extractor
    feature_extractor.reset_feature_extractor()
