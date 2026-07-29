"""Which jobs are registered, by which domain API (§2, §6, §9, §10).

Two responsibilities, deliberately in one file because they are the same fact seen twice:

1. **The live registry** — what is registered in *this process* right now, which domain APIs
   populate at startup. A genuinely mutable internal structure, so a plain `dict` behind a
   lock rather than a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent).
2. **`KNOWN_JOBS`** — the consolidated inventory §6.1 maintains as a table in the deep-dive,
   mirrored here as data.

**Why §6.1's table is mirrored in code at all**, since duplicating a document into a constant
is normally the wrong instinct: §6.5 makes the table a standing obligation — every new job is
added to it in the same PR that designs it — and then §9 asks for a *registry-completeness
test* proving code and table agree. A table that exists only in Markdown cannot be checked by
anything. Mirroring it here is what turns "someone should remember to update the table" into a
test failure. `tests/unit/core/background_workers/test_registry_completeness.py` parses the
deep-dive's actual table and asserts it matches this constant, so the two cannot drift in
either direction — a job added to the doc but not here fails, and so does the reverse.

**Nothing registers a real job in this build yet**, and `default_registry()` therefore returns
an empty registry — the same posture `core/task_scheduler/registry.py` and
`core/health/resource_ledger.py` take toward their own not-yet-existing dependencies. Every
job in `KNOWN_JOBS` is owned by an API that either does not exist yet or has not been wired to
register it; the inventory is what those APIs will register *against*, not a claim that they
already have.
"""

from __future__ import annotations

import threading

from common.frozen_dict import FrozenDict

from .contracts import JobClass, JobHealth, JobOutcome, JobRegistration
from .errors import DuplicateJobRegistration, InvalidJobRegistration, UnknownJob

#: §6.1's consolidated table, as data: job id -> owning API. The ids are the deep-dive's own
#: job names in snake_case; the owners are its own "Owner" column verbatim.
#:
#: §6.2's still-open jobs are deliberately absent. They are open precisely because something
#: they depend on is unresolved (Reconciliation's rescue-ordering question, Notifications'
#: retry policy — the latter now resolved and implemented in wave 2 but not yet registered
#: here by that API), and listing a job that cannot be dispatched would make this inventory
#: describe intentions rather than the actual background workload, which is the one thing
#: §6.5 says it exists to answer.
KNOWN_JOBS: FrozenDict = FrozenDict(
    {
        # §6.1 — jobs with a fully resolved design today
        "webhook_circadian_renewal": "ingestion",
        "release_directory_gc": "update",
        "dependencies_warden_polling": "telemetrees",
        "archive_sync_execution": "persistence",
        "reconciliation_check_inventory": "reconciliation",
        "log_retention_purge": "logs",
        "capability_drift_periodic_check": "health",
        "bulk_migration_dispatch": "migration",
        "stage_checkpoint_purge": "execution_core",
        "standalone_integrity_spot_check": "disaster_recovery",
        "wikidata_vendor_directory_poll": "architect",
        # §6.4 — five jobs designed for the first time in that section
        "curate_learned_vendors": "architect",
        "expired_session_cleanup": "auth",
        "break_glass_grant_sweep": "auth",
        "account_deletion_grace_sweep": "account_guardian",
        "blob_backup_spot_verification": "persistence",
        # §10 — the near-duplicate detection job resolved there and registered into §6.1
        "near_duplicate_receipt_detection": "review_flagging",
    }
)


