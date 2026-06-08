"""
📁 File: src/layer0_model_infra/routing/telemetry.py
Layer: Layer 0 - Routing Pipeline (Step 9)
Purpose: Asynchronous telemetry logging + Layer 9 continuous learning hooks
Depends on: src/database
Used by: router.py

Implements the "Continuous Learning Loop" as described in Section 3.9:
  "Routing decisions, contextual features, latency measurements, cost statistics,
   escalation events, and implicit user feedback signals are logged asynchronously."

Also addresses Section 6.3 (MLOps) by providing hooks for:
  - Recalibration of triage classifiers (log escalation statistics by domain)
  - Pruning / re-weighting semantic memory entries
  - Adjusting routing thresholds based on observed outcomes

Design:
  • log_async() fires a daemon thread so it NEVER blocks the request path.
  • recalibrate_triage() is a structured stub that logs per-domain escalation
    counts — this acts as the hook that an offline MLOps job would consume.
"""

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from src.shared.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Telemetry Data Model
# ---------------------------------------------------------------------------

@dataclass
class RoutingTelemetry:
    """Per-request telemetry record for the continuous learning loop."""

    # Routing identification
    request_id: str = ""
    timestamp: float = field(default_factory=time.time)

    # Routing decision
    selected_model_id: str = ""
    final_model_id: str = ""        # May differ if escalated
    domain: str = ""
    intent: str = ""
    complexity_band: str = ""

    # Quality & outcome
    quality_score: float = 0.0
    escalated: bool = False
    escalation_count: int = 0
    refusal_detected: bool = False

    # Economic signals
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    # Confidence signals
    uncertainty_score: float = 0.0
    confidence_level: str = ""
    novelty_score: float = 0.0

    # ── Layer 3 routing signals (observability + drift detection) ──────────
    routing_source: str = ""                    # KNN_CORPUS / PRIOR / FALLBACK / ...
    predicted_quality: float = 0.0              # Layer 3's predicted quality for the pick
    prediction_confidence_score: float = 0.0    # neighbour-derived confidence (0-1)
    uncertainty_escalated: bool = False         # risk-aware escalation fired

    # User context
    user_tier: str = "standard"
    budget_remaining: float = 1.0

    # ── New fields (Enrichment) ────────────────────────────────────────────
    query: str = ""                     # Raw query text (truncated to 500 chars)
    query_hash: str = ""                # SHA256 of full query for dedup
    context_vector_dim: int = 0         # Dimensionality of embedding used
    user_behavior: str = ""             # Implicit signal: accepted/rejected/regenerated
    reward_per_arm: dict = field(default_factory=dict)   # Per-model reward scores from bandit
    ttc_strategy: str = ""              # Which TTC strategy was used (if any)
    validator_results: dict = field(default_factory=dict) # Quality validator outcomes

    # Modality signals
    primary_modality: str = ""
    language: str = "en"
    token_count: int = 0

    # Input signal features
    task_type: str = ""
    reasoning_depth: float = 0.0
    multi_intent_score: float = 0.0
    instruction_count: int = 0

    # Uncertainty breakdown (new components)
    classification_entropy: float = 0.0
    instruction_conflict_score: float = 0.0
    cross_domain_score: float = 0.0

    def __post_init__(self):
        """Auto-compute query_hash if query is provided."""
        if self.query and not self.query_hash:
            self.query_hash = hashlib.sha256(self.query.encode()).hexdigest()[:16]
        # Truncate query for storage
        if len(self.query) > 500:
            self.query = self.query[:500] + "...[TRUNCATED]"


# ---------------------------------------------------------------------------
# Telemetry Logger
# ---------------------------------------------------------------------------

