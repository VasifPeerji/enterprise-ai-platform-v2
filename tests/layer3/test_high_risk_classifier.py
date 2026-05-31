"""
Tests for Tier-2 high-risk detection (3.5): the bge-kNN classifier and the
modality-gated wiring in the feature extractor.

Loads bge-small-en (cached from the corpus build), so these are a touch slower
than the pure-regex tests — module-scoped fixtures keep the model load to once.
"""

from __future__ import annotations

import pytest

from src.layer0_model_infra.routing.feature_extractor import FeatureExtractor
from src.layer0_model_infra.routing.high_risk_classifier import BgeKnnHighRiskClassifier
from src.layer0_model_infra.routing.layer3_types import HighRiskDomain, Modality


@pytest.fixture(scope="module")
def bge():
    return BgeKnnHighRiskClassifier(threshold=0.62)


@pytest.fixture(scope="module")
def fx_bge():
    return FeatureExtractor(high_risk_tier2_mode="bge", high_risk_threshold=0.62)


# ---------------------------------------------------------------------------
# bge classifier directly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query,expected", [
    ("what should I do if someone is choking", HighRiskDomain.MEDICAL),
    ("can I take antihistamines and alcohol together", HighRiskDomain.MEDICAL),
    ("can I sue my employer for wrongful termination", HighRiskDomain.LEGAL),
    ("what are my rights if I'm being evicted", HighRiskDomain.LEGAL),
    ("should I move my 401k into gold right now", HighRiskDomain.FINANCIAL),
    ("how do I minimize taxes on my crypto gains", HighRiskDomain.FINANCIAL),
])
def test_bge_catches_high_risk(bge, query, expected):
    domain, _score = bge.classify(query)
    assert domain == expected


@pytest.mark.parametrize("query", [
    "write a haiku about autumn",
    "what is the capital of Australia",
    "how do I deploy a flask app to production",
    "explain how photosynthesis works",
])
def test_bge_ignores_general(bge, query):
    domain, _score = bge.classify(query)
    assert domain is None


# ---------------------------------------------------------------------------
# Tier-2 wiring in the feature extractor (regex → bge, gated to TEXT)
# ---------------------------------------------------------------------------


def test_tier2_rescues_regex_miss(fx_bge):
    # The Tier-1 regex misses this; Tier-2 must catch it.
    feats = fx_bge.extract("what should I do if someone is choking")
    assert feats.high_risk_domain == HighRiskDomain.MEDICAL
    assert feats.modality == Modality.TEXT


def test_tier2_gated_off_for_code(fx_bge):
    # Coding query that mentions a financial term — modality CODE → Tier-2 skipped.
    feats = fx_bge.extract("write a function to compute compound interest")
    assert feats.modality == Modality.CODE
    assert feats.high_risk_domain is None


def test_tier1_regex_still_fires_with_tier2(fx_bge):
    feats = fx_bge.extract("what is the dosage of ibuprofen for a child")
    assert feats.high_risk_domain == HighRiskDomain.MEDICAL


def test_mode_off_is_regex_only():
    fx = FeatureExtractor(high_risk_tier2_mode="off")
    # only Tier-2 would catch this — None when Tier-2 is disabled
    assert fx.extract("what should I do if someone is choking").high_risk_domain is None


# ---------------------------------------------------------------------------
# Regression guard on the 3.5 eval set
# ---------------------------------------------------------------------------


def test_eval_set_recall_and_precision(fx_bge):
    """Modality-gated bge must keep recall 1.0 and precision >= 0.90 on the
    held-out eval set (the 3.5 benchmark measured 1.0 / 0.936)."""
    from scripts.layer3._high_risk_eval import HIGH_RISK_EVAL
    tp = fp = fn = 0
    for query, label in HIGH_RISK_EVAL:
        pred = fx_bge.extract(query).high_risk_domain
        pred = pred.value if pred else None
        if pred and label:
            tp += 1
        elif pred and not label:
            fp += 1
        elif not pred and label:
            fn += 1
    recall = tp / (tp + fn)
    precision = tp / (tp + fp)
    assert recall == 1.0, f"recall regressed to {recall}"
    assert precision >= 0.90, f"precision regressed to {precision}"
