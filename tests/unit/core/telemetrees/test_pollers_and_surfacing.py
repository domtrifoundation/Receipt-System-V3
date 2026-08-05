"""Per-fact-kind polling, and getting a change in front of a developer (§3, §4, §8, §9).

The two remaining named testing hooks are here:

* **Telemetrees §8's issue-state-change detection test** — "confirms a tracked GitHub issue
  transitioning from open to closed actually surfaces as a changelog event, not silently missed
  by a poller only watching for version bumps."
* **Warden §8's free-threading classifier detection test** — "confirms the `FreeThreadingPoller`
  correctly reads the PyPI trove classifier where present, not just guessing from changelog text
  alone."

No test here touches the network. Every poller sits behind the `HttpTransport` seam
(`docs/PRINCIPLES.md` §1.3), so the tests inject a transport carrying real API-shaped payloads
and exercise the same parsing production runs — rather than mocking `urllib` somewhere deep in
a call stack and testing the mock.
"""

from __future__ import annotations

import pytest

from core.telemetrees.contracts import (
    FreeThreadingStatus,
    IssueState,
    TrackedFactKind,
)
from core.telemetrees.dependencies_warden.pollers.base import (
    StaticTransport,
    UnavailableTransport,
)
from core.telemetrees.dependencies_warden.pollers.free_threading_poller import (
    COMMUNITY_TRACKER_API,
    SOURCE_CLASSIFIER,
    SOURCE_COMMUNITY,
    SOURCE_NONE,
    FreeThreadingPoller,
)
from core.telemetrees.dependencies_warden.pollers.github_issue_poller import (
    GITHUB_ISSUE_URL,
    GitHubIssuePoller,
    parse_issue_ref,
)
from core.telemetrees.dependencies_warden.pollers.pypi_poller import (
    PYPI_JSON_URL,
    PyPIPoller,
    is_prerelease,
    version_key,
)
from core.telemetrees.dependencies_warden.poller import PollerRegistry, WardenPoller
from core.telemetrees.dependencies_warden.registry import TrackedDependencyRegistry
from core.telemetrees.dependencies_warden.surfacing import entries_for
from core.telemetrees.errors import InvalidIssueRef, UpstreamUnreachable

OPENCV_ISSUE = "opencv/opencv#27933"
ISSUE_URL = GITHUB_ISSUE_URL.format(owner="opencv", repo="opencv", number="27933")


# ------------------------------------------------------------------------ PyPI poller


def test_the_newest_release_is_reported():
    transport = StaticTransport(
        {PYPI_JSON_URL.format(name="numpy"): {"releases": {"1.26.4": [], "2.1.0": []}}}
    )

    event = PyPIPoller(transport).poll("numpy")

    assert event is not None
    assert event.version == "2.1.0"
    assert not event.is_prerelease


def test_a_prerelease_is_reported_and_labelled_rather_than_filtered_out():
    """File 02 rule #8: the point of day-0 support is knowing before it ships stable.

    A poller that filtered pre-releases would surface exactly the versions it is too late to
    prepare for.
    """
    transport = StaticTransport(
        {PYPI_JSON_URL.format(name="numpy"): {"releases": {"2.1.0": [], "2.2.0rc1": []}}}
    )

    event = PyPIPoller(transport).poll("numpy")

    assert event.version == "2.2.0rc1"
    assert event.is_prerelease


def test_a_release_candidate_never_outranks_its_own_final_release():
    """`2.0.0rc1` must not be reported as newer than `2.0.0`."""
    assert version_key("2.0.0rc1") < version_key("2.0.0")
    assert is_prerelease("2.0.0rc1")
    assert not is_prerelease("2.0.0")


def test_numeric_segments_sort_numerically_not_lexically():
    """The classic bug: `10.0.0` sorting below `9.0.0` as strings."""
    assert version_key("10.0.0") > version_key("9.0.0")


def test_a_project_with_no_releases_is_not_an_error():
    transport = StaticTransport({PYPI_JSON_URL.format(name="brand-new"): {"releases": {}}})

    assert PyPIPoller(transport).poll("brand-new") is None


def test_an_unreachable_registry_raises_rather_than_inventing_a_version():
    """Never report a fact that was not observed."""
    with pytest.raises(UpstreamUnreachable):
        PyPIPoller(UnavailableTransport()).poll("numpy")


# --------------------------------------------------------------- GitHub issue poller


