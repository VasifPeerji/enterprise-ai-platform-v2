"""
📁 File: src/layer0_model_infra/routing/drift_detector.py
Layer: Layer 0 — Layer 3 redesign (Stage / Layer 9 — drift)
Purpose: Per-model prediction-distribution drift detection with calibration freeze.
Depends on: config.routing_config.Layer3DriftConfig, calibration_store
Used by: the dashboard / an offline (weekly) MLOps scan over routing telemetry.

Why this exists
---------------
The online calibration EMA assumes a model's predicted-quality distribution within
a feature cell is roughly stationary. When it ISN'T (the input mix shifts, a
provider changes the model behind an id, the corpus is re-embedded), the EMA would
chase a moving target and corrupt routing. This detector compares each model's
RECENT predicted-quality distribution to an earlier REFERENCE window via KL
divergence; when the shift clears the configured halt threshold it FREEZES that
model's calibration (calibration_store.freeze) until a human reviews it.

It is pure statistics over numbers the router already produced — no model calls,
no training. Thresholds come straight from Layer3DriftConfig (kl_info / kl_warn /
kl_halt). Operates either on telemetry records (scan) or on explicit samples
(check_model), so it is fully testable offline with no live traffic.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from src.layer0_model_infra.config.routing_config import Layer3DriftConfig
from src.shared.logger import get_logger

logger = get_logger(__name__)

# Fixed [0, 1] histogram resolution for predicted-quality distributions.
_BINS = 10


@dataclass
class DriftResult:
    """Outcome of a single model's drift check."""

    model_id: str
    kl_divergence: float
    level: str            # "ok" | "info" | "warn" | "halt"
    n_reference: int
    n_recent: int
    frozen: bool = False


def _histogram(samples: Sequence[float], bins: int = _BINS) -> list[float]:
    """Normalised histogram over [0, 1] with Laplace smoothing so every bin is
    non-zero (keeps KL finite even when a bin is empty in one window)."""
    counts = [1.0] * bins  # +1 smoothing
    for s in samples:
        v = min(max(float(s), 0.0), 1.0)
        idx = min(int(v * bins), bins - 1)
        counts[idx] += 1.0
    total = sum(counts)
    return [c / total for c in counts]


def kl_divergence(recent: Sequence[float], reference: Sequence[float], bins: int = _BINS) -> float:
    """KL(recent || reference) over [0, 1] histograms. >= 0; 0 means identical."""
    p = _histogram(recent, bins)
    q = _histogram(reference, bins)
    return sum(pi * math.log(pi / qi) for pi, qi in zip(p, q) if pi > 0.0)


class DriftDetector:
    """Per-model prediction-distribution drift detector (Layer 9)."""

    def __init__(
        self,
        config: Optional[Layer3DriftConfig] = None,
        calibration_store=None,
        *,
        min_samples_per_window: int = 20,
    ) -> None:
        self._config = config or Layer3DriftConfig()
        self._calibration = calibration_store
        self._min_samples = max(1, min_samples_per_window)

    @property
    def calibration(self):
        if self._calibration is None:
            from src.layer0_model_infra.routing.calibration_store import get_calibration_store
            self._calibration = get_calibration_store()
        return self._calibration

    def _classify(self, kl: float) -> str:
        cfg = self._config
        if kl >= cfg.kl_halt:
            return "halt"
        if kl >= cfg.kl_warn:
            return "warn"
        if kl >= cfg.kl_info:
            return "info"
        return "ok"

    def check_model(
        self,
        model_id: str,
        recent: Sequence[float],
        reference: Sequence[float],
        *,
        freeze_on_halt: bool = True,
    ) -> DriftResult:
        """Check one model. Too few samples in either window → 'ok' (not enough
        evidence to act). On 'halt', freeze the model's calibration."""
        if len(recent) < self._min_samples or len(reference) < self._min_samples:
            return DriftResult(model_id, 0.0, "ok", len(reference), len(recent))

        kl = kl_divergence(recent, reference)
        level = self._classify(kl)
        frozen = False
        if level == "halt" and freeze_on_halt:
            self.calibration.freeze(model_id)
            frozen = True
            logger.warning(
                "layer3_drift_halt_freeze",
                model_id=model_id, kl=round(kl, 4), threshold=self._config.kl_halt,
            )
        elif level in ("warn", "info"):
            logger.info("layer3_drift_observed", model_id=model_id, kl=round(kl, 4), level=level)
        return DriftResult(model_id, kl, level, len(reference), len(recent), frozen)

    def scan(
        self,
        records: Sequence[Any],
        *,
        value_attr: str = "predicted_quality",
        freeze_on_halt: bool = True,
    ) -> list[DriftResult]:
        """Scan telemetry records: group by the routed model, split each model's
        samples by timestamp into an older REFERENCE half and a newer RECENT half,
        and check for drift. Records need a numeric ``value_attr``, a ``timestamp``,
        and a model id (``selected_model_id`` or ``final_model_id``)."""
        by_model: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for r in records:
            val = getattr(r, value_attr, None)
            mid = getattr(r, "selected_model_id", "") or getattr(r, "final_model_id", "")
            if val is None or not mid:
                continue
            ts = float(getattr(r, "timestamp", 0.0) or 0.0)
            by_model[mid].append((ts, float(val)))

        results: list[DriftResult] = []
        for mid, pairs in by_model.items():
            if len(pairs) < 2 * self._min_samples:
                continue
            pairs.sort(key=lambda p: p[0])
            split = len(pairs) // 2
            reference = [v for _, v in pairs[:split]]
            recent = [v for _, v in pairs[split:]]
            results.append(
                self.check_model(mid, recent, reference, freeze_on_halt=freeze_on_halt)
            )
        return results


_detector: Optional[DriftDetector] = None


def get_drift_detector() -> DriftDetector:
    """Process-wide drift detector wired to the routing drift config."""
    global _detector
    if _detector is None:
        from src.layer0_model_infra.config.routing_config import get_routing_config
        _detector = DriftDetector(get_routing_config().layer3.drift)
    return _detector


def reset_drift_detector() -> None:
    """Test helper — drop the singleton."""
    global _detector
    _detector = None
