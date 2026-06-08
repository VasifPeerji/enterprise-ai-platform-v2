"""
Layer 9 — per-model prediction-distribution drift detection.

Pure statistics over synthetic predicted-quality samples (no live traffic): KL is
0 for identical windows and large for a shifted one; a halt-level shift freezes
the model's calibration; too few samples is a no-op; scan groups by model and
splits each model's history by time into reference vs recent.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.layer0_model_infra.config.routing_config import Layer3DriftConfig
from src.layer0_model_infra.routing.drift_detector import DriftDetector, kl_divergence


class _FakeCalibration:
    def __init__(self):
        self.frozen: list[str] = []

    def freeze(self, model_id: str) -> None:
        self.frozen.append(model_id)


def _detector(cal=None, min_samples=20):
    return DriftDetector(Layer3DriftConfig(), cal or _FakeCalibration(), min_samples_per_window=min_samples)


def test_kl_zero_for_identical():
    xs = [0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.4, 0.6, 0.8, 0.5]
    assert kl_divergence(xs, xs) == pytest.approx(0.0, abs=1e-9)


def test_kl_large_for_opposite():
    assert kl_divergence([0.05] * 50, [0.95] * 50) > 0.30


def test_no_drift_is_ok_and_does_not_freeze():
    cal = _FakeCalibration()
    res = _detector(cal).check_model("m", [0.7] * 40, [0.7] * 40)
    assert res.level == "ok"
    assert not res.frozen
    assert cal.frozen == []


def test_halt_level_shift_freezes_calibration():
    cal = _FakeCalibration()
    res = _detector(cal).check_model("m", recent=[0.9] * 40, reference=[0.2] * 40)
    assert res.level == "halt"
    assert res.frozen is True
    assert cal.frozen == ["m"]


def test_insufficient_samples_is_noop():
    cal = _FakeCalibration()
    res = _detector(cal).check_model("m", [0.9] * 5, [0.2] * 5)
    assert res.level == "ok"
    assert cal.frozen == []


def test_scan_groups_by_model_and_splits_by_time():
    cal = _FakeCalibration()
    records = []
    # Model A: older half low (0.2), newer half high (0.9) → drift → halt
    for i in range(40):
        records.append(SimpleNamespace(
            selected_model_id="A", timestamp=float(i),
            predicted_quality=(0.2 if i < 20 else 0.9),
        ))
    # Model B: stable around 0.7 → ok
    for i in range(40):
        records.append(SimpleNamespace(
            selected_model_id="B", timestamp=float(i), predicted_quality=0.7,
        ))
    results = {r.model_id: r for r in _detector(cal).scan(records)}
    assert results["A"].level == "halt"
    assert "A" in cal.frozen
    assert results["B"].level == "ok"
    assert "B" not in cal.frozen
