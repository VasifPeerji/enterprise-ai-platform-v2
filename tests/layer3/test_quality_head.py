"""
Tests for the learned quality head (Layer 3 prior-path replacement).

Pure numpy — loads the committed artifact (src/.../data/quality_head.npz) and
checks load / predict / graceful-degradation. No torch, no encoder.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.layer0_model_infra.routing.quality_head import QualityHead

REPO = Path(__file__).resolve().parent.parent.parent
ARTIFACT = REPO / "src/layer0_model_infra/data/quality_head.npz"


@pytest.fixture(scope="module")
def head():
    return QualityHead(ARTIFACT)


def test_artifact_loads(head):
    assert head.is_active, "the committed quality_head.npz should load"
    assert len(head.model_ids) >= 3
    # the cheap/mid free models we rely on for easy->cheap routing
    assert "llama-3.1-8b-instant-groq" in head.model_ids
    assert "llama-3.3-70b-versatile-groq" in head.model_ids


def test_predict_all_in_range(head):
    preds = head.predict_all(np.ones(384, dtype=np.float32))
    assert set(preds) == head.model_ids
    assert all(0.0 <= v <= 1.0 for v in preds.values())


def test_predictions_are_query_aware(head):
    """Different embeddings must give different predictions — otherwise the head
    is no better than the flat prior it replaces."""
    rng = np.random.RandomState(0)
    a = head.predict_all(rng.randn(384).astype(np.float32))
    b = head.predict_all(rng.randn(384).astype(np.float32))
    assert any(abs(a[m] - b[m]) > 0.01 for m in a)


def test_inert_when_artifact_absent(tmp_path):
    h = QualityHead(tmp_path / "missing.npz")
    assert not h.is_active
    assert h.predict_all(np.ones(384, dtype=np.float32)) == {}


def test_wrong_dim_returns_empty(head):
    assert head.predict_all(np.ones(128, dtype=np.float32)) == {}
