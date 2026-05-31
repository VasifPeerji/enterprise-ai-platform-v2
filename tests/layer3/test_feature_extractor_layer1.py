"""
Tests for FeatureExtractor.extract_from_layer1 — the Stage B path that consumes
Layer 1's ModalityAnalysis instead of recomputing language/code/modality.

These are deliberately integration-style: they run the REAL Layer 1 ModalityGate
and feed its output through the bridge, so they verify the actual handoff (the
field names, enum values, and token estimate Layer 1 produces) rather than a
mocked stand-in.
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.routing.feature_extractor import FeatureExtractor
from src.layer0_model_infra.routing.layer3_types import HighRiskDomain, Modality
from src.layer0_model_infra.routing.modality_gate import get_modality_gate


@pytest.fixture(scope="module")
def gate():
    return get_modality_gate()


@pytest.fixture(scope="module")
def extractor():
    return FeatureExtractor()


def _bridge(gate, extractor, query: str, **kw):
    analysis = gate.analyze(query)
    return analysis, extractor.extract_from_layer1(analysis, query, **kw)


def test_plain_text_query(gate, extractor):
    analysis, feats = _bridge(gate, extractor, "What is the capital of France?")
    assert feats.modality == Modality.TEXT
    assert feats.language == "en"
    assert feats.high_risk_domain is None
    # Token estimate is reused from Layer 1 verbatim.
    assert feats.estimated_input_tokens == analysis.token_count
    assert feats.estimated_input_tokens > 0


def test_code_query_maps_to_code(gate, extractor):
    query = "```python\ndef add(a, b):\n    return a + b\n```\nMake this handle floats."
    analysis, feats = _bridge(gate, extractor, query)
    assert analysis.requires_code_model or analysis.primary_modality.value == "code_heavy"
    assert feats.has_code_block is True
    assert feats.modality == Modality.CODE


def test_math_query_maps_to_math(gate, extractor):
    # Layer 1 has no MATH bucket; the bridge must recompute it from the query.
    analysis, feats = _bridge(gate, extractor, "Prove that the square root of 2 is irrational.")
    assert feats.modality == Modality.MATH


def test_medical_query_sets_high_risk(gate, extractor):
    analysis, feats = _bridge(
        gate, extractor, "What is the recommended dosage of ibuprofen for an adult with a fever?"
    )
    assert feats.high_risk_domain == HighRiskDomain.MEDICAL
    assert feats.modality == Modality.TEXT  # high-risk is orthogonal to modality


def test_language_is_reused_from_layer1(gate, extractor):
    # A clearly-Spanish sentence — Layer 1's lingua tier should tag it 'es',
    # and the bridge must carry that through unchanged.
    analysis, feats = _bridge(
        gate, extractor, "¿Cuál es la capital de Francia y por qué es tan importante en la historia?"
    )
    assert analysis.language == "es"
    assert feats.language == "es"
    assert feats.modality == Modality.TEXT


def test_output_tokens_follow_modality(gate, extractor):
    _, code_feats = _bridge(gate, extractor, "```python\nfor i in range(10):\n    print(i)\n```")
    _, text_feats = _bridge(gate, extractor, "Tell me a short story about a robot.")
    assert code_feats.estimated_output_tokens == 500   # code default
    assert text_feats.estimated_output_tokens == 400   # text default
