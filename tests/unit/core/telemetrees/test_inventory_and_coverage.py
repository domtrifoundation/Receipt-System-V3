"""The §3.1 inventory, and that something can actually answer every fact it declares.

Both deep-dives ask for a coverage test, from opposite ends, and both are here:

* **Telemetrees §8's multi-fact-kind coverage test** — "confirms every dependency in the §3.1
  inventory actually has the right `fact_kinds` registered, not defaulting to plain
  `release_version` tracking for something that needed `free_threading_support` specifically —
  the concrete mechanism that keeps this registry from silently drifting out of sync with what
  every prior deep-dive actually asked for."
* **Warden §8's multi-poller coverage test** — "confirms every dependency in Telemetrees' own
  §3.1 inventory has a poller actually registered for each of its declared `fact_kinds`, not
  silently falling back to release-version-only monitoring for something that needed a
  different fact kind."

Both describe the same failure from different sides: a dependency that *looks* tracked while
the specific thing anyone cared about goes unwatched. §3.1 was assembled from deferred items
scattered across twenty-eight documents, and the failure mode is not that someone deletes an
entry — it is that an entry survives with the wrong `fact_kinds` and nobody notices, because
the poller runs, reports a version, and looks perfectly healthy.
"""

from __future__ import annotations

import pytest

from core.telemetrees.contracts import TrackedFactKind
from core.telemetrees.dependencies_warden.poller import PollerRegistry
from core.telemetrees.dependencies_warden.registry import (
    INVENTORY,
    TrackedDependencyRegistry,
    default_registry,
)

#: Dependencies §3.1 names under "free-threading support, per-dependency". Every one must carry
#: `FREE_THREADING_SUPPORT` specifically — a release-version-only entry for any of them is the
#: exact silent drift Telemetrees §8 describes.
FREE_THREADING_TRACKED = [
    "onnxruntime",
    "onnxruntime-genai",
    "opencv-python",
    "rapidfuzz",
    "numpy",
    "pymupdf",
    "pillow-heif",
    "authlib",
    "cryptography",
]


def test_the_shipped_registry_is_the_inventory():
    """Unlike Task Scheduler's allowlist or Background Workers' job registry, this starts full.

    Those wait for other APIs to register against them; this inventory is complete today and
    every entry names the document that asked for it. A Telemetrees process tracking nothing
    would be monitoring that silently does nothing — §4's own definition of pointless.
    """
    assert {d.name for d in default_registry().all_dependencies()} == set(INVENTORY)
    assert len(INVENTORY) >= 14


@pytest.mark.parametrize("name", FREE_THREADING_TRACKED)
def test_every_free_threading_dependency_declares_that_fact_kind(name):
    """§8's multi-fact-kind hook, on the group §3.1 is most specific about.

    Parametrised per dependency rather than asserted as a set, so a failure names the one that
    drifted instead of dumping a set difference someone has to read.
    """
    dependency = default_registry().require(name)

    assert TrackedFactKind.FREE_THREADING_SUPPORT in dependency.fact_kinds


def test_opencv_needs_all_three_fact_kinds_at_once():
    """The case the whole non-uniformity argument was drawn from (§3.2).

    A release feed alone would never surface the free-threaded-wheel blocker resolving, since
    that fact lives on an issue thread. The issue alone would never surface a wheel finally
    shipping. Either one on its own leaves a real question unanswered.
    """
    opencv = default_registry().require("opencv-python")

    assert TrackedFactKind.RELEASE_VERSION in opencv.fact_kinds
    assert TrackedFactKind.FREE_THREADING_SUPPORT in opencv.fact_kinds
    assert TrackedFactKind.UPSTREAM_ISSUE_STATUS in opencv.fact_kinds
    assert "opencv/opencv#27933" in opencv.upstream_issue_refs


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("rapidocr-models", TrackedFactKind.MODEL_CURRENCY),
        ("clamav-definitions", TrackedFactKind.DATASET_FRESHNESS),
        ("bir-slsp-thresholds", TrackedFactKind.REGULATORY_VALUE),
    ],
)
def test_the_three_non_release_shapes_are_not_tracked_as_release_versions(name, kind):
    """§3.1 calls each of these a genuinely distinct shape, and they are the easiest to get wrong.

    A vendored model generation, a virus-definition database and a government-set threshold all
    superficially resemble "a version that changes", and folding any of them into
    `RELEASE_VERSION` would point a PyPI poller at something that is not on PyPI — which fails
    quietly as "unreachable" rather than loudly as "misconfigured".
    """
    dependency = default_registry().require(name)

    assert dependency.fact_kinds == (kind,)
    assert TrackedFactKind.RELEASE_VERSION not in dependency.fact_kinds


