"""`FiledIssueLedger` and `GitHubIssueStatusClient` — the ledger is pure local-file logic
(no network); the status client makes real, live calls to the real public GitHub REST
API against a well-known, stable public issue (`python/cpython#1`) rather than a mock,
matching this project's own "never stub the thing under test" discipline. Skipped
automatically if the sandbox has no outbound network access.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from core.telemetrees.diagnostics.contracts import FiledIssueRecord
from core.telemetrees.diagnostics.github_status_client import GitHubIssueStatusClient
from core.telemetrees.diagnostics.ledger import FiledIssueLedger


def run(coro):
    return asyncio.run(coro)


def _network_available() -> bool:
    try:
        httpx.get("https://api.github.com", timeout=3.0)
        return True
    except httpx.HTTPError:
        return False


requires_network = pytest.mark.skipif(not _network_available(), reason="no outbound network access in this sandbox")


# --- FiledIssueLedger ----------------------------------------------------------------------


def test_list_all_on_a_fresh_ledger_is_empty(tmp_path: Path):
    ledger = FiledIssueLedger(tmp_path)

    assert ledger.list_all() == ()


def test_record_and_list_all_round_trip(tmp_path: Path):
    ledger = FiledIssueLedger(tmp_path)
    entry = FiledIssueRecord(fingerprint="abc123", issue_number=42, url="https://github.com/x/y/issues/42", title="Something broke")

    ledger.record(entry)

    assert ledger.list_all() == (entry,)


def test_record_never_duplicates_the_same_fingerprint(tmp_path: Path):
    ledger = FiledIssueLedger(tmp_path)
    first = FiledIssueRecord(fingerprint="abc123", issue_number=42, url="https://github.com/x/y/issues/42", title="Something broke")
    second = FiledIssueRecord(fingerprint="abc123", issue_number=99, url="https://github.com/x/y/issues/99", title="Different title")

    ledger.record(first)
    ledger.record(second)

    assert ledger.list_all() == (first,)


def test_two_different_fingerprints_both_persist(tmp_path: Path):
    ledger = FiledIssueLedger(tmp_path)
    first = FiledIssueRecord(fingerprint="abc123", issue_number=42, url="u1", title="One")
    second = FiledIssueRecord(fingerprint="def456", issue_number=43, url="u2", title="Two")

    ledger.record(first)
    ledger.record(second)

    assert set(ledger.list_all()) == {first, second}


def test_state_persists_across_a_new_ledger_instance(tmp_path: Path):
    entry = FiledIssueRecord(fingerprint="abc123", issue_number=42, url="u", title="t")
    FiledIssueLedger(tmp_path).record(entry)

    reopened = FiledIssueLedger(tmp_path)

    assert reopened.list_all() == (entry,)


# --- GitHubIssueStatusClient -----------------------------------------------------------------


@requires_network
def test_get_status_reads_a_real_public_issue():
    client = GitHubIssueStatusClient("python", "cpython")

    status = run(client.get_status(1))

    assert status.ok
    assert status.state in ("open", "closed")
    assert status.url


@requires_network
def test_get_status_reports_a_real_404_honestly():
    client = GitHubIssueStatusClient("domtrifoundation", "Receipt-System-V3")

    status = run(client.get_status(999999))

    assert status.ok is False
    assert "404" in status.error_detail


@requires_network
def test_get_status_finds_real_linked_pull_requests():
    """`python/cpython#1` has real, long-standing cross-referenced PRs — a genuine,
    stable fixture for confirming the timeline-based linked-PR lookup actually works,
    not just that it returns an empty tuple without erroring."""
    client = GitHubIssueStatusClient("python", "cpython")

    status = run(client.get_status(1))

    assert len(status.linked_pr_numbers) > 0
