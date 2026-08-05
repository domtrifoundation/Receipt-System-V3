"""Which dependencies are tracked, and what facts about each (§3.1, Warden §2).

**`INVENTORY` below is §3.1 as data**, and §3.1 is unusually emphatic about where it came
from: "Collected directly from every prior deep-dive's own deferred items, not invented fresh
here". Every entry carries the deep-dive that asked for it in `source_deep_dive`, because an
inventory assembled from twenty-eight documents' scattered deferrals is exactly the kind of
list that rots — an entry whose reason is lost becomes one nobody dares remove and nobody can
act on.

Both deep-dives independently ask for a test over this table. Telemetrees §8's multi-fact-kind
coverage test wants confirmation that "every dependency in the §3.1 inventory actually has the
right `fact_kinds` registered, not defaulting to plain `release_version` tracking for something
that needed `free_threading_support` specifically". Warden §8's multi-poller coverage test
wants the same fact from the other end — that every declared kind has a poller registered for
it. Both live in `tests/unit/core/telemetrees/`, and between them they keep this registry
honest as the corpus keeps moving.

**The live registry is genuinely mutable internal state** (config adds tracked dependencies at
startup, §7), so it holds a plain `dict` behind a lock while `INVENTORY` — the shipped
constant — is a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent).
"""

from __future__ import annotations

import threading

from common.frozen_dict import FrozenDict

from ..contracts import TrackedDependency, TrackedFactKind
from ..errors import UnknownDependency

_RV = TrackedFactKind.RELEASE_VERSION
_FT = TrackedFactKind.FREE_THREADING_SUPPORT
_ISSUE = TrackedFactKind.UPSTREAM_ISSUE_STATUS
_MODEL = TrackedFactKind.MODEL_CURRENCY
_DATASET = TrackedFactKind.DATASET_FRESHNESS
_REG = TrackedFactKind.REGULATORY_VALUE


def _dep(
    name: str,
    kinds: tuple[TrackedFactKind, ...],
    *,
    issues: tuple[str, ...] = (),
    source: str = "",
    notes: str = "",
) -> TrackedDependency:
    return TrackedDependency(
        name=name,
        fact_kinds=kinds,
        upstream_issue_refs=issues,
        source_deep_dive=source,
        notes=notes,
    )


#: §3.1's full inventory. Keyed by dependency name so a poller resolves one without scanning,
#: and ordered by that section's own grouping so the mapping back to the document stays legible.
INVENTORY: FrozenDict = FrozenDict(
    {
        # §3.1 — free-threading support, per dependency
        "onnxruntime": _dep(
            "onnxruntime",
            (_RV, _FT),
            source="v3-deepdive-01-ocr-api.md, v3-deepdive-02-inference-api.md",
            notes="shared by OCR and Inference; the free-threading posture matters to both",
        ),
        "onnxruntime-genai": _dep(
            "onnxruntime-genai",
            (_RV, _FT),
            source="v3-deepdive-02-inference-api.md",
            notes="named directly in Telemetrees §7's own config example",
        ),
        "opencv-python": _dep(
            "opencv-python",
            (_RV, _FT, _ISSUE),
            issues=("opencv/opencv#27933", "opencv/opencv-python#1051"),
            source="v3-deepdive-03-preprocessing-api.md §8.2/§9.2",
            notes=(
                "the free-threaded-wheel blocker. Needs all three kinds at once: a release "
                "feed alone would never surface the issue resolving, and the issue alone "
                "would never surface a wheel finally shipping"
            ),
        ),
        "rapidfuzz": _dep(
            "rapidfuzz",
            (_RV, _FT),
            source="v3-deepdive-01-ocr-api.md, v3-deepdive-15-matching-api.md",
        ),
        "numpy": _dep(
            "numpy",
            (_RV, _FT),
            source="v3-deepdive-01-ocr-api.md, v3-deepdive-15-matching-api.md",
        ),
        "pymupdf": _dep("pymupdf", (_RV, _FT), source="v3-deepdive-04-ingestion-api.md"),
        "pillow-heif": _dep(
            "pillow-heif",
            (_RV, _FT),
            source="v3-deepdive-04-ingestion-api.md",
            notes=(
                "already confirmed to declare support — §3.1 calls this a genuinely different "
                "starting position worth tracking as a positive data point, not just a gap"
            ),
        ),
        "authlib": _dep("authlib", (_RV, _FT), source="v3-deepdive-05-auth-tenancy-api.md"),
        "cryptography": _dep(
            "cryptography", (_RV, _FT), source="v3-deepdive-05-auth-tenancy-api.md"
        ),
        "frozendict": _dep(
            "frozendict",
            (_RV,),
            source="v3-deepdive-07-tool-call-api.md §6",
            notes=(
                "tracked for its compatibility posture against the 3.15 builtin's exact "
                "semantics — the pre-3.15 shim's correctness depends on it matching, not "
                "merely existing"
            ),
        ),
        # §3.1 — model and dataset currency, genuinely different shapes from a release feed
        "rapidocr-models": _dep(
            "rapidocr-models",
            (_MODEL,),
            source="v3-deepdive-01-ocr-api.md §9",
            notes="is our vendored ONNX copy stale relative to PaddleOCR's newer generations",
        ),
        "clamav-definitions": _dep(
            "clamav-definitions",
            (_DATASET,),
            source="v3-deepdive-27-content-security-api.md §5.1",
            notes=(
                "a stale definitions database is a silent security gap, distinct from the "
                "pyclamd package itself being outdated"
            ),
        ),
        # §3.1 — the interpreter, tracked like any other dependency (file 02 rule #8)
        "cpython": _dep(
            "cpython",
            (_RV, _FT),
            source="v3-plan-02-architecture.md rule #8",
            notes="3.14t/3.15 adoption readiness, tracked continuously, not a one-time decision",
        ),
        # §3.1 — regulatory currency, moving independently of any software release
        "bir-slsp-thresholds": _dep(
            "bir-slsp-thresholds",
            (_REG,),
            source="v3-deepdive-31-export-framework.md §4.1/§10",
            notes="a government-set numeric threshold, not a package version",
        ),
    }
)