def test_a_tracked_issue_state_is_read():
    transport = StaticTransport(
        {ISSUE_URL: {"state": "closed", "title": "free-threading wheels", "html_url": "u"}}
    )

    event = GitHubIssuePoller(transport).poll("opencv-python", OPENCV_ISSUE)

    assert event.state is IssueState.CLOSED
    assert event.issue_ref == OPENCV_ISSUE


def test_an_unrecognised_state_is_unknown_rather_than_guessed_as_open():
    """Reporting a state we did not understand as "still open" would keep a resolved blocker
    looking unresolved — precisely the signal this poller exists to deliver."""
    transport = StaticTransport({ISSUE_URL: {"state": "some_new_state"}})

    event = GitHubIssuePoller(transport).poll("opencv-python", OPENCV_ISSUE)

    assert event.state is IssueState.UNKNOWN


def test_a_repo_name_containing_a_hyphen_parses():
    """The inventory carries `opencv/opencv-python#1051`, so this is not hypothetical."""
    assert parse_issue_ref("opencv/opencv-python#1051") == ("opencv", "opencv-python", "1051")


@pytest.mark.parametrize("ref", ["opencv#27933", "opencv/opencv", "", "opencv/opencv#abc"])
def test_a_malformed_issue_ref_raises_rather_than_yielding_no_event(ref):
    """A typo'd ref means a fact nobody is watching while the inventory claims otherwise.

    Failing loudly at the point of use is what makes that discoverable; resolving to a quiet
    "no event" would make it indistinguishable from an issue that simply has not moved.
    """
    with pytest.raises(InvalidIssueRef):
        parse_issue_ref(ref)


# --------------------------------------------------------- free-threading poller (§8)


def test_the_trove_classifier_is_read_where_present():
    """Warden §8's classifier-detection hook, verbatim.

    "Not just guessing from changelog text alone" — so the check is a real match against the
    standardized classifier string, and the event records that the classifier is what spoke.
    """
    transport = StaticTransport(
        {
            PYPI_JSON_URL.format(name="pillow-heif"): {
                "info": {
                    "classifiers": [
                        "Programming Language :: Python :: 3",
                        "Programming Language :: Python :: Free Threading",
                    ]
                }
            }
        }
    )

    event = FreeThreadingPoller(transport).poll("pillow-heif")

    assert event.status is FreeThreadingStatus.SUPPORTED
    assert event.source == SOURCE_CLASSIFIER


def test_no_classifier_is_unknown_not_unsupported():
    """Most packages have said nothing at all.

    Reporting silence as a refusal would fill the changelog with false negatives and make the
    genuine ones unfindable.
    """
    transport = StaticTransport(
        {PYPI_JSON_URL.format(name="numpy"): {"info": {"classifiers": []}}}
    )

    event = FreeThreadingPoller(transport).poll("numpy")

    assert event.status is FreeThreadingStatus.UNKNOWN
    assert event.source == SOURCE_NONE


def test_the_community_tracker_is_a_cross_check_when_the_classifier_is_silent():
    """§9's resolved secondary signal, and the case it actually catches.

    A package can support free threading in practice for months before declaring it; the
    tracker says what the community observed, the classifier says what the maintainer declared.
    """
    transport = StaticTransport(
        {
            PYPI_JSON_URL.format(name="numpy"): {"info": {"classifiers": []}},
            COMMUNITY_TRACKER_API: {"numpy": {"supported": True, "detail": "verified 2026-06"}},
        }
    )

    event = FreeThreadingPoller(transport).poll("numpy")

    assert event.status is FreeThreadingStatus.SUPPORTED
    assert event.source == SOURCE_COMMUNITY


def test_the_maintainers_own_classifier_wins_over_the_tracker():
    """Nothing the community says should override a package's own declaration about itself."""
    transport = StaticTransport(
        {
            PYPI_JSON_URL.format(name="numpy"): {
                "info": {"classifiers": ["Programming Language :: Python :: Free Threading"]}
            },
            COMMUNITY_TRACKER_API: {"numpy": {"supported": False}},
        }
    )

    assert FreeThreadingPoller(transport).poll("numpy").source == SOURCE_CLASSIFIER


