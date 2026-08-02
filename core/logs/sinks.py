"""Where an accepted `LogEntry` actually goes — a Provider Registry, not a config switch.

**Not in the deep-dive's §2 package layout.** The deep-dive names exactly one destination
(rotated JSONL files, §3.1) and that remains the canonical one, but "where trace goes" is a
pluggable capability by `docs/PRINCIPLES.md` §1.2's own definition, and §1.3 wants the actual
file I/O behind one small adapter rather than open-coded across the write path. Both are
satisfied by one registry with `JsonlFileSink` in it.

**More than one sink can be enabled at once, and all of them receive every accepted entry.**
That is not decoration: an attached client tailing a run wants entries as they happen without
re-reading the file it just wrote, and a self-hosted install forwarding operational trace to
its own collector should not have to give up the local JSONL to do it. A failing sink is
degraded on its own, never allowed to take down the others or the caller's run (§4.4) — the
one thing this API must never do is make logging able to fail the thing being logged.

Sinks are synchronous by design. `writer.py` owns the async boundary and dispatches every
emit through `run_in_executor`, so a sink implementation is a plain blocking function and
there is exactly one place in this package that knows about the event loop.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from .contracts import LogEntry, WriteReceipt
from .errors import SinkWriteError
from .jsonl import encode
from .paths import describe, file_for_entry


@runtime_checkable
class LogSink(Protocol):
    """One destination for accepted entries."""

    @property
    def name(self) -> str:
        """Stable identifier, used as the registry key and in metrics."""

    def emit(self, entry: LogEntry) -> WriteReceipt:
        """Write one entry. Returns where it landed; raises `SinkWriteError` on failure."""

    def close(self) -> None:
        """Release any held handles. Idempotent."""


class JsonlFileSink:
    """The canonical destination: one append-only JSONL file per service per day (§3.1).

    Pure append — no in-place rewrite, ever — which is what makes rotation a new file at the
    day boundary with no truncation logic, and what makes the byte offset this returns stable
    for the index to point at (§3.2).

    Handles are cached per path and flushed on every entry. Flushing per entry is deliberate:
    the entries most worth having are the ones written immediately before a process died, and
    a buffered handle is exactly how those get lost.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._handles: dict[Path, object] = {}  # genuinely mutable cache, not a constant
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "jsonl_file"

    @property
    def root(self) -> Path:
        return self._root

    def emit(self, entry: LogEntry) -> WriteReceipt:
        path = file_for_entry(self._root, entry.service, entry.timestamp, entry.level)
        blob = encode(entry)
        try:
            with self._lock:
                handle = self._handle_for(path)
                offset = handle.tell()
                handle.write(blob)
                handle.flush()
        except OSError as exc:
            raise SinkWriteError(f"{path}: {exc}") from exc
        return WriteReceipt(written=True, path=str(path), offset=offset, length=len(blob))

    def _handle_for(self, path: Path):
        handle = self._handles.get(path)
        if handle is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "ab")
            # Rotation is just a new path: drop this service's handles for *earlier days*
            # rather than holding one open per day forever in a long-running process.
            #
            # Evicting on day, not on directory. A service's own day file and its sibling
            # `.trace` file live in the same directory, and OCR and Inference default to
            # `trace` while still emitting INFO and ERROR — so evicting every handle in the
            # directory made the two tracks close and reopen each other on literally every
            # entry, on this API's two highest-volume services.
            described = describe(path)
            day = described[1] if described else None
            for old, old_handle in list(self._handles.items()):
                if old.parent != path.parent:
                    continue
                old_described = describe(old)
                if day is not None and old_described is not None and old_described[1] >= day:
                    continue  # same day, other track — both stay open
                old_handle.close()
                del self._handles[old]
            self._handles[path] = handle
        return handle

    def close(self) -> None:
        with self._lock:
            for handle in self._handles.values():
                try:
                    handle.close()
                except OSError:  # pragma: no cover - closing twice is not worth failing on
                    pass
            self._handles.clear()


class MemorySink:
    """An in-process ring of recent entries.

    Real, not a test double: a client attaching mid-run wants the last N entries immediately
    rather than the file re-read from disk, and the registry running it *alongside*
    `JsonlFileSink` — not instead of it — is the concrete case §1.2 means by more than one
    provider running at once. Bounded on purpose; it is a buffer, never a store.
    """

    def __init__(self, capacity: int = 500) -> None:
        self._capacity = capacity
        self._entries: list[LogEntry] = []
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "memory"

    def emit(self, entry: LogEntry) -> WriteReceipt:
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._capacity:
                del self._entries[: len(self._entries) - self._capacity]
        return WriteReceipt(written=True)

    def recent(self, limit: int | None = None) -> tuple[LogEntry, ...]:
        with self._lock:
            entries = tuple(self._entries)
        return entries[-limit:] if limit else entries

    def close(self) -> None:
        with self._lock:
            self._entries.clear()


class SinkRegistry:
    """The registry itself. A genuinely mutable internal registry, populated at startup —
    a plain `dict`, not a `FrozenDict`, and the distinction is intentional and visible in the
    type (`docs/PRINCIPLES.md` §2.1.1: that rule reaches module-level *constants*, not this).
    """

    def __init__(self) -> None:
        self._sinks: dict[str, LogSink] = {}
        self._enabled: set[str] = set()

    def register(self, sink: LogSink, *, enabled: bool = True) -> None:
        self._sinks[sink.name] = sink
        if enabled:
            self._enabled.add(sink.name)
        else:
            self._enabled.discard(sink.name)

    def enable(self, name: str) -> bool:
        if name not in self._sinks:
            return False
        self._enabled.add(name)
        return True

    def disable(self, name: str) -> None:
        self._enabled.discard(name)

    def get(self, name: str) -> LogSink | None:
        return self._sinks.get(name)

    def enabled(self) -> tuple[LogSink, ...]:
        return tuple(self._sinks[n] for n in sorted(self._enabled))

    def close(self) -> None:
        for sink in self._sinks.values():
            sink.close()


def default_registry(root: Path, *, memory_capacity: int = 500) -> SinkRegistry:
    """The startup default: the canonical JSONL sink plus the live-tail buffer, both on."""
    registry = SinkRegistry()
    registry.register(JsonlFileSink(root))
    registry.register(MemorySink(memory_capacity))
    return registry


__all__ = [
    "JsonlFileSink",
    "LogSink",
    "MemorySink",
    "SinkRegistry",
    "default_registry",
]
