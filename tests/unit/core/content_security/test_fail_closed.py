"""Fail-closed, in every failure mode (`v3-deepdive-27-content-security-api.md` §4).

§8's first testing hook is the fail-closed test: "a simulated Content Security outage during
an Ingestion upload attempt confirms the file is rejected/held, never silently passed through
— direct validation of §4's core guarantee."

§4's own argument for why that guarantee belongs to *this* API rather than to every caller is
worth restating, because it is what this file is really protecting: "a security check that can
be silently skipped under some failure condition is, for practical purposes, not really a
security check." So every failure mode gets its own test here, and each asserts `safe is False`
specifically — not "falsy", not "not True". A verdict object that happened to be `None` would
satisfy a falsiness check while representing precisely the absent answer §4 forbids.
"""

from __future__ import annotations

import pytest

from core.content_security.contracts import ScanOutcome, ScanRequest
from core.content_security.errors import (
    E_MALICIOUS_CONFIRMED,
    E_NO_PROVIDER_AVAILABLE,
    E_SCAN_PROVIDER_FAILED,
    E_STAFF_REVIEW_REQUIRED,
)
from core.content_security.pipeline import ContentScanner
from core.content_security.providers.base import ProviderRegistry

from .conftest import FakeProvider, registry_of, run


def scan(registry: ProviderRegistry, content: bytes, **kwargs):
    scanner = ContentScanner(registry, **kwargs)
    return run(scanner.scan(ScanRequest(content=content))), scanner


def test_no_provider_configured_at_all_is_a_deny(png):
    """The startup state of a fresh install, and it must not be a hole.

    An empty registry is a legitimate way for the service to be running — `serve()` allows it
    deliberately — so this is not a hypothetical.
    """
    verdict, _ = scan(ProviderRegistry(), png)

    assert verdict.safe is False
    assert verdict.error_code == E_NO_PROVIDER_AVAILABLE


def test_every_provider_unavailable_is_a_deny(png):
    """A missing ClamAV binary and an unreachable cloud API are the §2 availability cases.

    §4.4's degrade-gracefully rule does not reach this: `docs/PRINCIPLES.md` §4.2 names a
    failed or timed-out content scan as unsafe explicitly, and "no scanner could be reached"
    is the same fact as "the file was never scanned".
    """
    registry = registry_of(
        FakeProvider("clamav", available=False),
        FakeProvider("virustotal", available=False),
    )

    verdict, _ = scan(registry, png)

    assert verdict.safe is False
    assert verdict.error_code == E_NO_PROVIDER_AVAILABLE


def test_provider_crash_is_a_deny_not_a_dropped_opinion(png):
    """A scanner that ran and blew up must be distinguishable from one never enabled.

    Dropping it silently would leave the remaining scanner's clean verdict looking unanimous,
    which is the precise shape of silent bypass §4.2 forbids.
    """
    registry = registry_of(
        FakeProvider("clamav", raises=RuntimeError("clamd socket closed")),
        FakeProvider("virustotal", ScanOutcome.CLEAN),
    )

    verdict, _ = scan(registry, png)

    assert verdict.safe is False
    assert verdict.error_code == E_SCAN_PROVIDER_FAILED
    assert "clamav" in verdict.rejection_reason


def test_provider_timeout_is_a_deny(png):
    """A hung scanner is the outage §8's hook describes, from inside the process."""
    registry = registry_of(FakeProvider("clamav", hangs=True))

    verdict, _ = scan(registry, png, provider_timeout=0.01)

    assert verdict.safe is False
    assert verdict.error_code == E_SCAN_PROVIDER_FAILED
    assert "timed out" in verdict.provider_verdicts.get("clamav", "") or verdict.rejection_reason


def test_availability_check_that_crashes_counts_as_unavailable(png):
    """A provider whose own health check throws must not be treated as reachable."""

    class ExplodingAvailability(FakeProvider):
        async def is_available(self) -> bool:
            raise OSError("no such file: clamscan")

    verdict, _ = scan(registry_of(ExplodingAvailability("clamav")), png)

    assert verdict.safe is False
    assert verdict.error_code == E_NO_PROVIDER_AVAILABLE


def test_unanimous_malicious_is_an_outright_reject(png):
    """§9: auto-reject outright only when every enabled scanner agrees."""
    registry = registry_of(
        FakeProvider("clamav", ScanOutcome.MALICIOUS),
        FakeProvider("virustotal", ScanOutcome.MALICIOUS),
    )

    verdict, _ = scan(registry, png)

    assert verdict.safe is False
    assert verdict.error_code == E_MALICIOUS_CONFIRMED
    assert verdict.requires_staff_review is False


def test_scanner_disagreement_goes_to_staff_review_not_to_either_extreme(png):
    """§9's resolved threshold, and `docs/PRINCIPLES.md` §4.3.

    Neither auto-rejecting on an ambiguous signal nor auto-accepting anything short of full
    consensus. The disagreement stays visible on `provider_verdicts` so a human can see what
    actually differed — a conflict folded into one boolean is not surfaced, it is discarded.
    """
    registry = registry_of(
        FakeProvider("clamav", ScanOutcome.MALICIOUS),
        FakeProvider("virustotal", ScanOutcome.CLEAN),
    )

    verdict, _ = scan(registry, png)

    assert verdict.safe is False
    assert verdict.requires_staff_review is True
    assert verdict.error_code == E_STAFF_REVIEW_REQUIRED
    assert verdict.provider_verdicts["clamav"] == "malicious"
    assert verdict.provider_verdicts["virustotal"] == "clean"


def test_single_low_confidence_result_goes_to_staff_review(png):
    """§9's other named case: a lone scanner's own borderline signal."""
    registry = registry_of(FakeProvider("clamav", ScanOutcome.SUSPICIOUS))

    verdict, _ = scan(registry, png)

    assert verdict.safe is False
    assert verdict.requires_staff_review is True


def test_unanimous_clean_is_the_only_path_to_safe(png):
    """The one positive case — and the only branch in the package that yields `safe=True`."""
    registry = registry_of(
        FakeProvider("clamav", ScanOutcome.CLEAN),
        FakeProvider("virustotal", ScanOutcome.CLEAN),
    )

    verdict, _ = scan(registry, png)

    assert verdict.safe is True
    assert verdict.error_code == ""
    assert verdict.detected_type == "image/png"


@pytest.mark.parametrize(
    "outcome",
    [ScanOutcome.MALICIOUS, ScanOutcome.SUSPICIOUS, ScanOutcome.ERROR],
)
def test_no_non_clean_outcome_can_ever_produce_safe(png, outcome):
    """Exhaustive over the outcome enum: only unanimous CLEAN passes.

    Parametrised rather than written out so that adding a new `ScanOutcome` member without
    considering this rule fails here rather than silently widening what counts as safe.
    """
    verdict, _ = scan(registry_of(FakeProvider("clamav", outcome)), png)

    assert verdict.safe is False


def test_metrics_record_each_denial_reason(png):
    registry = registry_of(FakeProvider("clamav", ScanOutcome.MALICIOUS))
    verdict, scanner = scan(registry, png)

    snapshot = scanner.metrics.snapshot()

    assert verdict.safe is False
    assert snapshot.scans_performed == 1
    assert snapshot.scans_denied_malicious == 1
    assert snapshot.scans_passed_clean == 0
