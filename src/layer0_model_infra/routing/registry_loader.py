"""
📁 File: src/layer0_model_infra/routing/registry_loader.py
Layer: Layer 0 — Layer 3 redesign
Purpose: Load the Layer 3 routing registry from data/registry.json with
         env-var-gated dynamic activation.
Depends on: pydantic, src/layer0_model_infra/routing/layer3_types
Used by: knn_router, feature_extractor (next batch), validation scripts

The plan calls for a single source of truth for model metadata in
``data/registry.json``. This module loads it, validates the schema, and gates
``is_active`` on the presence of each model's ``required_env_var`` — so adding
or removing an API key at runtime flips the relevant models in/out of routing
without restarting the process (call ``refresh_activation()`` on the singleton).

The legacy in-code registry (src/layer0_model_infra/registry.py) is preserved
for the duration of the parallel-build migration; once Layer 3 cuts over, it
goes away.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from src.layer0_model_infra.routing.layer3_types import (
    CoverageQuality,
    RegistryEntry,
    SafeDefaults,
)
from src.shared.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Loader
# ============================================================================


class Layer3Registry:
    """In-memory registry loaded from ``data/registry.json``.

    Thread-safe. Two refresh paths:
      • ``reload()`` re-reads the JSON file (use after editing the file)
      • ``refresh_activation()`` re-evaluates ``required_env_var`` for each
        entry (use after an API key is added/removed in the live process)

    Both are idempotent and inexpensive.
    """

    def __init__(self, registry_path: str | Path) -> None:
        self._path = Path(registry_path)
        if not self._path.is_absolute():
            # Resolve relative to repo root (this file is at
            # src/layer0_model_infra/routing/registry_loader.py — three
            # parents up gets us to repo root)
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            self._path = (repo_root / self._path).resolve()
        self._lock = threading.RLock()
        self._entries: dict[str, RegistryEntry] = {}
        self._safe_defaults: Optional[SafeDefaults] = None
        self._meta: dict = {}
        self.reload()

    # ---------- loading ----------

    def reload(self) -> None:
        """Re-read the JSON file from disk and rebuild the entry map."""
        with self._lock:
            if not self._path.exists():
                raise FileNotFoundError(
                    f"Layer 3 registry file not found: {self._path}"
                )
            with self._path.open("r", encoding="utf-8") as f:
                payload = json.load(f)

            self._meta = payload.get("_meta", {})
            safe_defaults_dict = payload.get("safe_defaults") or {}
            models = payload.get("models") or []

            if not models:
                raise ValueError(
                    f"Layer 3 registry has zero models: {self._path}"
                )

            entries: dict[str, RegistryEntry] = {}
            for raw in models:
                try:
                    entry = RegistryEntry(**raw)
                except ValidationError as exc:
                    logger.error(
                        "layer3_registry_entry_invalid",
                        model_id=raw.get("model_id", "?"),
                        errors=exc.errors(),
                    )
                    raise
                if entry.model_id in entries:
                    raise ValueError(
                        f"Duplicate model_id in registry: {entry.model_id}"
                    )
                entries[entry.model_id] = entry

            try:
                safe_defaults = SafeDefaults(**safe_defaults_dict)
            except ValidationError as exc:
                logger.error("layer3_registry_safe_defaults_invalid", errors=exc.errors())
                raise

            # Validate that every safe-default model_id exists in the registry
            for modality, model_id in safe_defaults_dict.items():
                if model_id not in entries:
                    raise ValueError(
                        f"safe_defaults['{modality}']='{model_id}' is not in the registry"
                    )

            self._entries = entries
            self._safe_defaults = safe_defaults
            self.refresh_activation()
            logger.info(
                "layer3_registry_loaded",
                path=str(self._path),
                models=len(self._entries),
                active=sum(1 for e in self._entries.values() if e.is_active),
            )

    def refresh_activation(self) -> dict[str, bool]:
        """Re-evaluate ``is_active`` for every entry based on its
        ``required_env_var``. Returns a dict of model_id -> new is_active value
        so callers can diff against the previous state if they want.
        """
        with self._lock:
            new_state: dict[str, bool] = {}
            for entry in self._entries.values():
                required = entry.required_env_var
                if required is None:
                    # No env-var gate — model is always active (e.g. local Ollama)
                    entry.is_active = True
                else:
                    value = os.getenv(required, "").strip()
                    entry.is_active = bool(value)
                new_state[entry.model_id] = entry.is_active
            return new_state

    # ---------- accessors ----------

    @property
    def safe_defaults(self) -> SafeDefaults:
        with self._lock:
            if self._safe_defaults is None:
                raise RuntimeError("Registry was not loaded")
            return self._safe_defaults

    def get(self, model_id: str) -> RegistryEntry:
        with self._lock:
            try:
                return self._entries[model_id]
            except KeyError as exc:
                raise KeyError(f"Unknown model_id in Layer 3 registry: {model_id}") from exc

    def has(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._entries

    def all_models(self) -> list[RegistryEntry]:
        with self._lock:
            return list(self._entries.values())

    def active_models(self) -> list[RegistryEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.is_active]

    def by_coverage(self, coverage: CoverageQuality) -> list[RegistryEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.coverage_quality == coverage]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._entries)
            active = sum(1 for e in self._entries.values() if e.is_active)
            by_provider: dict[str, int] = {}
            by_coverage: dict[str, int] = {"full": 0, "medium": 0, "low": 0}
            for e in self._entries.values():
                by_provider[e.provider] = by_provider.get(e.provider, 0) + 1
                by_coverage[e.coverage_quality.value] += 1
            return {
                "total": total,
                "active": active,
                "by_provider": by_provider,
                "by_coverage_quality": by_coverage,
                "schema_version": self._meta.get("schema_version", "unknown"),
                "last_verified": self._meta.get("last_verified", "unknown"),
            }


# ============================================================================
# Singleton — thread-safe lazy init
# ============================================================================

_registry: Optional[Layer3Registry] = None
_registry_lock = threading.Lock()


def get_layer3_registry(path: Optional[str] = None) -> Layer3Registry:
    """Process-wide Layer 3 registry. Constructed on first access; subsequent
    callers receive the same instance. Pass ``path`` only on first call (or
    after ``reset_layer3_registry()`` for tests).
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                config = get_routing_config()
                _registry = Layer3Registry(path or config.layer3.registry_path)
    return _registry


def reset_layer3_registry() -> None:
    """Test helper — drop the singleton so the next get_layer3_registry()
    constructs a fresh one. Not for production use.
    """
    global _registry
    with _registry_lock:
        _registry = None
