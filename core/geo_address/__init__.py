"""Geo/Address API — geocoding, multi-provider corroboration, and the vendor reverse-check.

Kept import-light on purpose. Other packages import `core.geo_address.contracts` and nothing
else (`docs/PRINCIPLES.md` §1.1), so this module must not pull the provider registry, the
cache, or `service.py` into memory as a side effect of that import.
"""

from __future__ import annotations

__all__: list[str] = []
