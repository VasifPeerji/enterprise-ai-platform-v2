"""
📁 File: src/layer0_model_infra/routing/calibration_store.py
Layer: Layer 0 — Layer 3 redesign (Stage C calibration)
Purpose: Online EMA calibration of kNN quality predictions, per (model, feature_cell).
Depends on: pyarrow, src/layer0_model_infra/routing/layer3_types, routing_config
Used by: knn_router (read path: get_multiplier), post-Layer-7 hook (write path: update)

The kNN router predicts a per-model quality for each query. Reality — the Layer 7
quality score observed AFTER the call — drifts from that prediction: a model can
systematically under- or over-perform its benchmark-derived estimate within a
slice of traffic (a modality / language / risk / difficulty cell). This store
learns a single multiplicative correction online, with no training loop.

The "learning" is one exponential moving average over the ratio
``observed_quality / predicted_quality``, bucketed by a coarse feature cell
("{modality}:{language}:{high_risk}:{difficulty}"):

    new_multiplier = (1 - α)·old_multiplier + α·ratio        (α = ema_alpha)

Confidence gating
-----------------
A multiplier is only APPLIED once its cell has accumulated enough observations
to be trusted:

    confidence(n) = 1 - exp(-n / confidence_observations_constant)

Below ``confidence_threshold_to_apply`` the multiplier is NOT applied —
get_multiplier returns 1.0 — so a handful of noisy early observations can't
swing routing. The raw EMA keeps accumulating in the background regardless.

What feeds the EMA
------------------
ONLY ``RoutingSource.KNN_CORPUS`` decisions update the multiplier. Cache hits,
fallbacks, exploration and warmup shots are deliberately off-policy or carry no
meaningful predicted_quality, so folding them into the EMA would poison the
correction for the cells they touch.

Persistence
-----------
The in-memory dict is the runtime source of truth (lookups are sub-microsecond
and on the hot path of every route). It is loaded from and flushed to a Parquet
file so calibration survives restarts. Writes are NOT auto-flushed per update
(that would add Parquet I/O to the post-call path); callers flush via ``save()``
on a cadence — the calibration auto-adjust job (Batch 5) owns that schedule.

Thread-safe (RLock around the cell dict + the frozen set). Drift halt: the drift
detector can ``freeze(model_id)`` to stop the EMA from moving while a model's
prediction distribution is under manual review.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.layer0_model_infra.config.routing_config import Layer3CalibrationConfig
from src.layer0_model_infra.routing.layer3_types import RoutingDecision, RoutingSource
from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Schema constants — shared with the persistence layer
# ============================================================================

CALIBRATION_COLUMNS = [
    "model_id",
    "feature_cell",
    "n_observations",
    "multiplier",
    "last_updated",
    "confidence",
]


# ============================================================================
# Cell
# ============================================================================


class _Cell:
    """One (model_id, feature_cell) calibration cell. Mutable, lock-protected
    by the owning store."""

    __slots__ = ("n_observations", "multiplier", "last_updated", "confidence")

    def __init__(
        self,
        n_observations: int = 0,
        multiplier: float = 1.0,
        last_updated: Optional[datetime] = None,
        confidence: float = 0.0,
    ) -> None:
        self.n_observations = n_observations
        self.multiplier = multiplier
        self.last_updated = last_updated or datetime.now(timezone.utc)
        self.confidence = confidence


# ============================================================================
# Store
# ============================================================================


class CalibrationStore:
    """Per-(model, feature_cell) EMA multiplier store.

    Public API:
        get_multiplier(model_id, feature_cell) -> float   # hot read path
        observations(model_id, feature_cell)   -> int
        total_observations(model_id)            -> int     # warmup check
        update(decision, observed_quality)      -> bool    # post-Layer-7 write
        freeze(model_id) / unfreeze(model_id) / is_frozen(model_id)
        save() / load()                                    # Parquet persistence
        stats() / clear()
    """

    def __init__(
        self,
        parquet_path: str | Path,
        config: Optional[Layer3CalibrationConfig] = None,
    ) -> None:
        self._config = config or Layer3CalibrationConfig()
        self._path = Path(parquet_path)
        if not self._path.is_absolute():
            # routing/calibration_store.py — four parents up is the repo root.
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            self._path = (repo_root / self._path).resolve()
        self._lock = threading.RLock()
        self._cells: dict[tuple[str, str], _Cell] = {}
        self._frozen: set[str] = set()
        self._dirty = False
        self._updates_since_save = 0
        self.load()

    # ---------- helpers ----------

    @staticmethod
    def _key(model_id: str, feature_cell: str) -> tuple[str, str]:
        return (model_id, feature_cell)

    def _confidence(self, n: int) -> float:
        """confidence(n) = 1 - exp(-n / const). Monotonic, saturates at 1.0."""
        const = self._config.confidence_observations_constant
        if const <= 0:
            return 1.0 if n > 0 else 0.0
        return 1.0 - math.exp(-n / const)

    # ---------- persistence ----------

    def load(self) -> None:
        """Load cells from the Parquet file if it exists. Confidence is
        recomputed from n_observations so a changed
        ``confidence_observations_constant`` takes effect on the next run rather
        than trusting a stale stored value.
        """
        with self._lock:
            self._cells.clear()
            if not self._path.exists():
                logger.info("layer3_calibration_store_empty", path=str(self._path))
                return
            try:
                import pyarrow.parquet as pq  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "pyarrow is required for CalibrationStore — run `pip install pyarrow`"
                ) from exc

            rows = pq.read_table(self._path).to_pylist()
            for r in rows:
                n = int(r["n_observations"])
                self._cells[self._key(r["model_id"], r["feature_cell"])] = _Cell(
                    n_observations=n,
                    multiplier=float(r["multiplier"]),
                    last_updated=r["last_updated"],
                    confidence=self._confidence(n),
                )
            self._dirty = False
            logger.info(
                "layer3_calibration_store_loaded",
                path=str(self._path),
                cells=len(self._cells),
            )

    def save(self) -> None:
        """Atomically flush all cells to Parquet (write-temp-then-replace so a
        crash mid-write can't corrupt the existing file)."""
        with self._lock:
            try:
                import pyarrow as pa  # type: ignore
                import pyarrow.parquet as pq  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "pyarrow is required for CalibrationStore — run `pip install pyarrow`"
                ) from exc

            self._path.parent.mkdir(parents=True, exist_ok=True)
            items = list(self._cells.items())
            table = pa.table(
                {
                    "model_id": [k[0] for k, _ in items],
                    "feature_cell": [k[1] for k, _ in items],
                    "n_observations": [c.n_observations for _, c in items],
                    "multiplier": [c.multiplier for _, c in items],
                    "last_updated": [c.last_updated for _, c in items],
                    "confidence": [c.confidence for _, c in items],
                },
                schema=pa.schema(
                    [
                        ("model_id", pa.string()),
                        ("feature_cell", pa.string()),
                        ("n_observations", pa.int64()),
                        ("multiplier", pa.float64()),
                        ("last_updated", pa.timestamp("us", tz="UTC")),
                        ("confidence", pa.float64()),
                    ]
                ),
            )
            tmp = self._path.with_name(self._path.name + ".tmp")
            pq.write_table(table, tmp, compression="zstd")
            tmp.replace(self._path)
            self._dirty = False
            self._updates_since_save = 0
            logger.info(
                "layer3_calibration_store_saved",
                path=str(self._path),
                cells=len(items),
            )

    # ---------- read path (hot) ----------

    def get_multiplier(self, model_id: str, feature_cell: str) -> float:
        """Return the calibration multiplier to apply to a raw kNN-weighted
        quality. Returns 1.0 (no correction) when the cell is unknown or its
        confidence hasn't yet cleared ``confidence_threshold_to_apply``.
        """
        with self._lock:
            cell = self._cells.get(self._key(model_id, feature_cell))
            if cell is None:
                return 1.0
            if cell.confidence < self._config.confidence_threshold_to_apply:
                return 1.0
            return cell.multiplier

    def observations(self, model_id: str, feature_cell: str) -> int:
        """Observation count for one cell (used by ε-exploration's
        max_observations_for_borderline gate)."""
        with self._lock:
            cell = self._cells.get(self._key(model_id, feature_cell))
            return cell.n_observations if cell else 0

    def total_observations(self, model_id: str) -> int:
        """Observations for a model across ALL feature cells (used by the
        warmup-exit check in knn_router.is_in_warmup)."""
        with self._lock:
            return sum(
                c.n_observations
                for (mid, _cell_key), c in self._cells.items()
                if mid == model_id
            )

    # ---------- write path (post-Layer-7) ----------

    def update(self, decision: RoutingDecision, observed_quality: float) -> bool:
        """Fold a single observed Layer-7 quality into the EMA for the decision's
        (selected_model, feature_cell). Returns True if the multiplier moved.

        No-ops (return False) when:
          • the decision didn't come from the kNN corpus path (off-policy),
          • predicted_quality is missing or non-positive (no ratio to form),
          • the decision carries no feature_cell,
          • the model is frozen by the drift detector.
        """
        if decision.source != RoutingSource.KNN_CORPUS:
            return False
        predicted = decision.predicted_quality
        if predicted is None or predicted <= 0.0:
            return False
        feature_cell = decision.feature_cell
        if not feature_cell:
            return False

        model_id = decision.selected_model
        observed = max(0.0, min(1.0, float(observed_quality)))
        alpha = self._config.ema_alpha

        with self._lock:
            if model_id in self._frozen:
                return False

            ratio = observed / predicted
            key = self._key(model_id, feature_cell)
            cell = self._cells.get(key)
            if cell is None:
                cell = _Cell(n_observations=0, multiplier=1.0)
                self._cells[key] = cell

            new_multiplier = (1.0 - alpha) * cell.multiplier + alpha * ratio
            new_multiplier = max(
                self._config.multiplier_min,
                min(self._config.multiplier_max, new_multiplier),
            )

            cell.multiplier = new_multiplier
            cell.n_observations += 1
            cell.last_updated = datetime.now(timezone.utc)
            cell.confidence = self._confidence(cell.n_observations)
            self._dirty = True
            self._updates_since_save += 1
            auto_every = self._config.auto_save_every
            should_save = auto_every > 0 and self._updates_since_save >= auto_every

        # Persist outside the locked update so Parquet I/O isn't on the path of
        # concurrent reads. save() re-acquires the lock and resets the counter.
        if should_save:
            try:
                self.save()
            except Exception as exc:  # a flush failure must never break routing
                logger.warning("layer3_calibration_autosave_failed", reason=str(exc))
        return True

    # ---------- drift control ----------

    def freeze(self, model_id: str) -> None:
        """Stop updating a model's multipliers (drift halt — manual review)."""
        with self._lock:
            self._frozen.add(model_id)
            logger.warning("layer3_calibration_frozen", model_id=model_id)

    def unfreeze(self, model_id: str) -> None:
        with self._lock:
            self._frozen.discard(model_id)

    def is_frozen(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._frozen

    # ---------- introspection ----------

    def stats(self) -> dict:
        with self._lock:
            threshold = self._config.confidence_threshold_to_apply
            applied = sum(1 for c in self._cells.values() if c.confidence >= threshold)
            total_obs = sum(c.n_observations for c in self._cells.values())
            return {
                "cells": len(self._cells),
                "cells_applied": applied,
                "total_observations": total_obs,
                "frozen_models": sorted(self._frozen),
                "dirty": self._dirty,
                "path": str(self._path),
            }

    def clear(self) -> None:
        """Drop all in-memory cells + frozen state. Does not touch the file
        until the next save()."""
        with self._lock:
            self._cells.clear()
            self._frozen.clear()
            self._dirty = False


# ============================================================================
# Singleton
# ============================================================================

_store: Optional[CalibrationStore] = None
_store_lock = threading.Lock()


def get_calibration_store() -> CalibrationStore:
    """Process-wide CalibrationStore using paths/config from routing_config."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                layer3_cfg = get_routing_config().layer3
                _store = CalibrationStore(
                    layer3_cfg.calibration_path,
                    layer3_cfg.calibration,
                )
    return _store


def reset_calibration_store() -> None:
    """Test helper — drop the singleton so the next get_calibration_store()
    constructs a fresh one. Not for production use."""
    global _store
    with _store_lock:
        _store = None
