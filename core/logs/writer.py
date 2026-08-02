"""The write path (§3, §6): verbosity gating, unconditional traceback capture, sink fan-out.

Three things this module is responsible for, in order:

1. **Deciding whether a routine entry is written at all**, from the per-service verbosity
   tier (§8). This is a volume control and nothing more.
2. **Capturing the full traceback of any failure, unconditionally.** §3.3 states this as a
   hard requirement rather than a preference: verbosity tiers never gate whether a failure's
   traceback is recorded, and `str(e)` is never acceptable in place of one. It discards the
   line, the call stack, and the chained-exception context — which is often the only way to
   diagnose something that happened inside a `run_in_executor`-dispatched call three layers
   deep, exactly the case `guarded_call` below exists for and the case V2 got wrong.
3. **Fanning the entry out to every enabled sink** and pointing the index at where it landed.

This is the only module in the package that knows about the event loop. Writes are
non-blocking appends dispatched through `run_in_executor` (§6) — this API is pure async I/O
with no compute-bound work of its own, so there is nothing here that a free-threaded build
changes and nothing that assumes GIL-serialized access (`docs/PRINCIPLES.md` §5).

Logging must never be able to fail the thing being logged. Every failure inside this module
degrades to a counter and a `WriteReceipt` carrying an error code (§4.4).
"""

from __future__ import annotations

import asyncio
import traceback as _traceback
from pathlib import Path

from common.frozen_dict import FrozenDict

from .contracts import LEVEL_SEVERITY, LogEntry, LogLevel, Verbosity, WriteReceipt, utcnow
from .errors import SinkWriteError, code_for
from .index import LogIndex
from .metrics import LogsMetricsCollector
from .paths import default_log_root
from .sinks import SinkRegistry, default_registry


def format_traceback(exc: BaseException) -> str:
    """The full formatted traceback, chained context included — never `str(exc)` (§3.3)."""
    return "".join(
        _traceback.format_exception(type(exc), exc, exc.__traceback__)
    ).rstrip("\n")


