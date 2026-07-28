"""Geo/Address provider adapters — LocationIQ, Mapbox, self-hosted Nominatim.

Import-light: a provider's own HTTP transport is constructed by whoever wires it in
(`service.py`'s default registry, or a test's fake `GeoHttpTransport`), never as a side
effect of importing this package.
"""

from __future__ import annotations

__all__: list[str] = []
