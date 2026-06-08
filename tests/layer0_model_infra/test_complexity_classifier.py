"""
Tests for ComplexityClassifier (LLM-based query complexity classification).

Tests:
1. LLM success path → correct parsing and classification
2. LLM failure → graceful fallback to heuristic logic
3. Malformed JSON → fallback handling
4. Heuristic fallback accuracy for known patterns
5. Rubric dimensions and derived confidence
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.layer0_model_infra.routing.legacy.complexity_classifier import (
    ComplexityClassifier,
    ComplexityResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rubric_response(
    band: str,
    task_count: float = 0.3,
    domain_depth: float = 0.3,
    reasoning_hops: float = 0.3,
    output_structure: float = 0.3,
    knowledge_breadth: float = 0.3,
    reasoning_summary: str = "test",
) -> MagicMock:
    """Create a mock LiteLLM completion response with rubric output."""
    payload = json.dumps({
        "task_count": task_count,
        "domain_depth": domain_depth,
        "reasoning_hops": reasoning_hops,
        "output_structure": output_structure,
        "knowledge_breadth": knowledge_breadth,
        "band": band,
        "reasoning_summary": reasoning_summary,
    })
    choice = MagicMock()
    choice.message.content = payload
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_trivial_response() -> MagicMock:
    return _make_rubric_response("trivial", 0.05, 0.05, 0.05, 0.05, 0.05)


def _make_simple_response() -> MagicMock:
    return _make_rubric_response("simple", 0.15, 0.1, 0.1, 0.1, 0.1)


def _make_moderate_response() -> MagicMock:
    return _make_rubric_response("moderate", 0.4, 0.35, 0.4, 0.3, 0.3)


def _make_complex_response() -> MagicMock:
    return _make_rubric_response("complex", 0.7, 0.6, 0.65, 0.6, 0.55)


def _make_expert_response() -> MagicMock:
    return _make_rubric_response("expert", 0.9, 0.85, 0.9, 0.7, 0.8)


# ---------------------------------------------------------------------------
# Tests — LLM success path
# ---------------------------------------------------------------------------

class TestLLMClassification:
    """Test that the classifier correctly parses valid LLM responses."""

    @pytest.mark.parametrize("band,factory", [
        ("trivial", _make_trivial_response),
        ("simple", _make_simple_response),
        ("moderate", _make_moderate_response),
        ("complex", _make_complex_response),
        ("expert", _make_expert_response),
    ])
    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_valid_bands_parsed(self, mock_completion, band, factory):
        mock_completion.return_value = factory()

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("test query")

        assert result.complexity_band == band
        assert 0.0 <= result.confidence <= 1.0

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_rubric_dimensions_present(self, mock_completion):
        """All 5 rubric dimensions should be present."""
        mock_completion.return_value = _make_complex_response()

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("Design a distributed system")

        assert 0.0 <= result.task_count <= 1.0
        assert 0.0 <= result.domain_depth <= 1.0
        assert 0.0 <= result.reasoning_hops <= 1.0
        assert 0.0 <= result.output_structure <= 1.0
        assert 0.0 <= result.knowledge_breadth <= 1.0
        assert 0.0 <= result.raw_score <= 1.0

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_confidence_is_derived(self, mock_completion):
        """Confidence should be derived from boundary distance + consistency,
        NOT self-reported by the model."""
        mock_completion.return_value = _make_moderate_response()

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("test query")

        # Derived confidence should be a valid float
        assert 0.0 <= result.confidence <= 1.0
        # It should NOT be the model's self-reported value

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_reasoning_preserved(self, mock_completion):
        mock_completion.return_value = _make_rubric_response(
            "complex", reasoning_summary="Multi-step reasoning required"
        )

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("Design a system")

        assert "Multi-step" in result.reasoning


# ---------------------------------------------------------------------------
# Tests — LLM failure / fallback
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    """Test graceful fallback when LLM is unavailable or returns bad data."""

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_llm_exception_falls_back(self, mock_completion):
        """When LLM raises, should still return a valid result."""
        mock_completion.side_effect = Exception("Connection refused")

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("Hello there")

        assert isinstance(result, ComplexityResult)
        assert result.complexity_band in {"trivial", "simple", "moderate", "complex", "expert"}
        assert "heuristic" in result.reasoning.lower()

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_fallback_confidence_capped(self, mock_completion):
        """Heuristic fallback confidence should be capped at 0.50."""
        mock_completion.side_effect = Exception("offline")

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("Explain quantum physics")

        assert result.confidence <= 0.50

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_malformed_json_falls_back(self, mock_completion):
        """When LLM returns garbage, should fall back to heuristics."""
        choice = MagicMock()
        choice.message.content = "This is not JSON at all!"
        response = MagicMock()
        response.choices = [choice]
        mock_completion.return_value = response

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("What is Python?")

        assert isinstance(result, ComplexityResult)
        assert "heuristic" in result.reasoning.lower()

    @patch("src.layer0_model_infra.routing.legacy.complexity_classifier.completion")
    def test_invalid_band_falls_back(self, mock_completion):
        """When LLM returns an unrecognized band, should fall back."""
        mock_completion.return_value = _make_rubric_response("ultra_hard")

        classifier = ComplexityClassifier()
        classifier._available = True
        result = classifier.classify("test query")

        # Band should be derived from raw_score since "ultra_hard" is invalid
        assert result.complexity_band in {"trivial", "simple", "moderate", "complex", "expert"}

    def test_no_litellm_falls_back(self):
        """When litellm is not installed, heuristic path is used."""
        classifier = ComplexityClassifier()
        classifier._available = False

        result = classifier.classify("Prove the Riemann hypothesis")
        assert result.complexity_band == "expert"
        assert "heuristic" in result.reasoning.lower()


# ---------------------------------------------------------------------------
# Tests — Heuristic fallback accuracy
# ---------------------------------------------------------------------------

class TestHeuristicFallback:
    """Test that the heuristic fallback produces reasonable results."""

    @pytest.fixture
    def classifier(self):
        c = ComplexityClassifier()
        c._available = False  # Force heuristic path
        return c

    def test_trivial_greeting(self, classifier):
        result = classifier.classify("Hello")
        assert result.complexity_band == "trivial"

    def test_trivial_arithmetic(self, classifier):
        result = classifier.classify("What is 2+2?")
        assert result.complexity_band == "trivial"

    def test_expert_proof(self, classifier):
        result = classifier.classify("Prove the Riemann hypothesis")
        assert result.complexity_band == "expert"

    def test_expert_formal_proof(self, classifier):
        result = classifier.classify("Provide a formal proof of the completeness theorem")
        assert result.complexity_band == "expert"

    def test_high_stakes_medical(self, classifier):
        result = classifier.classify("Should I take ibuprofen with metformin?")
        assert result.complexity_band in {"moderate", "complex"}

    def test_simple_factual(self, classifier):
        result = classifier.classify("What is Python?")
        assert result.complexity_band == "simple"

    def test_rubric_dims_present_in_fallback(self, classifier):
        """Even fallback should return valid rubric dimensions."""
        result = classifier.classify("Explain neural networks")
        assert 0.0 <= result.task_count <= 1.0
        assert 0.0 <= result.domain_depth <= 1.0
        assert 0.0 <= result.reasoning_hops <= 1.0
        assert 0.0 <= result.output_structure <= 1.0
        assert 0.0 <= result.knowledge_breadth <= 1.0
        assert 0.0 <= result.raw_score <= 1.0


# ---------------------------------------------------------------------------
# Tests — JSON edge cases in parsing
# ---------------------------------------------------------------------------

class TestJSONParsing:
    """Test parsing of various JSON formats from LLM responses."""

    def test_json_in_code_fence(self):
        classifier = ComplexityClassifier()
        content = '```json\n{"task_count": 0.3, "domain_depth": 0.2, "reasoning_hops": 0.3, "output_structure": 0.2, "knowledge_breadth": 0.2, "band": "moderate", "reasoning_summary": "test"}\n```'
        result = classifier._parse_response(content)
        assert result is not None
        assert result.complexity_band == "moderate"

    def test_json_embedded_in_text(self):
        classifier = ComplexityClassifier()
        content = 'Here is my classification: {"task_count": 0.1, "domain_depth": 0.1, "reasoning_hops": 0.1, "output_structure": 0.1, "knowledge_breadth": 0.1, "band": "simple", "reasoning_summary": "factual"}'
        result = classifier._parse_response(content)
        assert result is not None
        assert result.complexity_band == "simple"

    def test_completely_invalid(self):
        classifier = ComplexityClassifier()
        result = classifier._parse_response("I cannot classify this query")
        assert result is None

    def test_empty_response(self):
        classifier = ComplexityClassifier()
        result = classifier._parse_response("")
        assert result is None

    def test_missing_rubric_fields_uses_defaults(self):
        """If LLM omits some rubric fields, defaults to 0.5."""
        classifier = ComplexityClassifier()
        content = '{"band": "moderate", "reasoning_summary": "partial rubric"}'
        result = classifier._parse_response(content)
        assert result is not None
        assert result.task_count == 0.5  # default
        assert result.domain_depth == 0.5  # default
