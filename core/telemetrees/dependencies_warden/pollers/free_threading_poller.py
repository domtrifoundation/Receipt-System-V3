"""The `free_threading_support` fact kind (Warden §3, §9).

Warden §3 is specific about the sources and about not trusting any one of them alone: "via its
PyPI classifiers (a real, standardized signal: the 'Programming Language :: Python :: Free
Threading' trove classifier), its own changelog/release notes, or a maintained community
compatibility tracker as a cross-check — not a single source assumed always current or
authoritative on its own."

So this poller reads the classifier first, and treats the community tracker
(`py-free-threading.github.io`, §9's resolved choice) as a genuine secondary signal rather than
a fallback of last resort. The two answer subtly different questions: the classifier says what
a package *declares*, the tracker says what the community has *observed*. A package can
support free threading in practice for months before declaring it, and the gap between those
two answers is itself useful — so `FreeThreadingStatusEvent.source` records which one spoke.

**Warden §8's own hook tests that the classifier is actually read where present**, "not just
guessing from changelog text alone", which is why the classifier check is a real string match
against the standardized trove value rather than a substring search over release prose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...contracts import (
    COMMUNITY_TRACKER_URL,
    FREE_THREADING_CLASSIFIER,
    FreeThreadingStatus,
    FreeThreadingStatusEvent,
)
from ...errors import MalformedUpstreamResponse, UpstreamUnreachable
from .base import HttpTransport, UnavailableTransport
from .pypi_poller import PYPI_JSON_URL

COMMUNITY_TRACKER_API = f"{COMMUNITY_TRACKER_URL}/api/compatibility.json"

SOURCE_CLASSIFIER = "pypi_trove_classifier"
SOURCE_COMMUNITY = "community_tracker"
SOURCE_NONE = "no_signal"


class FreeThreadingPoller:
    """Reads a dependency's declared free-threading support (Warden §3)."""

    fact_kind_name = "free_threading_support"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport: HttpTransport = transport or UnavailableTransport()

    def poll(self, dep_name: str) -> FreeThreadingStatusEvent | None:
        """The dependency's status, and which signal produced it.

        The classifier is authoritative when present: it is a standardized declaration by the
        maintainer, and nothing the community tracker says should override a package's own
        statement about itself. The tracker only speaks when the classifier is absent — which
        is the real case worth catching, a package that works but has not declared it yet.

        Absence of a classifier is **not** `UNSUPPORTED`. Most packages have said nothing at
        all, and reporting silence as a refusal would fill the changelog with false negatives
        and make the genuine ones unfindable.
        """
        classifier_status = self._from_classifier(dep_name)
        if classifier_status is not None:
            return classifier_status

        community = self._from_community(dep_name)
        if community is not None:
            return community

        return FreeThreadingStatusEvent(
            dependency=dep_name,
            status=FreeThreadingStatus.UNKNOWN,
            source=SOURCE_NONE,
            detail="no trove classifier and no community tracker entry",
        )

    def _from_classifier(self, dep_name: str) -> FreeThreadingStatusEvent | None:
        payload = self._transport.get_json(PYPI_JSON_URL.format(name=dep_name))
        if not isinstance(payload, Mapping):
            raise MalformedUpstreamResponse(f"PyPI returned a non-object for {dep_name!r}")
        info = payload.get("info")
        if not isinstance(info, Mapping):
            return None
        classifiers = info.get("classifiers")
        if not isinstance(classifiers, Sequence) or isinstance(classifiers, (str, bytes)):
            return None
        if FREE_THREADING_CLASSIFIER in classifiers:
            return FreeThreadingStatusEvent(
                dependency=dep_name,
                status=FreeThreadingStatus.SUPPORTED,
                source=SOURCE_CLASSIFIER,
                detail=FREE_THREADING_CLASSIFIER,
            )
        return None

    def _from_community(self, dep_name: str) -> FreeThreadingStatusEvent | None:
        """The §9 cross-check. Unreachable here is not an error for the whole poll.

        The classifier already came back absent by this point, so failing to reach the tracker
        simply leaves the answer `UNKNOWN` — which is the honest result, and better than
        failing a poll that had a perfectly good primary source available.
        """
        try:
            payload = self._transport.get_json(COMMUNITY_TRACKER_API)
        except UpstreamUnreachable:
            return None
        if not isinstance(payload, Mapping):
            return None
        entry = payload.get(dep_name)
        if not isinstance(entry, Mapping):
            return None
        supported = entry.get("supported")
        if supported is None:
            return None
        return FreeThreadingStatusEvent(
            dependency=dep_name,
            status=(
                FreeThreadingStatus.SUPPORTED if supported else FreeThreadingStatus.UNSUPPORTED
            ),
            source=SOURCE_COMMUNITY,
            detail=str(entry.get("detail", "")),
        )


__all__ = [
    "COMMUNITY_TRACKER_API",
    "SOURCE_CLASSIFIER",
    "SOURCE_COMMUNITY",
    "SOURCE_NONE",
    "FreeThreadingPoller",
]