class LogWriter:
    """Accepts entries, decides, writes, indexes. One instance per Logs process."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        verbosity: Verbosity | None = None,
        registry: SinkRegistry | None = None,
        index: LogIndex | None = None,
        metrics: LogsMetricsCollector | None = None,
    ) -> None:
        self._root = Path(root) if root else default_log_root()
        self._verbosity = verbosity or Verbosity()
        self._registry = registry or default_registry(self._root)
        self._index = index
        self._metrics = metrics or LogsMetricsCollector()

    # ------------------------------------------------------------------ accessors
    @property
    def root(self) -> Path:
        return self._root

    @property
    def registry(self) -> SinkRegistry:
        return self._registry

    @property
    def metrics(self) -> LogsMetricsCollector:
        return self._metrics

    @property
    def verbosity(self) -> Verbosity:
        return self._verbosity

    def close(self) -> None:
        self._registry.close()

    # ------------------------------------------------------------------ the decision
    def should_write(self, entry: LogEntry) -> bool:
        """Whether a *routine* entry clears its service's own verbosity tier.

        **An entry carrying a traceback always clears it, at every tier, without exception**
        — that is §3.3's hard requirement, expressed as a branch that runs before the tier is
        even consulted rather than as a caller-side convention that could be forgotten. The
        same applies to `ERROR` and `ATTENTION`: a failure and a "running below its own
        achievable baseline" finding are not routine logging and are not volume to control.
        """
        if entry.traceback is not None:
            return True
        if entry.level in (LogLevel.ERROR, LogLevel.ATTENTION):
            return True
        return entry.severity >= LEVEL_SEVERITY[self._verbosity.level_for(entry.service)]

    # ------------------------------------------------------------------ write path
    def write_sync(self, entry: LogEntry) -> WriteReceipt:
        """The blocking write. `write()` dispatches this through the executor (§6).

        Exposed on its own because a synchronous caller — a crash handler running as the
        process is going down, a bench harness — genuinely has no loop to await on, and the
        alternative is that caller re-implementing the fan-out.
        """
        if not self.should_write(entry):
            self._metrics.increment("entries_dropped_by_verbosity")
            return WriteReceipt(written=False)

        if entry.traceback is not None:
            self._metrics.increment("tracebacks_captured")

        receipt = WriteReceipt(written=False)
        failures: list[str] = []
        for sink in self._registry.enabled():
            try:
                emitted = sink.emit(entry)
            except Exception as exc:  # noqa: BLE001
                # Degrade this sink alone. The caller's run is never failed by logging.
                #
                # Deliberately every exception, not just `SinkWriteError`: sinks are a
                # Provider Registry (§1.2), so a sink is not necessarily one of this
                # package's own — a forwarder to a self-hosted collector raises whatever its
                # own HTTP library raises. Narrowing this to the internal type would mean
                # any such provider could take down the run it was only supposed to be
                # logging, which is the one thing this API must never do (§4.4).
                self._metrics.increment("sink_failures")
                failures.append(f"{sink.name}: {type(exc).__name__}: {exc}")
                continue
            if emitted.path and not receipt.path:
                receipt = emitted  # the addressable one, which the index points at
            elif emitted.written and not receipt.written:
                receipt = emitted

        if not receipt.written:
            return WriteReceipt(
                written=False,
                error_code=code_for(SinkWriteError()) if failures else "NO_SINK_ENABLED",
                error_detail="; ".join(failures),
            )

        self._metrics.increment("entries_written")
        if self._index is not None and receipt.path and self._index.record(entry, receipt):
            self._metrics.increment("index_records")
        return receipt

    async def write(self, entry: LogEntry) -> WriteReceipt:
        """Non-blocking append (§6). Never raises."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.write_sync, entry)

    async def log(
        self,
        service: str,
        level: LogLevel,
        message: str,
        *,
        run_id: str | None = None,
        user_id: str | None = None,
        context: dict | None = None,
        traceback_text: str | None = None,
    ) -> WriteReceipt:
        return await self.write(
            self.build(
                service, level, message, run_id=run_id, user_id=user_id,
                context=context, traceback_text=traceback_text,
            )
        )

    @staticmethod
    def build(
        service: str,
        level: LogLevel,
        message: str,
        *,
        run_id: str | None = None,
        user_id: str | None = None,
        context: dict | None = None,
        traceback_text: str | None = None,
    ) -> LogEntry:
        return LogEntry(
            timestamp=utcnow(),
            run_id=run_id,
            user_id=user_id,
            service=service,
            level=level,
            message=message,
            traceback=traceback_text,
            context=FrozenDict(context or {}),
        )

    async def log_exception(
        self,
        service: str,
        message: str,
        exc: BaseException,
        *,
        run_id: str | None = None,
        user_id: str | None = None,
        context: dict | None = None,
        level: LogLevel = LogLevel.ERROR,
    ) -> WriteReceipt:
        """Record a failure with its full traceback. The only correct way to log one here."""
        return await self.log(
            service, level, message, run_id=run_id, user_id=user_id,
            context=context, traceback_text=format_traceback(exc),
        )

    async def guarded_call(
        self,
        service: str,
        func,
        *args,
        run_id: str | None = None,
        user_id: str | None = None,
        message: str | None = None,
        reraise: bool = True,
        **kwargs,
    ):
        """Run a blocking callable in the executor, logging a full traceback if it raises.

        This exists because §3.3's own worst case is stated concretely: a failure inside a
        `run_in_executor`-dispatched call, several layers deep, where the traceback is the
        only thing that makes it diagnosable. Capturing it inside the `except` — while the
        exception's `__traceback__` still reaches back through the executor frames — is what
        makes that true; a caller that catches it further out and logs `str(e)` is exactly the
        V2 bug this corrects.

        The exception is re-raised by default. Logs API records what happened; deciding
        whether a failure is survivable belongs to the caller, never to the logger.
        """
        loop = asyncio.get_running_loop()

        def _invoke():
            return func(*args, **kwargs)

        try:
            return await loop.run_in_executor(None, _invoke)
        except Exception as exc:  # noqa: BLE001 - deliberately broad; re-raised below
            await self.log_exception(
                service,
                message or f"{getattr(func, '__name__', 'call')} raised {type(exc).__name__}",
                exc,
                run_id=run_id,
                user_id=user_id,
            )
            if reraise:
                raise
            return None


__all__ = ["LogWriter", "format_traceback"]
