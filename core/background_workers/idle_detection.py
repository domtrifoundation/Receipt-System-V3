"""Is the relevant scope quiet right now? (`v3-deepdive-12-background-workers-api.md` §4)

An idle-time job runs only when the system is genuinely otherwise quiet — concretely, when
Execution Core reports no `OPEN` or `CLOSING` runs in progress for whichever scope the job
cares about. This matches V2's own already-validated behaviour of idle jobs yielding to active
foreground scans, which §4 keeps deliberately rather than rederiving.

**Background Workers does not track run state itself.** §4 says so directly: it asks the API
that owns it. That is why `RunStateReader` is an adapter rather than a table read here — the
alternative is a second, quietly diverging opinion about what counts as an active run
(`docs/PRINCIPLES.md` §1.3, §1.5).

**Per-user versus system-wide is a real distinction, not a knob** (§10). A job touching
per-user resources — archive sync, that user's session cleanup — checks *that user's* own idle
state, because one user's active session has no business blocking another user's unrelated
maintenance. A genuinely system-wide job (log retention, Dependencies Warden polling) checks
nobody's idle state at all, since it touches no per-user resource in the first place. The
distinction tracks whether the job's own target is per-user or system-wide; it is not a
separate axis someone configures.

**Unavailable means not idle.** Execution Core does not exist in this build, so the default
reader reports exactly that, and every idle-only job is held back. This is the one genuinely
conservative default in this package (`docs/PRINCIPLES.md` §4.2 over §4.4): an idle-only job
exists specifically to yield to foreground work, so running one while unable to confirm the
system is quiet defeats the class entirely. Skipping a sweep costs one interval; running a
`CPU_PROCESS` sweep during a live batch costs the user's actual work.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import GLOBAL_SCOPE, IdleWindow, utcnow
from .metrics import BackgroundWorkersMetricsCollector


@runtime_checkable
class RunStateReader(Protocol):
    """The one adapter between this module and Execution Core's own run states.

    When Execution Core lands, wiring it in means passing a real reader here — not editing
    this module (`docs/PRINCIPLES.md` §1.3).
    """

    def active_run_count(self, scope: str) -> int:
        """How many `OPEN`/`CLOSING` runs exist for `scope` right now.

        `scope` is `GLOBAL_SCOPE` for a system-wide question, or a real user id. Raises if it
        cannot answer — `is_idle` below converts that to "not idle", never to "idle".
        """


class ExecutionCoreUnavailable:
    """The default reader: Execution Core does not exist in this build.

    Deliberately not an optimistic stub. A placeholder reporting zero active runs would make
    every idle-only job run immediately and unconditionally, which is precisely the behaviour
    §4 exists to prevent — and it would do so silently, on a system where nothing yet exists
    to notice the contention.
    """

    def active_run_count(self, scope: str) -> int:
        raise RuntimeError("Execution Core is not available in this build")


class StaticRunState:
    """A reader over a fixed scope→count map.

    Real rather than a test double: an operator pinning a maintenance window ("treat the system
    as busy until further notice") is a genuine deployment shape, and it is also what lets the
    idle-scope tests exercise the same code path production does.
    """

    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self._counts = dict(counts or {})

    def active_run_count(self, scope: str) -> int:
        return self._counts.get(scope, 0)


class IdleDetector:
    """Answers §4's `is_idle` for a scope, through whichever reader is wired in."""

    def __init__(
        self,
        reader: RunStateReader | None = None,
        *,
        metrics: BackgroundWorkersMetricsCollector | None = None,
    ) -> None:
        self._reader: RunStateReader = reader or ExecutionCoreUnavailable()
        self._metrics = metrics or BackgroundWorkersMetricsCollector()

    def is_idle(self, scope: str = GLOBAL_SCOPE) -> IdleWindow:
        """Whether `scope` is quiet enough to dispatch an idle-only job.

        Returns an `IdleWindow` rather than a bare bool so a scheduler skipping a job can say
        *why* in one line — "3 active run(s)" rather than a False an operator has to read
        source to interpret.
        """
        try:
            active = self._reader.active_run_count(scope)
        except Exception as exc:  # noqa: BLE001 - unavailable is not idle, see module docstring
            self._metrics.increment("idle_checks_unavailable")
            return IdleWindow(
                scope=scope,
                idle=False,
                checked_at=utcnow(),
                reason=f"could not determine run state, treating as busy: {exc}",
            )

        if active > 0:
            return IdleWindow(
                scope=scope,
                idle=False,
                checked_at=utcnow(),
                reason=f"{active} active run(s) in scope {scope!r}",
            )
        return IdleWindow(
            scope=scope, idle=True, checked_at=utcnow(), reason=f"no active runs in scope {scope!r}"
        )


__all__ = [
    "ExecutionCoreUnavailable",
    "IdleDetector",
    "RunStateReader",
    "StaticRunState",
]
