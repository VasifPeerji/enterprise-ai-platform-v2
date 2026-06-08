"""
Test suite for Uncertainty Estimation (Layer 4)

Target Metrics:
- Calibration: High uncertainty → safer routing
- Misroute correlation: High uncertainty = fewer failures
- Multi-signal integration accuracy
"""

import pytest
from src.layer0_model_infra.routing.legacy.uncertainty_estimator import get_uncertainty_estimator
from src.layer0_model_infra.routing.input_signals import get_input_extractor


@pytest.fixture
def uncertainty_estimator():
    """Get uncertainty estimator instance."""
    return get_uncertainty_estimator()


@pytest.fixture
def input_extractor():
    """Get input signal extractor."""
    return get_input_extractor()


class TestBasicUncertaintyEstimation:
    """Test basic uncertainty calculation."""
    
    def test_high_confidence_low_uncertainty(self, uncertainty_estimator):
        """High classifier confidence should yield low uncertainty."""
        result = uncertainty_estimator.estimate(
            query="What is 2+2?",
            classifier_confidence=0.95,  # High confidence
            query_length=5,
            novelty_score=0.1,  # Low novelty
        )
        
        assert result.total_uncertainty < 0.4, "High confidence should yield low uncertainty"
        assert result.confidence_level == "HIGH"
    
    def test_low_confidence_high_uncertainty(self, uncertainty_estimator):
        """Low classifier confidence should yield high uncertainty."""
        result = uncertainty_estimator.estimate(
            query="Explain the implications of quantum entanglement on causality",
            classifier_confidence=0.3,  # Low confidence
            query_length=50,
            novelty_score=0.9,  # High novelty
        )
        
        assert result.total_uncertainty > 0.6, "Low confidence should yield high uncertainty"
        assert result.confidence_level == "LOW"


class TestMultiSignalIntegration:
    """Test that multiple signals are properly combined."""
    
    def test_novelty_increases_uncertainty(self, uncertainty_estimator):
        """High novelty should increase uncertainty."""
        # Low novelty case
        result_familiar = uncertainty_estimator.estimate(
            query="What is Python?",
            classifier_confidence=0.8,
            query_length=10,
            novelty_score=0.1,  # Familiar
        )
        
        # High novelty case
        result_novel = uncertainty_estimator.estimate(
            query="What is Python?",
            classifier_confidence=0.8,
            query_length=10,
            novelty_score=0.9,  # Novel
        )
        
        assert result_novel.total_uncertainty > result_familiar.total_uncertainty, \
            "Novelty should increase uncertainty"
    
    def test_input_difficulty_increases_uncertainty(self, uncertainty_estimator, input_extractor):
        """Complex input signals should increase uncertainty."""
        # Simple query
        simple_signals = input_extractor.extract("What is AI?")
        result_simple = uncertainty_estimator.estimate(
            query="What is AI?",
            classifier_confidence=0.8,
            query_length=10,
            novelty_score=0.5,
            input_signals=simple_signals.model_dump()
        )
        
        # Complex query
        complex_query = """
        I need a multi-threaded solution that:
        1. Handles async I/O
        2. Maintains ACID properties
        3. Scales horizontally
        Please provide detailed implementation.
        """
        complex_signals = input_extractor.extract(complex_query)
        result_complex = uncertainty_estimator.estimate(
            query=complex_query,
            classifier_confidence=0.8,
            query_length=len(complex_query.split()),
            novelty_score=0.5,
            input_signals=complex_signals.model_dump()
        )
        
        assert result_complex.total_uncertainty > result_simple.total_uncertainty, \
            "Complex inputs should increase uncertainty"


