"""
Tests for code-generation intent detection (M2).

Natural-language coding requests (no literal code block) must map to CODE so
they get the code safe-default, while general/creative queries must stay TEXT
(high precision — false positives only cost a free code-capable model). Math
must not be clobbered.
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.routing.feature_extractor import FeatureExtractor
from src.layer0_model_infra.routing.layer3_types import Modality
from src.layer0_model_infra.routing.modality_gate import get_modality_gate


@pytest.fixture(scope="module")
def fx():
    return FeatureExtractor()


CODE_QUERIES = [
    "Write a Python function to reverse a linked list",
    "Implement binary search in C++",
    "How do I fix a NullPointerException in Java?",
    "Design a distributed rate limiter for a microservices architecture",
    "write code to parse a CSV file",
    "Refactor this function to be more efficient",
    "Build a REST API endpoint for user login",
]

NON_CODE_QUERIES = [
    "Write a haiku about autumn",
    "What are the benefits of remote work?",
    "Summarize the plot of Hamlet",
    "Write an essay about climate change",
    "Design a marketing plan for a new product",
    "What is the capital of Australia?",
]


@pytest.mark.parametrize("q", CODE_QUERIES)
def test_code_intent_maps_to_code(fx, q):
    assert fx.extract(q).modality == Modality.CODE


@pytest.mark.parametrize("q", NON_CODE_QUERIES)
def test_non_code_stays_text(fx, q):
    assert fx.extract(q).modality == Modality.TEXT


def test_math_not_clobbered_by_code_intent(fx):
    # "prove" makes this MATH; the code-intent upgrade only touches TEXT.
    assert fx.extract("Prove that the square root of 2 is irrational").modality == Modality.MATH


def test_code_intent_through_layer1_bridge(fx):
    gate = get_modality_gate()
    q = "Write a Python function to reverse a linked list"
    analysis = gate.analyze(q)
    assert fx.extract_from_layer1(analysis, q).modality == Modality.CODE