def test_the_interpreter_is_tracked_like_any_other_dependency():
    """File 02 rule #8: day-0 support is a tracked discipline, not a one-time migration."""
    cpython = default_registry().require("cpython")

    assert TrackedFactKind.FREE_THREADING_SUPPORT in cpython.fact_kinds


def test_every_inventory_entry_records_which_deep_dive_asked_for_it():
    """§3.1 was collected from every prior deep-dive's deferred items, not invented fresh.

    An entry whose reason is lost becomes one nobody dares remove and nobody can act on — which
    over twenty-eight source documents is how an inventory turns into folklore.
    """
    for dependency in default_registry().all_dependencies():
        assert dependency.source_deep_dive, f"{dependency.name} records no source"


def test_every_tracked_issue_ref_is_well_formed():
    """A typo'd ref means a fact nobody watches while the inventory claims otherwise."""
    from core.telemetrees.dependencies_warden.pollers.github_issue_poller import parse_issue_ref

    for ref in default_registry().all_issue_refs():
        parse_issue_ref(ref)


# ----------------------------------------------------------- Warden §8's poller coverage


def full_poller_registry() -> PollerRegistry:
    """Every declared fact kind bound to a probe — what a real process wires up at startup."""
    pollers = PollerRegistry()
    for kind in default_registry().declared_fact_kinds():
        pollers.register(kind, lambda _name: None)
    return pollers


def test_a_fully_wired_process_has_a_poller_for_every_declared_fact_kind():
    """Warden §8's multi-poller coverage hook — the reachable end state, asserted positively."""
    assert full_poller_registry().missing_for(default_registry()) == frozenset()


def test_a_missing_poller_is_surfaced_rather_than_silently_falling_back():
    """The failure this hook is really about.

    §8's own wording is "not silently falling back to release-version-only monitoring for
    something that needed a different fact kind". A registry that answered an unregistered kind
    with the release poller would report a version for ClamAV's definition database — a fact
    that looks fine and means nothing.
    """
    pollers = PollerRegistry()
    pollers.register(TrackedFactKind.RELEASE_VERSION, lambda _name: None)

    missing = pollers.missing_for(default_registry())

    assert TrackedFactKind.FREE_THREADING_SUPPORT in missing
    assert TrackedFactKind.DATASET_FRESHNESS in missing


def test_a_dependency_declaring_an_unpollable_kind_is_reported_not_skipped():
    """An unanswerable fact kind must be visible in the pass result, not simply absent.

    Absent looks identical to "nothing changed", which is precisely the ambiguity that lets an
    unwatched fact stay unwatched.
    """
    from core.telemetrees.dependencies_warden.poller import WardenPoller

    registry = TrackedDependencyRegistry(seed=INVENTORY)
    poller = WardenPoller(registry, PollerRegistry())

    result = poller.poll_once()

    assert result.changes == ()
    assert any(v == "NO_POLLER_FOR_FACT_KIND" for v in result.unreachable.values())


def test_registering_two_pollers_for_one_kind_is_rejected():
    """Which poller answers a kind must not depend on import order."""
    from core.telemetrees.dependencies_warden.errors import PollerAlreadyRegistered

    pollers = PollerRegistry()
    pollers.register(TrackedFactKind.RELEASE_VERSION, lambda _name: None)

    with pytest.raises(PollerAlreadyRegistered):
        pollers.register(TrackedFactKind.RELEASE_VERSION, lambda _name: None)


def test_config_may_add_or_override_a_tracked_dependency():
    """§7's config-driven additions.

    Replacement rather than rejection, unlike Background Workers' job registry: a self-hosted
    install with no interest in free threading narrowing an entry's `fact_kinds` is a legitimate
    deployment choice, whereas two APIs claiming one job id is always a bug.
    """
    from core.telemetrees.contracts import TrackedDependency

    registry = default_registry()
    registry.register(
        TrackedDependency(name="opencv-python", fact_kinds=(TrackedFactKind.RELEASE_VERSION,))
    )

    assert registry.require("opencv-python").fact_kinds == (TrackedFactKind.RELEASE_VERSION,)


def test_an_unknown_dependency_raises_rather_than_returning_a_blank():
    from core.telemetrees.errors import UnknownDependency

    with pytest.raises(UnknownDependency):
        default_registry().require("not-tracked-at-all")
