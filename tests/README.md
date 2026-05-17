# Elite Router Testing Suite

## Overview

Comprehensive testing for the Elite Router (Layer 0) implementation following industry best practices.

## Test Structure

```
tests/
├── layer0_model_infra/        # Layer 0 component tests
│   ├── test_modality_gate.py
│   ├── test_semantic_memory.py
│   ├── test_fast_triage.py
│   ├── test_uncertainty_estimator.py
│   ├── test_bandit_router.py
│   ├── test_quality_evaluator.py
│   └── test_escalation.py
├── integration/               # E2E pipeline tests
└── performance/              # Stress and benchmark tests
```

## Running Tests

### All Tests
```bash
pytest tests/
```

### Specific Layer
```bash
pytest tests/layer0_model_infra/test_modality_gate.py -v
```

### With Coverage
```bash
pytest tests/ --cov=src/layer0_model_infra --cov-report=html
```

### Performance Tests Only
```bash
pytest tests/ -m performance
```

## Test Metrics & Targets

### Layer 1: Modality Gate
- **Accuracy**: >95% correct modality detection
- **False Positives**: <5% unnecessary multimodal calls
- **Key Tests**: Text/Image/Audio/Code classification

### Layer 2: Semantic Memory
- **Precision**: >90% cache hits are useful
- **Wrong Route Rate**: <10%
- **Key Tests**: Similarity threshold, quality filtering, novelty

### Layer 3: Fast Triage
- **Accuracy**: >70% (directionally correct, not perfect)
- **Confidence Calibration**: High confidence = high accuracy
- **Key Tests**: Intent/Domain/Complexity classification

### Layer 4: Uncertainty Estimator
- **Calibration**: High uncertainty → safer routing
- **Misroute Correlation**: Fewer failures at high uncertainty
- **Key Tests**: Multi-signal aggregation

### Layer 5: Bandit Router
- **Reward Improvement**: >10% over baseline
- **Exploration/Exploitation**: Balanced learning
- **Key Tests**: Offline replay, context-aware selection

### Layer 6: Quality Evaluator
- **Recall**: >90% detection of bad responses
- **False Alarms**: Acceptable (<20%)
- **Key Tests**: Hallucination, refusal, incompleteness

### Layer 7: Escalation
- **Recovery Rate**: >85% successful escalations
- **Loop Prevention**: No infinite escalation
- **Key Tests**: Multi-tier escalation, bounded depth

## Test Data

Test datasets are embedded in test files using `@pytest.mark.parametrize` for:
- Maintainability
- Version control
- Easy expansion

For large datasets, use `tests/fixtures/` directory.

## CI/CD Integration

Tests run automatically on:
- Every commit (unit tests)
- Every PR (unit + integration)
- Nightly (full suite + performance)

## Adding New Tests

1. Follow naming convention: `test_<component>.py`
2. Use descriptive test names: `test_<what>_<condition>`
3. Add docstrings explaining the test purpose
4. Use parametrize for multiple similar cases
5. Add metrics assertions where applicable
