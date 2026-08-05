"""Code and §6.1's table say the same thing (§6.5, §9).

§9's third named testing hook:

> **Registry-completeness test**: confirms every job registered in code appears in §6.1's own
> table and vice versa — the concrete enforcement of §6.5's extensibility clause, which is
> otherwise honor-system.

"Otherwise honor-system" is the operative phrase, and §6.5 explains why it matters more here
than it looks: a job designed at its own owning document but never added to the consolidated
table "isn't actually discoverable as part of the system's background workload, which defeats
the point of this table existing at all". §6.1's own text records that this already happened —
three jobs were fully designed in their own documents and simply never made it into the table.

So these tests parse the **actual deep-dive Markdown** rather than asserting against a copy.
That is deliberate: a test comparing one hardcoded list against another hardcoded list would
pass forever while the document drifted away from both, which is precisely the failure being
guarded. Parsing the real table means a job added to the doc but not to `KNOWN_JOBS` fails
here, and so does the reverse.

The mapping between a table row's prose name and a `KNOWN_JOBS` id cannot be derived
mechanically — "Webhook Circadian renewal" is not an algorithmic transform of
`webhook_circadian_renewal`, and "Reconciliation's real check inventory" is not one of
`reconciliation_check_inventory` at all. `ROW_TO_JOB_ID` below is that mapping, written once.
It is the one hand-maintained piece, and it is small, explicit, and itself checked: an
unmapped row fails.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from core.background_workers.registry import (
    KNOWN_JOBS,
    JobRegistry,
    default_registry,
    unknown_registered_jobs,
    unregistered_known_jobs,
)

from .conftest import RecordingHandler, registration

DEEP_DIVE = (
    pathlib.Path(__file__).resolve().parents[4]
    / "docs"
    / "apis"
    / "v3-deepdive-12-background-workers-api.md"
)

#: §6.1's and §6.4's table rows, mapped to the job ids `KNOWN_JOBS` uses. Bold markers are
#: stripped before lookup, since §6.1 bolds the rows added during its own later correction.
ROW_TO_JOB_ID: dict[str, str] = {
    "Webhook Circadian renewal": "webhook_circadian_renewal",
    "Release directory garbage collection": "release_directory_gc",
    "Dependencies Warden polling": "dependencies_warden_polling",
    "Archive Sync execution": "archive_sync_execution",
    "Reconciliation's real check inventory": "reconciliation_check_inventory",
    "Log retention purge": "log_retention_purge",
    "Capability drift periodic check": "capability_drift_periodic_check",
    "Bulk migration dispatch": "bulk_migration_dispatch",
    "Stage-checkpoint purge": "stage_checkpoint_purge",
    "Standalone integrity spot-check": "standalone_integrity_spot_check",
    "Wikidata vendor directory poll": "wikidata_vendor_directory_poll",
    "Curate (self-cleaning learned-vendor pass)": "curate_learned_vendors",
    "Expired session cleanup": "expired_session_cleanup",
    "Break-glass grant cleanliness sweep": "break_glass_grant_sweep",
    "Account deletion grace-period sweep": "account_deletion_grace_sweep",
    "Blob backup spot-verification": "blob_backup_spot_verification",
}


def documented_job_rows() -> list[str]:
    """Every job name in the deep-dive's own §6.1 and §6.4 tables.

    Both tables share the shape `| <job> | <owner> | <trigger> | ...`, and both are job
    inventories — §6.4's five are explicitly described there as jobs that "genuinely didn't
    exist anywhere" and were designed into the same registry. A parser that read only §6.1
    would silently miss them.
    """
    text = DEEP_DIVE.read_text(encoding="utf-8")
    rows: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[0].strip("*").strip()
        if not name or name in {"Job", "---"} or set(name) <= {"-", " "}:
            continue
        if cells[1].strip() in {"Owner", "---"}:
            continue
        rows.append(name)
    return rows


def test_the_deep_dive_table_is_actually_parseable():
    """A guard on the guard.

    If the document were reformatted so this parser matched nothing, every assertion below
    would pass vacuously — the completeness check would stop checking anything while still
    reporting green, which is the same class of silent failure it exists to catch.
    """
    rows = documented_job_rows()

    assert len(rows) >= 15
    assert "Log retention purge" in rows


def test_every_documented_job_is_mapped_to_a_job_id():
    """An unmapped row means a job was added to the doc and nowhere else.

    This is the direction §6.1 records having actually gone wrong — three jobs designed in
    their own documents, added to no table, invisible as part of the workload.
    """
    unmapped = [row for row in documented_job_rows() if row not in ROW_TO_JOB_ID]

    assert not unmapped, (
        f"{unmapped} appear in the deep-dive's job tables but have no entry in ROW_TO_JOB_ID. "
        f"Add the job to core/background_workers/registry.py's KNOWN_JOBS and map it here."
    )


def test_every_documented_job_is_in_known_jobs():
    """The doc → code direction of §9's hook."""
    missing = [
        ROW_TO_JOB_ID[row]
        for row in documented_job_rows()
        if row in ROW_TO_JOB_ID and ROW_TO_JOB_ID[row] not in KNOWN_JOBS
    ]

    assert not missing, f"{missing} are documented but absent from KNOWN_JOBS"


