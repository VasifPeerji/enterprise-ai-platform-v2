"""
📁 File: src/layer0_model_infra/routing/quality_head.py
Layer: Layer 0 — Layer 3 (learned quality head — inference)
Purpose: Predict per-(query, model) quality from the query embedding so the prior
         path (no kNN neighbours) becomes query-AWARE instead of routing every
         model off a flat constant. A drop-in replacement for the aggregate prior,
         for the models the head was trained on.
Depends on: numpy + artifact src/layer0_model_infra/data/quality_head.npz
            (built by scripts/layer3/train_quality_head.py).
Used by: knn_router (prior path)

Inference is one matrix multiply (W·embedding + b, clipped to [0,1]) — NO torch or
sklearn at runtime. If the artifact is missing or malformed the head is INERT
(predict_all -> {}) and the router transparently falls back to the flat prior, so
this can never break routing.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import numpy as np

from src.shared.logger import get_logger

logger = get_logger(__name__)

ARTIFACT_FILENAME = "quality_head.npz"


class QualityHead:
    """Stack of per-model linear regressors over the query embedding."""

    def __init__(self, artifact_path: str | Path, expected_encoder: Optional[str] = None) -> None:
        self._path = Path(artifact_path)
        self._expected_encoder = expected_encoder
        self._lock = threading.Lock()
        self._model_ids: list[str] = []
        self._W: Optional[np.ndarray] = None   # (k, dim)
        self._b: Optional[np.ndarray] = None   # (k,)
        self._loaded = False
        self.load()

    def load(self) -> None:
        with self._lock:
            self._model_ids, self._W, self._b, self._loaded = [], None, None, False
            if not self._path.exists():
                logger.info("layer3_quality_head_absent", path=str(self._path))
                return
            try:
                data = np.load(self._path, allow_pickle=False)
                self._model_ids = [str(m) for m in data["model_ids"].tolist()]
                self._W = data["weights"].astype(np.float32)
                self._b = data["biases"].astype(np.float32)
                enc = str(data["encoder_name"]) if "encoder_name" in data.files else None
                if self._expected_encoder and enc and enc != self._expected_encoder:
                    logger.warning(
                        "layer3_quality_head_encoder_mismatch",
                        artifact=enc, expected=self._expected_encoder,
                    )
                self._loaded = self._W is not None and len(self._model_ids) == self._W.shape[0]
                logger.info(
                    "layer3_quality_head_loaded",
                    models=len(self._model_ids),
                    dim=(self._W.shape[1] if self._W is not None else 0),
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("layer3_quality_head_load_failed", reason=str(exc))
                self._model_ids, self._W, self._b, self._loaded = [], None, None, False

    @property
    def is_active(self) -> bool:
        return self._loaded

    @property
    def model_ids(self) -> set[str]:
        return set(self._model_ids)

    def has(self, model_id: str) -> bool:
        return model_id in self._model_ids

    def predict_all(self, embedding) -> dict[str, float]:
        """{model_id: predicted_quality in [0,1]} for every covered model. Returns
        {} when the head is inert or the embedding dimension doesn't match."""
        with self._lock:
            if not self._loaded or self._W is None or self._b is None:
                return {}
            emb = np.asarray(embedding, dtype=np.float32).ravel()
            if emb.shape[0] != self._W.shape[1]:
                return {}
            raw = np.clip(self._W @ emb + self._b, 0.0, 1.0)
            return {mid: float(raw[i]) for i, mid in enumerate(self._model_ids)}


# ============================================================================
# Singleton
# ============================================================================

_head: Optional[QualityHead] = None
_head_lock = threading.Lock()


def get_quality_head() -> QualityHead:
    """Process-wide QualityHead, reading the artifact next to the registry data."""
    global _head
    if _head is None:
        with _head_lock:
            if _head is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                enc = get_routing_config().layer3.encoder.model_name
                data_dir = Path(__file__).resolve().parent.parent / "data"
                _head = QualityHead(data_dir / ARTIFACT_FILENAME, expected_encoder=enc)
    return _head


def reset_quality_head() -> None:
    """Test helper — drop the singleton."""
    global _head
    with _head_lock:
        _head = None
