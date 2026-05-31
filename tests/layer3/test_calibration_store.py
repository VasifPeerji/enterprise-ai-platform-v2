"""
Tests for the online EMA calibration store.

Covers the multiplier math (EMA blend, clamping), confidence gating (a
multiplier is only applied once a cell is trusted), the source filter (only
KNN_CORPUS decisions feed the EMA), drift freeze, and Parquet round-trip.

Uses tmp_path so nothing touches the real data/processed/calibration.parquet.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.layer0_model_infra.config.routing_config import Layer3CalibrationConfig
from src.layer0_model_infra.routing.calibration_store import CalibrationStore
from src.layer0_model_infra.routing.layer3_types import (
    Modality,
    QueryFeatures,
    RoutingDecision,
    RoutingSource,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CELL = "text:en:none:normal"
MODEL = "llama-3.3-70b-versatile-groq"


def _features() -> QueryFeatures:
    return QueryFeatures(
        language="en",
        modality=Modality.TEXT,
        estimated_input_tokens=10,
        estimated_output_tokens=400,
    )


def make_decision(
    *,
    source: RoutingSource = RoutingSource.KNN_CORPUS,
    predicted_quality: float | None = 0.8,
    feature_cell: str | None = CELL,
    selected_model: str = MODEL,
) -> RoutingDecision:
    return RoutingDecision(
        request_id="test-req",
        timestamp=datetime.now(timezone.utc),
        selected_model=selected_model,
        source=source,
        predicted_quality=predicted_quality,
        estimated_cost_usd=0.0,
        features=_features(),
        feature_cell=feature_cell,
    )


def _store(tmp_path: Path, **overrides) -> CalibrationStore:
    cfg = Layer3CalibrationConfig(**overrides) if overrides else Layer3CalibrationConfig()
    return CalibrationStore(tmp_path / "calibration.parquet", cfg)


# ---------------------------------------------------------------------------
# Empty / unknown
# ---------------------------------------------------------------------------


def test_unknown_cell_returns_neutral_multiplier(tmp_path):
    store = _store(tmp_path)
    assert store.get_multiplier(MODEL, CELL) == 1.0
    assert store.observations(MODEL, CELL) == 0
    assert store.total_observations(MODEL) == 0


def test_missing_file_loads_empty(tmp_path):
    store = _store(tmp_path)
    assert store.stats()["cells"] == 0


# ---------------------------------------------------------------------------
# Source / validity filtering — only KNN_CORPUS with a real prediction counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_source", [
    RoutingSource.CACHE_HIT,
    RoutingSource.FALLBACK,
    RoutingSource.EXPLORATION,
    RoutingSource.WARMUP,
    RoutingSource.FORCED,
])
def test_non_knn_sources_are_ignored(tmp_path, bad_source):
    store = _store(tmp_path)
    moved = store.update(make_decision(source=bad_source, predicted_quality=0.5), observed_quality=0.1)
    assert moved is False
    assert store.observations(MODEL, CELL) == 0


def test_missing_predicted_quality_is_ignored(tmp_path):
    store = _store(tmp_path)
    assert store.update(make_decision(predicted_quality=None), 0.9) is False
    assert store.update(make_decision(predicted_quality=0.0), 0.9) is False
    assert store.observations(MODEL, CELL) == 0


def test_missing_feature_cell_is_ignored(tmp_path):
    store = _store(tmp_path)
    assert store.update(make_decision(feature_cell=None), 0.9) is False
    assert store.observations(MODEL, CELL) == 0


# ---------------------------------------------------------------------------
# EMA math
# ---------------------------------------------------------------------------


def test_single_update_records_observation_but_not_yet_applied(tmp_path):
    store = _store(tmp_path)
    # predicted == observed → ratio 1.0 → multiplier stays ~1.0
    assert store.update(make_decision(predicted_quality=0.8), observed_quality=0.8) is True
    assert store.observations(MODEL, CELL) == 1
    # confidence(1) = 1 - exp(-1/50) ≈ 0.0198 < 0.3 → not applied yet
    assert store.get_multiplier(MODEL, CELL) == 1.0


def test_ema_converges_downward_when_model_underperforms(tmp_path):
    store = _store(tmp_path)
    # observed 0.4 vs predicted 0.8 → ratio 0.5. EMA from 1.0:
    #   m_k = 0.5 + 0.5 * 0.9^k
    for _ in range(20):
        store.update(make_decision(predicted_quality=0.8), observed_quality=0.4)
    expected = 0.5 + 0.5 * (0.9 ** 20)
    assert store.observations(MODEL, CELL) == 20
    # confidence(20) ≈ 0.33 ≥ 0.3 → applied
    assert store.get_multiplier(MODEL, CELL) == pytest.approx(expected, abs=1e-3)
    assert store.get_multiplier(MODEL, CELL) < 1.0


def test_multiplier_clamped_to_max(tmp_path):
    store = _store(tmp_path)
    # ratio 10 (observed 1.0 / predicted 0.1) → EMA blows past the ceiling,
    # must clamp at multiplier_max (1.5).
    for _ in range(20):
        store.update(make_decision(predicted_quality=0.1), observed_quality=1.0)
    assert store.get_multiplier(MODEL, CELL) == pytest.approx(1.5, abs=1e-9)


def test_multiplier_clamped_to_min(tmp_path):
    store = _store(tmp_path)
    # ratio 0 (observed 0.0) → EMA decays toward 0, must clamp at min (0.5).
    for _ in range(20):
        store.update(make_decision(predicted_quality=0.8), observed_quality=0.0)
    assert store.get_multiplier(MODEL, CELL) == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Confidence gating
# ---------------------------------------------------------------------------


def test_confidence_threshold_gates_application(tmp_path):
    store = _store(tmp_path)
    # 17 observations → confidence < 0.3 → neutral; 18 → confidence ≥ 0.3 → applied.
    for _ in range(17):
        store.update(make_decision(predicted_quality=0.8), observed_quality=0.4)
    assert store.get_multiplier(MODEL, CELL) == 1.0  # still gated
    store.update(make_decision(predicted_quality=0.8), observed_quality=0.4)
    assert store.observations(MODEL, CELL) == 18
    assert 1.0 - math.exp(-18 / 50.0) >= 0.3
    assert store.get_multiplier(MODEL, CELL) < 1.0  # now applied


# ---------------------------------------------------------------------------
# Observation counting
# ---------------------------------------------------------------------------


def test_total_observations_sums_across_cells(tmp_path):
    store = _store(tmp_path)
    store.update(make_decision(feature_cell="text:en:none:normal"), 0.5)
    store.update(make_decision(feature_cell="code:en:none:hard"), 0.5)
    store.update(make_decision(feature_cell="code:en:none:hard"), 0.5)
    assert store.observations(MODEL, "text:en:none:normal") == 1
    assert store.observations(MODEL, "code:en:none:hard") == 2
    assert store.total_observations(MODEL) == 3
    assert store.total_observations("some-other-model") == 0


# ---------------------------------------------------------------------------
# Drift freeze
# ---------------------------------------------------------------------------


def test_freeze_blocks_updates(tmp_path):
    store = _store(tmp_path)
    store.freeze(MODEL)
    assert store.is_frozen(MODEL) is True
    assert store.update(make_decision(), 0.1) is False
    assert store.observations(MODEL, CELL) == 0
    store.unfreeze(MODEL)
    assert store.update(make_decision(), 0.1) is True
    assert store.observations(MODEL, CELL) == 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_and_reload_roundtrip(tmp_path):
    store = _store(tmp_path)
    for _ in range(20):
        store.update(make_decision(predicted_quality=0.8), observed_quality=0.4)
    multiplier_before = store.get_multiplier(MODEL, CELL)
    store.save()

    reloaded = _store(tmp_path)
    assert reloaded.observations(MODEL, CELL) == 20
    # confidence recomputed on load → multiplier applied again, value preserved
    assert reloaded.get_multiplier(MODEL, CELL) == pytest.approx(multiplier_before, abs=1e-9)


def test_reload_recomputes_confidence(tmp_path):
    # A model with enough observations should be "applied" after reload even
    # though the in-memory state is rebuilt from scratch.
    store = _store(tmp_path)
    for _ in range(25):
        store.update(make_decision(predicted_quality=0.8), observed_quality=0.4)
    store.save()
    reloaded = _store(tmp_path)
    assert reloaded.get_multiplier(MODEL, CELL) < 1.0


def test_clear_empties_cells(tmp_path):
    store = _store(tmp_path)
    store.update(make_decision(), 0.5)
    store.clear()
    assert store.stats()["cells"] == 0
    assert store.observations(MODEL, CELL) == 0


def test_stats_reports_applied_cells(tmp_path):
    store = _store(tmp_path)
    # one well-observed cell (applied), one barely-observed (gated)
    for _ in range(25):
        store.update(make_decision(feature_cell="text:en:none:normal"), 0.4)
    store.update(make_decision(feature_cell="math:en:none:hard"), 0.4)
    s = store.stats()
    assert s["cells"] == 2
    assert s["cells_applied"] == 1
    assert s["total_observations"] == 26


def test_auto_save_persists_after_n_updates(tmp_path):
    store = _store(tmp_path, auto_save_every=3)
    path = tmp_path / "calibration.parquet"
    store.update(make_decision(), 0.5)
    store.update(make_decision(), 0.5)
    assert not path.exists()          # below threshold — not flushed yet
    store.update(make_decision(), 0.5)  # 3rd update → auto-saves
    assert path.exists()
    # a fresh store loads the persisted state
    reloaded = _store(tmp_path)
    assert reloaded.observations(MODEL, CELL) == 3


def test_auto_save_disabled_when_zero(tmp_path):
    store = _store(tmp_path, auto_save_every=0)
    path = tmp_path / "calibration.parquet"
    for _ in range(10):
        store.update(make_decision(), 0.5)
    assert not path.exists()  # never auto-saves when disabled
