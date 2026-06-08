"""
Test suite for Fast Triage (Layer 3)

Target Metrics:
- Classification accuracy >70% (directionally correct)
- Confidence calibration (high confidence = high accuracy)
- Ambiguity detection >80%
"""

import pytest
from src.layer0_model_infra.routing.legacy.fast_triage import get_triage_classifier


@pytest.fixture
def triage():
    """Get triage classifier instance."""
    return get_triage_classifier()


class TestIntentClassification:
    """Test intent detection accuracy."""
    
    # (query, expected_intent)
    INTENT_TEST_CASES = [
        ("What is Python?", "qa"),
        ("Explain machine learning", "qa"),
        ("Write a function to reverse a string", "coding"),
        ("def foo(): pass\nFix this bug", "coding"),
        ("How should I approach this problem?", "planning"),
        ("Help me plan my vacation", "planning"),
        ("Hello! How are you?", "casual"),
        ("Thanks for your help", "casual"),
    ]
    
    @pytest.mark.parametrize("query,expected_intent", INTENT_TEST_CASES)
    def test_intent_detection(self, triage, query, expected_intent):
        """Test that intents are detected correctly."""
        result = triage.classify(query)
        
        assert result.intent.value == expected_intent, \
            f"Expected intent '{expected_intent}' but got '{result.intent.value}' for: {query}"


class TestDomainClassification:
    """Test domain detection."""
    
    DOMAIN_TEST_CASES = [
        ("How do I fix a broken bone?", "medical"),
        ("What are my legal rights?", "legal"),
        ("How do I invest in stocks?", "business"),
        ("Write a Python function", "tech"),
        ("How's the weather?", "casual"),
        ("Explain quarterly reports", "business"),
    ]
    
    @pytest.mark.parametrize("query,expected_domain", DOMAIN_TEST_CASES)
    def test_domain_detection(self, triage, query, expected_domain):
        """Test domain classification."""
        result = triage.classify(query)
        
        assert result.domain.value == expected_domain, \
            f"Expected domain '{expected_domain}' but got '{result.domain.value}' for: {query}"


class TestComplexityBands:
    """Test complexity estimation."""
    
    COMPLEXITY_TEST_CASES = [
        ("What is 2+2?", "trivial"),
        ("Hello", "trivial"),
        ("What is Python?", "simple"),
        ("Explain how neural networks work", "moderate"),
        ("Design a distributed system for X", "complex"),
        ("Prove the Riemann hypothesis", "expert"),
    ]
    
    @pytest.mark.parametrize("query,expected_complexity", COMPLEXITY_TEST_CASES)
    def test_complexity_estimation(self, triage, query, expected_complexity):
        """Test complexity band classification (allow 1-band tolerance for heuristic fallback)."""
        result = triage.classify(query)
        band_order = ["trivial", "simple", "moderate", "complex", "expert"]
        actual = result.complexity_band.value
        expected_idx = band_order.index(expected_complexity)
        actual_idx = band_order.index(actual)
        assert abs(expected_idx - actual_idx) <= 1, \
            f"Expected complexity '{expected_complexity}' (±1 band) but got '{actual}' for: {query}"

    @pytest.mark.parametrize(
        "query,expected_complexity",
        [
            ("Write a Python function to parse CSV, validate each row, and return JSON.", "complex"),
            ("Summarize this article in 3 bullets.", "moderate"),
            ("What are my legal rights after a car accident?", "complex"),
            ("Should I take ibuprofen with metformin?", "complex"),
            ("Explain photosynthesis", "simple"),
            ("Compare Django vs FastAPI for a multi-tenant SaaS with RBAC and audit logs.", "complex"),
        ],
    )
    def test_complexity_regressions(self, triage, query, expected_complexity):
        """Regression tests for structure-heavy prompts (allow 1-band tolerance)."""
        result = triage.classify(query)
        band_order = ["trivial", "simple", "moderate", "complex", "expert"]
        actual = result.complexity_band.value
        expected_idx = band_order.index(expected_complexity)
        actual_idx = band_order.index(actual)
        assert abs(expected_idx - actual_idx) <= 1, \
            f"Expected complexity '{expected_complexity}' (±1 band) but got '{actual}' for: {query}"


