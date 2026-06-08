"""Layer 9 observability: Layer 3 telemetry fields + the scheduled drift scan.

Pure offline checks (no live traffic, no encoder, no Qdrant) — they exercise the
telemetry record shape, the DB columns, and TelemetryLogger.run_drift_scan over a
synthetic buffer.
"""

from src.layer0_model_infra.config.routing_config import Layer3DriftConfig
from src.layer0_model_infra.routing.drift_detector import DriftDetector
from src.layer0_model_infra.routing.telemetry import RoutingTelemetry, TelemetryLogger


def _records(model_id, values, t0=0.0):
    return [
        RoutingTelemetry(selected_model_id=model_id, predicted_quality=v, timestamp=t0 + i)
        for i, v in enumerate(values)
    ]


def test_routing_telemetry_carries_layer3_fields():
    t = RoutingTelemetry(
        selected_model_id="m1",
        routing_source="knn_corpus",
        predicted_quality=0.82,
        prediction_confidence_score=0.2,
        uncertainty_escalated=True,
    )
    assert t.routing_source == "knn_corpus"
    assert t.predicted_quality == 0.82
    assert t.prediction_confidence_score == 0.2
    assert t.uncertainty_escalated is True


def test_db_record_has_layer3_columns():
    from src.database.models.routing_telemetry import RoutingTelemetryRecord

    cols = set(RoutingTelemetryRecord.model_fields)
    assert {
        "routing_source",
        "predicted_quality",
        "prediction_confidence_score",
        "uncertainty_escalated",
    } <= cols


def test_drift_scan_flags_shift_and_leaves_stationary_ok():
    det = DriftDetector(Layer3DriftConfig(), min_samples_per_window=20)
    recs = _records("stable", [0.8] * 50) + _records("shifted", [0.8] * 25 + [0.15] * 25)
    by_model = {r.model_id: r for r in det.scan(recs, freeze_on_halt=False)}
    assert by_model["stable"].level == "ok"
    assert by_model["shifted"].level == "halt"
    assert by_model["shifted"].kl_divergence > Layer3DriftConfig().kl_halt


def test_run_drift_scan_is_safe_on_empty_buffer():
    saved = TelemetryLogger._buffer
    try:
        TelemetryLogger._buffer = []
        assert TelemetryLogger.run_drift_scan() == []
    finally:
        TelemetryLogger._buffer = saved


def test_run_drift_scan_over_buffer_returns_results():
    # Stationary data only, so no halt fires and no calibration state is mutated.
    saved = TelemetryLogger._buffer
    try:
        TelemetryLogger._buffer = _records("bufA", [0.8] * 50)
        results = TelemetryLogger.run_drift_scan()
        assert len(results) == 1
        assert results[0].model_id == "bufA"
        assert results[0].level == "ok"
    finally:
        TelemetryLogger._buffer = saved