def test_an_unreachable_tracker_leaves_the_answer_unknown_rather_than_failing_the_poll():
    """The classifier already came back absent, so this is the honest result.

    Failing a poll that had a perfectly good primary source available would cost the other
    facts in the same pass for no gain.
    """
    transport = StaticTransport(
        {PYPI_JSON_URL.format(name="numpy"): {"info": {"classifiers": []}}}
    )

    assert FreeThreadingPoller(transport).poll("numpy").status is FreeThreadingStatus.UNKNOWN


# --------------------------------------------------- §8's issue-state-change detection


def _issue_poller_registry(states: list[str]) -> tuple[WardenPoller, TrackedDependencyRegistry]:
    """A warden watching one issue whose state changes between passes."""
    from common.frozen_dict import FrozenDict

    from core.telemetrees.contracts import TrackedDependency

    seed = FrozenDict(
        {
            "opencv-python": TrackedDependency(
                name="opencv-python",
                fact_kinds=(TrackedFactKind.UPSTREAM_ISSUE_STATUS,),
                upstream_issue_refs=(OPENCV_ISSUE,),
            )
        }
    )
    registry = TrackedDependencyRegistry(seed=seed)
    sequence = iter(states)
    pollers = PollerRegistry()
    pollers.register(
        TrackedFactKind.UPSTREAM_ISSUE_STATUS, lambda _n: (next(sequence), OPENCV_ISSUE)
    )
    return WardenPoller(registry, pollers), registry


def test_an_issue_closing_surfaces_as_a_changelog_event():
    """§8's issue-state-change hook, end to end.

    §3.2's whole argument is that a release poller would never see this: the fact lives on an
    issue thread and can resolve with or without a version bump. So the assertion is not only
    that the state changed but that it produced a line a developer will actually read.
    """
    warden, _registry = _issue_poller_registry(["open", "closed"])

    first = warden.poll_once()
    second = warden.poll_once()

    assert first.real_changes == ()
    assert len(second.real_changes) == 1

    entries = entries_for(second.changes)
    assert len(entries) == 1
    assert "opencv/opencv#27933" in entries[0].text
    assert "now closed" in entries[0].text
    assert warden.metrics.snapshot().issue_state_changes_detected == 1


def test_the_first_observation_is_not_reported_as_a_change():
    """On a fresh install every fact would otherwise look like news.

    Fourteen inventory entries dumped into the changelog on day one would bury the one thing
    that actually moves in the next cycle.
    """
    warden, _registry = _issue_poller_registry(["open", "open"])

    first = warden.poll_once()

    assert first.changes[0].is_first_observation
    assert entries_for(first.changes) == ()


def test_an_unchanged_fact_produces_no_entry():
    warden, _registry = _issue_poller_registry(["open", "open"])
    warden.poll_once()

    assert entries_for(warden.poll_once().changes) == ()


def test_one_unreachable_source_never_stops_the_rest_of_the_pass():
    """Monitoring that stopped at the first failure would silently take everything else down."""
    from common.frozen_dict import FrozenDict

    from core.telemetrees.contracts import TrackedDependency

    def explodes(_name: str):
        raise UpstreamUnreachable("pypi down")

    seed = FrozenDict(
        {
            "numpy": TrackedDependency(
                name="numpy", fact_kinds=(TrackedFactKind.RELEASE_VERSION,)
            ),
            "opencv-python": TrackedDependency(
                name="opencv-python", fact_kinds=(TrackedFactKind.UPSTREAM_ISSUE_STATUS,)
            ),
        }
    )
    pollers = PollerRegistry()
    pollers.register(TrackedFactKind.RELEASE_VERSION, explodes)
    pollers.register(TrackedFactKind.UPSTREAM_ISSUE_STATUS, lambda _n: ("closed", OPENCV_ISSUE))
    warden = WardenPoller(TrackedDependencyRegistry(seed=seed), pollers)

    result = warden.poll_once()

    assert "numpy:release_version" in result.unreachable
    assert any(c.fact.dependency == "opencv-python" for c in result.changes)


def test_a_dataset_change_is_filed_under_security_rather_than_changed():
    """A stale virus-definition database is a security fact, not routine dependency churn.

    Filing it under `Changed` would let it scroll past unread among version bumps, which is
    exactly how a silent security gap stays silent.
    """
    from core.telemetrees.contracts import FactChange, TrackedFact

    change = FactChange(
        fact=TrackedFact(
            dependency="clamav-definitions",
            kind=TrackedFactKind.DATASET_FRESHNESS,
            value="27100",
        ),
        previous="27099",
    )

    assert entries_for([change])[0].category == "Security"