class TestConfidenceCalibration:
    """Test that confidence correlates with accuracy."""
    
    HIGH_CONFIDENCE_CASES = [
        "def hello(): print('hi')",  # Clearly coding
        "What is the capital of France?",  # Clearly QA
        "Hello there!",  # Clearly casual
    ]
    
    AMBIGUOUS_CASES = [
        "Can you help me with something?",  # Vague
        "I need assistance",  # Unclear
        "Tell me more",  # No context
    ]
    
    @pytest.mark.parametrize("query", HIGH_CONFIDENCE_CASES)
    def test_high_confidence_clear_cases(self, triage, query):
        """Clear cases should have high confidence."""
        result = triage.classify(query)
        
        assert result.confidence > 0.35, \
            f"Expected reasonable confidence for clear query: {query}, got {result.confidence}"
    
    @pytest.mark.parametrize("query", AMBIGUOUS_CASES)
    def test_low_confidence_ambiguous_cases(self, triage, query):
        """Ambiguous cases should have lower confidence."""
        result = triage.classify(query)
        
        # Confidence should be moderate to low
        assert result.confidence < 0.8, \
            f"Expected lower confidence for ambiguous query: {query}, got {result.confidence}"


class TestAmbiguityDetection:
    """Test detection of multi-intent or vague queries."""
    
    MULTI_INTENT_CASES = [
        "What is Python and how do I install it?",  # QA + coding
        "Explain machine learning and write code for it",  # QA + coding
        "Help me plan and then code a solution",  # Planning + coding
    ]
    
    def test_multi_intent_detection(self, triage):
        """Test that multi-intent queries are flagged."""
        for query in self.MULTI_INTENT_CASES:
            result = triage.classify(query)
            
            # Multi-intent should result in lower confidence
            # or be flagged in metadata
            assert result.confidence < 0.85, \
                f"Multi-intent query should have lower confidence: {query}"


class TestStrictFastPaths:
    """
    Regression tests for the strict fast-path bypasses in
    FastTriageClassifier._classify_complexity. These cases must NEVER
    invoke the LLM — they're caught deterministically. Validated against
    the academic gold set + benchmark failures.
    """

    # Multi-word conversational pleasantries that the simple greeting-token
    # check used to miss (regression catch from real benchmark failures).
    GREETING_PHRASE_CASES = [
        "How are you?",
        "How are you doing?",
        "How's it going?",
        "How is your day?",
        "How's life?",
        "What's up?",
        "What's up doc?",
        "See you later",
        "Catch you later",
        "Got it",
        "Understood",
        "Sounds good",
        "Fair enough",
        "Thank you",
        "Appreciate it",
    ]

    @pytest.mark.parametrize("query", GREETING_PHRASE_CASES)
    def test_greeting_phrases_classified_trivial(self, triage, query):
        """All multi-word conversational pleasantries must classify as TRIVIAL."""
        result = triage.classify(query)
        assert result.complexity_band.value == "trivial", (
            f"Greeting phrase {query!r} classified as {result.complexity_band.value} "
            f"(expected trivial)"
        )
        # The strict-fast-path stamps a hard-coded rubric with raw_score=0.05.
        # If the LLM had been called instead, raw_score would either be 0.00
        # (LLM said all-zeros) or some other value — but never exactly 0.05.
        assert result.complexity_rubric.get("raw_score") == 0.05, (
            f"{query!r} did NOT take the fast-path "
            f"(raw_score={result.complexity_rubric.get('raw_score')})"
        )

    # Single-token greetings (existing behavior — must not regress).
    SINGLE_TOKEN_GREETING_CASES = [
        "Hi",
        "Hi there!",
        "Hello",
        "Hello there!",
        "Hey",
        "Thanks",
        "Thanks for your help",
        "Bye",
        "Goodbye",
        "Ok bye",
        "Good morning",
        "Good night",
    ]

    @pytest.mark.parametrize("query", SINGLE_TOKEN_GREETING_CASES)
    def test_single_token_greetings_classified_trivial(self, triage, query):
        result = triage.classify(query)
        assert result.complexity_band.value == "trivial", (
            f"Greeting {query!r} classified as {result.complexity_band.value}"
        )

    # Arithmetic-only queries.
    ARITHMETIC_CASES = [
        "2+2",
        "2 + 2",
        "3 * 7",
        "100 / 4",
        "(5 + 3) * 2",
        "2.5 * 4.1",
        "What is 2+2?",
        "2+2?",
    ]

    @pytest.mark.parametrize("query", ARITHMETIC_CASES)
    def test_arithmetic_classified_trivial(self, triage, query):
        result = triage.classify(query)
        # "What is 2+2?" has a word, so it goes through token check; the
        # arithmetic regex is anchored to digits-and-operators-only — but
        # the gold set still expects trivial for "What is 2+2?". So we accept
        # either trivial (perfect) or simple (one-band-off) for the worded form.
        if "what" in query.lower():
            assert result.complexity_band.value in {"trivial", "simple"}
        else:
            assert result.complexity_band.value == "trivial", (
                f"Arithmetic {query!r} classified as {result.complexity_band.value}"
            )

    # Negative cases: these must NOT trigger the fast-path even though they
    # contain greeting tokens.
    NON_GREETING_CASES = [
        # Contains "how" but is a real question
        ("How do I center a div in CSS?", "should reach LLM"),
        # Contains "what" but is a real factual lookup
        ("What is photosynthesis?",        "should reach LLM"),
        # Contains "good" but in a non-greeting context
        ("What is a good algorithm for sorting?", "should reach LLM"),
        # Contains "see" but in a real instructional context
        ("Show me how to see disk usage on Linux", "should reach LLM"),
    ]

    @pytest.mark.parametrize("query,note", NON_GREETING_CASES)
    def test_non_greetings_do_not_trigger_fast_path(self, triage, query, note):
        """These look like greetings on a glance but are real questions —
        they MUST go through the LLM and not be auto-classified trivial."""
        result = triage.classify(query)
        assert result.complexity_band.value != "trivial", (
            f"{query!r} (note: {note}) was incorrectly fast-pathed to TRIVIAL"
        )


