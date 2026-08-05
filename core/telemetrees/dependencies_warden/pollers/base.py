"""The transport seam every poller sits behind (Warden §3, `docs/PRINCIPLES.md` §1.3).

Every external service this package reads — PyPI's JSON API, GitHub's issue API, the community
free-threading tracker — goes through one small internal adapter rather than being called from
scattered points. That is §1.3's standing rule, and it buys something concrete here: **no unit
test in this package touches the network**, because the tests inject a transport rather than
mocking `urllib` somewhere deep in a call stack.

`UnavailableTransport` is the default, and it is honest rather than convenient: with nothing
configured, every poll reports the source as unreachable and no fact is observed. A stub that
returned plausible-looking data would be worse than useless — this package's entire job is to
tell developers what actually changed upstream, and inventing that would poison the one signal
it exists to provide.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...errors import UpstreamUnreachable


@runtime_checkable
class HttpTransport(Protocol):
    """One HTTP GET returning decoded JSON, or raising `UpstreamUnreachable`.

    Narrow on purpose: everything this package reads is a JSON GET, and a wider interface would
    invite a poller to reach for something the adapter boundary is meant to contain.
    """

    def get_json(self, url: str) -> object:
        """Fetch and decode `url`, or raise `UpstreamUnreachable`."""


class UnavailableTransport:
    """The default: nothing is configured, so nothing is reachable.

    Never fabricates a response. See this module's docstring for why that matters more here
    than in most packages.
    """

    def get_json(self, url: str) -> object:
        raise UpstreamUnreachable(f"no HTTP transport configured; cannot reach {url}")


class StaticTransport:
    """A transport over a fixed url→payload map.

    Real rather than a test double: an air-gapped self-hosted install pointing this at a
    vendored mirror snapshot is a genuine deployment shape, and it is also what lets the tests
    exercise the same parsing code production runs instead of a mock of it.
    """

    def __init__(self, payloads: dict[str, object] | None = None) -> None:
        self._payloads = dict(payloads or {})
        self.requested: list[str] = []

    def get_json(self, url: str) -> object:
        self.requested.append(url)
        if url not in self._payloads:
            raise UpstreamUnreachable(f"no payload configured for {url}")
        return self._payloads[url]


__all__ = ["HttpTransport", "StaticTransport", "UnavailableTransport"]
