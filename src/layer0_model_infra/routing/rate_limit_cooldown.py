"""
📁 File: src/layer0_model_infra/routing/rate_limit_cooldown.py
Layer: Layer 0 — Layer 3 redesign
Purpose: Short-lived per-model rate-limit cooldown so the router stops selecting
         a model that just returned 429s until its window likely resets.
Depends on: (stdlib only)
Used by: knn_router (read: is_cooling_down during cost-min),
         the execution/gateway path (write: mark on a 429 — wired in Batch 3.6)

The cost-minimizer happily keeps picking the cheapest qualifying model. For the
free tiers that's exactly the one with the tightest quotas (OpenRouter free =
200 requests/day, Groq free = 30 rpm), so under load it would route every
request to a model that's already rate-limited and let the gateway eat the 429.

This store lets the gateway report a 429 (``mark(model_id)``) and the router
avoid that model for a short cooldown. It's intentionally tiny and in-memory:
rate-limit state is inherently transient and per-process; nothing here needs to
survive a restart. Thread-safe (RLock). Lazily expires entries on read so it
never grows unbounded.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from src.shared.logger import get_logger

logger = get_logger(__name__)


class RateLimitCooldown:
    """Per-model_id cooldown clock keyed on time.monotonic()."""

    def __init__(self, default_cooldown_seconds: float = 60.0) -> None:
        self._lock = threading.RLock()
        self._until: dict[str, float] = {}
        self._default = float(default_cooldown_seconds)

    def mark(self, model_id: str, cooldown_seconds: Optional[float] = None) -> None:
        """Put a model on cooldown for ``cooldown_seconds`` (config default if
        None). Called by the execution path when the provider returns a 429."""
        secs = self._default if cooldown_seconds is None else float(cooldown_seconds)
        with self._lock:
            self._until[model_id] = time.monotonic() + secs
        logger.info("layer3_rate_limit_cooldown_marked", model_id=model_id, seconds=secs)

    def is_cooling_down(self, model_id: str) -> bool:
        with self._lock:
            expiry = self._until.get(model_id)
            if expiry is None:
                return False
            if time.monotonic() >= expiry:
                del self._until[model_id]
                return False
            return True

    def active(self) -> set[str]:
        """Currently-cooling model_ids (expired entries are reaped)."""
        with self._lock:
            now = time.monotonic()
            for mid in [m for m, e in self._until.items() if e <= now]:
                del self._until[mid]
            return set(self._until.keys())

    def clear(self) -> None:
        with self._lock:
            self._until.clear()


# ============================================================================
# Singleton
# ============================================================================

_cooldown: Optional[RateLimitCooldown] = None
_cooldown_lock = threading.Lock()


def get_rate_limit_cooldown() -> RateLimitCooldown:
    """Process-wide cooldown using rate_limit_blacklist_seconds from config."""
    global _cooldown
    if _cooldown is None:
        with _cooldown_lock:
            if _cooldown is None:
                from src.layer0_model_infra.config.routing_config import get_routing_config
                secs = get_routing_config().layer3.rate_limit_blacklist_seconds
                _cooldown = RateLimitCooldown(default_cooldown_seconds=secs)
    return _cooldown


def reset_rate_limit_cooldown() -> None:
    """Test helper — drop the singleton."""
    global _cooldown
    with _cooldown_lock:
        _cooldown = None
