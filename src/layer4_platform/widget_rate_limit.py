"""
In-process abuse guard for the public widget chat endpoint.

``bot_id`` is public (it sits in the page source) and ``Origin``/``Referer`` are
trivially spoofable by non-browser clients, so origin enforcement alone leaves
the chat endpoint open to anyone willing to script it — a budget-drain and a
knowledge-base-scraping hazard. This sliding-window limiter caps:

* per visitor IP, per bot, per minute   (stops a single client hammering)
* per bot, per minute (all visitors)    (stops a distributed burst on one bot)
* per bot, per UTC day                  (a hard daily ceiling on spend)

It is intentionally dependency-light (no Redis): a process-local limiter is
enough for the single-process demo/dev runtime. The multi-process upgrade is a
shared store (Redis), noted here so it isn't mistaken for production-complete.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

_MINUTE = 60.0
_DAY = 86_400.0


class WidgetRateLimiter:
    """Sliding-window-log limiter keyed by IP and bot."""

    def __init__(
        self,
        *,
        per_ip_per_min: int,
        per_bot_per_min: int,
        bot_daily_cap: int,
    ) -> None:
        self.per_ip_per_min = per_ip_per_min
        self.per_bot_per_min = per_bot_per_min
        self.bot_daily_cap = bot_daily_cap
        self._ip_log: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._bot_min_log: dict[str, deque[float]] = defaultdict(deque)
        self._bot_day_log: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @staticmethod
    def _trim(log: deque[float], now: float, window: float) -> None:
        cutoff = now - window
        while log and log[0] <= cutoff:
            log.popleft()

    def check_and_record(
        self,
        *,
        ip: str,
        bot_id: str,
        now: Optional[float] = None,
    ) -> Optional[str]:
        """Return ``None`` if the request is allowed (and record it), or a short
        reason string if it is rate-limited (recording nothing, so a rejected
        request never consumes more quota)."""
        ts = time.time() if now is None else now
        ip_key = (ip or "unknown", bot_id)

        with self._lock:
            ip_log = self._ip_log[ip_key]
            bot_min_log = self._bot_min_log[bot_id]
            bot_day_log = self._bot_day_log[bot_id]

            self._trim(ip_log, ts, _MINUTE)
            self._trim(bot_min_log, ts, _MINUTE)
            self._trim(bot_day_log, ts, _DAY)

            if len(ip_log) >= self.per_ip_per_min:
                return "per_ip_per_min"
            if len(bot_min_log) >= self.per_bot_per_min:
                return "per_bot_per_min"
            if len(bot_day_log) >= self.bot_daily_cap:
                return "per_bot_daily"

            ip_log.append(ts)
            bot_min_log.append(ts)
            bot_day_log.append(ts)
            return None
