""""Webhook Circadian" — inferred third-party delivery health from timing alone (deep-dive
§4). There is no ping/status endpoint for these providers, so health is *inferred* from
delivery *rhythm*: proactive renewal well ahead of the known expiry (`subscription.py`) is
the primary defense; the fallback poll this module gates is a much-less-frequent safety
net whose only job is catching the rare case a healthy webhook should have already
reported.

**Deliberately distinct from Watchdog** (`core/execution_core/` or wherever Watchdog
lives): Watchdog proves *this program's own* process is alive via kicks it controls;
Circadian infers a *third party's* delivery health from timing it does not control —
genuinely different kinds of liveness signal, kept as two separate mechanisms on purpose.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

__all__ = ["CircadianMonitor"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CircadianMonitor:
    """Tracks the last-known delivery time per channel. A plain mutable dict guarded by a
    lock, not a `FrozenDict` — genuinely mutable runtime state
    (`docs/PRINCIPLES.md` §2.1.1's own carve-out)."""

    def __init__(self, fallback_poll_interval: timedelta = timedelta(days=1)) -> None:
        self._fallback_poll_interval = fallback_poll_interval
        self._lock = threading.Lock()
        self._last_delivery_at: dict[str, datetime] = {}

    def record_delivery(self, channel_id: str, at: datetime | None = None) -> None:
        """Called every time a real callback arrives for this channel — the only signal
        this module has that the channel is actually alive."""
        with self._lock:
            self._last_delivery_at[channel_id] = at or _utcnow()

    def needs_fallback_poll(self, channel_id: str, now: datetime | None = None) -> bool:
        """`True` when this channel has gone longer than `fallback_poll_interval` without
        a recorded delivery — including a channel that has *never* delivered at all
        (registered but silently dead from the start), which is exactly the rare failure
        mode this safety net exists to catch (deep-dive §4)."""
        now = now or _utcnow()
        with self._lock:
            last = self._last_delivery_at.get(channel_id)
        if last is None:
            return True
        return (now - last) >= self._fallback_poll_interval
