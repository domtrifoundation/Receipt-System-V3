"""`batching.py`'s micro-batch window (deep-dive §6.3) — real `queue.Queue`, real
`time.sleep`, no mocking of time itself."""

from __future__ import annotations

import queue
import threading
import time

from core.inference.batching import drain_batch


def test_drain_batch_returns_immediately_available_items_without_waiting_full_window():
    q = queue.Queue()
    q.put("a")
    q.put("b")
    start = time.monotonic()
    batch = drain_batch(q, window_ms=200, max_batch_size=16)
    elapsed = time.monotonic() - start
    assert batch == ["a", "b"]
    assert elapsed < 0.2 + 0.05  # small tolerance for scheduler jitter; well under the window


def test_drain_batch_collects_items_that_arrive_during_the_window():
    q = queue.Queue()
    q.put("first")

    def _late_arrival():
        time.sleep(0.03)
        q.put("second")

    threading.Thread(target=_late_arrival).start()
    batch = drain_batch(q, window_ms=150, max_batch_size=16)
    assert batch == ["first", "second"]


def test_drain_batch_respects_max_batch_size():
    q = queue.Queue()
    for i in range(10):
        q.put(i)
    batch = drain_batch(q, window_ms=100, max_batch_size=3)
    assert batch == [0, 1, 2]


def test_drain_batch_with_first_item_timeout_returns_empty_when_nothing_arrives():
    q = queue.Queue()
    batch = drain_batch(q, window_ms=50, max_batch_size=16, first_item_timeout=0.05)
    assert batch == []
