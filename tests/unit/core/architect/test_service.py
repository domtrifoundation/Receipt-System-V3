"""`ArchitectServicer` — the real assembly point tying the read registry, temporal_
learning's moderation pipeline, and the vendor directory to `architect.proto`'s wire
surface. This was a real, complete gap found only by checking that every module built in
this package is genuinely reachable through a running service, not just independently
tested (`service.py`'s own module docstring)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.architect.generated import architect_pb2 as pb  # noqa: E402
from core.architect.service import ArchitectServicer  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_get_taxonomy_returns_seeded_categories():
    servicer = ArchitectServicer()

    response = run(servicer.GetTaxonomy(pb.TaxonomyRequest(kind="taxonomy_category")))

    assert response.error_code == ""
    assert len(response.definitions) > 0
    assert all(d.kind == "taxonomy_category" for d in response.definitions)


def test_get_taxonomy_reports_unknown_kind_for_a_bad_kind_string():
    servicer = ArchitectServicer()

    response = run(servicer.GetTaxonomy(pb.TaxonomyRequest(kind="not_a_real_kind")))

    assert response.error_code == "unknown_kind"
    assert len(response.definitions) == 0


def test_get_taxonomy_with_parent_code_returns_children_only():
    servicer = ArchitectServicer()

    all_categories = run(servicer.GetTaxonomy(pb.TaxonomyRequest(kind="taxonomy_category")))
    parent = next(d for d in all_categories.definitions if d.parent_code == "")

    response = run(servicer.GetTaxonomy(pb.TaxonomyRequest(kind="taxonomy_category", parent_code=parent.code)))

    assert response.error_code == ""
    assert all(d.parent_code == parent.code for d in response.definitions)


def test_submit_review_approve_merges_a_new_corporation_into_the_directory():
    servicer = ArchitectServicer()

    submitted = run(servicer.SubmitContribution(pb.ContributionRequest(
        contributor="human:u1", target_entity_type="corporation", target_entity_id="",
        proposed_change={"name": "Acme Corp", "corporate_tin": "123-456-789"},
        staff_authored=False,
    )))
    assert submitted.error_code == ""
    assert submitted.contribution.staff_review_status == "pending"
    assert submitted.contribution.merged is False

    reviewed = run(servicer.ReviewContribution(pb.ReviewRequest(
        contribution_id=submitted.contribution.contribution_id, reviewer="staff-1",
        approved=True, reason="looks right",
    )))
    assert reviewed.error_code == ""
    assert reviewed.contribution.merged is True

    search = run(servicer.SearchVendorDirectory(pb.VendorSearchRequest(query="Acme Corp", limit=5)))
    assert [r.name for r in search.records] == ["Acme Corp"]


def test_submit_review_reject_never_merges():
    servicer = ArchitectServicer()

    submitted = run(servicer.SubmitContribution(pb.ContributionRequest(
        contributor="human:u1", target_entity_type="corporation", target_entity_id="",
        proposed_change={"name": "Rejected Corp", "corporate_tin": "111-111-111"},
    )))

    reviewed = run(servicer.ReviewContribution(pb.ReviewRequest(
        contribution_id=submitted.contribution.contribution_id, reviewer="staff-1",
        approved=False, reason="duplicate",
    )))
    assert reviewed.error_code == ""
    assert reviewed.contribution.merged is False
    assert reviewed.contribution.staff_review_status == "rejected"

    search = run(servicer.SearchVendorDirectory(pb.VendorSearchRequest(query="Rejected Corp", limit=5)))
    assert search.records == []


def test_staff_authored_contribution_merges_without_a_separate_review_call():
    """§3.2's direct-to-global path: prescreen only, no second staff approval — `process()`
    merges as soon as prescreen passes, since `staff_review_status` is already
    `not_applicable`."""
    servicer = ArchitectServicer()

    submitted = run(servicer.SubmitContribution(pb.ContributionRequest(
        contributor="human:staff-1", target_entity_type="corporation", target_entity_id="",
        proposed_change={"name": "Direct Corp", "corporate_tin": "222-222-222"},
        staff_authored=True,
    )))

    assert submitted.error_code == ""
    assert submitted.contribution.staff_review_status == "not_applicable"
    assert submitted.contribution.merged is True

    search = run(servicer.SearchVendorDirectory(pb.VendorSearchRequest(query="Direct Corp", limit=5)))
    assert [r.name for r in search.records] == ["Direct Corp"]


def test_review_contribution_reports_unknown_contribution():
    servicer = ArchitectServicer()

    response = run(servicer.ReviewContribution(pb.ReviewRequest(
        contribution_id="does-not-exist", reviewer="staff-1", approved=True,
    )))

    assert response.error_code == "unknown_contribution"


def test_submit_contribution_reports_invalid_change_for_an_empty_proposed_change():
    servicer = ArchitectServicer()

    response = run(servicer.SubmitContribution(pb.ContributionRequest(
        contributor="human:u1", target_entity_type="corporation", target_entity_id="",
        staff_authored=False,
    )))

    assert response.error_code == "invalid_change"


def test_search_vendor_directory_on_an_empty_directory_returns_no_error():
    servicer = ArchitectServicer()

    response = run(servicer.SearchVendorDirectory(pb.VendorSearchRequest(query="anything", limit=5)))

    assert response.error_code == ""
    assert response.records == []