class TrackedDependencyRegistry:
    """The live registry: what this process actually polls.

    Seeded from `INVENTORY` by default rather than starting empty — deliberately unlike Task
    Scheduler's allowlist or Background Workers' job registry, which wait for other APIs to
    register against them. The difference is real: those are populated by code that does not
    exist yet, while this inventory is complete today and every entry names the document that
    asked for it. A Telemetrees process tracking nothing on startup would be monitoring that
    silently does nothing, which is the exact failure §4 says makes tracking pointless.
    """

    def __init__(self, seed: FrozenDict | None = None) -> None:
        self._lock = threading.Lock()
        source = INVENTORY if seed is None else seed
        self._deps: dict[str, TrackedDependency] = dict(source)

    def register(self, dependency: TrackedDependency) -> None:
        """Add or replace a tracked dependency — §7's config-driven additions.

        Replacement rather than rejection, unlike Background Workers' job registry: config
        overriding a shipped entry's `fact_kinds` is a legitimate deployment choice (a
        self-hosted install with no interest in free threading), whereas two APIs claiming one
        job id is always a bug.
        """
        with self._lock:
            self._deps[dependency.name] = dependency

    def get(self, name: str) -> TrackedDependency | None:
        with self._lock:
            return self._deps.get(name)

    def require(self, name: str) -> TrackedDependency:
        found = self.get(name)
        if found is None:
            raise UnknownDependency(name)
        return found

    def all_dependencies(self) -> tuple[TrackedDependency, ...]:
        with self._lock:
            return tuple(sorted(self._deps.values(), key=lambda d: d.name))

    def for_fact_kind(self, kind: TrackedFactKind) -> tuple[TrackedDependency, ...]:
        return tuple(d for d in self.all_dependencies() if kind in d.fact_kinds)

    def declared_fact_kinds(self) -> frozenset[TrackedFactKind]:
        """Every kind any registered dependency declares.

        What Warden §8's multi-poller coverage test compares against the poller registry: a
        declared kind with no poller behind it is a fact nobody is actually watching.
        """
        kinds: set[TrackedFactKind] = set()
        for dependency in self.all_dependencies():
            kinds.update(dependency.fact_kinds)
        return frozenset(kinds)

    def all_issue_refs(self) -> tuple[str, ...]:
        refs: list[str] = []
        for dependency in self.all_dependencies():
            refs.extend(dependency.upstream_issue_refs)
        return tuple(sorted(set(refs)))


def default_registry() -> TrackedDependencyRegistry:
    """The startup default: §3.1's inventory, complete."""
    return TrackedDependencyRegistry()


__all__ = ["INVENTORY", "TrackedDependencyRegistry", "default_registry"]