class TestConfidenceLevelMapping:
    """Test that uncertainty maps to correct confidence levels."""
    
    def test_low_uncertainty_high_confidence(self, uncertainty_estimator):
        """Uncertainty <0.3 should map to HIGH confidence."""
        result = uncertainty_estimator.estimate(
            query="Hello",
            classifier_confidence=0.95,
            query_length=1,
            novelty_score=0.0,
        )
        
        assert result.confidence_level == "HIGH"
    
    def test_medium_uncertainty_medium_confidence(self, uncertainty_estimator):
        """Uncertainty 0.3-0.6 should map to MEDIUM confidence."""
        result = uncertainty_estimator.estimate(
            query="Explain machine learning approaches",
            classifier_confidence=0.6,
            query_length=20,
            novelty_score=0.5,
        )
        
        assert result.confidence_level == "MEDIUM"
    
    def test_high_uncertainty_low_confidence(self, uncertainty_estimator):
        """Uncertainty >0.6 should map to LOW confidence."""
        result = uncertainty_estimator.estimate(
            query="Complex theoretical physics question with multiple constraints",
            classifier_confidence=0.2,
            query_length=50,
            novelty_score=0.95,
        )
        
        assert result.confidence_level == "LOW"


class TestCalibration:
    """Test that uncertainty is well-calibrated."""
    
    # (query, expected_uncertainty_range, description)
    CALIBRATION_CASES = [
        ("Hello", (0.0, 0.3), "trivial_greeting"),
        ("What is Python?", (0.1, 0.5), "simple_qa"),
        ("Explain neural networks", (0.3, 0.7), "moderate_qa"),
        ("Design a distributed consensus algorithm", (0.6, 1.0), "expert_task"),
    ]
    
    @pytest.mark.parametrize("query,expected_range,description", CALIBRATION_CASES)
    def test_uncertainty_calibration(self, uncertainty_estimator, query, expected_range, description):
        """Test that uncertainty estimates are well-calibrated."""
        result = uncertainty_estimator.estimate(
            query=query,
            classifier_confidence=0.7,  # Neutral
            query_length=len(query.split()),
            novelty_score=0.5,  # Neutral
        )
        
        min_uncertainty, max_uncertainty = expected_range
        assert min_uncertainty <= result.total_uncertainty <= max_uncertainty, \
            f"Uncertainty {result.total_uncertainty:.2f} out of expected range {expected_range} for {description}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_handles_missing_signals(self, uncertainty_estimator):
        """Should handle missing input signals gracefully."""
        result = uncertainty_estimator.estimate(
            query="Test query",
            classifier_confidence=0.7,
            query_length=10,
            novelty_score=0.5,
            input_signals=None  # Missing
        )
        
        # Should still return valid uncertainty
        assert 0.0 <= result.total_uncertainty <= 1.0
    
    def test_handles_extreme_values(self, uncertainty_estimator):
        """Should handle extreme input values."""
        result = uncertainty_estimator.estimate(
            query="Test",
            classifier_confidence=0.0,  # Extreme
            query_length=1000,  # Extreme
            novelty_score=1.0,  # Extreme
        )
        
        # Should clamp to valid range
        assert 0.0 <= result.total_uncertainty <= 1.0
    
    def test_empty_query(self, uncertainty_estimator):
        """Should handle empty query."""
        result = uncertainty_estimator.estimate(
            query="",
            classifier_confidence=0.5,
            query_length=0,
            novelty_score=0.5,
        )
        
        assert result.total_uncertainty is not None


class TestMetrics:
    """Test aggregate metrics and performance."""
    
    def test_uncertainty_distribution(self, uncertainty_estimator):
        """Test that uncertainty has reasonable distribution."""
        queries = [
            "Hi",
            "What is AI?",
            "Explain quantum computing",
            "Design a distributed system",
            "Prove the Riemann hypothesis",
        ]
        
        uncertainties = []
        for query in queries:
            result = uncertainty_estimator.estimate(
                query=query,
                classifier_confidence=0.7,
                query_length=len(query.split()),
                novelty_score=0.5,
            )
            uncertainties.append(result.total_uncertainty)
        
        # Should be monotonically increasing (simple → complex)
        for i in range(len(uncertainties) - 1):
            assert uncertainties[i] <= uncertainties[i + 1] + 0.2, \
                "Uncertainty should generally increase with complexity"
        
        print(f"\nUncertainty Distribution: {[f'{u:.2f}' for u in uncertainties]}")
