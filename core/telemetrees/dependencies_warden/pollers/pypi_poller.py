"""The `release_version` fact kind — PyPI's JSON release feed (Warden §3).

**Pre-releases count.** File 02's rule #8 makes day-0 support a tracked discipline, and the
entire point of it is knowing about a beta before it ships stable — a poller that filtered
pre-releases out would surface exactly the versions it is too late to prepare for. §3's own
docstring says "stable and pre-release (beta/alpha/RC) versions both", and `ReleaseEvent`
carries `is_prerelease` so a consumer can tell them apart without the poller deciding for it.

Version ordering is done here rather than deferred to a dependency: `packaging` is not in this
project's manifest, and adding one to answer "is this string newer than that string" for a
handful of daily polls would be a real dependency for a small, self-contained problem. The
parser below handles PEP 440's common shapes — release segments plus an optional
`a`/`b`/`rc`/`.devN`/`.postN` suffix — and falls back to string comparison for anything
genuinely exotic rather than guessing wrong silently.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ...contracts import ReleaseEvent
from ...errors import MalformedUpstreamResponse
from .base import HttpTransport, UnavailableTransport

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"

#: PEP 440's pre-release markers. `dev` counts as a pre-release too — it is earlier than an
#: alpha, not somehow more final than one.
_PRERELEASE = re.compile(r"(a|b|rc|alpha|beta|dev)\d*", re.IGNORECASE)
_SEGMENT = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")


def is_prerelease(version: str) -> bool:
    """Whether a version string carries a pre-release marker."""
    _, _, suffix = version.partition("-")
    match = _SEGMENT.match(version)
    tail = match.group(2) if match else suffix
    return bool(_PRERELEASE.search(tail))


def version_key(version: str) -> tuple:
    """A sortable key: numeric release segments first, then pre-release ordering.

    A pre-release sorts *below* the same release without one, which is the property that
    matters — `2.0.0rc1` must not be reported as newer than `2.0.0`.
    """
    match = _SEGMENT.match(version.strip())
    if not match:
        return ((), 1, version)
    numbers = tuple(int(p) for p in match.group(1).split(".") if p.isdigit())
    return (numbers, 0 if _PRERELEASE.search(match.group(2)) else 1, match.group(2))


class PyPIPoller:
    """Standard PyPI JSON API release-feed check (Warden §3)."""

    fact_kind_name = "release_version"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport: HttpTransport = transport or UnavailableTransport()

    def poll(self, dep_name: str) -> ReleaseEvent | None:
        """The newest version PyPI knows about, pre-releases included.

        Returns `None` for a project with no releases at all rather than raising: a brand-new
        or yanked-empty project is a real state, and it is not this poller's business to have
        an opinion about it.
        """
        payload = self._transport.get_json(PYPI_JSON_URL.format(name=dep_name))
        if not isinstance(payload, Mapping):
            raise MalformedUpstreamResponse(f"PyPI returned a non-object for {dep_name!r}")

        releases = payload.get("releases")
        if not isinstance(releases, Mapping) or not releases:
            info = payload.get("info")
            if isinstance(info, Mapping) and info.get("version"):
                latest = str(info["version"])
                return ReleaseEvent(
                    dependency=dep_name, version=latest, is_prerelease=is_prerelease(latest)
                )
            return None

        latest = max(releases, key=version_key)
        return ReleaseEvent(
            dependency=dep_name,
            version=latest,
            is_prerelease=is_prerelease(latest),
            changelog_url=f"https://pypi.org/project/{dep_name}/{latest}/",
        )


__all__ = ["PYPI_JSON_URL", "PyPIPoller", "is_prerelease", "version_key"]
