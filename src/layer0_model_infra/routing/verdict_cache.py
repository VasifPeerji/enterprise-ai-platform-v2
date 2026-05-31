"""
📁 File: src/layer0_model_infra/routing/verdict_cache.py
Layer: Layer 0 — Layer 3 redesign (Stage A)
Purpose: Two-tier verdict cache for the kNN router.
Depends on: numpy, model2vec (optional), src/layer0_model_infra/routing/layer3_types
Used by: knn_router (next batch)

Stage A short-circuits the routing pipeline for queries we've already decided
on. Two tiers:

  Tier 1 — Exact match (SHA256 of normalised query). ~0.1 ms.
  Tier 2 — Semantic near-duplicate via Model2Vec ANN over cached signatures
           at cosine ≥ 0.93 (configurable). ~0.5-1 ms.

When either tier hits AND the entry isn't stale (TTL not exceeded, schema
version still current), we return the cached RoutingDecision with
``source=CACHE_HIT`` and ``cache_hit_kind`` set so telemetry can attribute
the latency saved.

Capacity: 10 000 most-recent entries, LRU-evicted on insert. In-memory only
for this batch; optional SQLite persistence can be added later if telemetry
shows cold-start hit rate is suffering.

Thread-safe (RLock around the dict + the embedding matrix).

Graceful degradation: if model2vec is not importable, Tier 2 is silently
disabled — Tier 1 alone still works. Same pattern as Layer 0 and Layer 2.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from src.layer0_model_infra.routing.layer3_types import (
    LAYER3_SCHEMA_VERSION,
    RoutingDecision,
    RoutingSource,
    VerdictCacheEntry,
)
from src.shared.logger import get_logger

logger = get_logger(__name__)


# Negation/polarity scoring is shared with Layer 2's semantic memory so both
# caches reject the same "install vs uninstall" class of false near-duplicates.
# Imported lazily + cached to avoid pulling semantic_memory into this module's
# import path (and it's only needed on a Tier-2 hit, by which point the embedder
# is already loaded anyway).
_neg_score_fn = None


def _negation_score(text: str) -> int:
    global _neg_score_fn
    if _neg_score_fn is None:
        from src.layer0_model_infra.routing.semantic_memory import _negation_score as _ns
        _neg_score_fn = _ns
    return _neg_score_fn(text)


# ============================================================================
# Embedder — Model2Vec with no-op fallback
# ============================================================================


class _Embedder:
    """Wraps Model2Vec for near-duplicate detection.

    If model2vec isn't installed, ``available`` is False and the cache
    operates in Tier-1-only mode.
    """

    def __init__(self, model_name: str) -> None:
        self.dim: int = 0
        self._model = None
        try:
            from model2vec import StaticModel  # type: ignore
            self._model = StaticModel.from_pretrained(model_name)
            self.dim = self._model.dim
            logger.info("layer3_verdict_cache_embedder_loaded", model=model_name, dim=self.dim)
        except ImportError:
            logger.warning(
                "layer3_verdict_cache_embedder_unavailable",
                reason="model2vec not installed",
                fallback="Tier-1 only (exact-match)",
            )
        except Exception as exc:
            logger.warning(
                "layer3_verdict_cache_embedder_init_failed",
                reason=str(exc),
                fallback="Tier-1 only",
            )

    @property
    def available(self) -> bool:
        return self._model is not None

    def encode(self, text: str) -> np.ndarray:
        if self._model is None:
            return np.zeros(0, dtype=np.float32)
        vec = np.asarray(self._model.encode(text), dtype=np.float32)
        norm = float(np.linalg.norm(vec)) + 1e-9
        return vec / norm


# Module-level embedder cache so multiple cache instances (e.g. in tests)
# share one model load.
_embedder_cache: dict[str, _Embedder] = {}
_embedder_cache_lock = threading.Lock()


def _get_or_build_embedder(model_name: str) -> _Embedder:
    if model_name in _embedder_cache:
        return _embedder_cache[model_name]
    with _embedder_cache_lock:
        if model_name in _embedder_cache:
            return _embedder_cache[model_name]
        emb = _Embedder(model_name)
        _embedder_cache[model_name] = emb
        return emb


# ============================================================================
# Hit result
# ============================================================================


class VerdictCacheHit:
    """Light wrapper around a hit. Encapsulates the kind (exact/semantic) +
    the underlying entry. The router consumes ``decision`` and logs ``kind``.
    """

    __slots__ = ("entry", "kind", "similarity")

    def __init__(self, entry: VerdictCacheEntry, kind: str, similarity: float = 1.0) -> None:
        self.entry = entry
        self.kind = kind  # "exact" | "semantic"
        self.similarity = similarity

    @property
    def decision(self) -> RoutingDecision:
        return self.entry.decision


# ============================================================================
# Cache
# ============================================================================


class VerdictCache:
    """LRU-bounded, two-tier (exact + semantic) verdict cache.

    Public API:
        lookup(query)  -> Optional[VerdictCacheHit]
        put(query, decision)
        invalidate(query) -> bool
        stats()
        clear()
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 168 * 3600.0,
        max_entries: int = 10_000,
        semantic_threshold: float = 0.93,
        semantic_model_name: str = "minishlab/potion-base-8M",
        enable_semantic_tier: bool = True,
        enable_negation_guard: bool = True,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._semantic_threshold = semantic_threshold
        self._negation_guard = enable_negation_guard

        # OrderedDict by query_signature → entry; LRU order maintained on
        # access. Tier 1 lookups go straight against this.
        self._lock = threading.RLock()
        self._entries: "OrderedDict[str, VerdictCacheEntry]" = OrderedDict()

        # Tier 2 — parallel arrays of embeddings + signature list. NumPy matrix
        # is rebuilt lazily when stale.
        self._embedder: Optional[_Embedder] = None
        if enable_semantic_tier:
            self._embedder = _get_or_build_embedder(semantic_model_name)
        self._sig_to_embedding: dict[str, np.ndarray] = {}
        self._matrix_cache: Optional[tuple[list[str], np.ndarray]] = None

        # Metrics
        self._lookup_count = 0
        self._hit_count_exact = 0
        self._hit_count_semantic = 0
        self._miss_count = 0
        self._eviction_count = 0
        self._stale_count = 0

    # ---------- normalisation ----------

    @staticmethod
    def _normalise(query: str) -> str:
        """Lowercase + collapse whitespace. The exact-match tier hashes this
        string, so two queries that differ only in casing or whitespace are
        treated as equivalent.
        """
        return " ".join((query or "").lower().split())

    @staticmethod
    def _signature(normalised: str) -> str:
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    # ---------- public ----------

    def lookup(self, query: str) -> Optional[VerdictCacheHit]:
        """Return a VerdictCacheHit on cache hit, else None.

        On any hit (exact or semantic) the entry is moved to the most-recently-
        used end of the LRU and its hit_count is incremented.
        """
        with self._lock:
            self._lookup_count += 1
            if not query or not query.strip():
                self._miss_count += 1
                return None

            normalised = self._normalise(query)
            signature = self._signature(normalised)

            # Tier 1 — exact match
            entry = self._entries.get(signature)
            if entry is not None:
                if entry.is_stale(self._ttl, LAYER3_SCHEMA_VERSION):
                    self._stale_count += 1
                    self._remove_locked(signature)
                else:
                    self._entries.move_to_end(signature)
                    entry.hit_count += 1
                    self._hit_count_exact += 1
                    return VerdictCacheHit(entry, kind="exact", similarity=1.0)

            # Tier 2 — semantic ANN
            if self._embedder is not None and self._embedder.available and self._entries:
                hit = self._tier2_lookup(normalised)
                if hit is not None:
                    self._hit_count_semantic += 1
                    return hit

            self._miss_count += 1
            return None

    def put(self, query: str, decision: RoutingDecision) -> None:
        """Store a routing decision. Evicts the LRU entry if at capacity.

        Caller is responsible for not storing cache_hit decisions back into
        the cache (would be circular).
        """
        if decision.source == RoutingSource.CACHE_HIT:
            return
        with self._lock:
            normalised = self._normalise(query)
            if not normalised:
                return
            signature = self._signature(normalised)
            entry = VerdictCacheEntry(
                query_signature=signature,
                normalised_query=normalised,
                decision=decision,
                cached_at=datetime.now(timezone.utc),
                hit_count=0,
            )
            # If replacing an existing entry, drop the prior embedding row
            if signature in self._entries:
                self._remove_locked(signature)
            self._entries[signature] = entry
            self._entries.move_to_end(signature)

            # Tier 2 — compute + cache embedding
            if self._embedder is not None and self._embedder.available:
                vec = self._embedder.encode(normalised)
                if vec.size > 0:
                    self._sig_to_embedding[signature] = vec
                    self._matrix_cache = None  # invalidate stacked matrix

            # LRU eviction
            while len(self._entries) > self._max:
                old_sig, _ = self._entries.popitem(last=False)
                self._sig_to_embedding.pop(old_sig, None)
                self._eviction_count += 1
                self._matrix_cache = None

    def invalidate(self, query: str) -> bool:
        """Drop a specific query's entry. Returns True if anything was removed."""
        with self._lock:
            signature = self._signature(self._normalise(query))
            if signature in self._entries:
                self._remove_locked(signature)
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sig_to_embedding.clear()
            self._matrix_cache = None

    def stats(self) -> dict:
        with self._lock:
            total = self._lookup_count
            hits = self._hit_count_exact + self._hit_count_semantic
            return {
                "size": len(self._entries),
                "capacity": self._max,
                "embedder_available": bool(self._embedder and self._embedder.available),
                "lookups": total,
                "hits_exact": self._hit_count_exact,
                "hits_semantic": self._hit_count_semantic,
                "misses": self._miss_count,
                "stale_evictions": self._stale_count,
                "lru_evictions": self._eviction_count,
                "hit_rate": hits / total if total > 0 else 0.0,
            }

    # ---------- internals ----------

    def _remove_locked(self, signature: str) -> None:
        """Caller must hold ``_lock``."""
        self._entries.pop(signature, None)
        self._sig_to_embedding.pop(signature, None)
        self._matrix_cache = None

    def _tier2_lookup(self, normalised: str) -> Optional[VerdictCacheHit]:
        """Embedding-similarity tier. Caller holds the lock. Returns a
        VerdictCacheHit or None.
        """
        # Build the (signatures, matrix) stack lazily — invalidated on every
        # put / eviction
        if self._matrix_cache is None or len(self._matrix_cache[0]) != len(self._sig_to_embedding):
            if not self._sig_to_embedding:
                return None
            sigs = list(self._sig_to_embedding.keys())
            vectors = [self._sig_to_embedding[s] for s in sigs]
            try:
                matrix = np.stack(vectors, axis=0)
            except ValueError:
                # Inconsistent dims — defensive guard, shouldn't normally fire
                return None
            self._matrix_cache = (sigs, matrix)

        sigs, matrix = self._matrix_cache

        query_vec = self._embedder.encode(normalised)
        if query_vec.size == 0:
            return None
        if query_vec.shape[0] != matrix.shape[1]:
            return None  # dim mismatch (changing embedder mid-run)

        sims = matrix @ query_vec
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        if best_sim < self._semantic_threshold:
            return None

        best_sig = sigs[best_idx]
        entry = self._entries.get(best_sig)
        if entry is None:
            return None
        if entry.is_stale(self._ttl, LAYER3_SCHEMA_VERSION):
            self._stale_count += 1
            self._remove_locked(best_sig)
            return None

        # M3 — negation/polarity guard. A near-duplicate embedding can still be
        # the opposite intent ("install X" vs "uninstall X"); reject the hit when
        # polarity differs. Tier-1 exact matches can't differ, so this is
        # semantic-only.
        if self._negation_guard and abs(
            _negation_score(normalised) - _negation_score(entry.normalised_query)
        ) >= 1:
            return None

        self._entries.move_to_end(best_sig)
        entry.hit_count += 1
        return VerdictCacheHit(entry, kind="semantic", similarity=best_sim)


# ============================================================================
# Singleton
# ============================================================================

_cache: Optional[VerdictCache] = None
_cache_lock = threading.Lock()


def get_verdict_cache() -> VerdictCache:
    """Process-wide VerdictCache. Constructed from routing_config on first call."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                cfg = get_routing_config().layer3.verdict_cache
                _cache = VerdictCache(
                    ttl_seconds=cfg.ttl_seconds,
                    max_entries=cfg.max_entries,
                    semantic_threshold=cfg.semantic_threshold,
                    semantic_model_name=cfg.semantic_model_name,
                    enable_semantic_tier=cfg.enable,
                    enable_negation_guard=cfg.enable_negation_guard,
                )
    return _cache


def reset_verdict_cache() -> None:
    """Test helper — drop the singleton."""
    global _cache
    with _cache_lock:
        _cache = None