class JobRegistry:
    """The live registry: what this process will actually dispatch.

    Holds `JobHealth` alongside each registration because §10's failure guard needs somewhere
    durable to count consecutive failures, and a counter that lived in the scheduler would
    reset every time the scheduler was reconstructed — which would make a permanently-failing
    job permanently retryable again, defeating the guard.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRegistration] = {}
        self._handlers: dict[str, object] = {}
        self._health: dict[str, JobHealth] = {}

    # ------------------------------------------------------------------ registration

    def register(self, registration: JobRegistration, handler: object) -> None:
        """Register one domain API's job.

        Raises on a duplicate rather than replacing: two APIs both believing they own a job id
        is a real bug, and last-one-wins would make which job actually runs depend on import
        order — an especially bad property for work nobody is watching.
        """
        if not registration.job_id or not registration.owning_api:
            raise InvalidJobRegistration("job_id and owning_api must both be non-empty")
        if registration.interval_seconds is not None and registration.interval_seconds <= 0:
            raise InvalidJobRegistration(
                f"{registration.job_id!r} declared a non-positive interval; "
                "an interval is in seconds and must be positive"
            )
        with self._lock:
            if registration.job_id in self._jobs:
                raise DuplicateJobRegistration(registration.job_id)
            self._jobs[registration.job_id] = registration
            self._handlers[registration.job_id] = handler
            self._health[registration.job_id] = JobHealth(job_id=registration.job_id)

    def get(self, job_id: str) -> JobRegistration | None:
        with self._lock:
            return self._jobs.get(job_id)

    def require(self, job_id: str) -> JobRegistration:
        registration = self.get(job_id)
        if registration is None:
            raise UnknownJob(job_id)
        return registration

    def handler_for(self, job_id: str) -> object:
        with self._lock:
            if job_id not in self._handlers:
                raise UnknownJob(job_id)
            return self._handlers[job_id]

    def all_jobs(self) -> tuple[JobRegistration, ...]:
        with self._lock:
            return tuple(sorted(self._jobs.values(), key=lambda j: j.job_id))

    def jobs_for_class(self, job_class: JobClass) -> tuple[JobRegistration, ...]:
        return tuple(j for j in self.all_jobs() if j.job_class is job_class)

    # ------------------------------------------------------------------------ health

    def health(self, job_id: str) -> JobHealth:
        with self._lock:
            existing = self._health.get(job_id)
        if existing is None:
            raise UnknownJob(job_id)
        return existing

    def all_health(self) -> tuple[JobHealth, ...]:
        with self._lock:
            return tuple(sorted(self._health.values(), key=lambda h: h.job_id))

    def record_health(self, health: JobHealth) -> None:
        """Replace a job's health record. Called by the scheduler after every dispatch."""
        with self._lock:
            if health.job_id not in self._jobs:
                raise UnknownJob(health.job_id)
            self._health[health.job_id] = health

    def enable(self, job_id: str, *, cleared_by: str) -> JobHealth:
        """Re-enable an auto-disabled job — an explicit staff action, never automatic (§10).

        The consecutive-failure counter is reset here and only here. If the scheduler reset it
        on its own after some cooldown, the guard would degrade into a slower retry loop, which
        is the failure mode §10 rejects rather than a milder version of it.
        """
        with self._lock:
            existing = self._health.get(job_id)
            if existing is None:
                raise UnknownJob(job_id)
            cleared = JobHealth(
                job_id=existing.job_id,
                consecutive_failures=0,
                total_runs=existing.total_runs,
                total_failures=existing.total_failures,
                last_run_at=existing.last_run_at,
                last_outcome=existing.last_outcome,
                last_error_detail=existing.last_error_detail,
                disabled_at=None,
                disabled_reason=f"re-enabled by {cleared_by}",
            )
            self._health[job_id] = cleared
        return cleared

    def disabled_jobs(self) -> tuple[str, ...]:
        return tuple(h.job_id for h in self.all_health() if h.disabled)


def default_registry() -> JobRegistry:
    """The startup default — empty. See this module's docstring for why that is deliberate."""
    return JobRegistry()


def unregistered_known_jobs(registry: JobRegistry) -> tuple[str, ...]:
    """Which of §6.1's inventoried jobs no API has actually registered in this process.

    Not an error and not a warning: on a partially-built system it is simply the truth, and it
    is the honest answer to §6.5's own question — "what does this program do while nobody's
    watching". Exposed as a function so an operator-facing status view can show it rather than
    a reader having to diff two lists by hand.
    """
    registered = {job.job_id for job in registry.all_jobs()}
    return tuple(sorted(set(KNOWN_JOBS) - registered))


def unknown_registered_jobs(registry: JobRegistry) -> tuple[str, ...]:
    """Which registered jobs are absent from §6.1's inventory.

    This one *is* a problem, and it is what §9's registry-completeness hook is really guarding:
    a job running in production that the consolidated table never mentions is exactly the
    "designed at its own document, invisible as part of the whole system's workload" failure
    §6.5 describes.
    """
    registered = {job.job_id for job in registry.all_jobs()}
    return tuple(sorted(registered - set(KNOWN_JOBS)))


__all__ = [
    "KNOWN_JOBS",
    "JobRegistry",
    "default_registry",
    "unknown_registered_jobs",
    "unregistered_known_jobs",
]