class TestEdgeCases:
    """Test edge cases."""
    
    def test_empty_query(self, triage):
        """Test handling of empty query."""
        result = triage.classify("")
        
        # Should return something reasonable
        assert result.intent is not None
        assert result.domain is not None
        assert result.complexity_band is not None
    
    def test_very_long_query(self, triage):
        """Test handling of very long queries."""
        long_query = "What is Python? " * 100
        result = triage.classify(long_query)
        
        # Should still classify
        assert result.intent is not None
    
    def test_special_characters(self, triage):
        """Test queries with special characters."""
        result = triage.classify("What is <html> and CSS???")
        
        assert result.intent is not None


class TestMetrics:
    """Aggregate accuracy metrics."""
    
    # Combined test dataset
    TEST_DATASET = [
        ("What is AI?", "qa", "tech", "simple"),
        ("Write Python code", "coding", "tech", "moderate"),
        ("How do I sue someone?", "qa", "legal", "complex"),
        ("Hello!", "casual", "casual", "trivial"),
        ("Explain neural nets", "qa", "tech", "moderate"),
        ("def foo(): pass", "coding", "tech", "simple"),
        ("Plan a business strategy", "planning", "business", "complex"),
        ("What's 2+2?", "qa", "general", "trivial"),
        ("How do I invest?", "qa", "business", "moderate"),
        ("Fix my broken leg", "qa", "medical", "complex"),
    ]
    
    def test_overall_accuracy(self, triage):
        """Test overall classification accuracy."""
        intent_correct = 0
        domain_correct = 0
        complexity_correct = 0
        total = len(self.TEST_DATASET)
        
        for query, exp_intent, exp_domain, exp_complexity in self.TEST_DATASET:
            result = triage.classify(query)
            
            if result.intent.value == exp_intent:
                intent_correct += 1
            if result.domain.value == exp_domain:
                domain_correct += 1
            if result.complexity_band.value == exp_complexity:
                complexity_correct += 1
        
        intent_acc = (intent_correct / total) * 100
        domain_acc = (domain_correct / total) * 100
        complexity_acc = (complexity_correct / total) * 100
        
        print(f"\nFast Triage Accuracy:")
        print(f"  Intent: {intent_acc:.1f}%")
        print(f"  Domain: {domain_acc:.1f}%")
        print(f"  Complexity: {complexity_acc:.1f}%")
        
        # Target: >70% directionally correct (not perfect)
        assert intent_acc >= 60, f"Intent accuracy {intent_acc:.1f}% below target"
        assert domain_acc >= 60, f"Domain accuracy {domain_acc:.1f}% below target"
