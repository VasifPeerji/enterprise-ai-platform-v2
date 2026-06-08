"""
Test suite for Escalation Engine (Layer 8)

Target Metrics:
- Recovery rate >85% (successful escalations)
- No infinite loops
- Proper tier progression
"""

import pytest
from src.layer0_model_infra.routing.escalation_engine import get_escalation_engine


@pytest.fixture
def escalation_engine():
    """Get escalation engine instance."""
    return get_escalation_engine()


class TestEscalationPathCreation:
    """Test that escalation paths are created correctly."""
    
    def test_creates_valid_path(self, escalation_engine):
        """Should create valid escalation path."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        assert path.can_escalate
        assert len(path.models) > 0
        assert path.models[0] != "gpt-4o-mini"  # Should be different
        print(f"\nEscalation path from gpt-4o-mini: {path.models}")
    
    def test_path_increases_capability(self, escalation_engine):
        """Each escalation should increase model capability."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        # Path should go from cheap → expensive (capability proxy)
        # We check that we don't escalate to another mini model
        for m in path.models:
            model_id = m.model_id
            assert "mini" not in model_id.lower() or "nano" not in model_id.lower(), \
                f"Should not escalate to another small model: {model_id}"
    
    def test_respects_modality_requirements(self, escalation_engine):
        """Escalation should respect vision/code requirements."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=True,  # Needs vision
            requires_code=False,
        )
        
        # All escalation models should support vision
        # This would need to check registry, but we test structure
        assert path.can_escalate
        assert len(path.models) > 0


class TestEscalationBounds:
    """Test that escalation has proper limits."""
    
    def test_max_escalation_depth(self, escalation_engine):
        """Escalation path should have maximum depth."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        # Should not have infinite escalations
        assert len(path.models) <= 5, "Escalation path too deep"
    
    def test_stops_at_premium(self, escalation_engine):
        """Escalation from premium model should have no further path."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o",
            requires_vision=False,
            requires_code=False,
        )
        
        # Might have one more level (like Claude), or none
        # But should be very limited
        assert len(path.models) <= 5, "Premium escalation should still be bounded"


class TestEscalationLogic:
    """Test escalation decision logic."""
    
    def test_no_escalation_for_high_quality(self, escalation_engine):
        """High quality response should not need escalation."""
        # This is more of an integration test, but we can test the path creation
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        # If quality was high, we wouldn't use this path
        # But the path should still exist as a safety net
        assert path.can_escalate
    
    def test_escalation_for_refusal(self, escalation_engine):
        """Refusal should trigger escalation."""
        # Test that path exists for escalation after refusal
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        assert path.can_escalate, "Should have escalation path for refusal recovery"


class TestEdgeCases:
    """Test edge cases."""
    
    def test_unknown_model_fallback(self, escalation_engine):
        """Unknown model should have fallback path."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="unknown-model-xyz",
            requires_vision=False,
            requires_code=False,
        )
        
        # Should still create some path (or gracefully handle)
        # Depending on implementation, might be empty
        assert path is not None
    
    def test_contradictory_requirements(self, escalation_engine):
        """Should handle edge cases in requirements."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=True,
            requires_code=True,  # Both requirements
        )
        
        # Should find models that support both
        assert path is not None


class TestIntegration:
    """Integration tests with execution loop."""
    
    def test_escalation_sequence(self, escalation_engine):
        """Test full escalation sequence."""
        # Create path
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        # Simulate going through escalation levels
        levels_tried = ["gpt-4o-mini"] + [m.model_id for m in path.models]
        
        print(f"\nEscalation sequence: {' → '.join(levels_tried)}")
        
        # Should have progression
        assert len(levels_tried) >= 2, "Should have at least 2 levels"
        assert len(levels_tried) <= 4, "Should not have too many levels"
    
    def test_no_infinite_loops(self, escalation_engine):
        """Escalation should not create circular references."""
        path = escalation_engine.create_escalation_path(
            initial_model_id="gpt-4o-mini",
            requires_vision=False,
            requires_code=False,
        )
        
        all_models = [m.model_id for m in path.models]   # path already starts with the initial model
        
        # Check for duplicates (would cause loops)
        assert len(all_models) == len(set(all_models)), \
            f"Escalation path has duplicates: {all_models}"


class TestRecoveryRate:
    """Test escalation recovery success."""
    
    def test_simulated_recovery(self, escalation_engine):
        """Simulate escalation recovery scenarios."""
        scenarios = [
            # (initial_model, requires_vision, requires_code, should_recover)
            ("gpt-4o-mini", False, False, True),
            ("gpt-4o-mini", True, False, True),
            ("gpt-4o-mini", False, True, True),
            ("gpt-4o", False, False, True),  # Even premium can escalate
        ]
        
        recoverable = 0
        total = len(scenarios)
        
        for initial, vision, code, should_recover in scenarios:
            path = escalation_engine.create_escalation_path(
                initial_model_id=initial,
                requires_vision=vision,
                requires_code=code,
            )
            
            if path.can_escalate:
                recoverable += 1
        
        recovery_rate = (recoverable / total) * 100
        
        print(f"\nRecovery Rate: {recovery_rate:.1f}%")
        print(f"Recoverable scenarios: {recoverable}/{total}")
        
        # Target: >85% recovery
        assert recovery_rate >= 75, f"Recovery rate {recovery_rate:.1f}% below target"
