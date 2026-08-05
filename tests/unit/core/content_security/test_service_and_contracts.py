"""The gRPC servicer and the frozen contracts (§7, `docs/PRINCIPLES.md` §2.1, §4.1, §4.2).

The servicer tests are about one thing: **no failure mode on this surface can produce anything
a caller could read as permission.** §4 makes fail-closed a contract-level guarantee rather
than a caller convention, and a servicer that raised out to gRPC would push the decision back
into every caller's `except` block — which is exactly where a silent bypass gets written by
accident.

The `forward_compat`-marked test covers `ScanVerdict.provider_verdicts` and
`ContainerScanVerdict.member_verdicts`, both `FrozenDict`-typed. On 3.15 the builtin
`frozendict` is not a `dict` subclass, so any `isinstance(x, dict)` check against them
silently takes the wrong branch — and for `provider_verdicts` that means a disagreement
between scanners quietly failing to render for the human §4.3 requires it to reach.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.content_security.contracts import (
    ContainerScanVerdict,
    ScanOutcome,
    ScanVerdict,
)
from core.content_security.errors import ERROR_SUMMARIES, E_INVALID_REQUEST
from core.content_security.pipeline import ContentScanner
from core.content_security.providers.base import ProviderRegistry
from core.content_security.service import ContentSecurityServicer

from .conftest import PNG_BYTES, FakeProvider, make_zip, registry_of

pb = pytest.importorskip(
    "core.content_security.generated.content_security_pb2",
    reason="grpcio/protobuf has no wheel on this interpreter yet (docs/MAINTENANCE.md §3)",
)


def servicer_with(*providers) -> ContentSecurityServicer:
    registry = registry_of(*providers) if providers else ProviderRegistry()
    return ContentSecurityServicer(ContentScanner(registry))


# ------------------------------------------------------------------------ servicer


def test_clean_file_round_trips_as_safe():
    servicer = servicer_with(FakeProvider("clamav", ScanOutcome.CLEAN))

    verdict = servicer.ScanFile(pb.ScanRequest(content=PNG_BYTES), None)

    assert verdict.safe is True
    assert verdict.detected_type == "image/png"
    assert verdict.error_code == ""


def test_empty_request_is_denied_not_treated_as_nothing_to_check():
    """A zero-byte upload is a request this API cannot evaluate, so it is a deny.

    Treating "no content" as "nothing suspicious" is the most trivially exploitable version of
    the bypass §4 exists to prevent.
    """
    verdict = servicer_with(FakeProvider("clamav")).ScanFile(pb.ScanRequest(content=b""), None)

    assert verdict.safe is False
    assert verdict.error_code == E_INVALID_REQUEST
    assert verdict.rejection_reason == ERROR_SUMMARIES[E_INVALID_REQUEST]


def test_an_exception_inside_the_pipeline_becomes_a_deny_not_a_grpc_status():
    """§4.1 and §4.2 together: errors are data, and this API's data is always a deny.

    A raised gRPC status would abort the call, and the caller's own error handling is where a
    "couldn't check, let it through" branch gets written. The servicer removes that option.
    """

    class ExplodingScanner(ContentScanner):
        async def scan(self, request):  # type: ignore[override]
            raise RuntimeError("pipeline exploded")

    servicer = ContentSecurityServicer(ExplodingScanner(ProviderRegistry()))

    verdict = servicer.ScanFile(pb.ScanRequest(content=PNG_BYTES), None)

    assert verdict.safe is False
    assert verdict.error_code == "SCAN_UNAVAILABLE"
    assert "treated as unscanned" in verdict.rejection_reason


def test_container_exception_becomes_a_deny_too():
    class ExplodingScanner(ContentScanner):
        async def scan_container(self, request):  # type: ignore[override]
            raise RuntimeError("pipeline exploded")

    servicer = ContentSecurityServicer(ExplodingScanner(ProviderRegistry()))

    verdict = servicer.ScanContainer(pb.ContainerScanRequest(content=b"PK\x03\x04junk"), None)

    assert verdict.safe is False
    assert verdict.error_code == "SCAN_UNAVAILABLE"


def test_disagreement_survives_the_wire_boundary():
    """§4.3 only means something if the conflict is visible to the human resolving it."""
    servicer = servicer_with(
        FakeProvider("clamav", ScanOutcome.MALICIOUS),
        FakeProvider("virustotal", ScanOutcome.CLEAN),
    )

    verdict = servicer.ScanFile(pb.ScanRequest(content=PNG_BYTES), None)

    assert verdict.requires_staff_review is True
    assert dict(verdict.provider_verdicts) == {"clamav": "malicious", "virustotal": "clean"}


def test_container_member_verdicts_survive_the_wire_boundary():
    servicer = servicer_with(FakeProvider("clamav", ScanOutcome.CLEAN))
    archive = make_zip({"a.png": PNG_BYTES})

    verdict = servicer.ScanContainer(pb.ContainerScanRequest(content=archive), None)

    assert verdict.safe is True
    assert verdict.member_verdicts["a.png"].safe is True
    assert verdict.bomb_check.safe is True


def test_the_wire_surface_has_no_field_for_could_not_check():
    """The §4 guarantee, asserted against the generated descriptor.

    A future `unknown` or `scan_skipped` field would be the one change that reopens the hole
    this API exists to close, so it fails here before anyone can rely on it.
    """
    fields = {f.name for f in pb.ScanVerdict.DESCRIPTOR.fields}

    assert fields == {
        "safe",
        "detected_type",
        "rejection_reason",
        "requires_staff_review",
        "error_code",
        "provider_verdicts",
    }


# ----------------------------------------------------------------------- contracts


@pytest.mark.forward_compat
def test_frozen_dict_fields_are_mappings_not_dict_subclasses():
    """The check every consumer must make is `Mapping`, never `dict`.

    On 3.14 the PyPI `frozendict` satisfies both; on 3.15 the builtin satisfies only
    `Mapping`. Asserting `Mapping` is what stays true when the interpreter moves.
    """
    verdict = ScanVerdict(safe=False, provider_verdicts=FrozenDict({"clamav": "malicious"}))
    container = ContainerScanVerdict(safe=False, member_verdicts=FrozenDict({"a": verdict}))

    assert isinstance(verdict.provider_verdicts, Mapping)
    assert isinstance(container.member_verdicts, Mapping)


@pytest.mark.forward_compat
def test_provider_verdicts_cannot_be_rewritten_after_the_fact():
    """A verdict whose evidence could be edited in place is not evidence."""
    verdict = ScanVerdict(safe=False, provider_verdicts=FrozenDict({"clamav": "malicious"}))

    with pytest.raises(Exception):
        verdict.provider_verdicts["clamav"] = "clean"  # type: ignore[index]


def test_error_summaries_table_is_a_frozen_dict():
    """§2.1.1: a module-level constant lookup table is a `FrozenDict` too."""
    assert isinstance(ERROR_SUMMARIES, Mapping)
    with pytest.raises(Exception):
        ERROR_SUMMARIES[E_INVALID_REQUEST] = "something else"  # type: ignore[index]


def test_magic_signature_table_is_a_frozen_dict():
    from core.content_security.scanning.magic_bytes import MAGIC_SIGNATURES

    assert isinstance(MAGIC_SIGNATURES, Mapping)
    with pytest.raises(Exception):
        MAGIC_SIGNATURES["image/png"] = (0, b"nope")  # type: ignore[index]


def test_verdict_is_frozen():
    verdict = ScanVerdict(safe=False)

    with pytest.raises(Exception):
        verdict.safe = True  # type: ignore[misc]