def test_every_known_job_is_documented():
    """The code → doc direction.

    The one deliberate exception is `near_duplicate_receipt_detection`, which §10 resolves and
    explicitly states is "registered as a real job in §6.1's own table" — it is prose there
    rather than a table row, so it is asserted separately below instead of being quietly
    exempted here.
    """
    documented_ids = {ROW_TO_JOB_ID[row] for row in documented_job_rows() if row in ROW_TO_JOB_ID}
    undocumented = set(KNOWN_JOBS) - documented_ids - {"near_duplicate_receipt_detection"}

    assert not undocumented, f"{sorted(undocumented)} are in KNOWN_JOBS but in no table"


def test_the_near_duplicate_job_resolved_in_section_10_is_registered():
    """§10 resolves near-duplicate detection and says it becomes a real registered job.

    Asserted on its own rather than folded into the exemption above, so that "we know about
    this one" stays a positive claim someone can read, not a hole in the check.
    """
    assert "near_duplicate_receipt_detection" in KNOWN_JOBS
    assert KNOWN_JOBS["near_duplicate_receipt_detection"] == "review_flagging"


def test_no_job_id_is_claimed_by_two_owners():
    """Two APIs believing they own one job is the bug `DuplicateJobRegistration` guards at
    runtime; this is the same fact checked in the inventory, before anything runs."""
    assert len(KNOWN_JOBS) == len(set(KNOWN_JOBS))


def test_the_five_jobs_designed_in_section_6_4_all_carry_a_starting_cadence():
    """§10 locks in reasoned starting cadences for these rather than leaving them unset.

    A job inventoried with no cadence is a job nobody scheduled — the shipping default is what
    makes it actually run.
    """
    from core.background_workers.contracts import DEFAULT_CADENCE_SECONDS

    for job_id in (
        "expired_session_cleanup",
        "break_glass_grant_sweep",
        "account_deletion_grace_sweep",
        "blob_backup_spot_verification",
    ):
        assert job_id in KNOWN_JOBS
        assert DEFAULT_CADENCE_SECONDS[job_id] > 0


# ------------------------------------------------------- the live registry vs the inventory


def test_the_default_registry_is_empty_and_that_is_deliberate():
    """No domain API registers a real job in this build yet.

    Same posture as `core/task_scheduler/registry.py` and `core/health/resource_ledger.py`
    toward their own not-yet-existing dependencies. An inventory is what those APIs will
    register *against*; it is not a claim that they already have.
    """
    assert default_registry().all_jobs() == ()


def test_the_inventory_reports_which_known_jobs_nobody_has_registered():
    """§6.5's real question — "what does this program do while nobody's watching" — needs an
    honest answer on a partially-built system, not a silent one."""
    registry = JobRegistry()

    assert set(unregistered_known_jobs(registry)) == set(KNOWN_JOBS)


def test_registering_a_known_job_removes_it_from_the_unregistered_list():
    registry = JobRegistry()
    registry.register(registration(job_id="log_retention_purge"), RecordingHandler())

    assert "log_retention_purge" not in unregistered_known_jobs(registry)


def test_a_registered_job_absent_from_the_inventory_is_surfaced():
    """This is the direction that is actually a problem.

    A job running in production that the consolidated table never mentions is exactly the
    "designed at its own document, invisible as part of the whole system's workload" failure
    §6.5 describes — caught here rather than discovered by someone wondering what is writing
    to their database at 3am.
    """
    registry = JobRegistry()
    registry.register(registration(job_id="some_undocumented_job"), RecordingHandler())

    assert unknown_registered_jobs(registry) == ("some_undocumented_job",)


def test_a_fully_registered_system_reports_nothing_missing_in_either_direction():
    """The end state this whole check is aiming at, asserted so it is reachable at all."""
    registry = JobRegistry()
    for job_id, owner in KNOWN_JOBS.items():
        registry.register(registration(job_id=job_id, owning_api=owner), RecordingHandler())

    assert unregistered_known_jobs(registry) == ()
    assert unknown_registered_jobs(registry) == ()


def test_duplicate_registration_is_rejected():
    from core.background_workers.errors import DuplicateJobRegistration

    registry = JobRegistry()
    registry.register(registration(job_id="log_retention_purge"), RecordingHandler())

    with pytest.raises(DuplicateJobRegistration):
        registry.register(registration(job_id="log_retention_purge"), RecordingHandler())


@pytest.mark.parametrize("interval", [0, -1, -3600])
def test_a_non_positive_interval_is_rejected_rather_than_clamped(interval):
    """It almost always means a unit mix-up — milliseconds where seconds were meant.

    Clamping would turn that into a job hammering the pool every tick instead of an error the
    author sees immediately.
    """
    from core.background_workers.errors import InvalidJobRegistration

    registry = JobRegistry()

    with pytest.raises(InvalidJobRegistration):
        registry.register(registration(interval_seconds=interval), RecordingHandler())
