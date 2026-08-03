"""Micro-batch window (deep-dive §6.3) — drains whatever's immediately queued, then waits
up to a small configurable window for more requests destined for the same preset before
the worker dispatches on the batch it collected.

Plain, dependency-free logic against any object exposing a blocking `.get(timeout=...)`
and a non-blocking `.get_nowait()` — both `multiprocessing.Queue` and stdlib `queue.Queue`
satisfy this, which is what makes this module directly unit-testable without spawning a
real child process (`generation.py`'s own worker loop is where this actually runs against
a real `multiprocessing.Queue`).
"""

from __future__ import annotations

import queue as queue_module
import time

__all__ = ["drain_batch"]


def drain_batch(source_queue, *, window_ms: int, max_batch_size: int, first_item_timeout: float | None = None):
    """Blocks for the first item (respecting `first_item_timeout`, `None` meaning wait
    forever — the worker's normal idle state), then drains additional items non-blockingly
    for up to `window_ms`, stopping early if `max_batch_size` is reached. Returns an empty
    list only when `first_item_timeout` was given and nothing arrived in time — the normal
    "poll for worker liveness" case (`generation.py`'s own `_worker_main` loop uses this to
    periodically check whether it's been asked to shut down)."""
    try:
        first = source_queue.get(timeout=first_item_timeout) if first_item_timeout is not None else source_queue.get()
    except queue_module.Empty:
        return []

    batch = [first]
    deadline = time.monotonic() + (window_ms / 1000)
    while len(batch) < max_batch_size and time.monotonic() < deadline:
        try:
            batch.append(source_queue.get_nowait())
        except queue_module.Empty:
            time.sleep(0.001)
    return batch