class TelemetryLogger:
    """
    Layer 9: Continuous Learning Loop.

    Logs structured routing telemetry asynchronously and exposes recalibration
    hooks for offline MLOps pipelines.
    """

    # In-memory accumulation buffer (thread-safe via lock)
    _buffer: list[RoutingTelemetry] = []
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def log_async(cls, telemetry: RoutingTelemetry) -> None:
        """
        Log a routing event asynchronously (non-blocking).

        The telemetry is appended to an in-memory buffer and persisted to
        the database in a background daemon thread, so request latency is
        never affected.
        """
        threading.Thread(
            target=cls._persist,
            args=(telemetry,),
            daemon=True,
        ).start()

    @classmethod
    def _persist(cls, telemetry: RoutingTelemetry) -> None:
        """Background thread: persist telemetry + buffer it for recalibration."""
        # Append to in-memory buffer (for MLOps batch reads)
        with cls._lock:
            cls._buffer.append(telemetry)
            # Keep buffer bounded to 10 000 most recent records
            if len(cls._buffer) > 10_000:
                cls._buffer = cls._buffer[-10_000:]

        # Persist to DB
        cls._write_to_db(telemetry)

        # Periodically trigger recalibration checks
        with cls._lock:
            buf_size = len(cls._buffer)
        if buf_size % 100 == 0:
            cls.recalibrate_triage()
        if buf_size % 200 == 0:
            cls.run_drift_scan()

    @classmethod
    def _write_to_db(cls, t: RoutingTelemetry) -> None:
        """Write a single telemetry record to the database."""
        try:
            from sqlmodel import Session
            from src.database.connection import get_engine
            from src.database.models.routing_telemetry import RoutingTelemetryRecord

            engine = get_engine()
            with Session(engine) as session:
                record = RoutingTelemetryRecord(
                    request_id=t.request_id,
                    timestamp=t.timestamp,
                    selected_model_id=t.selected_model_id,
                    final_model_id=t.final_model_id,
                    domain=t.domain,
                    intent=t.intent,
                    complexity_band=t.complexity_band,
                    quality_score=t.quality_score,
                    escalated=t.escalated,
                    escalation_count=t.escalation_count,
                    refusal_detected=t.refusal_detected,
                    cost_usd=t.cost_usd,
                    latency_ms=t.latency_ms,
                    uncertainty_score=t.uncertainty_score,
                    confidence_level=t.confidence_level,
                    novelty_score=t.novelty_score,
                    user_tier=t.user_tier,
                    budget_remaining=t.budget_remaining,
                    routing_source=t.routing_source,
                    predicted_quality=t.predicted_quality,
                    prediction_confidence_score=t.prediction_confidence_score,
                    uncertainty_escalated=t.uncertainty_escalated,
                )
                session.add(record)
                session.commit()
            logger.debug("telemetry_persisted", request_id=t.request_id)
        except Exception as e:
            # Never propagate — telemetry failure must never break routing
            logger.error("telemetry_persist_failed", error=str(e))

    @classmethod
    def recalibrate_triage(cls) -> None:
        """
        Layer 9 Recalibration Hook.

        Computes per-domain escalation statistics from the in-memory buffer
        and logs them as structured events. An offline MLOps job can consume
        these logs to:
          - Retrain the triage classifier with updated domain weights
          - Adjust bandit prior distributions
          - prune low-quality entries from semantic memory

        This fulfils the synopsis requirement:
          "Recalibration of triage classifiers" and
          "Adjusting routing thresholds"
        """
        with cls._lock:
            buffer_snapshot = list(cls._buffer)

        if not buffer_snapshot:
            return

        # Aggregate escalation rates by domain
        domain_stats: dict[str, dict] = {}
        for record in buffer_snapshot:
            d = record.domain or "unknown"
            if d not in domain_stats:
                domain_stats[d] = {
                    "total": 0, "escalated": 0, "avg_quality": 0.0,
                    "avg_cost": 0.0, "avg_latency": 0.0,
                }
            domain_stats[d]["total"] += 1
            domain_stats[d]["escalated"] += int(record.escalated)
            domain_stats[d]["avg_quality"] += record.quality_score
            domain_stats[d]["avg_cost"] += record.cost_usd
            domain_stats[d]["avg_latency"] += record.latency_ms

        # Compute and log the rates
        for domain, stats in domain_stats.items():
            n = stats["total"]
            esc_rate = stats["escalated"] / n if n > 0 else 0.0
            avg_quality = stats["avg_quality"] / n if n > 0 else 0.0
            avg_cost = stats["avg_cost"] / n if n > 0 else 0.0
            avg_latency = stats["avg_latency"] / n if n > 0 else 0.0
            logger.info(
                "triage_recalibration_signal",
                domain=domain,
                sample_count=n,
                escalation_rate=round(esc_rate, 4),
                avg_quality=round(avg_quality, 4),
                avg_cost_usd=round(avg_cost, 6),
                avg_latency_ms=round(avg_latency, 2),
            )

    @classmethod
    def run_drift_scan(cls) -> list:
        """Layer 9 drift scan over the buffered telemetry. Groups records by the
        routed model, compares each model's recent vs reference predicted-quality
        distribution (KL divergence), and freezes that model's calibration on a
        halt-level shift. Pure statistics over numbers the router already
        produced; never blocks the request path."""
        with cls._lock:
            snapshot = list(cls._buffer)
        if not snapshot:
            return []
        try:
            from src.layer0_model_infra.routing.drift_detector import get_drift_detector
            results = get_drift_detector().scan(snapshot)
            flagged = [r for r in results if r.level in ("info", "warn", "halt")]
            if flagged:
                logger.info(
                    "layer3_drift_scan",
                    models_scanned=len(results),
                    flagged=[
                        {"model": r.model_id, "level": r.level,
                         "kl": round(r.kl_divergence, 4), "frozen": r.frozen}
                        for r in flagged
                    ],
                )
            return results
        except Exception as e:
            logger.error("layer3_drift_scan_failed", error=str(e))
            return []

    @classmethod
    def update_semantic_memory_entries(cls) -> None:
        """
        Mark stale semantic memory entries for pruning based on recent telemetry.

        Heuristic: if a model that was cached starts escalating frequently,
        the cached route is stale and should be pruned.
        """
        with cls._lock:
            buffer_snapshot = list(cls._buffer)

        if not buffer_snapshot:
            return

        # Find models with high escalation rates
        model_escalation: dict[str, dict] = {}
        for record in buffer_snapshot:
            mid = record.selected_model_id
            if mid not in model_escalation:
                model_escalation[mid] = {"total": 0, "escalated": 0}
            model_escalation[mid]["total"] += 1
            model_escalation[mid]["escalated"] += int(record.escalated)

        stale_models = []
        for mid, stats in model_escalation.items():
            if stats["total"] >= 10:
                esc_rate = stats["escalated"] / stats["total"]
                if esc_rate > 0.5:  # >50% escalation → stale
                    stale_models.append(mid)

        if stale_models:
            logger.info(
                "semantic_memory_prune_signal",
                stale_models=stale_models,
                message="These models have >50% escalation rate; cached entries should be pruned",
            )

    @classmethod
    def compute_evaluation_statistics(cls) -> dict:
        """
        Aggregate quality/cost/latency stats by domain and time window.

        Returns dict of domain → {avg_quality, avg_cost, avg_latency, count}.
        Used by monitoring dashboards and MLOps jobs.
        """
        with cls._lock:
            buffer_snapshot = list(cls._buffer)

        if not buffer_snapshot:
            return {}

        stats_by_domain: dict[str, dict] = {}
        for record in buffer_snapshot:
            d = record.domain or "unknown"
            if d not in stats_by_domain:
                stats_by_domain[d] = {
                    "count": 0, "total_quality": 0.0,
                    "total_cost": 0.0, "total_latency": 0.0,
                    "escalated": 0, "refusals": 0,
                }
            s = stats_by_domain[d]
            s["count"] += 1
            s["total_quality"] += record.quality_score
            s["total_cost"] += record.cost_usd
            s["total_latency"] += record.latency_ms
            s["escalated"] += int(record.escalated)
            s["refusals"] += int(record.refusal_detected)

        result = {}
        for domain, s in stats_by_domain.items():
            n = s["count"]
            result[domain] = {
                "count": n,
                "avg_quality": round(s["total_quality"] / n, 4),
                "avg_cost_usd": round(s["total_cost"] / n, 6),
                "avg_latency_ms": round(s["total_latency"] / n, 2),
                "escalation_rate": round(s["escalated"] / n, 4),
                "refusal_rate": round(s["refusals"] / n, 4),
            }

        return result

    @classmethod
    def get_buffer_stats(cls) -> dict:
        """Return summary of the in-memory telemetry buffer (for monitoring)."""
        with cls._lock:
            buf = list(cls._buffer)
        if not buf:
            return {"buffer_size": 0}

        total = len(buf)
        escalated = sum(1 for r in buf if r.escalated)
        avg_quality = sum(r.quality_score for r in buf) / total
        avg_cost = sum(r.cost_usd for r in buf) / total
        avg_latency = sum(r.latency_ms for r in buf) / total
        return {
            "buffer_size":     total,
            "escalation_rate": round(escalated / total, 4),
            "avg_quality":     round(avg_quality, 4),
            "avg_cost_usd":    round(avg_cost, 6),
            "avg_latency_ms":  round(avg_latency, 2),
        }


# Module-level convenience alias
def get_telemetry_logger() -> type[TelemetryLogger]:
    """Return the TelemetryLogger class (it is stateless / classmethod-only)."""
    return TelemetryLogger
