"""Geo/Address API-owned menu data (`v3-deepdive-16-geo-address-api.md`).

Deliberately empty for now, the same honest partiality `settings.py` documents for its own
tree: Geo/Address API's own config surface (geocoder provider selection, cache TTLs) has
not yet been transcribed into declarative menu-data form as of this pass. An empty tuple
here is correct — a fabricated entry pointing at a target that was never actually decided
would be worse than nothing, per this project's own "never plausible-looking data" rule.
"""

from __future__ import annotations

from services.interface.contracts import MenuItemSpec

GEO_TOOLS_MENU: tuple[MenuItemSpec, ...] = ()
