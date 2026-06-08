"""
Shared pytest fixtures and configuration for Layer 0 tests.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests to avoid state leakage."""
    # Import all singleton modules
    from src.layer0_model_infra.routing import (
        modality_gate,
        semantic_memory,
        quality_evaluator,
    )
    from src.layer0_model_infra.routing.legacy import bandit_router
    
    # Reset singletons
    modality_gate._modality_gate = None
    semantic_memory._semantic_memory = None
    bandit_router._bandit_router = None
    quality_evaluator._quality_evaluator = None
    
    yield
    
    # Cleanup after test
    modality_gate._modality_gate = None
    semantic_memory._semantic_memory = None
    bandit_router._bandit_router = None
    quality_evaluator._quality_evaluator = None


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests for individual components"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests for full pipeline"
    )
    config.addinivalue_line(
        "markers", "performance: Performance and stress tests"
    )
